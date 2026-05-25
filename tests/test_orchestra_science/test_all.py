from __future__ import annotations

import asyncio
import unittest


class TestScienceConfig(unittest.TestCase):
    def test_default_config(self):
        from orchestra_science.config import ScienceConfig
        cfg = ScienceConfig()
        self.assertEqual(cfg.model_provider, "opencode")
        self.assertEqual(cfg.model, "opencode")
        self.assertEqual(cfg.pubchem_base_url, "https://pubchem.ncbi.nlm.nih.gov/rest/pug")
        self.assertEqual(cfg.citation_style, "apa")


class TestScienceEngine(unittest.TestCase):
    def test_task_types(self):
        from orchestra_science.engine import ScienceTaskType
        self.assertIn("RESEARCH", ScienceTaskType.__members__)
        self.assertIn("ANALYSIS", ScienceTaskType.__members__)
        self.assertIn("REPORT", ScienceTaskType.__members__)

    def test_science_task_creation(self):
        from orchestra_science.engine import ScienceTask, ScienceTaskType
        task = ScienceTask(
            task_type=ScienceTaskType.ANALYSIS,
            description="Test analysis",
            context={"key": "value"},
        )
        self.assertEqual(task.task_type, ScienceTaskType.ANALYSIS)
        self.assertEqual(task.description, "Test analysis")
        self.assertEqual(task.context, {"key": "value"})

    def test_science_result(self):
        from orchestra_science.engine import ScienceResult, ScienceTask, ScienceTaskType
        task = ScienceTask(task_type=ScienceTaskType.RESEARCH, description="test")
        result = ScienceResult(
            task=task,
            content="Result content",
            duration=1.5,
            model_used="opencode",
            provider_used="opencode",
        )
        d = result.to_dict()
        self.assertEqual(d["task_type"], "research")
        self.assertEqual(d["content"], "Result content")
        self.assertEqual(d["duration"], 1.5)

    def test_result_with_error(self):
        from orchestra_science.engine import ScienceResult, ScienceTask, ScienceTaskType
        task = ScienceTask(task_type=ScienceTaskType.ANALYSIS, description="test")
        result = ScienceResult(task=task, error="Something broke")
        self.assertEqual(result.error, "Something broke")
        d = result.to_dict()
        self.assertEqual(d["error"], "Something broke")

    def test_system_prompt_builds(self):
        from orchestra_science.engine import ScienceEngine, ScienceTask, ScienceTaskType
        engine = ScienceEngine()
        task = ScienceTask(task_type=ScienceTaskType.ANALYSIS, description="test")
        prompt = engine._build_system_prompt(task)
        self.assertIn("Orchestra Science", prompt)
        self.assertIn("analyzing", prompt.lower())

        task2 = ScienceTask(task_type=ScienceTaskType.REPORT, description="test")
        prompt2 = engine._build_system_prompt(task2)
        self.assertIn("Abstract", prompt2)


class TestPubChemClient(unittest.TestCase):
    def test_compound_dataclass(self):
        from orchestra_science.ingestion.pubchem import Compound
        c = Compound(cid=2244, smiles="CC(=O)OC1=CC=CC=C1C(=O)O", iupac_name="aspirin")
        self.assertEqual(c.cid, 2244)
        self.assertEqual(c.iupac_name, "aspirin")
        d = c.to_dict()
        self.assertEqual(d["cid"], 2244)
        self.assertEqual(d["iupac_name"], "aspirin")

    def test_compound_property_dataclass(self):
        from orchestra_science.ingestion.pubchem import CompoundProperty
        p = CompoundProperty(cid=2244, name="MolecularWeight", value=180.16, units="g/mol")
        self.assertEqual(p.name, "MolecularWeight")
        self.assertEqual(p.value, 180.16)

    def test_assay_dataclass(self):
        from orchestra_science.ingestion.pubchem import Assay
        a = Assay(aid=1234, name="Inhibitor assay", organism="Homo sapiens")
        self.assertEqual(a.aid, 1234)
        self.assertEqual(a.organism, "Homo sapiens")

    def test_namespace_constants(self):
        from orchestra_science.ingestion.pubchem import (
            CID_NAMESPACE, NAME_NAMESPACE, SMILES_NAMESPACE, INCHI_NAMESPACE, INCHIKEY_NAMESPACE,
        )
        self.assertEqual(CID_NAMESPACE, "cid")
        self.assertEqual(NAME_NAMESPACE, "name")
        self.assertEqual(SMILES_NAMESPACE, "smiles")

    def test_search_url_format(self):
        from orchestra_science.ingestion.pubchem import PubChemClient
        client = PubChemClient()
        expected = f"{client.BASE}/compound/name/aspirin/property/MolecularFormula,MolecularWeight,IUPACName,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Charge,HeavyAtomCount,CanonicalSMILES/JSON"
        self.assertIn("aspirin", expected)
        self.assertIn("CanonicalSMILES", expected)


