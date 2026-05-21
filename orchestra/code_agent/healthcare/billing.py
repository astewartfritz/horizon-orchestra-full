"""CPT/ICD-10 reference database and claim generation logic."""
from __future__ import annotations

from typing import Any

# ── Common CPT codes (Evaluation & Management + common procedures) ────────────

CPT_CODES: dict[str, dict[str, Any]] = {
    # Office/Outpatient E&M — New Patient
    "99201": {"description": "Office visit, new patient, 10 min", "fee": 68.00, "rvu": 0.97, "category": "E&M"},
    "99202": {"description": "Office visit, new patient, 20 min", "fee": 109.00, "rvu": 1.61, "category": "E&M"},
    "99203": {"description": "Office visit, new patient, 30 min", "fee": 151.00, "rvu": 2.27, "category": "E&M"},
    "99204": {"description": "Office visit, new patient, 45 min", "fee": 224.00, "rvu": 3.21, "category": "E&M"},
    "99205": {"description": "Office visit, new patient, 60 min", "fee": 290.00, "rvu": 4.03, "category": "E&M"},
    # Office/Outpatient E&M — Established Patient
    "99211": {"description": "Office visit, established patient, 5 min", "fee": 25.00, "rvu": 0.48, "category": "E&M"},
    "99212": {"description": "Office visit, established patient, 10 min", "fee": 75.00, "rvu": 1.17, "category": "E&M"},
    "99213": {"description": "Office visit, established patient, 20 min", "fee": 115.00, "rvu": 1.88, "category": "E&M"},
    "99214": {"description": "Office visit, established patient, 25 min", "fee": 167.00, "rvu": 2.56, "category": "E&M"},
    "99215": {"description": "Office visit, established patient, 40 min", "fee": 228.00, "rvu": 3.50, "category": "E&M"},
    # Preventive Medicine — New Patient
    "99381": {"description": "Preventive visit, new patient, infant (under 1)", "fee": 165.00, "rvu": 2.10, "category": "Preventive"},
    "99382": {"description": "Preventive visit, new patient, age 1-4", "fee": 165.00, "rvu": 2.10, "category": "Preventive"},
    "99383": {"description": "Preventive visit, new patient, age 5-11", "fee": 165.00, "rvu": 2.10, "category": "Preventive"},
    "99384": {"description": "Preventive visit, new patient, age 12-17", "fee": 175.00, "rvu": 2.20, "category": "Preventive"},
    "99385": {"description": "Preventive visit, new patient, age 18-39", "fee": 175.00, "rvu": 2.25, "category": "Preventive"},
    "99386": {"description": "Preventive visit, new patient, age 40-64", "fee": 195.00, "rvu": 2.45, "category": "Preventive"},
    "99387": {"description": "Preventive visit, new patient, age 65+", "fee": 210.00, "rvu": 2.65, "category": "Preventive"},
    # Preventive Medicine — Established Patient
    "99391": {"description": "Preventive visit, established, infant", "fee": 145.00, "rvu": 1.85, "category": "Preventive"},
    "99392": {"description": "Preventive visit, established, age 1-4", "fee": 145.00, "rvu": 1.85, "category": "Preventive"},
    "99393": {"description": "Preventive visit, established, age 5-11", "fee": 145.00, "rvu": 1.85, "category": "Preventive"},
    "99394": {"description": "Preventive visit, established, age 12-17", "fee": 155.00, "rvu": 1.95, "category": "Preventive"},
    "99395": {"description": "Preventive visit, established, age 18-39", "fee": 155.00, "rvu": 2.00, "category": "Preventive"},
    "99396": {"description": "Preventive visit, established, age 40-64", "fee": 170.00, "rvu": 2.15, "category": "Preventive"},
    "99397": {"description": "Preventive visit, established, age 65+", "fee": 185.00, "rvu": 2.35, "category": "Preventive"},
    # Hospital/Inpatient E&M
    "99221": {"description": "Initial hospital care, low complexity", "fee": 220.00, "rvu": 3.17, "category": "Hospital"},
    "99222": {"description": "Initial hospital care, moderate complexity", "fee": 305.00, "rvu": 4.35, "category": "Hospital"},
    "99223": {"description": "Initial hospital care, high complexity", "fee": 390.00, "rvu": 5.59, "category": "Hospital"},
    "99231": {"description": "Subsequent hospital care, low complexity", "fee": 105.00, "rvu": 1.55, "category": "Hospital"},
    "99232": {"description": "Subsequent hospital care, moderate complexity", "fee": 150.00, "rvu": 2.20, "category": "Hospital"},
    "99233": {"description": "Subsequent hospital care, high complexity", "fee": 210.00, "rvu": 3.05, "category": "Hospital"},
    # Critical Care
    "99291": {"description": "Critical care, first 30-74 min", "fee": 420.00, "rvu": 6.00, "category": "Critical Care"},
    "99292": {"description": "Critical care, each additional 30 min", "fee": 195.00, "rvu": 2.85, "category": "Critical Care"},
    # Telehealth
    "99441": {"description": "Telephone E&M, 5-10 min", "fee": 55.00, "rvu": 0.97, "category": "Telehealth"},
    "99442": {"description": "Telephone E&M, 11-20 min", "fee": 90.00, "rvu": 1.50, "category": "Telehealth"},
    "99443": {"description": "Telephone E&M, 21-30 min", "fee": 125.00, "rvu": 2.10, "category": "Telehealth"},
    # Mental Health
    "90791": {"description": "Psychiatric diagnostic evaluation", "fee": 220.00, "rvu": 3.21, "category": "Mental Health"},
    "90832": {"description": "Psychotherapy, 30 min", "fee": 100.00, "rvu": 1.71, "category": "Mental Health"},
    "90834": {"description": "Psychotherapy, 45 min", "fee": 130.00, "rvu": 2.18, "category": "Mental Health"},
    "90837": {"description": "Psychotherapy, 60 min", "fee": 170.00, "rvu": 2.83, "category": "Mental Health"},
    "90847": {"description": "Family psychotherapy with patient, 50 min", "fee": 145.00, "rvu": 2.45, "category": "Mental Health"},
    # Procedures
    "10060": {"description": "Incision and drainage of abscess, simple", "fee": 190.00, "rvu": 2.99, "category": "Procedure"},
    "10061": {"description": "Incision and drainage of abscess, complex", "fee": 340.00, "rvu": 5.25, "category": "Procedure"},
    "11200": {"description": "Removal of skin tags, up to 15", "fee": 125.00, "rvu": 2.01, "category": "Procedure"},
    "11400": {"description": "Excision, benign lesion, 0.5 cm or less", "fee": 175.00, "rvu": 2.85, "category": "Procedure"},
    "11401": {"description": "Excision, benign lesion, 0.6-1.0 cm", "fee": 225.00, "rvu": 3.50, "category": "Procedure"},
    "12001": {"description": "Repair, simple, 2.5 cm or less", "fee": 200.00, "rvu": 3.18, "category": "Procedure"},
    "12002": {"description": "Repair, simple, 2.6-7.5 cm", "fee": 240.00, "rvu": 3.79, "category": "Procedure"},
    "17000": {"description": "Destruction, premalignant lesions, first", "fee": 140.00, "rvu": 1.59, "category": "Procedure"},
    "17003": {"description": "Destruction, premalignant lesions, each addl", "fee": 20.00, "rvu": 0.21, "category": "Procedure"},
    "20610": {"description": "Arthrocentesis, major joint", "fee": 140.00, "rvu": 2.22, "category": "Procedure"},
    "29131": {"description": "Application of finger splint", "fee": 95.00, "rvu": 1.52, "category": "Procedure"},
    "36415": {"description": "Venipuncture (blood draw)", "fee": 30.00, "rvu": 0.28, "category": "Procedure"},
    "36416": {"description": "Fingerstick blood collection", "fee": 20.00, "rvu": 0.16, "category": "Procedure"},
    "43239": {"description": "Upper endoscopy with biopsy", "fee": 550.00, "rvu": 7.15, "category": "Procedure"},
    "45378": {"description": "Colonoscopy, diagnostic", "fee": 600.00, "rvu": 7.82, "category": "Procedure"},
    "45380": {"description": "Colonoscopy with biopsy", "fee": 680.00, "rvu": 9.13, "category": "Procedure"},
    # Lab / Diagnostics
    "81001": {"description": "Urinalysis, automated", "fee": 12.00, "rvu": 0.20, "category": "Lab"},
    "81002": {"description": "Urinalysis, non-automated", "fee": 10.00, "rvu": 0.17, "category": "Lab"},
    "81025": {"description": "Urine pregnancy test", "fee": 25.00, "rvu": 0.21, "category": "Lab"},
    "82043": {"description": "Microalbumin, urine", "fee": 30.00, "rvu": 0.18, "category": "Lab"},
    "82607": {"description": "Vitamin B12 level", "fee": 45.00, "rvu": 0.22, "category": "Lab"},
    "82947": {"description": "Glucose, blood", "fee": 20.00, "rvu": 0.16, "category": "Lab"},
    "82962": {"description": "Glucose, fingerstick", "fee": 18.00, "rvu": 0.14, "category": "Lab"},
    "83036": {"description": "Hemoglobin A1c", "fee": 35.00, "rvu": 0.22, "category": "Lab"},
    "83721": {"description": "LDL cholesterol, direct", "fee": 40.00, "rvu": 0.21, "category": "Lab"},
    "84153": {"description": "PSA (prostate specific antigen)", "fee": 50.00, "rvu": 0.21, "category": "Lab"},
    "84155": {"description": "Serum protein", "fee": 25.00, "rvu": 0.16, "category": "Lab"},
    "84443": {"description": "TSH (thyroid stimulating hormone)", "fee": 55.00, "rvu": 0.22, "category": "Lab"},
    "84479": {"description": "Thyroid hormone (T3 uptake)", "fee": 40.00, "rvu": 0.20, "category": "Lab"},
    "85025": {"description": "Complete blood count (CBC) with differential", "fee": 28.00, "rvu": 0.23, "category": "Lab"},
    "85027": {"description": "CBC without differential", "fee": 20.00, "rvu": 0.17, "category": "Lab"},
    "86592": {"description": "Rapid strep test", "fee": 25.00, "rvu": 0.15, "category": "Lab"},
    "86703": {"description": "HIV 1 and 2 antibody test", "fee": 65.00, "rvu": 0.21, "category": "Lab"},
    "87210": {"description": "Wet mount, vaginal secretions", "fee": 22.00, "rvu": 0.18, "category": "Lab"},
    "87430": {"description": "Rapid influenza test", "fee": 30.00, "rvu": 0.17, "category": "Lab"},
    "87880": {"description": "Rapid Strep A, direct", "fee": 28.00, "rvu": 0.15, "category": "Lab"},
    # Imaging
    "71046": {"description": "Chest X-ray, 2 views", "fee": 85.00, "rvu": 0.61, "category": "Imaging"},
    "72040": {"description": "X-ray spine, cervical, 2-3 views", "fee": 90.00, "rvu": 0.65, "category": "Imaging"},
    "72100": {"description": "X-ray spine, lumbar, 2-3 views", "fee": 95.00, "rvu": 0.69, "category": "Imaging"},
    "73060": {"description": "X-ray humerus, 2+ views", "fee": 75.00, "rvu": 0.54, "category": "Imaging"},
    "73562": {"description": "X-ray knee, 3 views", "fee": 80.00, "rvu": 0.59, "category": "Imaging"},
    "73630": {"description": "X-ray foot, 3+ views", "fee": 75.00, "rvu": 0.55, "category": "Imaging"},
    "93000": {"description": "ECG with interpretation", "fee": 55.00, "rvu": 0.79, "category": "Imaging"},
    "93005": {"description": "ECG tracing only", "fee": 30.00, "rvu": 0.43, "category": "Imaging"},
    # Immunizations
    "90460": {"description": "Immunization administration, first component", "fee": 28.00, "rvu": 0.47, "category": "Immunization"},
    "90471": {"description": "Immunization administration, intramuscular", "fee": 25.00, "rvu": 0.47, "category": "Immunization"},
    "90662": {"description": "Influenza vaccine, high dose", "fee": 68.00, "rvu": 0.00, "category": "Immunization"},
    "90686": {"description": "Influenza vaccine, quadrivalent", "fee": 38.00, "rvu": 0.00, "category": "Immunization"},
    "90714": {"description": "Tetanus toxoid (Td) vaccine", "fee": 55.00, "rvu": 0.00, "category": "Immunization"},
    "90716": {"description": "Chickenpox (varicella) vaccine", "fee": 125.00, "rvu": 0.00, "category": "Immunization"},
    "90723": {"description": "DTaP-HepB-IPV vaccine", "fee": 85.00, "rvu": 0.00, "category": "Immunization"},
    "90732": {"description": "Pneumococcal polysaccharide vaccine", "fee": 95.00, "rvu": 0.00, "category": "Immunization"},
    "90746": {"description": "Hepatitis B vaccine, adult", "fee": 80.00, "rvu": 0.00, "category": "Immunization"},
    # Chronic Care Management
    "99490": {"description": "Chronic care management, 20 min/month", "fee": 62.00, "rvu": 1.00, "category": "CCM"},
    "99491": {"description": "Chronic care management, 30 min/month", "fee": 82.00, "rvu": 1.45, "category": "CCM"},
    "99487": {"description": "Complex chronic care management, 60 min", "fee": 132.00, "rvu": 2.10, "category": "CCM"},
    # Annual Wellness Visits
    "G0438": {"description": "Annual wellness visit, initial", "fee": 185.00, "rvu": 2.60, "category": "Wellness"},
    "G0439": {"description": "Annual wellness visit, subsequent", "fee": 150.00, "rvu": 2.10, "category": "Wellness"},
    "G0444": {"description": "Annual depression screening", "fee": 45.00, "rvu": 0.53, "category": "Wellness"},
    "G0446": {"description": "Intensive behavior therapy, CVD", "fee": 55.00, "rvu": 0.64, "category": "Wellness"},
}

