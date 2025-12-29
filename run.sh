#!/bin/bash
# VMA Application Startup Script

set -e

cd "$(dirname "$0")"

echo "Starting VMA - Video Metrics Analyzer..."
echo "================================================"
echo ""

if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment not found!"
    echo "Please run: uv venv && uv pip install -r requirements.txt"
    exit 1
fi

mkdir -p jobs

export PYTHONPATH=.

.venv/bin/streamlit run src/Homepage.py \
    --server.port 8079 \
    --server.address 127.0.0.1 \
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
echo "   Web UI:  http://localhost:8080"
echo "   Reports: http://localhost:8079"
echo "   API:     http://localhost:8080/api/docs"
echo ""
.venv/bin/uvicorn src.main:app --reload --host 0.0.0.0 --port 8080 --log-level error

echo "Press Ctrl+C to stop servers"
echo ""
