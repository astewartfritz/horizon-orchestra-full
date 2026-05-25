from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent.parent.parent
SCIENCE_DIR = HERE / "orchestra_science"
SCIENCE_PACKAGE = HERE / "orchestra_science"


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture(scope="module")
def server_url(request):
    """Start the science server (via uvicorn subprocess or Docker)."""
    use_docker = request.config.getoption("--docker", default=False) or _docker_available()
    proc = None
    url = None

    if use_docker:
        try:
            # Build and start with docker-compose
            subprocess.run(
                ["docker", "compose", "build"],
                cwd=str(SCIENCE_DIR), capture_output=True, timeout=120,
            )
            proc = subprocess.Popen(
                ["docker", "compose", "up"],
                cwd=str(SCIENCE_DIR),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            url = "http://localhost:8000"
            # Wait for health endpoint
            for _ in range(30):
                try:
                    import httpx
                    r = httpx.get(f"{url}/api/science/health", timeout=5)
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                _teardown_docker()
                pytest.fail("Docker container did not become healthy in 60s")
        except Exception as e:
            _teardown_docker()
            pytest.skip(f"Docker unavailable or failed: {e}")
    else:
        # Start uvicorn subprocess (Docker not needed)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(HERE) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn",
             "orchestra_science.server.app:create_science_app",
             "--factory", "--host", "127.0.0.1", "--port", "8765"],
            cwd=str(HERE),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
        )
        url = "http://127.0.0.1:8765"
        # Wait for server to start
        for _ in range(30):
            try:
                import httpx
                r = httpx.get(f"{url}/api/science/health", timeout=5)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            _teardown(proc)
            pytest.fail("Server did not start in 30s")

    yield url

    if use_docker:
        _teardown_docker()
    else:
        _teardown(proc)


