# VMA - Video Metrics Analyzer
# Docker 镜像构建文件

FROM python:3.11-slim

LABEL maintainer="Jack"
LABEL description="Video Metrics Analyzer - 视频指标分析工具"

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 设置工作目录
WORKDIR /app

# 安装系统依赖
# - ffmpeg: 视频处理
# - procps: 进程管理工具 (ps)
# - curl: 健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 复制依赖文件并安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY src/ /app/src/
COPY templates/ /app/templates/
COPY config.yml /app/config.yml

# 复制启动脚本
COPY docker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# 创建数据目录
RUN mkdir -p /data/jobs /data/templates

# 设置默认环境变量（仅用于 Python 路径）
ENV PYTHONPATH=/app

# 暴露端口
EXPOSE 8080 8081

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# 启动命令
CMD ["/app/start.sh"]
