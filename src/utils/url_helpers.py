"""
URL helpers

集中构建跨端口访问的基础 URL（例如 Streamlit 报告），避免在模板里写死 localhost。
"""
from fastapi import Request

from src.config import settings


def build_reports_base_url(request: Request) -> str:
    """
    根据请求推导出 Streamlit 报告的基础 URL。

    - 取 Host / X-Forwarded-Host（去掉端口）
    - 取协议 / X-Forwarded-Proto
    - 使用配置的 streamlit_port
    """
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()

    host = forwarded_host or (request.url.hostname or "localhost")
    # 去掉可能带入的端口
    if ":" in host and not host.startswith("["):  # 简单排除 IPv6 场景
        host = host.split(":")[0]

    scheme = forwarded_proto or (request.url.scheme or "http")

    return f"{scheme}://{host}:{settings.streamlit_port}"
