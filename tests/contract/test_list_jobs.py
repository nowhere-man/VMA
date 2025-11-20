"""
US1 Contract Tests - 列出任务

测试 GET /api/jobs 端点的契约
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
def test_list_jobs_empty(client: TestClient) -> None:
    """测试空任务列表"""
    response = client.get("/api/jobs")

    assert response.status_code == 200
    json_data = response.json()

    # 响应应该是数组
    assert isinstance(json_data, list)


@pytest.mark.contract
@pytest.mark.US1
def test_list_jobs_with_data(client: TestClient) -> None:
    """测试包含数据的任务列表"""
    # 创建几个任务
    video_content = b"fake video"
    for i in range(3):
        files = {"file": (f"test_{i}.mp4", video_content, "video/mp4")}
        data = {"mode": "single_file"}
        response = client.post("/api/jobs", files=files, data=data)
        assert response.status_code == 201

    # 列出任务
    response = client.get("/api/jobs")

    assert response.status_code == 200
    json_data = response.json()

    # 应该至少有3个任务
    assert isinstance(json_data, list)
    assert len(json_data) >= 3

    # 验证每个任务的结构
    for job in json_data:
        assert "job_id" in job
        assert "status" in job
        assert "mode" in job
        assert "created_at" in job


@pytest.mark.contract
@pytest.mark.US1
def test_list_jobs_with_status_filter(client: TestClient) -> None:
    """测试状态过滤"""
    # 创建任务
    video_content = b"fake video"
    files = {"file": ("test.mp4", video_content, "video/mp4")}
    data = {"mode": "single_file"}
    client.post("/api/jobs", files=files, data=data)

    # 使用状态过滤
    response = client.get("/api/jobs?status=pending")

    assert response.status_code == 200
    json_data = response.json()

    assert isinstance(json_data, list)
    # 验证所有返回的任务状态都是 pending
    for job in json_data:
        assert job["status"] == "pending"


@pytest.mark.contract
@pytest.mark.US1
def test_list_jobs_with_limit(client: TestClient) -> None:
    """测试数量限制"""
    # 创建多个任务
    video_content = b"fake video"
    for i in range(5):
        files = {"file": (f"test_{i}.mp4", video_content, "video/mp4")}
        data = {"mode": "single_file"}
        client.post("/api/jobs", files=files, data=data)

    # 使用 limit 参数
    response = client.get("/api/jobs?limit=2")

    assert response.status_code == 200
    json_data = response.json()

    assert isinstance(json_data, list)
    # 返回的任务数量应该不超过 2
    assert len(json_data) <= 2


@pytest.mark.contract
@pytest.mark.US1
def test_list_jobs_sorted_by_created_at(client: TestClient) -> None:
    """测试任务按创建时间倒序排列"""
    # 创建多个任务
    video_content = b"fake video"
    job_ids = []
    for i in range(3):
        files = {"file": (f"test_{i}.mp4", video_content, "video/mp4")}
        data = {"mode": "single_file"}
        response = client.post("/api/jobs", files=files, data=data)
        job_ids.append(response.json()["job_id"])

    # 列出任务
    response = client.get("/api/jobs")
    json_data = response.json()

    # 最新创建的任务应该在前面
    # 由于可能有其他测试创建的任务，我们只验证顺序关系
    found_jobs = [job for job in json_data if job["job_id"] in job_ids]
    if len(found_jobs) >= 2:
        # 验证时间戳递减（最新的在前）
        for i in range(len(found_jobs) - 1):
            # 比较创建时间（ISO 格式字符串可以直接比较）
            assert found_jobs[i]["created_at"] >= found_jobs[i + 1]["created_at"]
