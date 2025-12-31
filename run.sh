#!/bin/bash
# VMA Application Startup Script

set -e

cd "$(dirname "$0")"

CONFIG_FILE="${CONFIG_FILE:-config.yml}"

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Error: Config file not found: ${CONFIG_FILE}"
    exit 1
fi

parse_yaml() {
    local key="$1"
    grep "^${key}:" "$CONFIG_FILE" | sed 's/^[^:]*:[[:space:]]*//' | sed 's/^["'"'"']\(.*\)["'"'"']$/\1/' | sed 's/^null$//'
}

HOST=$(parse_yaml "host")
FASTAPI_PORT=$(parse_yaml "fastapi_port")
STREAMLIT_PORT=$(parse_yaml "streamlit_port")
JOBS_ROOT_DIR=$(parse_yaml "jobs_root_dir")
TEMPLATES_ROOT_DIR=$(parse_yaml "templates_root_dir")
REPORTS_ROOT_DIR=$(parse_yaml "reports_root_dir")
LOG_LEVEL=$(parse_yaml "log_level")

echo "Starting VMA - Video Metrics Analyzer..."
echo "================================================"
echo ""

if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment not found!"
    echo "Please run: uv venv && uv pip install -r requirements.txt"
    exit 1
fi

mkdir -p "${JOBS_ROOT_DIR}"
mkdir -p "${TEMPLATES_ROOT_DIR}"
mkdir -p "${REPORTS_ROOT_DIR}"

export PYTHONPATH=.

.venv/bin/streamlit run "src/1_🏠_Home.py" \
    --server.port "${STREAMLIT_PORT}" \
    --server.address "${HOST}" \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --browser.gatherUsageStats false \
    > /dev/null 2>&1 &

STREAMLIT_PID=$!

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down applications..."
    kill $STREAMLIT_PID 2>/dev/null || true
}

trap cleanup EXIT
trap 'exit 0' SIGINT SIGTERM

echo "Starting server..."
echo "   Web UI:  http://${HOST}:${FASTAPI_PORT}"
echo "   Reports: http://${HOST}:${STREAMLIT_PORT}"
echo ""
.venv/bin/uvicorn src.main:app \
  --reload \
  --host "${HOST}" \
  --port "${FASTAPI_PORT}" \
  --log-level "${LOG_LEVEL}"

echo "Press Ctrl+C to stop servers"
echo ""
