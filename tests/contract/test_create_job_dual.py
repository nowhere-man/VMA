"""
US1 Contract Tests - 创建任务（双文件模式）

测试 POST /api/jobs 端点的契约（双文件模式）
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
def test_create_job_dual_file_success(client: TestClient) -> None:
    """测试成功创建双文件模式任务"""
    # 准备测试视频文件
    reference_content = b"fake reference video content"
    distorted_content = b"fake distorted video content"

    files = [
        ("reference", ("reference.mp4", reference_content, "video/mp4")),
        ("distorted", ("distorted.mp4", distorted_content, "video/mp4")),
    ]
    data = {"mode": "dual_file"}

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
    assert json_data["mode"] == "dual_file"
    assert len(json_data["job_id"]) == 12


@pytest.mark.contract
@pytest.mark.US1
def test_create_job_dual_file_missing_reference(client: TestClient) -> None:
    """测试缺少参考视频时返回 400"""
    distorted_content = b"fake distorted video"
    files = {"distorted": ("distorted.mp4", distorted_content, "video/mp4")}
    data = {"mode": "dual_file"}

    response = client.post("/api/jobs", files=files, data=data)

    assert response.status_code == 400
    json_data = response.json()
    assert "detail" in json_data


@pytest.mark.contract
@pytest.mark.US1
def test_create_job_dual_file_missing_distorted(client: TestClient) -> None:
    """测试缺少待测视频时返回 400"""
    reference_content = b"fake reference video"
    files = {"reference": ("reference.mp4", reference_content, "video/mp4")}
    data = {"mode": "dual_file"}

    response = client.post("/api/jobs", files=files, data=data)

    assert response.status_code == 400
    json_data = response.json()
    assert "detail" in json_data


@pytest.mark.contract
@pytest.mark.US1
def test_create_job_invalid_mode(client: TestClient) -> None:
    """测试无效的模式参数"""
    video_content = b"fake video content"
    files = {"file": ("test.mp4", video_content, "video/mp4")}
    data = {"mode": "invalid_mode"}

    response = client.post("/api/jobs", files=files, data=data)

    assert response.status_code == 400
    json_data = response.json()
    assert "detail" in json_data