# ── Common ICD-10 codes ───────────────────────────────────────────────────────

ICD10_CODES: dict[str, dict[str, str]] = {
    # Endocrine
    "E11.9": {"description": "Type 2 diabetes mellitus without complications", "category": "Endocrine"},
    "E11.65": {"description": "Type 2 diabetes mellitus with hyperglycemia", "category": "Endocrine"},
    "E11.40": {"description": "Type 2 diabetes with diabetic neuropathy, unspecified", "category": "Endocrine"},
    "E11.311": {"description": "Type 2 diabetes with unspecified diabetic retinopathy, with macular edema", "category": "Endocrine"},
    "E10.9": {"description": "Type 1 diabetes mellitus without complications", "category": "Endocrine"},
    "E03.9": {"description": "Hypothyroidism, unspecified", "category": "Endocrine"},
    "E05.90": {"description": "Hyperthyroidism, unspecified", "category": "Endocrine"},
    "E78.5": {"description": "Hyperlipidemia, unspecified", "category": "Endocrine"},
    "E78.00": {"description": "Pure hypercholesterolemia, unspecified", "category": "Endocrine"},
    "E66.9": {"description": "Obesity, unspecified", "category": "Endocrine"},
    "E66.01": {"description": "Morbid (severe) obesity due to excess calories", "category": "Endocrine"},
    # Cardiovascular
    "I10": {"description": "Essential (primary) hypertension", "category": "Cardiovascular"},
    "I11.9": {"description": "Hypertensive heart disease without heart failure", "category": "Cardiovascular"},
    "I25.10": {"description": "Atherosclerotic heart disease, unspecified", "category": "Cardiovascular"},
    "I48.91": {"description": "Unspecified atrial fibrillation", "category": "Cardiovascular"},
    "I50.9": {"description": "Heart failure, unspecified", "category": "Cardiovascular"},
    "I21.9": {"description": "Acute myocardial infarction, unspecified", "category": "Cardiovascular"},
    "I63.9": {"description": "Cerebral infarction, unspecified", "category": "Cardiovascular"},
    "I65.29": {"description": "Occlusion and stenosis of carotid artery, unspecified", "category": "Cardiovascular"},
    # Respiratory
    "J06.9": {"description": "Acute upper respiratory infection, unspecified", "category": "Respiratory"},
    "J00": {"description": "Acute nasopharyngitis (common cold)", "category": "Respiratory"},
    "J02.9": {"description": "Acute pharyngitis, unspecified", "category": "Respiratory"},
    "J03.90": {"description": "Acute tonsillitis, unspecified", "category": "Respiratory"},
    "J04.0": {"description": "Acute laryngitis", "category": "Respiratory"},
    "J18.9": {"description": "Pneumonia, unspecified organism", "category": "Respiratory"},
    "J20.9": {"description": "Acute bronchitis, unspecified", "category": "Respiratory"},
    "J40": {"description": "Bronchitis, not specified as acute or chronic", "category": "Respiratory"},
    "J44.1": {"description": "Chronic obstructive pulmonary disease with acute exacerbation", "category": "Respiratory"},
    "J44.0": {"description": "COPD with acute lower respiratory infection", "category": "Respiratory"},
    "J45.20": {"description": "Mild intermittent asthma, uncomplicated", "category": "Respiratory"},
    "J45.30": {"description": "Mild persistent asthma, uncomplicated", "category": "Respiratory"},
    "J45.40": {"description": "Moderate persistent asthma, uncomplicated", "category": "Respiratory"},
    "J45.50": {"description": "Severe persistent asthma, uncomplicated", "category": "Respiratory"},
    # Musculoskeletal
    "M54.5": {"description": "Low back pain", "category": "Musculoskeletal"},
    "M54.50": {"description": "Low back pain, unspecified", "category": "Musculoskeletal"},
    "M54.2": {"description": "Cervicalgia (neck pain)", "category": "Musculoskeletal"},
    "M25.511": {"description": "Pain in right shoulder", "category": "Musculoskeletal"},
    "M25.512": {"description": "Pain in left shoulder", "category": "Musculoskeletal"},
    "M25.561": {"description": "Pain in right knee", "category": "Musculoskeletal"},
    "M25.562": {"description": "Pain in left knee", "category": "Musculoskeletal"},
    "M79.3": {"description": "Panniculitis", "category": "Musculoskeletal"},
    "M79.7": {"description": "Fibromyalgia", "category": "Musculoskeletal"},
    "M17.11": {"description": "Primary osteoarthritis, right knee", "category": "Musculoskeletal"},
    "M17.12": {"description": "Primary osteoarthritis, left knee", "category": "Musculoskeletal"},
    "M19.011": {"description": "Primary osteoarthritis, right shoulder", "category": "Musculoskeletal"},
    "M16.11": {"description": "Unilateral primary osteoarthritis, right hip", "category": "Musculoskeletal"},
    # Neurological
    "G43.909": {"description": "Migraine, unspecified, not intractable", "category": "Neurological"},
    "G43.019": {"description": "Migraine with aura, not intractable", "category": "Neurological"},
    "G47.00": {"description": "Insomnia, unspecified", "category": "Neurological"},
    "G47.33": {"description": "Obstructive sleep apnea", "category": "Neurological"},
    "G40.909": {"description": "Epilepsy, unspecified, not intractable", "category": "Neurological"},
    "G35": {"description": "Multiple sclerosis", "category": "Neurological"},
    "G30.9": {"description": "Alzheimer's disease, unspecified", "category": "Neurological"},
    "G20": {"description": "Parkinson's disease", "category": "Neurological"},
    # Mental Health
    "F32.9": {"description": "Major depressive disorder, single episode, unspecified", "category": "Mental Health"},
    "F33.9": {"description": "Major depressive disorder, recurrent, unspecified", "category": "Mental Health"},
    "F41.1": {"description": "Generalized anxiety disorder", "category": "Mental Health"},
    "F41.0": {"description": "Panic disorder without agoraphobia", "category": "Mental Health"},
    "F40.10": {"description": "Social phobia, unspecified", "category": "Mental Health"},
    "F43.10": {"description": "Post-traumatic stress disorder, unspecified", "category": "Mental Health"},
    "F90.0": {"description": "ADHD, predominantly inattentive type", "category": "Mental Health"},
    "F90.1": {"description": "ADHD, predominantly hyperactive type", "category": "Mental Health"},
    "F90.2": {"description": "ADHD, combined type", "category": "Mental Health"},
    "F31.9": {"description": "Bipolar disorder, unspecified", "category": "Mental Health"},
    "F20.9": {"description": "Schizophrenia, unspecified", "category": "Mental Health"},
    # GI
    "K21.0": {"description": "GERD with esophagitis", "category": "GI"},
    "K21.9": {"description": "GERD without esophagitis", "category": "GI"},
    "K57.30": {"description": "Diverticulosis of large intestine without perforation", "category": "GI"},
    "K92.1": {"description": "Melena", "category": "GI"},
    "K59.00": {"description": "Constipation, unspecified", "category": "GI"},
    "K58.9": {"description": "Irritable bowel syndrome without diarrhea", "category": "GI"},
    "K58.0": {"description": "Irritable bowel syndrome with diarrhea", "category": "GI"},
    "K76.0": {"description": "Fatty (change of) liver, not elsewhere classified", "category": "GI"},
    "K29.70": {"description": "Gastritis, unspecified, without bleeding", "category": "GI"},
    # Skin
    "L40.0": {"description": "Psoriasis vulgaris", "category": "Skin"},
    "L20.9": {"description": "Atopic dermatitis, unspecified", "category": "Skin"},
    "L30.9": {"description": "Dermatitis, unspecified", "category": "Skin"},
    "L70.0": {"description": "Acne vulgaris", "category": "Skin"},
    "L50.9": {"description": "Urticaria, unspecified", "category": "Skin"},
    "B35.4": {"description": "Tinea corporis (ringworm)", "category": "Skin"},
    # Genitourinary
    "N40.0": {"description": "Benign prostatic hyperplasia without obstruction", "category": "GU"},
    "N18.3": {"description": "Chronic kidney disease, stage 3", "category": "GU"},
    "N39.0": {"description": "Urinary tract infection, site unspecified", "category": "GU"},
    "N20.0": {"description": "Calculus of kidney (kidney stone)", "category": "GU"},
    "N95.1": {"description": "Menopausal and female climacteric states", "category": "GU"},
    # Preventive / Screening
    "Z00.00": {"description": "General adult medical exam without abnormal findings", "category": "Preventive"},
    "Z00.01": {"description": "General adult medical exam with abnormal findings", "category": "Preventive"},
    "Z12.31": {"description": "Encounter for screening mammogram for malignant neoplasm of breast", "category": "Preventive"},
    "Z12.11": {"description": "Encounter for screening for malignant neoplasm of colon", "category": "Preventive"},
    "Z23": {"description": "Encounter for immunization", "category": "Preventive"},
    "Z82.49": {"description": "Family history of ischemic heart disease", "category": "Preventive"},
    # Injuries
    "S09.90XA": {"description": "Unspecified injury of head, initial encounter", "category": "Injury"},
    "S72.001A": {"description": "Fracture of femoral neck, initial encounter", "category": "Injury"},
    "S93.401A": {"description": "Sprain of unspecified ligament of right ankle, initial encounter", "category": "Injury"},
    # Infections
    "A49.01": {"description": "MRSA infection, unspecified site", "category": "Infection"},
    "B19.9": {"description": "Unspecified viral hepatitis", "category": "Infection"},
    "J09.X1": {"description": "Influenza due to identified novel influenza A virus", "category": "Infection"},
    "A41.9": {"description": "Sepsis, unspecified organism", "category": "Infection"},
}