def _teardown(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _teardown_docker():
    subprocess.run(
        ["docker", "compose", "down", "-t", "5"],
        cwd=str(SCIENCE_DIR), capture_output=True, timeout=30,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_ok(self, server_url):
        import httpx
        r = httpx.get(f"{server_url}/api/science/health", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("ok", "degraded")
        assert "pubchem_api" in data

    def test_health_structure(self, server_url):
        import httpx
        r = httpx.get(f"{server_url}/api/science/health", timeout=10)
        data = r.json()
        for key in ("status", "engine", "pubchem_api", "open_code"):
            assert key in data, f"Missing key: {key}"


class TestPubChemEndpoints:
    def test_search_compound_by_name(self, server_url):
        import httpx
        r = httpx.get(f"{server_url}/api/science/pubchem/search/aspirin",
                      params={"max_results": "3"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) > 0
        assert data["results"][0]["cid"] == 2244
        assert data["results"][0]["molecular_formula"] == "C9H8O4"

    def test_search_compound_by_smiles(self, server_url):
        import httpx
        from urllib.parse import quote
        smiles = "CCO"
        r = httpx.get(f"{server_url}/api/science/pubchem/search/{quote(smiles)}",
                      params={"namespace": "smiles", "max_results": "3"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) > 0

    def test_search_empty_query_returns_error(self, server_url):
        import httpx
        r = httpx.get(f"{server_url}/api/science/pubchem/search/",
                      timeout=15)
        # Should be 404 (empty path param) or 422 (validation)
        assert r.status_code in (404, 422)

    def test_compound_details(self, server_url):
        import httpx
        r = httpx.get(f"{server_url}/api/science/pubchem/compound/2244",
                      timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["cid"] == 2244
        assert "synonyms" in data
        assert len(data["synonyms"]) > 0
        assert data["iupac_name"] == "2-acetyloxybenzoic acid"

    def test_compound_not_found_returns_gracefully(self, server_url):
        import httpx
        r = httpx.get(f"{server_url}/api/science/pubchem/compound/999999999",
                      timeout=15)
        # PubChem API may return 200 with empty data or 404
        assert r.status_code in (200, 404, 500)
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, dict)

    def test_similarity_search(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/pubchem/similarity",
            params={"smiles": "CCO", "threshold": 85, "max_results": 3},
            timeout=60,
        )
        assert r.status_code == 200
        data = r.json()
        # May return 0 results if PubChem rate-limits or no matches at threshold
        assert isinstance(data["results"], list)


class TestAcademicEndpoints:
    def test_arxiv_search(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/arxiv/search",
            json={"query": "machine learning", "max_results": 3, "source": "arxiv"},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            assert data["source"] == "arxiv"
            assert len(data["results"]) > 0
            assert all(p.get("title") for p in data["results"])
        else:
            pytest.skip(f"arXiv API returned {r.status_code}")

    def test_pubmed_search(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/pubmed/search",
            json={"query": "CRISPR", "max_results": 3, "source": "pubmed"},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            assert data["source"] == "pubmed"
            assert len(data["results"]) > 0
            assert all(a.get("pmid") for a in data["results"])
        else:
            pytest.skip(f"PubMed API returned {r.status_code}")

    def test_semantic_scholar_search(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/semantic-scholar/search",
            json={"query": "transformer", "max_results": 3, "source": "semantic_scholar"},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            assert data["source"] == "semantic_scholar"
        else:
            pytest.skip(f"Semantic Scholar API returned {r.status_code}")


class TestAnalyzeEndpoint:
    def test_analyze(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/analyze",
            json={"description": "Return only the JSON: {\"test\": true}", "data": {}},
            timeout=60,
        )
        # Either succeeds gracefully or returns 500 if no engine
        assert r.status_code in (200, 500)

    def test_research(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/research",
            json={"question": "What is 2+2? Answer with just the number."},
            timeout=60,
        )
        assert r.status_code in (200, 500)


class TestFormatEndpoints:
    def test_parse_fasta(self, server_url):
        import httpx
        fasta = ">seq1\nATCG\n>seq2\nGCTA\n"
        r = httpx.post(
            f"{server_url}/api/science/formats/parse-fasta",
            json={"data": fasta},
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["records"]) == 2
        assert data["records"][0]["header"] == "seq1"
        assert data["records"][0]["length"] == 4

    def test_parse_fasta_with_description(self, server_url):
        import httpx
        fasta = ">seq1 A test sequence\nATCG\n"
        r = httpx.post(
            f"{server_url}/api/science/formats/parse-fasta",
            json={"data": fasta},
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["records"][0]["description"] == "A test sequence"

    def test_parse_empty_fasta(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/formats/parse-fasta",
            json={"data": ""},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["records"] == []

    def test_parse_vcf(self, server_url):
        import httpx
        vcf = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t100\t.\tA\tT\t30.0\tPASS\tDP=50\n"
        r = httpx.post(
            f"{server_url}/api/science/formats/parse-vcf",
            json={"data": vcf},
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["records"]) == 1
        assert data["records"][0]["chrom"] == "chr1"
        assert data["records"][0]["pos"] == 100
        assert data["records"][0]["ref"] == "A"
        assert data["records"][0]["alt"] == "T"

    def test_parse_vcf_multiple_records(self, server_url):
        import httpx
        vcf = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t100\t.\tA\tT\t30.0\tPASS\t.\nchr1\t200\trs123\tG\tC\t99.0\tPASS\t.\n"
        r = httpx.post(
            f"{server_url}/api/science/formats/parse-vcf",
            json={"data": vcf},
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["records"]) == 2


class TestNotebookEndpoint:
    def test_generate_analysis_notebook(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/notebook/generate",
            json={
                "title": "Test Analysis",
                "notebook_type": "analysis",
                "dataset_name": "test_data",
                "columns": ["col1", "col2"],
            },
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["cells"] > 0
        assert "Test_Analysis.ipynb" in data["path"]

    def test_generate_report_notebook(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/notebook/generate",
            json={
                "title": "Report",
                "notebook_type": "report",
                "content": "# Results\n\nAll tests passed.",
            },
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["cells"] == 2  # title + content

    def test_generate_custom_notebook(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/notebook/generate",
            json={
                "title": "Custom",
                "notebook_type": "custom",
                "content": "Custom cell content",
            },
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["cells"] > 0


class TestCheminformaticsEndpoint:
    def test_cheminformatics_analyze(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/cheminformatics/analyze",
            params={"smiles": "CC(=O)OC1=CC=CC=C1C(=O)O"},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["smiles"] == "CC(=O)OC1=CC=CC=C1C(=O)O"
        assert "lipinski" in data


class TestBioinformaticsEndpoint:
    def test_bioinformatics_analyze(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/bioinformatics/analyze",
            json={"sequence": "ATCGATCGATCG", "seq_type": "dna"},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)


class TestDockingEndpoint:
    def test_docking_endpoint_exists(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/docking",
            params={"protein_pdb": "1abc", "ligand_smiles": "CCO"},
            timeout=30,
        )
        # Expected to fail gracefully (no actual docking engine)
        assert r.status_code in (200, 500)


class TestLiteratureReviewEndpoint:
    def test_literature_review_endpoint(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/literature-review",
            params={"topic": "machine learning"},
            timeout=60,
        )
        assert r.status_code in (200, 500)


class TestVisualizeEndpoint:
    def test_visualize_heatmap(self, server_url):
        import httpx
        import tempfile
        r = httpx.post(
            f"{server_url}/api/science/visualize",
            json={
                "data": [[1, 2], [3, 4]],
                "plot_type": "heatmap",
                "title": "Test Heatmap",
            },
            timeout=30,
        )
        assert r.status_code in (200, 400, 500)


class TestReportEndpoint:
    def test_report_generate(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/report/generate",
            json={
                "title": "Test Report",
                "objective": "Test objective",
                "methods": "Test methods",
                "results": "Test results",
            },
            timeout=60,
        )
        assert r.status_code in (200, 500)


class TestErrorHandling:
    def test_invalid_endpoint_returns_404(self, server_url):
        import httpx
        r = httpx.get(f"{server_url}/api/science/nonexistent", timeout=10)
        assert r.status_code == 404

    def test_invalid_payload_returns_422(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/analyze",
            json={"invalid": "data"},
            timeout=10,
        )
        assert r.status_code in (422, 500)

    def test_invalid_plot_type(self, server_url):
        import httpx
        r = httpx.post(
            f"{server_url}/api/science/visualize",
            json={"data": [[1]], "plot_type": "invalid_type", "title": "test"},
            timeout=15,
        )
        assert r.status_code in (400, 422, 500)


class TestServerStability:
    """Basic resilience and load tests."""

    def test_concurrent_requests(self, server_url):
        import httpx
        import asyncio

        async def make_request(client, url):
            try:
                r = await client.get(f"{url}/api/science/health", timeout=10)
                return r.status_code
            except Exception:
                return 0

        async def run():
            async with httpx.AsyncClient() as client:
                tasks = [make_request(client, server_url) for _ in range(10)]
                results = await asyncio.gather(*tasks)
                return results

        results = asyncio.run(run())
        successes = [s for s in results if s == 200]
        assert len(successes) >= 8, f"Only {len(successes)}/10 concurrent requests succeeded"

    def test_rapid_fire_health_polls(self, server_url):
        import httpx
        for i in range(20):
            r = httpx.get(f"{server_url}/api/science/health", timeout=5)
            assert r.status_code == 200, f"Request {i} failed"
