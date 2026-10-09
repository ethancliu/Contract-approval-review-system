"""企业合同审批自动审查系统 —— 主应用入口。

启动：
    开发：python run.py
    生产：uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

本服务仅辅助人工审批，不替代人工审核决策。
"""

from __future__ import annotations

import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import admin, tools
from .config import settings
from .constants import LogType
from .database import health_check, init_db
from .exceptions import BlockedError, NotFoundError, ReviewBaseError
from .logger import log_error, log_info

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

#: 允许跨域，便于调用端（企业门户 / 前端调试页）直接调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================================
# 生命周期
# ======================================================================
@app.on_event("startup")
def on_startup() -> None:
    """服务启动：建表、灌入内置规则、输出运行配置。"""
    settings.ensure_dirs()
    init_db()
    log_info(0, LogType.TASK,
             f"===== {settings.PROJECT_NAME} v{__version__} 启动完成 =====")
    log_info(0, LogType.TASK,
             f"审批系统接入地址：{settings.APPROVAL_BASE_URL}"
             f"（{'内置模拟审批系统' if settings.APPROVAL_MOCK_MODE else '真实审批系统'}）")
    log_info(0, LogType.TASK, f"数据库：{settings.DB_PATH}")
    log_info(0, LogType.TASK, f"附件存储目录：{settings.STORAGE_DIR}")
    log_info(0, LogType.TASK, f"OCR 引擎配置：{settings.OCR_ENGINE}（语言 {settings.OCR_LANG}）")


# ======================================================================
# 异常处理（保证任何异常都不会导致服务崩溃）
# ======================================================================
@app.exception_handler(NotFoundError)
def _handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={
        "detail": exc.message, "error_type": exc.__class__.__name__, "extra": exc.detail,
    })


@app.exception_handler(BlockedError)
def _handle_blocked(request: Request, exc: BlockedError) -> JSONResponse:
    log_error(0, LogType.ERROR, f"接口 {request.url.path} 触发阻塞：{exc.message}｜{exc.detail}")
    return JSONResponse(status_code=409, content={
        "detail": exc.message,
        "error_type": exc.__class__.__name__,
        "block_reason": exc.block_reason,
        "extra": exc.detail,
        "hint": "该异常会把对应任务置为 blocked 状态，可由系统管理员在管理接口中手动重试。",
    })


@app.exception_handler(ReviewBaseError)
def _handle_business_error(request: Request, exc: ReviewBaseError) -> JSONResponse:
    return JSONResponse(status_code=400, content={
        "detail": exc.message, "error_type": exc.__class__.__name__, "extra": exc.detail,
    })


@app.exception_handler(ValueError)
def _handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc), "error_type": "ValueError"})


@app.exception_handler(Exception)
def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理：记录完整堆栈并返回 500，服务不中断。"""
    log_error(0, LogType.ERROR,
              f"接口 {request.url.path} 发生未预期异常：{exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={
        "detail": f"服务内部错误：{exc}",
        "error_type": exc.__class__.__name__,
        "hint": "详细堆栈已记录到 task_logs 表（log_level=ERROR），可由管理员查询日志排查。",
    })


# ======================================================================
# 路由注册
# ======================================================================
app.include_router(tools.router)             # 7 个核心工具接口
app.include_router(tools.pipeline_router)    # 全流程编排
app.include_router(tools.task_router)        # 任务查询
app.include_router(admin.router)             # 管理员接口


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health() -> dict:
    """服务与数据库健康检查。"""
    return {
        "service": settings.PROJECT_NAME,
        "version": __version__,
        "status": "ok",
        "database": health_check(),
        "approval_base_url": settings.APPROVAL_BASE_URL,
        "mock_approval_mode": settings.APPROVAL_MOCK_MODE,
    }


# ======================================================================
# 静态调用端页面
# ======================================================================
if settings.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    """调用端展示页面（覆盖全流程五大模块）。"""
    index_file = settings.STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(content={
        "service": settings.PROJECT_NAME,
        "message": "调用端页面未找到，请访问 /docs 查看接口文档",
    })
