#!/bin/sh
# Horizon Orchestra — Docker Entrypoint
# Starts both the Python API server and the Node.js bridge

set -e

echo "╔═══════════════════════════════════════════════════╗"
echo "║  Horizon Orchestra — Starting Production Stack    ║"
echo "╚═══════════════════════════════════════════════════╝"

PYTHON_PORT=${PORT:-8000}
NODE_PORT=${NODE_PORT:-3001}

# Start Python API (background)
echo "[1/2] Starting Python API on port ${PYTHON_PORT}..."
python -m uvicorn orchestra.api.server:app \
    --host 0.0.0.0 \
    --port "${PYTHON_PORT}" \
    --workers "${WORKERS:-2}" \
    --log-level "${LOG_LEVEL:-info}" \
    &
PYTHON_PID=$!

# Wait for Python to be ready
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${PYTHON_PORT}/v1/admin/health" > /dev/null 2>&1; then
        echo "  Python API ready."
        break
    fi
    sleep 1
done

# Start Node.js bridge (background)
if [ -f /app/node/dist/server.js ]; then
    echo "[2/2] Starting Node.js bridge on port ${NODE_PORT}..."
    PYTHON_BACKEND_URL="http://localhost:${PYTHON_PORT}" \
    PORT="${NODE_PORT}" \
    node /app/node/dist/server.js &
    NODE_PID=$!
    echo "  Node.js bridge ready."
else
    echo "[2/2] Node.js bridge not built — skipping."
    NODE_PID=""
fi

echo ""
echo "Horizon Orchestra is running."
echo "  Python API:   http://0.0.0.0:${PYTHON_PORT}"
if [ -n "${NODE_PID}" ]; then
    echo "  Node Bridge:  http://0.0.0.0:${NODE_PORT}"
fi
echo ""

# Trap signals for graceful shutdown
shutdown() {
    echo "Shutting down gracefully..."
    [ -n "${NODE_PID}" ] && kill "${NODE_PID}" 2>/dev/null
    kill "${PYTHON_PID}" 2>/dev/null
    wait
    echo "Shutdown complete."
    exit 0
}

trap shutdown SIGTERM SIGINT

# Wait for either process to exit
wait -n "${PYTHON_PID}" ${NODE_PID:+"${NODE_PID}"}
shutdown