# ── Denial reason codes ────────────────────────────────────────────────────────

DENIAL_REASONS: dict[str, str] = {
    "CO-4": "Service is not covered by this plan",
    "CO-11": "Diagnosis inconsistent with procedure",
    "CO-15": "Payment adjusted due to authorization not obtained",
    "CO-22": "Duplicate claim",
    "CO-29": "The time limit for filing has expired",
    "CO-45": "Charge exceeds fee schedule/maximum allowable",
    "CO-50": "Not medically necessary",
    "CO-55": "Procedure inconsistent with patient's age",
    "CO-57": "Charge exceeds fee schedule for out-of-network",
    "CO-97": "Payment is included in allowance for another service",
    "CO-119": "Benefit maximum for this time period has been reached",
    "CO-167": "Diagnosis is not covered",
    "CO-197": "Precertification required",
    "PR-1": "Deductible amount",
    "PR-2": "Coinsurance amount",
    "PR-3": "Copay amount",
    "PR-27": "Expenses incurred after coverage terminated",
    "PR-96": "Non-covered charge",
    "OA-18": "Duplicate claim",
    "OA-23": "Claim was paid in a prior adjudication",
}


# ── Claim generation helpers ──────────────────────────────────────────────────

def lookup_cpt(code: str) -> dict[str, Any] | None:
    return CPT_CODES.get(code.strip().upper())


