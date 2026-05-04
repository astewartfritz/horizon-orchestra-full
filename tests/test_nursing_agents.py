"""Tests for orchestra.verticals.nursing — 6 agents, 32 tools."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


class TestShiftScribeAgent(unittest.TestCase):
    def setUp(self):
        from orchestra.verticals.nursing.shift_scribe import ShiftScribeAgent
        self.agent = ShiftScribeAgent(model="test", hipaa_mode=True)

    def test_instantiation(self):
        self.assertEqual(self.agent.model, "test")
        self.assertTrue(self.agent.hipaa_mode)

    def test_get_tools_count(self):
        tools = self.agent.get_tools()
        self.assertEqual(len(tools), 6)
        names = {t["name"] for t in tools}
        self.assertIn("scribe_voice_note", names)
        self.assertIn("scribe_soap_note", names)

    def test_generate_soap_note(self):
        note = self.agent.generate_soap_note(
            "pt-001", "nurse-01",
            {"chief_complaint": "chest pain", "vitals": {"hr": 88}, "interventions_performed": ["O2 applied"]}
        )
        self.assertEqual(note.patient_id, "pt-001")
        self.assertTrue(note.subjective)
        self.assertTrue(note.objective)
        self.assertTrue(note.assessment)
        self.assertTrue(note.plan)

    def test_generate_soap_note_empty_raises(self):
        with self.assertRaises(ValueError):
            self.agent.generate_soap_note("pt", "n", {})

    def test_auto_fill_flowsheet(self):
        entry = self.agent.auto_fill_flowsheet(
            "pt-001", "nurse-01",
            {"hr": 88, "bp_sys": 120, "bp_dia": 80, "rr": 16, "temp": 98.6, "spo2": 98, "pain": 3},
            ["IV maintenance"], "Alert, oriented x4"
        )
        self.assertEqual(entry.patient_id, "pt-001")
        self.assertIsNotNone(entry.fhir_observation_bundle)
        self.assertEqual(entry.fhir_observation_bundle["resourceType"], "Bundle")

    def test_flowsheet_fhir_observations(self):
        entry = self.agent.auto_fill_flowsheet(
            "pt-002", "nurse-01", {"hr": 72, "spo2": 97}, [], ""
        )
        bundle = entry.fhir_observation_bundle
        self.assertTrue(len(bundle["entry"]) >= 2)
        self.assertEqual(bundle["entry"][0]["resource"]["resourceType"], "Observation")

    def test_flowsheet_empty_vitals_raises(self):
        with self.assertRaises(ValueError):
            self.agent.auto_fill_flowsheet("pt", "n", {}, [], "")

    def test_transcribe_voice_note(self):
        note = self.agent.transcribe_voice_note(b"fake_audio_data", "pt-001", "nurse-01")
        self.assertEqual(note.patient_id, "pt-001")
        self.assertIsNotNone(note.fhir_bundle)

    def test_transcribe_empty_audio_raises(self):
        with self.assertRaises(ValueError):
            self.agent.transcribe_voice_note(b"", "pt", "n")

    def test_discharge_summary(self):
        ds = self.agent.draft_discharge_summary("pt-001", "nurse-01", {"primary_diagnosis": "CHF"})
        self.assertEqual(ds.primary_diagnosis, "CHF")
        self.assertEqual(ds.patient_id, "pt-001")

    def test_nursing_note_to_fhir(self):
        from orchestra.verticals.nursing.shift_scribe import NursingNote, NoteType
        note = NursingNote(patient_id="pt-001", nurse_id="n-01", note_type=NoteType.SOAP, content="Test content")
        fhir = note.to_fhir_composition()
        self.assertEqual(fhir["resourceType"], "Composition")
        self.assertEqual(fhir["subject"]["reference"], "Patient/pt-001")


class TestHandoffAgent(unittest.TestCase):
    def setUp(self):
        from orchestra.verticals.nursing.handoff_agent import HandoffAgent
        self.agent = HandoffAgent()

    def test_generate_sbar(self):
        sbar = self.agent.generate_sbar("pt-001", "nurse-01", {
            "primary_diagnosis": "pneumonia", "admission_date": "2026-04-01",
            "latest_vitals": {"hr": 92}, "recent_labs": [], "medications_due": [],
        })
        self.assertTrue(sbar.situation)
        self.assertTrue(sbar.background)
        self.assertTrue(sbar.assessment)
        self.assertTrue(sbar.recommendation)
        self.assertTrue(sbar.validate())

    def test_sbar_missing_patient_raises(self):
        with self.assertRaises(ValueError):
            self.agent.generate_sbar("", "nurse-01")

    def test_flag_critical_pending(self):
        items = self.agent.flag_critical_pending("pt-001", {
            "pending_labs": [{"test": "troponin"}],
            "overdue_meds": [{"drug": "heparin"}],
        })
        self.assertTrue(len(items) >= 2)
        overdue = [i for i in items if i.overdue]
        self.assertTrue(len(overdue) >= 1)

    def test_batch_unit_handoff(self):
        report = self.agent.batch_unit_handoff("unit-3N", ["pt-001", "pt-002", "pt-003"], "day_to_evening")
        self.assertEqual(len(report.patient_reports), 3)
        self.assertEqual(report.unit_id, "unit-3N")

    def test_batch_empty_raises(self):
        with self.assertRaises(ValueError):
            self.agent.batch_unit_handoff("unit", [], "day")

    def test_bedside_handoff_script(self):
        sbar = self.agent.generate_sbar("pt-001", "nurse-01")
        script = self.agent.bedside_handoff_script(sbar)
        self.assertIn("SITUATION", script)
        self.assertIn("BACKGROUND", script)
        self.assertIn("ASSESSMENT", script)
        self.assertIn("RECOMMENDATION", script)

    def test_get_tools(self):
        self.assertEqual(len(self.agent.get_tools()), 5)


class TestMedReconciliationAgent(unittest.TestCase):
    def setUp(self):
        from orchestra.verticals.nursing.med_reconciliation import MedReconciliationAgent
        self.agent = MedReconciliationAgent()

    def test_five_rights_all_pass(self):
        result = self.agent.check_five_rights(
            "pt-001", "metoprolol", "25mg", "oral",
            datetime.utcnow(),
            {"confirmed_patient_id": "pt-001", "ordered_drug": "metoprolol", "ordered_dose": "25mg", "ordered_route": "oral"}
        )
        self.assertTrue(result.all_five_rights_pass)
        self.assertEqual(result.risk_level, "safe")

    def test_five_rights_drug_mismatch(self):
        result = self.agent.check_five_rights(
            "pt-001", "lisinopril", "25mg", "oral",
            datetime.utcnow(),
            {"ordered_drug": "metoprolol"}
        )
        self.assertFalse(result.all_five_rights_pass)
        self.assertFalse(result.right_drug)
        self.assertEqual(result.risk_level, "critical")

    def test_five_rights_high_alert_flagged(self):
        result = self.agent.check_five_rights(
            "pt-001", "heparin", "5000 units", "subq",
            datetime.utcnow(),
            {"ordered_drug": "heparin", "ordered_dose": "5000 units", "ordered_route": "subq"}
        )
        self.assertTrue(any("HIGH-ALERT" in a for a in result.alerts))

    def test_five_rights_missing_fields_raises(self):
        with self.assertRaises(ValueError):
            self.agent.check_five_rights("", "drug", "dose", "route", datetime.utcnow())

    def test_detect_interactions(self):
        interactions = self.agent.detect_interactions(["warfarin", "aspirin", "metformin"])
        self.assertTrue(len(interactions) >= 1)
        self.assertEqual(interactions[0].drug_a, "warfarin")
        self.assertEqual(interactions[0].drug_b, "aspirin")
        self.assertEqual(interactions[0].severity, "major")

    def test_detect_interactions_none(self):
        interactions = self.agent.detect_interactions(["acetaminophen", "omeprazole"])
        self.assertEqual(len(interactions), 0)

    def test_allergy_conflict_detected(self):
        alert = self.agent.verify_allergy_conflict("pt-001", "amoxicillin", [
            {"allergen": "amoxicillin", "reaction": "anaphylaxis", "severity": "anaphylaxis"}
        ])
        self.assertIsNotNone(alert)
        self.assertIn("DO NOT ADMINISTER", alert.action_required)

    def test_allergy_no_conflict(self):
        alert = self.agent.verify_allergy_conflict("pt-001", "metoprolol", [
            {"allergen": "penicillin"}
        ])
        self.assertIsNone(alert)

    def test_allergy_cross_reactivity(self):
        alert = self.agent.verify_allergy_conflict("pt-001", "amoxicillin", [
            {"allergen": "penicillin", "reaction": "rash", "severity": "moderate"}
        ])
        self.assertIsNotNone(alert)
        self.assertIn("cross-reactivity", alert.cross_reactivity_risk.lower())

    def test_weight_based_dose_check_in_range(self):
        result = self.agent.weight_based_dose_check("pt-001", "acetaminophen", "750 mg", 70)
        self.assertIsInstance(result.within_range, bool)
        self.assertGreater(result.calculated_dose_mgkg, 0)

    def test_weight_based_dose_invalid_weight(self):
        with self.assertRaises(ValueError):
            self.agent.weight_based_dose_check("pt", "drug", "100mg", 0)

    def test_reconciliation(self):
        report = self.agent.reconcile_home_meds(
            "pt-001",
            [{"drug": "metoprolol"}, {"drug": "lisinopril"}, {"drug": "atorvastatin"}],
            [{"drug": "metoprolol"}, {"drug": "heparin"}],
        )
        self.assertTrue(report.review_required)
        self.assertTrue(len(report.discrepancies) >= 2)

    def test_high_alert_check(self):
        result = self.agent.high_alert_medication_check("insulin")
        self.assertTrue(result["is_high_alert"])
        self.assertTrue(len(result["precautions"]) > 0)

    def test_high_alert_negative(self):
        result = self.agent.high_alert_medication_check("acetaminophen")
        self.assertFalse(result["is_high_alert"])

    def test_get_tools(self):
        self.assertEqual(len(self.agent.get_tools()), 6)


class TestEarlyWarningAgent(unittest.TestCase):
    def setUp(self):
        from orchestra.verticals.nursing.early_warning import EarlyWarningAgent, VitalsBundle
        self.agent = EarlyWarningAgent()
        self.VitalsBundle = VitalsBundle

    def _make_vitals(self, **kwargs):
        defaults = {
            "patient_id": "pt-001", "timestamp": datetime.utcnow(),
            "respiratory_rate": 16, "spo2": 97, "supplemental_oxygen": False,
            "hypercapnic_risk": False, "systolic_bp": 120, "heart_rate": 75,
            "consciousness": "alert", "temperature": 37.0,
        }
        defaults.update(kwargs)
        return self.VitalsBundle(**defaults)

    def test_news2_normal_vitals(self):
        result = self.agent.score_news2(self._make_vitals())
        self.assertEqual(result.risk_level, "low")
        self.assertLessEqual(result.total_score, 4)
        self.assertFalse(result.alert_triggered)

    def test_news2_high_risk(self):
        result = self.agent.score_news2(self._make_vitals(
            respiratory_rate=28, spo2=88, systolic_bp=85,
            heart_rate=135, consciousness="voice", temperature=39.5
        ))
        self.assertEqual(result.risk_level, "high")
        self.assertGreaterEqual(result.total_score, 7)
        self.assertTrue(result.alert_triggered)
        self.assertIn("Emergency", result.clinical_response)

    def test_news2_medium_single_param_3(self):
        result = self.agent.score_news2(self._make_vitals(consciousness="pain"))
        self.assertEqual(result.risk_level, "medium")
        self.assertTrue(result.alert_triggered)

    def test_news2_hypercapnic_scale2(self):
        result = self.agent.score_news2(self._make_vitals(
            hypercapnic_risk=True, spo2=90, supplemental_oxygen=False
        ))
        self.assertEqual(result.component_scores["spo2"], 0)  # 88-92 is target for Scale 2

    def test_mews_normal(self):
        result = self.agent.score_mews(self._make_vitals())
        self.assertEqual(result.risk_level, "low")
        self.assertFalse(result.alert_triggered)

    def test_mews_urgent(self):
        result = self.agent.score_mews(self._make_vitals(
            systolic_bp=70, heart_rate=135, respiratory_rate=32,
            temperature=39.5, consciousness="pain"
        ))
        self.assertGreaterEqual(result.total_score, 5)
        self.assertTrue(result.alert_triggered)

    def test_clinical_response_text(self):
        low = self.agent.compute_news2_clinical_response(2)
        self.assertIn("4–6 hourly", low)
        high = self.agent.compute_news2_clinical_response(8)
        self.assertIn("Emergency", high)

    def test_trend_analysis_deteriorating(self):
        now = datetime.utcnow()
        from orchestra.verticals.nursing.early_warning import NEWS2Score
        scores = [
            NEWS2Score("pt-001", now - timedelta(hours=4), 2, {}, "low", "", False),
            NEWS2Score("pt-001", now - timedelta(hours=2), 4, {}, "low", "", False),
            NEWS2Score("pt-001", now, 7, {}, "high", "", True),
        ]
        trend = self.agent.trend_analysis("pt-001", scores)
        self.assertEqual(trend.trend_direction, "deteriorating")
        self.assertGreater(trend.rate_of_change, 0)

    def test_trend_analysis_empty(self):
        trend = self.agent.trend_analysis("pt-001", [])
        self.assertEqual(trend.trend_direction, "unknown")

    def test_rrt_brief(self):
        vitals = self._make_vitals(heart_rate=140, systolic_bp=80)
        news2 = self.agent.score_news2(vitals)
        brief = self.agent.generate_rapid_response_brief(
            "pt-001", news2, [vitals],
            history="CHF, DM2", meds=["metoprolol", "insulin"],
            attending="Dr. Smith", code_status="Full code"
        )
        self.assertIn("SITUATION", brief.sbar_brief)
        self.assertEqual(brief.full_code_status, "Full code")

    def test_get_tools(self):
        self.assertEqual(len(self.agent.get_tools()), 4)


class TestStaffingOptimizerAgent(unittest.TestCase):
    def setUp(self):
        from orchestra.verticals.nursing.staffing_optimizer import StaffingOptimizerAgent
        self.agent = StaffingOptimizerAgent()

    def test_acuity_score_routine(self):
        score = self.agent.calculate_acuity_score("pt-001", {"iv_lines": 0, "fall_risk": False})
        self.assertEqual(score.category, "routine")
        self.assertAlmostEqual(score.score, 1.0, places=0)

    def test_acuity_score_critical(self):
        score = self.agent.calculate_acuity_score("pt-001", {
            "iv_lines": 4, "ventilator": True, "vasopressors": True, "isolation": True
        })
        self.assertGreaterEqual(score.score, 3.0)
        self.assertIn(score.category, ("critical", "intensive"))

    def test_acuity_empty_data_raises(self):
        with self.assertRaises(ValueError):
            self.agent.calculate_acuity_score("pt", {})

    def test_staffing_recommendation_understaffed(self):
        rec = self.agent.recommend_staffing(
            "unit-3N", "day", ["pt-001", "pt-002", "pt-003", "pt-004", "pt-005", "pt-006", "pt-007", "pt-008"],
            current_schedule={"rn_count": 1}, unit_type="med_surg"
        )
        self.assertLess(rec.staffing_gap, 0)
        self.assertGreater(rec.mortality_risk_delta, 0)
        self.assertIn("UNDERSTAFFED", rec.rationale)

    def test_mortality_risk_delta_aiken(self):
        # 4:1 to 8:1 → should be ~31% increase (Aiken 2002)
        delta = self.agent.compute_mortality_risk_delta(8.0, 4.0, "med_surg")
        self.assertGreater(delta, 25)  # ~31% per Aiken
        self.assertLess(delta, 40)

    def test_mortality_risk_delta_equal(self):
        delta = self.agent.compute_mortality_risk_delta(4.0, 4.0)
        self.assertAlmostEqual(delta, 0, places=1)

    def test_predict_census(self):
        historical = [{"census": 20}, {"census": 22}, {"census": 21}, {"census": 23}]
        forecast = self.agent.predict_census("unit-3N", historical, hours_ahead=24)
        self.assertEqual(forecast.unit_id, "unit-3N")
        self.assertTrue(len(forecast.predicted_census) > 0)

    def test_get_tools(self):
        self.assertEqual(len(self.agent.get_tools()), 5)


class TestNurseEducationCoach(unittest.TestCase):
    def setUp(self):
        from orchestra.verticals.nursing.education_coach import NurseEducationCoach
        self.coach = NurseEducationCoach()

    def test_explain_medication_known(self):
        brief = self.coach.explain_medication("heparin")
        self.assertIn("antithrombin", brief.mechanism_of_action.lower())
        self.assertTrue(any("HIGH-ALERT" in c for c in brief.key_nursing_considerations))

    def test_explain_medication_unknown(self):
        brief = self.coach.explain_medication("obscure_drug_xyz")
        self.assertIsInstance(brief, type(self.coach.explain_medication("heparin")))

    def test_explain_medication_empty_raises(self):
        with self.assertRaises(ValueError):
            self.coach.explain_medication("")

    def test_procedure_checklist_known(self):
        checklist = self.coach.procedure_checklist("foley catheter insertion", {"age": 65})
        self.assertTrue(len(checklist.steps) > 5)
        self.assertTrue(len(checklist.equipment_needed) > 3)

    def test_procedure_checklist_unknown(self):
        checklist = self.coach.procedure_checklist("xyz_procedure", {})
        self.assertTrue(len(checklist.steps) >= 1)

    def test_lab_value_low(self):
        result = self.coach.explain_lab_value("potassium", 2.8, "mEq/L")
        self.assertIn("LOW", result)

    def test_lab_value_normal(self):
        result = self.coach.explain_lab_value("sodium", 140, "mEq/L")
        self.assertIn("NORMAL", result)

    def test_lab_value_high(self):
        result = self.coach.explain_lab_value("glucose", 350, "mg/dL")
        self.assertIn("HIGH", result)

    def test_differential_support(self):
        brief = self.coach.differential_support(["chest pain", "diaphoresis", "dyspnea"])
        self.assertIsNotNone(brief.topic)
        self.assertTrue(len(brief.key_nursing_considerations) > 0)

    def test_competency_tracker(self):
        report = self.coach.skills_competency_tracker("nurse-01", [
            {"skill": "insulin administration", "date": "2026-01-15", "score": 95},
            {"skill": "blood transfusion", "date": "2026-02-01", "score": 88},
        ])
        self.assertEqual(report.nurse_id, "nurse-01")
        self.assertTrue(len(report.high_alert_med_competencies) >= 1)

    def test_get_tools(self):
        self.assertEqual(len(self.coach.get_tools()), 6)


if __name__ == "__main__":
    unittest.main()
