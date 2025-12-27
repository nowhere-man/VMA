#!/bin/bash
# VMA 容器启动脚本
# 启动 FastAPI 和 Streamlit 服务

set -e

echo "=========================================="
echo "  VMA - Video Metrics Analyzer"
echo "=========================================="
echo ""

# 确保数据目录存在
mkdir -p "${VMA_JOBS_ROOT_DIR:-/data/jobs}"
mkdir -p "${VMA_TEMPLATES_ROOT_DIR:-/data/templates}"

# 启动 Streamlit (后台运行，仅监听本地)
echo "[1/2] Starting Streamlit..."
streamlit run /app/src/Homepage.py \
    --server.port 8079 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --browser.gatherUsageStats false \
    > /var/log/streamlit.log 2>&1 &
STREAMLIT_PID=$!
echo "    Streamlit started (PID: $STREAMLIT_PID)"

# 等待 Streamlit 启动
sleep 2

# 检查 Streamlit 是否正常启动
if ! kill -0 $STREAMLIT_PID 2>/dev/null; then
    echo "ERROR: Streamlit failed to start"
    cat /var/log/streamlit.log
    exit 1
fi

# 信号处理：优雅关闭
cleanup() {
    echo ""
    echo "Shutting down services..."
    kill $STREAMLIT_PID 2>/dev/null || true
    echo "Goodbye!"
    exit 0
}

trap cleanup SIGTERM SIGINT SIGQUIT

# 启动 FastAPI (前台运行，作为主进程)
echo "[2/2] Starting FastAPI..."
echo ""
echo "=========================================="
echo "  VMA is ready!"
echo "  Access: http://localhost:8080"
echo "  Reports: http://localhost:8079"
echo "=========================================="
echo ""

uvicorn src.main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --log-level "${VMA_LOG_LEVEL:-error}" &
FASTAPI_PID=$!

# 等待任意进程退出
wait -n $FASTAPI_PID $STREAMLIT_PID

# 如果有进程退出，清理并退出
cleanup
