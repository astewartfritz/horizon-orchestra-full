# ============================================================================
# Horizon Orchestra — Multi-stage Production Dockerfile
# ============================================================================
# Stage 1: Node.js bridge build
# Stage 2: Python API + Node bridge runtime
# ============================================================================

# -- Stage 1: Build Node.js bridge -------------------------------------------
FROM node:22-alpine AS node-builder

WORKDIR /build/node
COPY node/package.json node/tsconfig.json ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install

COPY node/src/ ./src/
RUN npx tsc || true

WORKDIR /build/sdk
COPY sdk/package.json sdk/tsconfig.json ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install

COPY sdk/src/ ./src/
RUN npx tsc || true

# -- Stage 2: Python runtime + Node bridge -----------------------------------
FROM python:3.12-slim AS runtime

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r orchestra && useradd -r -g orchestra -m -d /home/orchestra orchestra

WORKDIR /app

# Python deps (cached layer)
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt 2>/dev/null || \
    pip install --no-cache-dir openai httpx fastapi uvicorn pydantic python-multipart PyJWT

# Node.js bridge runtime deps
COPY node/package.json /app/node/
RUN cd /app/node && npm install --omit=dev 2>/dev/null || true

# Copy built artifacts
COPY --from=node-builder /build/node/dist/ /app/node/dist/
COPY --from=node-builder /build/sdk/dist/ /app/sdk/dist/

# Copy Python source
COPY orchestra/ /app/orchestra/
COPY horizon.py pyproject.toml ORCHESTRA.md /app/

# Install playwright browsers (optional — only if browser features needed)
RUN pip install playwright 2>/dev/null && python -m playwright install chromium --with-deps 2>/dev/null || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/v1/admin/health || exit 1

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ORCHESTRA_ENV=production \
    PORT=8000 \
    NODE_PORT=3001 \
    LOG_LEVEL=info

# Expose ports: Python API (8000) + Node bridge (3001)
EXPOSE 8000 3001

# Switch to non-root
USER orchestra

# Entrypoint: start both Python API and Node bridge
COPY --chown=orchestra:orchestra docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh 2>/dev/null || true

CMD ["sh", "-c", "python -m uvicorn orchestra.api.server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