def _has_rdkit():
    try:
        import rdkit
        return True
    except ImportError:
        return False

def _has_biopython():
    try:
        import Bio
        return True
    except ImportError:
        return False

@unittest.skipIf(not _has_rdkit(), "RDKit not installed")
class TestRDKitMolProcessor(unittest.TestCase):

    def setUp(self):
        from orchestra_science.ingestion.rdkit import RDKitMolProcessor
        self.processor = RDKitMolProcessor(smiles="CC(=O)OC1=CC=CC=C1C(=O)O")

    def test_smiles_roundtrip(self):
        s = self.processor.to_smiles()
        self.assertIn("CC", s)

    def test_molecular_properties(self):
        self.assertGreater(self.processor.molecular_weight(), 100)
        self.assertGreater(self.processor.h_bond_donors(), 0)
        self.assertGreater(self.processor.h_bond_acceptors(), 1)

    def test_fingerprint(self):
        fp = self.processor.morgan_fingerprint(radius=2, n_bits=2048)
        self.assertEqual(len(fp), 2048)

    def test_substructure_search(self):
        self.assertTrue(self.processor.substructure_search("C1=CC=CC=C1"))
        self.assertFalse(self.processor.substructure_search("C1CCCCC1"))

    def test_similarity_to_self(self):
        from orchestra_science.ingestion.rdkit import RDKitMolProcessor
        other = RDKitMolProcessor(smiles="CC(=O)OC1=CC=CC=C1C(=O)O")
        sim = self.processor.similarity_to(other)
        self.assertAlmostEqual(sim, 1.0, places=4)


class TestBioSeqAnalyzer(unittest.TestCase):
    def test_seq_type_detection_dna(self):
        from orchestra_science.ingestion.biopython import BioSeqAnalyzer
        if not _has_biopython():
            raise unittest.SkipTest("BioPython not installed")
        analyzer = BioSeqAnalyzer()
        record = analyzer.from_string("ATGCGTACGATCGTAGCTAGCTAGCTAGCTAGCTAGC")
        self.assertEqual(record.seq_type, "dna")
        self.assertGreater(record.gc_content, 0)

    def test_seq_type_detection_protein(self):
        from orchestra_science.ingestion.biopython import BioSeqAnalyzer
        if not _has_biopython():
            raise unittest.SkipTest("BioPython not installed")
        analyzer = BioSeqAnalyzer()
        record = analyzer.from_string("MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHF")
        self.assertEqual(record.seq_type, "protein")

    def test_reverse_complement(self):
        from orchestra_science.ingestion.biopython import BioSeqAnalyzer
        if not _has_biopython():
            raise unittest.SkipTest("BioPython not installed")
        analyzer = BioSeqAnalyzer()
        rc = analyzer.reverse_complement("ATGC")
        self.assertEqual(rc, "GCAT")

    def test_translate(self):
        from orchestra_science.ingestion.biopython import BioSeqAnalyzer
        if not _has_biopython():
            raise unittest.SkipTest("BioPython not installed")
        analyzer = BioSeqAnalyzer()
        prot = analyzer.translate("ATGGTGCTGTCCCCCGCCAAGACC")
        self.assertIn("M", prot)

    def test_pairwise_alignment(self):
        from orchestra_science.ingestion.biopython import BioSeqAnalyzer
        if not _has_biopython():
            raise unittest.SkipTest("BioPython not installed")
        analyzer = BioSeqAnalyzer()
        result = analyzer.align_pairwise("ATGC", "ATGC")
        self.assertEqual(result.identity, 100.0)

    def test_alignment_dataclass(self):
        from orchestra_science.ingestion.biopython import AlignmentResult
        a = AlignmentResult(seq1="ATGC", seq2="ATGC", score=8.0, identity=100.0)
        self.assertEqual(a.identity, 100.0)


