#!/bin/bash
# VMA Application Startup Script

set -e

cd "$(dirname "$0")"

CONFIG_FILE="${CONFIG_FILE:-config.yml}"

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Error: Config file not found: ${CONFIG_FILE}"
    exit 1
fi

read_config_vars() {
python - "$CONFIG_FILE" <<'PY'
import sys, yaml, shlex
config_path = sys.argv[1]
with open(config_path, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

required = [
    "host",
    "fastapi_port",
    "streamlit_port",
    "jobs_root_dir",
    "templates_root_dir",
    "reports_root_dir",
    "log_level",
]
missing = [k for k in required if k not in cfg]
if missing:
    print(f"Missing config keys in {config_path}: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)

for key in required:
    val = str(cfg[key])
    print(f"{key.upper()}={shlex.quote(val)}")
PY
}

eval "$(read_config_vars)" || exit 1

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

.venv/bin/streamlit run "src/1_🏠_Homepage.py" \
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
echo "   API:     http://${HOST}:${FASTAPI_PORT}/api/docs"
echo ""
.venv/bin/uvicorn src.main:app \
  --reload \
  --host "${HOST}" \
  --port "${FASTAPI_PORT}" \
  --log-level "$(echo "${LOG_LEVEL}" | tr '[:upper:]' '[:lower:]')"

echo "Press Ctrl+C to stop servers"
echo ""
