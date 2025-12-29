#!/bin/bash
# VMA 容器启动脚本
# 启动 FastAPI 和 Streamlit 服务

set -e

CONFIG_FILE="${CONFIG_FILE:-/app/config.yml}"

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

echo "=========================================="
echo "  VMA - Video Metrics Analyzer"
echo "=========================================="
echo ""

# 确保数据目录存在
mkdir -p "${JOBS_ROOT_DIR}"
mkdir -p "${TEMPLATES_ROOT_DIR}"
mkdir -p "${REPORTS_ROOT_DIR}"

# 启动 Streamlit (后台运行，仅监听本地)
echo "[1/2] Starting Streamlit..."
streamlit run /app/src/Homepage.py \
    --server.port "${STREAMLIT_PORT}" \
    --server.address "${HOST}" \
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
echo "  Access: http://${HOST}:${FASTAPI_PORT}"
echo "  Reports: http://${HOST}:${STREAMLIT_PORT}"
echo "=========================================="
echo ""

uvicorn src.main:app \
    --host "${HOST}" \
    --port "${FASTAPI_PORT}" \
    --log-level "$(echo "${LOG_LEVEL}" | tr '[:upper:]' '[:lower:]')" &
FASTAPI_PID=$!

# 等待任意进程退出
wait -n $FASTAPI_PID $STREAMLIT_PID

# 如果有进程退出，清理并退出
cleanup
