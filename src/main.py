"""
VMA FastAPI 应用入口点
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.utils.url_helpers import build_reports_base_url
from src.api import (
    jobs_router,
    metrics_analysis_router,
    pages_router,
    templates_router,
)
from src.config import settings
from src.services import stream_analysis_runner


# 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理器"""
    # 启动时：启动后台任务处理器
    task = asyncio.create_task(stream_analysis_runner.start_background_processor())
    yield
    # 关闭时：停止后台任务处理器
    stream_analysis_runner.stop_background_processor()
    await task


# 创建 FastAPI 应用实例
app = FastAPI(
    title="VMA - Video Metrics Analyzer",
    description="Web application for video encoding quality analysis",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# 注册 API 路由
app.include_router(jobs_router)
app.include_router(pages_router)
app.include_router(templates_router)
app.include_router(metrics_analysis_router)

# 配置静态文件和模板
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# 挂载静态文件目录（如果存在）
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 配置 Jinja2 模板
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """根路径，返回首页"""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "recent_jobs": [],
            "reports_base_url": build_reports_base_url(request),
        },
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """健康检查端点"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.fastapi_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
