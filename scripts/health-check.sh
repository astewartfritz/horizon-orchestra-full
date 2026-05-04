#!/usr/bin/env bash
# health-check.sh — Health probe script for Horizon Orchestra services.
# Checks Python API, Node bridge, Go envd (gRPC), Redis, and PostgreSQL.
# Returns a JSON health report and exits 0 (healthy) or 1 (unhealthy).
set -euo pipefail

# --- Configuration ---
PYTHON_API_URL="${PYTHON_API_URL:-http://localhost:8000/health}"
NODE_BRIDGE_URL="${NODE_BRIDGE_URL:-http://localhost:3000/health}"
ENVD_HEALTH_URL="${ENVD_HEALTH_URL:-http://localhost:8081/healthz}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
TIMEOUT="${HEALTH_CHECK_TIMEOUT:-5}"

HEALTHY=true
REPORT="{}"

# --- Helper functions ---
check_http() {
    local name="$1"
    local url="$2"
    local status
    local body

    if body=$(curl -sf --max-time "${TIMEOUT}" "${url}" 2>/dev/null); then
        status="healthy"
    else
        status="unhealthy"
        HEALTHY=false
        body="{}"
    fi

    REPORT=$(echo "${REPORT}" | jq --arg name "${name}" --arg status "${status}" --argjson body "${body:-{}}" \
        '. + {($name): {"status": $status, "details": $body}}')
}

check_tcp() {
    local name="$1"
    local host="$2"
    local port="$3"
    local status

    if timeout "${TIMEOUT}" bash -c "echo >/dev/tcp/${host}/${port}" 2>/dev/null; then
        status="healthy"
    else
        status="unhealthy"
        HEALTHY=false
    fi

    REPORT=$(echo "${REPORT}" | jq --arg name "${name}" --arg status "${status}" --arg host "${host}" --arg port "${port}" \
        '. + {($name): {"status": $status, "host": $host, "port": ($port | tonumber)}}')
}

check_redis() {
    local status

    if command -v redis-cli &>/dev/null; then
        if redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping 2>/dev/null | grep -q "PONG"; then
            status="healthy"
        else
            status="unhealthy"
            HEALTHY=false
        fi
    else
        # Fallback to TCP check.
        if timeout "${TIMEOUT}" bash -c "echo >/dev/tcp/${REDIS_HOST}/${REDIS_PORT}" 2>/dev/null; then
            status="healthy"
        else
            status="unhealthy"
            HEALTHY=false
        fi
    fi

    REPORT=$(echo "${REPORT}" | jq --arg status "${status}" \
        '. + {"redis": {"status": $status}}')
}

check_postgres() {
    local status

    if command -v pg_isready &>/dev/null; then
        if pg_isready -h "${PG_HOST}" -p "${PG_PORT}" -t "${TIMEOUT}" &>/dev/null; then
            status="healthy"
        else
            status="unhealthy"
            HEALTHY=false
        fi
    else
        # Fallback to TCP check.
        if timeout "${TIMEOUT}" bash -c "echo >/dev/tcp/${PG_HOST}/${PG_PORT}" 2>/dev/null; then
            status="healthy"
        else
            status="unhealthy"
            HEALTHY=false
        fi
    fi

    REPORT=$(echo "${REPORT}" | jq --arg status "${status}" \
        '. + {"postgresql": {"status": $status}}')
}

# --- Run health checks ---
check_http "python_api" "${PYTHON_API_URL}"
check_http "node_bridge" "${NODE_BRIDGE_URL}"
check_http "envd" "${ENVD_HEALTH_URL}"
check_redis
check_postgres

# --- Build final report ---
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if ${HEALTHY}; then
    OVERALL="healthy"
else
    OVERALL="unhealthy"
fi

FINAL_REPORT=$(echo "${REPORT}" | jq \
    --arg overall "${OVERALL}" \
    --arg timestamp "${TIMESTAMP}" \
    '{overall_status: $overall, timestamp: $timestamp, services: .}')

echo "${FINAL_REPORT}"

if ${HEALTHY}; then
    exit 0
else
    exit 1
fi
