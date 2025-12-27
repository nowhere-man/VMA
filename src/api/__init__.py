"""
API module

提供 RESTful API 端点
"""
from .jobs import router as jobs_router
from .pages import router as pages_router
from .templates import router as templates_router
from .metrics_analysis import router as metrics_analysis_router

__all__ = [
    "jobs_router",
    "pages_router",
    "templates_router",
    "metrics_analysis_router",
]
