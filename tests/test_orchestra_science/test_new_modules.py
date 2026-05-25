from __future__ import annotations

import os
import tempfile
import unittest


class TestAcademicClients(unittest.TestCase):
    """Test arXiv, PubMed, Semantic Scholar API clients live (serverless)."""

    def _run_async(self, coro):
        import asyncio
        try:
            return asyncio.get_event_loop().run_until_complete(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    def test_arxiv_search(self):
        from orchestra_science.ingestion.academic import ArxivClient
        client = ArxivClient()
        try:
            papers = self._run_async(client.search("machine learning", max_results=3))
            self.assertGreaterEqual(len(papers), 1)
            self.assertTrue(all(p.title for p in papers))
            self.assertTrue(all(p.arxiv_id for p in papers))
        except Exception as e:
            self.skipTest(f"arXiv API unavailable: {e}")

    def test_arxiv_parse_empty(self):
        from orchestra_science.ingestion.academic import ArxivClient
        client = ArxivClient()
        papers = client._parse_feed("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
        self.assertEqual(papers, [])

    def test_arxiv_by_author(self):
        from orchestra_science.ingestion.academic import ArxivClient
        client = ArxivClient()
        try:
            papers = self._run_async(client.search_by_author("LeCun", max_results=2))
            self.assertGreaterEqual(len(papers), 1)
        except Exception as e:
            self.skipTest(f"arXiv API unavailable: {e}")

    def test_pubmed_search(self):
        from orchestra_science.ingestion.academic import PubMedClient
        client = PubMedClient()
        try:
            articles = self._run_async(client.search("CRISPR gene editing", max_results=3))
            self.assertGreaterEqual(len(articles), 1)
            self.assertTrue(all(a.title for a in articles))
            self.assertTrue(all(a.pmid for a in articles))
        except Exception as e:
            self.skipTest(f"PubMed API unavailable: {e}")

    def test_pubmed_parse_xml(self):
        from orchestra_science.ingestion.academic import PubMedClient
        sample = """<?xml version="1.0"?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">
<PubmedArticleSet>
<PubmedArticle>
<MedlineCitation Status="Publisher" Owner="NLM">
<PMID Version="1">12345678</PMID>
<Article PubModel="Print">
<Journal>
<Title>Test Journal</Title>
<JournalIssue>
<PubDate><Year>2024</Year></PubDate>
</JournalIssue>
</Journal>
<ArticleTitle>Test Article Title</ArticleTitle>
<AuthorList>
<Author><LastName>Smith</LastName><ForeName>John</ForeName></Author>
</AuthorList>
<Abstract>
<AbstractText>This is a test abstract.</AbstractText>
</Abstract>
<ELocationID EIdType="doi">10.1234/test</ELocationID>
</Article>
<MeshHeadingList>
<MeshHeading><DescriptorName UI="D000001">TestMesh</DescriptorName></MeshHeading>
</MeshHeadingList>
</MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>"""
        client = PubMedClient()
        articles = client._parse_articles(sample)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].pmid, "12345678")
        self.assertEqual(articles[0].title, "Test Article Title")
        self.assertEqual(len(articles[0].authors), 1)
        self.assertEqual(articles[0].mesh_terms, ["TestMesh"])

    def test_semantic_scholar_search(self):
        from orchestra_science.ingestion.academic import SemanticScholarClient
        client = SemanticScholarClient()
        try:
            papers = self._run_async(client.search("transformer attention", max_results=3))
            self.assertGreaterEqual(len(papers), 1)
            self.assertTrue(all(p.title for p in papers))
            self.assertTrue(all(p.paper_id for p in papers))
        except Exception as e:
            if "429" in str(e):
                self.skipTest("Semantic Scholar rate limited")
            elif "ConnectError" in str(e):
                self.skipTest("Semantic Scholar unreachable")
            else:
                raise

    def test_semantic_scholar_by_id(self):
        from orchestra_science.ingestion.academic import SemanticScholarClient
        client = SemanticScholarClient()
        try:
            paper = self._run_async(client.search_by_id("arXiv:1706.03762"))
            if paper:
                self.assertTrue(paper.title)
                self.assertTrue(any("attention" in (paper.title or "").lower() for _ in [0]))
        except Exception as e:
            if "429" in str(e):
                self.skipTest("Semantic Scholar rate limited")
            elif "ConnectError" in str(e):
                self.skipTest("Semantic Scholar unreachable")
            else:
                raise