def lookup_icd10(code: str) -> dict[str, str] | None:
    return ICD10_CODES.get(code.strip().upper())


def search_cpt(query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = query.lower()
    results = []
    for code, info in CPT_CODES.items():
        if q in info["description"].lower() or q in code.lower() or q in info["category"].lower():
            results.append({"code": code, **info})
        if len(results) >= limit:
            break
    return results


def search_icd10(query: str, limit: int = 10) -> list[dict[str, str]]:
    q = query.lower()
    results = []
    for code, info in ICD10_CODES.items():
        if q in info["description"].lower() or q in code.lower() or q in info["category"].lower():
            results.append({"code": code, **info})
        if len(results) >= limit:
            break
    return results


def calculate_claim_total(procedure_codes: list[dict[str, Any]]) -> float:
    total = 0.0
    for pc in procedure_codes:
        code = pc.get("code", "")
        qty = float(pc.get("quantity", 1))
        ref = CPT_CODES.get(code)
        if ref:
            total += ref["fee"] * qty
        elif "fee" in pc:
            total += float(pc["fee"]) * qty
    return round(total, 2)


def generate_claim_from_encounter(encounter_data: dict[str, Any], patient_data: dict[str, Any]) -> dict[str, Any]:
    soap = encounter_data.get("soap", {})
    icd10_codes = [c["code"] for c in soap.get("icd10_codes", [])]
    cpt_codes = soap.get("cpt_codes", [])
    total = calculate_claim_total(cpt_codes)
    return {
        "patient_id": encounter_data["patient_id"],
        "patient_name": encounter_data.get("patient_name", ""),
        "encounter_id": encounter_data["id"],
        "date_of_service": encounter_data.get("date", ""),
        "provider_npi": encounter_data.get("provider_npi", ""),
        "provider_name": encounter_data.get("provider", ""),
        "diagnosis_codes": icd10_codes,
        "procedure_codes": cpt_codes,
        "total_charge": total,
        "insurance_name": patient_data.get("insurance_name", ""),
        "insurance_id": patient_data.get("insurance_id", ""),
    }
