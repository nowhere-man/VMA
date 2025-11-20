#!/bin/bash
# VQMR 报告应用启动脚本

# 切换到项目根目录
cd "$(dirname "$0")"

echo "🚀 启动 VQMR 报告应用..."

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 错误: 未找到虚拟环境 venv/"
    echo "请先运行: python -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

# 激活虚拟环境并启动Streamlit
./venv/bin/streamlit run streamlit_app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
