.PHONY: test serve clean docker lint

# ── Development ──────────────────────────────────────────────

serve:
	python run.py

serve-openai:
	ORCHESTRA_PROVIDER=openai LLM_API_KEY=$${OPENAI_API_KEY} python run.py

# ── Testing ─────────────────────────────────────────────────

test:
	python -m pytest -x -q

test-v:
	python -m pytest -x -v

test-all:
	python -m pytest

# ── Code Quality ─────────────────────────────────────────────

lint:
	python -m ruff check src/

format:
	python -m ruff format src/

typecheck:
	python -m mypy src/ --ignore-missing-imports || true

# ── Docker ──────────────────────────────────────────────────

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-up-detach:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ── Cleanup ─────────────────────────────────────────────────

clean:
	rm -rf __pycache__ .pytest_cache *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .agent-* .code-agent-*

clean-all: clean
	rm -rf venv .venv node_modules
