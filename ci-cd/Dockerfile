# ── Multi-stage Docker build ─────────────────
# Stage 1: Python deps
FROM python:3.13-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --upgrade pip && \
    pip install build && \
    python -m build --wheel && \
    pip install dist/*.whl

# Stage 2: TypeScript deps (channels)
FROM node:22-alpine AS ts-builder

WORKDIR /app
COPY channels/ts/package.json channels/ts/package-lock.json* ./channels/ts/
RUN cd channels/ts && npm ci
COPY channels/ts/ ./channels/ts/

# Stage 3: Production image
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

COPY --from=ts-builder /app/channels/ts/ ./channels/ts/

COPY ci-cd/scripts/ ./ci-cd/scripts/
COPY Dockerfile .dockerignore ./

ENV PYTHONPATH=/app/src:/app/src/code_agent
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["uvicorn", "code_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