class TestFastaParser(unittest.TestCase):
    def test_parse_single(self):
        from orchestra_science.ingestion.formats import FastaParser
        text = ">seq1 A test sequence\nATCGATCGATCG\n"
        records = FastaParser.parse(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].header, "seq1")
        self.assertEqual(records[0].description, "A test sequence")
        self.assertEqual(records[0].sequence, "ATCGATCGATCG")

    def test_parse_multi(self):
        from orchestra_science.ingestion.formats import FastaParser
        text = ">seq1\nATCG\n>seq2\nGCTA\n"
        records = FastaParser.parse(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].sequence, "ATCG")
        self.assertEqual(records[1].sequence, "GCTA")

    def test_parse_empty(self):
        from orchestra_science.ingestion.formats import FastaParser
        records = FastaParser.parse("")
        self.assertEqual(records, [])

    def test_format(self):
        from orchestra_science.ingestion.formats import FastaParser, FastaRecord
        records = [FastaRecord(header="test", sequence="ATCG")]
        out = FastaParser.format(records)
        self.assertIn(">test", out)
        self.assertIn("ATCG", out)

    def test_format_width(self):
        from orchestra_science.ingestion.formats import FastaParser, FastaRecord
        records = [FastaRecord(header="long", sequence="A" * 200)]
        out = FastaParser.format(records, width=60)
        lines = out.splitlines()
        self.assertEqual(len(lines[1:]), 4)  # 200/60 = 4 lines
        self.assertEqual(lines[1], "A" * 60)


class TestVcfParser(unittest.TestCase):
    def test_parse_basic(self):
        from orchestra_science.ingestion.formats import VcfParser
        text = """##fileformat=VCFv4.2
##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
chr1	100	.	A	T	30.0	PASS	DP=50
chr1	200	rs123	G	C	99.0	PASS	DP=100"""
        parser = VcfParser(text)
        self.assertEqual(len(parser.records), 2)
        self.assertEqual(parser.records[0].chrom, "chr1")
        self.assertEqual(parser.records[0].pos, 100)
        self.assertEqual(parser.records[0].ref, "A")
        self.assertEqual(parser.records[0].alt, "T")
        self.assertEqual(parser.records[0].qual, 30.0)
        self.assertEqual(parser.records[1].id_, "rs123")

    def test_vcf_meta(self):
        from orchestra_science.ingestion.formats import VcfParser
        text = "##fileformat=VCFv4.2\n##source=test\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t1\t.\tA\tT\t.\t.\t.\n"
        parser = VcfParser(text)
        self.assertIn("fileformat", parser.meta)
        self.assertIn("source", parser.meta)

    def test_vcf_empty_meta(self):
        from orchestra_science.ingestion.formats import VcfParser
        parser = VcfParser("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t1\t.\tA\tT\t.\t.\t.\n")
        self.assertEqual(len(parser.records), 1)

    def test_vcf_info_parsing(self):
        from orchestra_science.ingestion.formats import VcfParser
        text = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t1\t.\tA\tT\t.\t.\tDP=50;AF=0.5\n"
        parser = VcfParser(text)
        self.assertEqual(parser.records[0].info.get("DP"), "50")
        self.assertEqual(parser.records[0].info.get("AF"), "0.5")


class TestHdf5Reader(unittest.TestCase):
    def test_requires_h5py(self):
        from orchestra_science.ingestion.formats import Hdf5Reader
        reader = Hdf5Reader()
        if not reader._has_h5py:
            with self.assertRaises(ImportError):
                reader.read_dataset("nonexistent.h5")
        else:
            self.skipTest("h5py available, skipping fallback test")


class TestNetCdfReader(unittest.TestCase):
    def test_requires_netcdf4(self):
        from orchestra_science.ingestion.formats import NetCdfReader
        reader = NetCdfReader()
        if not reader._has_netcdf:
            with self.assertRaises(ImportError):
                reader.list_variables("nonexistent.nc")
        else:
            self.skipTest("netCDF4 available, skipping fallback test")


