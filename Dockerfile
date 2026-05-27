# ── Stage 1: Build ──────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY entrypoint.py .

RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir fastapi uvicorn httpx langfuse prometheus-client && \
    pip install -e . 2>/dev/null || true

# ── Stage 2: Runtime ────────────────────────────────────────────
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1001 orchestra && \
    useradd --uid 1001 --gid orchestra --shell /bin/bash --create-home orchestra

WORKDIR /workspace
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /app/src /app/src
COPY --from=builder /app/entrypoint.py /entrypoint.py
COPY src/ /app/src/

RUN chown -R orchestra:orchestra /workspace /app

ENV PYTHONPATH=/app/src:$PYTHONPATH
ENV PYTHONUNBUFFERED=1
ENV ORCHESTRA_LOG_LEVEL=info

USER orchestra

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

ENTRYPOINT ["python", "/entrypoint.py"]
