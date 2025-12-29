#!/bin/bash
# VMA 服务器部署脚本
# 用法: ./deploy.sh <image-tar-file>

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CONTAINER_NAME="vma"
HOST_PORT="${VMA_HOST_PORT:-8080}"
HOST_REPORTS_PORT="${VMA_REPORTS_HOST_PORT:-8079}"
DATA_DIR="${VMA_DATA_DIR:-${SCRIPT_DIR}/data}"

if [ -z "$1" ]; then
    echo "Usage: $0 <image-tar-file>"
    echo "Example: $0 vma-latest.tar.gz"
    exit 1
fi

IMAGE_FILE="$1"

if [ ! -f "$IMAGE_FILE" ]; then
    echo "Error: File not found: $IMAGE_FILE"
    exit 1
fi

echo "=========================================="
echo "  VMA Deployment Script"
echo "=========================================="
echo ""
echo "Image file: ${IMAGE_FILE}"
echo "Container name: ${CONTAINER_NAME}"
echo "Host port: ${HOST_PORT}"
echo "Reports port: ${HOST_REPORTS_PORT}"
echo "Data directory: ${DATA_DIR}"
echo ""

echo "[1/4] Loading Docker image..."
docker load < "${IMAGE_FILE}"

IMAGE_NAME=$(docker load < "${IMAGE_FILE}" 2>&1 | grep "Loaded image" | sed 's/Loaded image: //')
if [ -z "$IMAGE_NAME" ]; then
    IMAGE_NAME="vma:latest"
fi
echo "    Loaded: ${IMAGE_NAME}"

echo "[2/4] Stopping old container (if exists)..."
docker stop "${CONTAINER_NAME}" 2>/dev/null || true
docker rm "${CONTAINER_NAME}" 2>/dev/null || true

echo "[3/4] Creating data directories..."
mkdir -p "${DATA_DIR}/jobs"
mkdir -p "${DATA_DIR}/templates"

echo "[4/4] Starting new container..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    -p "${HOST_PORT}:8080" \
    -p "${HOST_REPORTS_PORT}:8079" \
    -v "${DATA_DIR}/jobs:/data/jobs" \
    -v "${DATA_DIR}/templates:/data/templates" \
    -e VMA_LOG_LEVEL="${VMA_LOG_LEVEL:-error}" \
    "${IMAGE_NAME}"

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Container status:"
docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "Access VMA at: http://localhost:${HOST_PORT}"
echo "Reports at: http://localhost:${HOST_REPORTS_PORT}"
echo ""
echo "Useful commands:"
echo "  View logs:    docker logs -f ${CONTAINER_NAME}"
echo "  Stop:         docker stop ${CONTAINER_NAME}"
echo "  Restart:      docker restart ${CONTAINER_NAME}"
echo "  Remove:       docker rm -f ${CONTAINER_NAME}"
echo ""