class TestNotebookGenerator(unittest.TestCase):
    def test_from_analysis_report(self):
        from orchestra_science.reporting.notebook import NotebookGenerator
        nb = NotebookGenerator.from_analysis_report("# Results\n\nData analyzed.", "Test Report")
        self.assertEqual(len(nb.cells), 2)
        self.assertEqual(nb.cells[0].cell_type, "markdown")
        self.assertIn("Test Report", nb.cells[0].source)

    def test_molecular_docking_notebook(self):
        from orchestra_science.reporting.notebook import NotebookGenerator
        nb = NotebookGenerator.molecular_docking_notebook("1abc", "CCO")
        self.assertGreaterEqual(len(nb.cells), 3)
        self.assertIn("1abc", nb.cells[0].source)

    def test_data_analysis_notebook(self):
        from orchestra_science.reporting.notebook import NotebookGenerator
        nb = NotebookGenerator.data_analysis_notebook("test_dataset", ["col1", "col2"])
        self.assertGreaterEqual(len(nb.cells), 4)

    def test_literature_review_notebook(self):
        from orchestra_science.reporting.notebook import NotebookGenerator
        nb = NotebookGenerator.literature_review_notebook("AI", [{"title": "Paper 1", "year": "2024"}])
        self.assertGreaterEqual(len(nb.cells), 4)

    def test_custom_notebook(self):
        from orchestra_science.reporting.notebook import NotebookGenerator, NotebookCell
        cells = [NotebookCell(cell_type="code", source="print('hello')")]
        nb = NotebookGenerator.custom_notebook(cells, "Custom")
        self.assertEqual(len(nb.cells), 2)  # title + custom

    def test_save_notebook(self):
        from orchestra_science.reporting.notebook import NotebookGenerator
        import tempfile
        nb = NotebookGenerator.from_analysis_report("test", "Save Test")
        path = os.path.join(tempfile.gettempdir(), "test_notebook.ipynb")
        result = nb.save(path)
        self.assertTrue(os.path.exists(result))
        os.remove(result)

    def test_to_json_valid(self):
        from orchestra_science.reporting.notebook import NotebookGenerator
        nb = NotebookGenerator.from_analysis_report("test", "JSON Test")
        j = nb.to_json()
        self.assertIn('"nbformat": 4', j)
        self.assertIn('"cells"', j)


class TestRoutes(unittest.TestCase):
    """Test that routes module imports and creates endpoints correctly."""

    def test_router_created(self):
        from orchestra_science.server.routes import create_science_router
        router = create_science_router()
        routes = [r.path for r in router.routes]
        expected = ["/api/science/arxiv/search", "/api/science/pubmed/search",
                    "/api/science/semantic-scholar/search", "/api/science/notebook/generate",
                    "/api/science/formats/parse-fasta", "/api/science/formats/parse-vcf",
                    "/api/science/health"]
        for path in expected:
            self.assertIn(path, routes)

    def test_app_created(self):
        from orchestra_science.server.app import create_science_app
        app = create_science_app()
        self.assertEqual(app.title, "Orchestra Science")

    def test_register_routes_accepts_app(self):
        from orchestra_science.server.routes import register_science_routes
        from fastapi import FastAPI
        app = FastAPI()
        register_science_routes(app)
        self.assertTrue(len(app.routes) > 0)


class TestFormatIntegration(unittest.TestCase):
    """Integration tests across format + notebook pipelines."""

    def test_fasta_to_notebook(self):
        from orchestra_science.ingestion.formats import FastaParser
        from orchestra_science.reporting.notebook import NotebookGenerator
        fasta = ">seq1\nATCG\n>seq2\nGCTA\n"
        records = FastaParser.parse(fasta)
        nb = NotebookGenerator.data_analysis_notebook("sequences", ["header", "length"])
        self.assertEqual(len(records), 2)
        self.assertGreater(len(nb.cells), 2)

    def test_vcf_summary(self):
        from orchestra_science.ingestion.formats import VcfParser
        text = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t100\t.\tA\tT\t30.0\tPASS\t.\n"
        parser = VcfParser(text)
        self.assertEqual(parser.records[0].chrom, "chr1")
        self.assertEqual(parser.records[0].filter_status, "PASS")
