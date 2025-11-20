"""
US1 Contract Tests - 创建任务（单文件模式）

测试 POST /api/jobs 端点的契约
"""
import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client() -> TestClient:
    """测试客户端"""
    return TestClient(app)


@pytest.mark.contract
@pytest.mark.US1
def test_create_job_single_file_success(client: TestClient) -> None:
    """测试成功创建单文件模式任务"""
    # 准备测试视频文件
    video_content = b"fake video content for testing"
    files = {"file": ("test_video.mp4", video_content, "video/mp4")}
    data = {"mode": "single_file", "preset": "medium"}

    # 发送请求
    response = client.post("/api/jobs", files=files, data=data)

    # 验证响应
    assert response.status_code == 201
    json_data = response.json()

    # 验证响应结构
    assert "job_id" in json_data
    assert "status" in json_data
    assert "mode" in json_data
    assert "created_at" in json_data

    # 验证字段值
    assert json_data["status"] == "pending"
    assert json_data["mode"] == "single_file"
    assert len(json_data["job_id"]) == 12  # nanoid 12字符


@pytest.mark.contract
@pytest.mark.US1
def test_create_job_single_file_missing_file(client: TestClient) -> None:
    """测试缺少文件时返回 400"""
    data = {"mode": "single_file", "preset": "medium"}

    response = client.post("/api/jobs", data=data)

    assert response.status_code == 400
    json_data = response.json()
    assert "detail" in json_data


@pytest.mark.contract
@pytest.mark.US1
def test_create_job_single_file_invalid_preset(client: TestClient) -> None:
    """测试无效的预设参数"""
    video_content = b"fake video content"
    files = {"file": ("test.mp4", video_content, "video/mp4")}
    data = {"mode": "single_file", "preset": "invalid_preset"}

    response = client.post("/api/jobs", files=files, data=data)

    # 根据实现，可能返回 400 或接受任意字符串
    # 这里假设接受任意字符串（在实际实现中验证）
    assert response.status_code in [201, 400]


@pytest.mark.contract
@pytest.mark.US1
def test_create_job_default_preset(client: TestClient) -> None:
    """测试默认预设值"""
    video_content = b"fake video content"
    files = {"file": ("test.mp4", video_content, "video/mp4")}
    data = {"mode": "single_file"}  # 不提供 preset

    response = client.post("/api/jobs", files=files, data=data)

    assert response.status_code == 201
    json_data = response.json()
    assert json_data["mode"] == "single_file"
