"""日志模块。

职责：全链路操作日志、错误日志、任务流转日志统一落库到 task_logs 表，
并同步输出到控制台，便于排查。

设计约束：
    - 日志写入失败绝不能反向影响主流程（内部吞掉异常并打印到 stderr）；
    - task_id = 0 表示系统级日志。
"""

from __future__ import annotations

import sys
import uuid

from .constants import LogLevel, LogType
from .database import execute, now_str


def gen_trace_id() -> str:
    """生成一次执行链路的追踪号。"""
    return uuid.uuid4().hex[:12].upper()


def write_log(
    task_id: int | None,
    log_level: str,
    log_type: str,
    log_content: str,
    trace_id: str = "",
    cost_ms: int = 0,
) -> None:
    """写入一条任务日志（落库 + 控制台）。"""
    task_id = int(task_id or 0)
    log_level = log_level if log_level in LogLevel.ALL else LogLevel.INFO
    log_type = log_type if log_type in LogType.ALL else LogType.TASK
    content = str(log_content or "")

    # 1) 控制台输出（带时间/级别/类型，便于实时观察）
    try:
        print(f"[{now_str()}][{log_level}][{log_type}][task={task_id}] {content}", flush=True)
    except Exception:  # noqa: BLE001
        pass

    # 2) 落库
    try:
        execute(
            """
            INSERT INTO task_logs (task_id, log_level, log_type, log_content, created_at, trace_id, cost_ms)
            VALUES (?,?,?,?,?,?,?)
            """,
            (task_id, log_level, log_type, content, now_str(), trace_id, int(cost_ms or 0)),
        )
    except Exception as exc:  # noqa: BLE001 - 日志失败不得影响主流程
        print(f"[logger] 日志落库失败: {exc}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------
# 便捷封装
# ----------------------------------------------------------------------
def log_info(task_id, log_type, content, trace_id="", cost_ms=0) -> None:
    write_log(task_id, LogLevel.INFO, log_type, content, trace_id, cost_ms)


def log_warn(task_id, log_type, content, trace_id="", cost_ms=0) -> None:
    write_log(task_id, LogLevel.WARN, log_type, content, trace_id, cost_ms)


def log_error(task_id, log_type, content, trace_id="", cost_ms=0) -> None:
    write_log(task_id, LogLevel.ERROR, log_type, content, trace_id, cost_ms)


def log_task(task_id, content, log_level=LogLevel.INFO, trace_id="") -> None:
    """任务流转日志。"""
    write_log(task_id, log_level, LogType.TASK, content, trace_id)


def log_api(task_id, content, log_level=LogLevel.INFO, cost_ms=0, trace_id="") -> None:
    """外部接口调用日志。"""
    write_log(task_id, log_level, LogType.API, content, trace_id, cost_ms)


def query_logs(
    task_id: int | None = None,
    log_level: str | None = None,
    log_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """查询日志（管理员接口使用）。"""
    sql = "SELECT * FROM task_logs WHERE 1=1"
    params: list = []
    if task_id is not None:
        sql += " AND task_id = ?"
        params.append(int(task_id))
    if log_level:
        sql += " AND log_level = ?"
        params.append(log_level)
    if log_type:
        sql += " AND log_type = ?"
        params.append(log_type)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])

    from .database import query_all  # 局部导入避免循环引用

    return query_all(sql, params)