class TestPyMolStructure(unittest.TestCase):
    def test_structure_creation(self):
        from orchestra_science.ingestion.pymol import PyMolStructure
        s = PyMolStructure(pdb_code="1ake")
        self.assertEqual(s.pdb_code, "1ake")
        self.assertFalse(s._loaded)

    def test_visualize_returns_string(self):
        from orchestra_science.ingestion.pymol import PyMolStructure
        s = PyMolStructure(pdb_code="1ake")
        result = s.visualize()
        self.assertIn("queued", result)

    def test_to_task(self):
        from orchestra_science.ingestion.pymol import PyMolStructure
        s = PyMolStructure(pdb_code="1ake")
        task = s.to_task("analyze")
        self.assertEqual(task["task_type"], "molecular_structure")
        self.assertIn("1ake", task["description"])


class TestCheminformaticsAnalyzer(unittest.TestCase):
    def test_check_lipinski_no_rdkit(self):
        from orchestra_science.analysis.cheminformatics import CheminformaticsAnalyzer
        analyzer = CheminformaticsAnalyzer()
        result = analyzer.check_lipinski("CC(=O)OC1=CC=CC=C1C(=O)O")
        if analyzer._has_rdkit:
            self.assertIn("passes", result)
        else:
            self.assertIn("error", result)

    def test_similarity_result_dataclass(self):
        from orchestra_science.analysis.cheminformatics import SimilarityResult
        r = SimilarityResult(target_smiles="CCO", query_smiles="CC", tanimoto=0.5)
        self.assertEqual(r.tanimoto, 0.5)
        self.assertEqual(r.target_smiles, "CCO")

    def test_descriptor_set_dataclass(self):
        from orchestra_science.analysis.cheminformatics import DescriptorSet
        ds = DescriptorSet(smiles="CCO", descriptors={"MW": 46.07})
        self.assertEqual(ds.descriptors["MW"], 46.07)


class TestBioinformaticsAnalyzer(unittest.TestCase):
    def test_analyze_sequence_no_biopython(self):
        from orchestra_science.analysis.bioinformatics import BioinformaticsAnalyzer
        analyzer = BioinformaticsAnalyzer()
        result = asyncio.new_event_loop().run_until_complete(
            analyzer.analyze_sequence("ATGCGTACG", engine=None)
        )
        self.assertIn("sequence_stats", result)


class TestScienceVisualizer(unittest.TestCase):
    def test_histogram_no_mpl(self):
        from orchestra_science.analysis.visualization import ScienceVisualizer
        viz = ScienceVisualizer()
        result = viz.plot_histogram([1, 2, 3], "/tmp/test.png")
        if not viz._has_mpl:
            self.assertIn("matplotlib", result)

    def test_scatter_no_mpl(self):
        from orchestra_science.analysis.visualization import ScienceVisualizer
        viz = ScienceVisualizer()
        result = viz.plot_scatter([1, 2, 3], [4, 5, 6], "/tmp/test.png")
        if not viz._has_mpl:
            self.assertIn("matplotlib", result)


class TestDockingWorkflow(unittest.TestCase):
    def test_to_dag(self):
        from orchestra_science.workflows.molecular_docking import DockingWorkflow
        wf = DockingWorkflow()
        dag = wf.to_dag()
        self.assertEqual(dag["workflow_id"], "molecular_docking")
        self.assertGreater(len(dag["steps"]), 3)
        self.assertEqual(dag["steps"][0]["id"], "fetch_protein")

    def test_docking_result_dataclass(self):
        from orchestra_science.workflows.molecular_docking import DockingResult
        r = DockingResult(protein_pdb="1ake", ligand_smiles="CCO")
        self.assertEqual(r.protein_pdb, "1ake")
        self.assertEqual(r.ligand_smiles, "CCO")


class TestLitReviewWorkflow(unittest.TestCase):
    def test_generate_sub_questions(self):
        from orchestra_science.workflows.literature_review import LitReviewWorkflow
        wf = LitReviewWorkflow()
        questions = wf._generate_sub_questions("CRISPR-Cas9")
        self.assertEqual(len(questions), 5)
        self.assertTrue(any("CRISPR-Cas9" in q for q in questions))

    def test_deduplicate_sources(self):
        from orchestra_science.workflows.literature_review import LitReviewWorkflow
        wf = LitReviewWorkflow()
        sources = [
            {"url": "https://example.com/1", "title": "A"},
            {"url": "https://example.com/1", "title": "A"},
            {"url": "https://example.com/2", "title": "B"},
        ]
        deduped = wf._deduplicate_sources(sources)
        self.assertEqual(len(deduped), 2)

    def test_estimate_confidence(self):
        from orchestra_science.workflows.literature_review import LitReviewWorkflow
        wf = LitReviewWorkflow()
        sections = {"intro": "Some text [1] with citation [2]"}
        confidence = wf._estimate_confidence(sections)
        self.assertGreater(confidence, 0)

    def test_review_result_dataclass(self):
        from orchestra_science.workflows.literature_review import ReviewResult
        r = ReviewResult(topic="CRISPR", summary="Summary text")
        self.assertEqual(r.topic, "CRISPR")
        self.assertEqual(r.summary, "Summary text")


