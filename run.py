"""一键启动脚本。

    python run.py                 启动主服务（8000）+ 内置模拟审批系统（9100）
    python run.py --no-mock       只启动主服务（对接真实审批系统时使用）
    python run.py --port 8080     指定主服务端口
    python run.py --gen-samples   仅重新生成示例合同文件后退出

启动后：
    调用端页面  http://127.0.0.1:8000/
    接口文档    http://127.0.0.1:8000/docs
    模拟审批系统 http://127.0.0.1:9100/
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import uvicorn

from app.config import settings
from app.database import init_db


def _start_mock_server() -> threading.Thread:
    """在后台线程启动模拟审批系统。"""
    from app.mock_approval.server import app as mock_app

    config = uvicorn.Config(
        mock_app,
        host=settings.MOCK_HOST,
        port=settings.MOCK_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="mock-approval-server", daemon=True)
    thread.start()
    return thread


def main() -> int:
    parser = argparse.ArgumentParser(description="企业合同审批自动审查系统 启动器")
    parser.add_argument("--host", default=settings.APP_HOST, help="主服务监听地址")
    parser.add_argument("--port", type=int, default=settings.APP_PORT, help="主服务监听端口")
    parser.add_argument("--no-mock", action="store_true", help="不启动内置模拟审批系统")
    parser.add_argument("--reload", action="store_true", help="开启热重载（开发模式）")
    parser.add_argument("--gen-samples", action="store_true", help="仅生成示例合同文件后退出")
    args = parser.parse_args()

    # ---------------- 示例合同文件 ----------------
    from scripts.gen_samples import ensure_samples

    created = ensure_samples(force=args.gen_samples)
    if created:
        print(f"[启动] 已生成/补齐示例合同文件 {len(created)} 个：{', '.join(created)}")
    if args.gen_samples:
        print("[启动] 示例文件已生成，退出。")
        return 0

    # ---------------- 数据库初始化 ----------------
    settings.ensure_dirs()
    init_db()
    print(f"[启动] 数据库初始化完成：{settings.DB_PATH}")

    # ---------------- 模拟审批系统 ----------------
    if settings.ENABLE_MOCK_SERVER and not args.no_mock:
        _start_mock_server()
        time.sleep(1.0)
        print(f"[启动] 模拟审批系统已启动：http://{settings.MOCK_HOST}:{settings.MOCK_PORT}")
    else:
        print(f"[启动] 未启动模拟审批系统，使用外部审批系统：{settings.APPROVAL_BASE_URL}")

    print(f"[启动] 调用端页面：http://{args.host}:{args.port}/")
    print(f"[启动] 接口文档  ：http://{args.host}:{args.port}/docs")
    print("[启动] 按 Ctrl+C 停止服务")

    # ---------------- 主服务 ----------------
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
