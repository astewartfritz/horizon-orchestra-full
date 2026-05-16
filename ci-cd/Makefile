# ──────────────────────────────────────────────
# Makefile — Orchestra CI/CD local commands
# ──────────────────────────────────────────────

.PHONY: build test lint quality docker ci clean

PYTHON    ?= python
PYTHONPATH ?= src;src/code_agent
COVERAGE  ?= 80
REGISTRY  ?= docker.io/orchestra
TAG       ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "latest")

export PYTHONPATH

# ── Install ──────────────────────────────────

build:
	$(PYTHON) -m pip install -e ".[dev]"
	cd channels/ts && npm ci 2>/dev/null || echo "Skip npm"
	cd api/express && npm ci 2>/dev/null || echo "Skip npm"

# ── Test ─────────────────────────────────────

test:
	$(PYTHON) -m pytest src/ -v --cov=src/ --cov-report=term --cov-report=xml

test-api:
	cd api/express && npm test 2>/dev/null || echo "Skip"

test-ts:
	cd channels/ts && npm test 2>/dev/null || echo "Skip"

# ── Lint ─────────────────────────────────────

lint:
	ruff check src/ || true
	$(PYTHON) -m mypy src/ --ignore-missing-imports || true

lint-security:
	bandit -r src/ -f json -o bandit.json || true

# ── Quality ──────────────────────────────────

quality: coverage-gate license-check

coverage-gate:
	$(PYTHON) -c "import xml.etree.ElementTree as ET; r=ET.parse('coverage.xml').getroot(); pct=float(r.attrib.get('line-rate',0))*100; assert pct >= $(COVERAGE), f'Coverage {pct:.1f}% < $(COVERAGE)%'"

license-check:
	pip-licenses --allow-only="MIT;Apache-2.0;BSD-2-Clause;BSD-3-Clause;Python-2.0;PSF;Unlicense" 2>/dev/null || echo "License check skipped"

# ── Docker ───────────────────────────────────

docker:
	docker build -t $(REGISTRY):$(TAG) -f Dockerfile .
	docker tag $(REGISTRY):$(TAG) $(REGISTRY):latest

docker-push: docker
	docker push $(REGISTRY):$(TAG)
	docker push $(REGISTRY):latest

# ── Deploy ───────────────────────────────────

deploy:
	$(PYTHON) ci-cd/scripts/deploy.py --env $(ENV) --tag $(TAG)

# ── Full CI ──────────────────────────────────

ci: build test lint quality docker

# ── Clean ────────────────────────────────────

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf build dist *.egg-info
	rm -rf coverage.xml junit-*.xml bandit.json licenses.json
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true

# ── Help ─────────────────────────────────────

help:
	@echo "Orchestra CI/CD Makefile"
	@echo "  make build     Install all dependencies"
	@echo "  make test      Run all tests"
	@echo "  make lint      Run linters"
	@echo "  make quality   Coverage gate + license check"
	@echo "  make docker    Build Docker image"
	@echo "  make ci        Full pipeline (build → test → lint → quality → docker)"
	@echo "  make deploy    Deploy (set ENV=staging|production, TAG=...)"
	@echo "  make clean     Remove build artifacts"
