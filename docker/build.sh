#!/bin/bash
# VMA Docker 镜像构建脚本
# 用法: ./docker/build.sh [tag] [platform]
# 平台: amd64 (默认，用于 x86_64 服务器) 或 arm64 (用于 ARM 服务器)

set -e

# 切换到项目根目录
cd "$(dirname "$0")/.."

# 镜像名称和标签
IMAGE_NAME="vma"
TAG="${1:-latest}"
PLATFORM="${2:-amd64}"
FULL_NAME="${IMAGE_NAME}:${TAG}"

echo "=========================================="
echo "  Building VMA Docker Image"
echo "=========================================="
echo ""
echo "Image: ${FULL_NAME}"
echo "Platform: linux/${PLATFORM}"
echo ""

# 构建镜像（指定目标平台）
echo "[1/3] Building Docker image for linux/${PLATFORM}..."
docker build \
    --platform "linux/${PLATFORM}" \
    -t "${FULL_NAME}" \
    -f docker/Dockerfile \
    .

echo ""
echo "[2/3] Image built successfully!"
echo ""

# 显示镜像信息
echo "Image details:"
docker images "${IMAGE_NAME}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"

echo ""
echo "[3/3] Exporting image to tar.gz..."

# 导出镜像
OUTPUT_FILE="vma-${TAG}-${PLATFORM}.tar.gz"
docker save "${FULL_NAME}" | gzip > "${OUTPUT_FILE}"

echo ""
echo "=========================================="
echo "  Build Complete!"
echo "=========================================="
echo ""
echo "Exported file: ${OUTPUT_FILE}"
echo "File size: $(du -h "${OUTPUT_FILE}" | cut -f1)"
echo ""
echo "To deploy to server:"
echo "  1. scp ${OUTPUT_FILE} user@server:/path/to/"
echo "  2. On server: docker load < ${OUTPUT_FILE}"
echo "  3. Run: docker run -d --name vma -p 8080:8080 \\"
echo "          -p 8079:8079 \\"
echo "          -v /data/vma/jobs:/data/jobs \\"
echo "          -v /data/vma/templates:/data/templates \\"
echo "          ${FULL_NAME}"
echo ""