class TestReportGenerator(unittest.TestCase):
    def test_lab_protocol(self):
        from orchestra_science.reporting.report_generator import ScienceReportGenerator
        r = ScienceReportGenerator(output_dir="/tmp")
        protocol = r.generate_lab_protocol(
            title="PCR Amplification",
            objective="Amplify target DNA sequence",
            materials=["Template DNA", "Primers", "Polymerase"],
            procedure=["Mix reagents", "Run thermocycler"],
        )
        self.assertIn("PCR Amplification", protocol)
        self.assertIn("Mix reagents", protocol)
        self.assertIn("Run thermocycler", protocol)
        self.assertIn("Materials", protocol)

    def test_save_report(self):
        import tempfile, os
        from orchestra_science.reporting.report_generator import ScienceReportGenerator
        tmpdir = tempfile.mkdtemp()
        r = ScienceReportGenerator(output_dir=tmpdir)
        content = "# Test Report\n\nContent here"
        path = r.save_report(content, "test_report")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            self.assertIn("Test Report", f.read())

    def test_report_format_enum(self):
        from orchestra_science.reporting.report_generator import ReportFormat
        self.assertIn("MARKDOWN", ReportFormat.__members__)
        self.assertIn("PDF", ReportFormat.__members__)
        self.assertIn("LATEX", ReportFormat.__members__)

    def test_report_section_dataclass(self):
        from orchestra_science.reporting.report_generator import ReportSection
        sec = ReportSection(title="Methods", content="PCR was performed")
        self.assertEqual(sec.title, "Methods")
        sub = ReportSection(title="Thermocycling", content="95C for 30s")
        sec.subsections.append(sub)
        self.assertEqual(len(sec.subsections), 1)


class TestIntegrationAdapter(unittest.TestCase):
    def test_get_tool_definitions(self):
        from orchestra_science.integration.adapter import ScienceAdapter
        adapter = ScienceAdapter()
        tools = adapter.get_tool_definitions()
        self.assertGreater(len(tools), 0)
        names = [t["name"] for t in tools]
        self.assertIn("science_analyze", names)
        self.assertIn("science_pubchem_search", names)
        self.assertIn("science_literature_review", names)

    def test_get_routes(self):
        from orchestra_science.integration.adapter import ScienceAdapter
        adapter = ScienceAdapter()
        routes = adapter.get_routes()
        self.assertEqual(routes["prefix"], "/api/science")
        self.assertIn("pubchem_compound_search", routes["capabilities"])


class TestPackageInit(unittest.TestCase):
    def test_version(self):
        from orchestra_science import __version__
        self.assertEqual(__version__, "0.1.0")

    def test_core_exports(self):
        from orchestra_science import (
            ScienceConfig, ScienceEngine, ScienceResult, ScienceTask,
            PubChemClient, Compound,
            CheminformaticsAnalyzer, BioinformaticsAnalyzer, ScienceVisualizer,
            ScienceReportGenerator, ReportFormat,
            create_science_app, ScienceAdapter,
        )
        self.assertIsNotNone(ScienceConfig)
        self.assertIsNotNone(ScienceEngine)

    def test_optional_exports_graceful(self):
        from orchestra_science import RDKitMolProcessor
        self.assertIsNotNone(RDKitMolProcessor)
        if _has_rdkit():
            from orchestra_science.ingestion.rdkit import HAS_RDKIT
            self.assertTrue(HAS_RDKIT)
        else:
            from orchestra_science.ingestion.rdkit import HAS_RDKIT
            self.assertFalse(HAS_RDKIT)

    def test_all_list(self):
        from orchestra_science import __all__
        self.assertIn("ScienceEngine", __all__)
        self.assertIn("PubChemClient", __all__)
        self.assertIn("CheminformaticsAnalyzer", __all__)
        self.assertIn("ScienceAdapter", __all__)


if __name__ == "__main__":
    unittest.main()
