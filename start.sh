#!/bin/bash
# VQMR Application Startup Script

set -e

echo "Starting VQMR - Video Quality Metrics Report..."
echo "================================================"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found!"
    echo "Please run: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found. Using default configuration."
    echo "To customize settings, copy .env.example to .env and edit it."
    echo ""
fi

# Create jobs directory if it doesn't exist
mkdir -p jobs

# Export PYTHONPATH to include current directory
export PYTHONPATH=.

echo "🚀 Starting FastAPI server..."
echo "   Web UI: http://localhost:8080"
echo "   API Docs: http://localhost:8080/api/docs"
echo ""

echo "📊 Starting Streamlit reports app..."
echo "   Reports: http://localhost:8501"
echo ""

echo "Press Ctrl+C to stop both servers"
echo ""

# Start Streamlit in background
./venv/bin/streamlit run streamlit_app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false \
    > /dev/null 2>&1 &

STREAMLIT_PID=$!

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down applications..."
    kill $STREAMLIT_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start FastAPI server (foreground)
./venv/bin/uvicorn src.main:app --reload --host 0.0.0.0 --port 8080
