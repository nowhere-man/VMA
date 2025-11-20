"""
US1 Contract Tests - 查询任务状态

测试 GET /api/jobs/{job_id} 端点的契约
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
def test_get_job_not_found(client: TestClient) -> None:
    """测试查询不存在的任务返回 404"""
    job_id = "nonexistent123"

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 404
    json_data = response.json()
    assert "detail" in json_data


@pytest.mark.contract
@pytest.mark.US1
def test_get_job_success(client: TestClient) -> None:
    """测试成功查询任务状态"""
    # 先创建一个任务
    video_content = b"fake video content"
    files = {"file": ("test.mp4", video_content, "video/mp4")}
    data = {"mode": "single_file", "preset": "medium"}

    create_response = client.post("/api/jobs", files=files, data=data)
    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    # 查询任务状态
    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    json_data = response.json()

    # 验证响应结构
    assert "job_id" in json_data
    assert "status" in json_data
    assert "mode" in json_data
    assert "created_at" in json_data
    assert "updated_at" in json_data

    # 验证字段值
    assert json_data["job_id"] == job_id
    assert json_data["status"] in ["pending", "processing", "completed", "failed"]
    assert json_data["mode"] == "single_file"


@pytest.mark.contract
@pytest.mark.US1
def test_get_job_response_structure_minimal(client: TestClient) -> None:
    """测试响应包含最小必需字段（pending 状态）"""
    # 创建任务
    video_content = b"fake video"
    files = {"file": ("test.mp4", video_content, "video/mp4")}
    data = {"mode": "single_file"}

    create_response = client.post("/api/jobs", files=files, data=data)
    job_id = create_response.json()["job_id"]

    # 查询任务
    response = client.get(f"/api/jobs/{job_id}")
    json_data = response.json()

    # Pending 状态应该包含这些字段
    required_fields = ["job_id", "status", "mode", "created_at", "updated_at"]
    for field in required_fields:
        assert field in json_data

    # 可选字段（在 pending 状态可能为 null）
    optional_fields = ["completed_at", "metrics", "error_message"]
    for field in optional_fields:
        # 字段可能存在且为 null，或者不存在
        if field in json_data:
            # 如果存在，pending 状态下应该为 null
            if json_data["status"] == "pending":
                assert json_data[field] is None
