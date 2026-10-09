"""数据访问层。

职责：
    1. 负责数据库连接管理（SQLite 默认，逐调用独立连接，天然线程安全）；
    2. 服务启动时执行 sql/init_schema.sql 完成建表（幂等）；
    3. 首次启动时灌入内置风控规则种子数据；
    4. 对外提供 query_all / query_one / execute / executemany 通用 DAO。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

from .config import settings

#: 建表只执行一次
_init_lock = threading.Lock()
_initialized = False


# ======================================================================
# 一、时间与 JSON 工具
# ======================================================================
def now_str() -> str:
    """统一时间格式：YYYY-MM-DD HH:MM:SS。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_dumps(value: Any) -> str:
    """安全序列化：确保中文可读、异常不抛出。"""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def json_loads(text: Any, default: Any = None):
    """安全反序列化：解析失败返回默认值，绝不抛异常。"""
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


# ======================================================================
# 二、连接管理
# ======================================================================
@contextmanager
def get_conn():
    """获取数据库连接上下文，自动提交/回滚/关闭。"""
    settings.ensure_dirs()
    conn = sqlite3.connect(str(settings.DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


def query_all(sql: str, params: Sequence[Any] = ()) -> list[dict]:
    """查询多行，返回 dict 列表。"""
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
    """查询单行，返回 dict 或 None。"""
    with get_conn() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    return _row_to_dict(row)


def query_scalar(sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
    """查询单值。"""
    row = query_one(sql, params)
    if not row:
        return default
    return list(row.values())[0] if row else default


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    """执行写操作，返回 lastrowid（无自增主键时返回受影响行数）。"""
    with get_conn() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.lastrowid if cur.lastrowid else cur.rowcount


def execute_return_rowcount(sql: str, params: Sequence[Any] = ()) -> int:
    """执行写操作，返回受影响行数。"""
    with get_conn() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.rowcount


def executemany(sql: str, seq: Iterable[Sequence[Any]]) -> int:
    """批量执行写操作。"""
    with get_conn() as conn:
        cur = conn.executemany(sql, [tuple(p) for p in seq])
        return cur.rowcount


# ======================================================================
# 三、初始化
# ======================================================================
def init_db(force: bool = False) -> None:
    """执行建表脚本并灌入种子规则（幂等）。"""
    global _initialized
    with _init_lock:
        if _initialized and not force:
            return

        settings.ensure_dirs()
        schema_file = settings.SQL_DIR / "init_schema.sql"
        if not schema_file.exists():
            raise FileNotFoundError(f"未找到数据库初始化脚本：{schema_file}")

        sql_text = schema_file.read_text(encoding="utf-8")
        with get_conn() as conn:
            conn.executescript(sql_text)

        # 灌入内置风控规则（已存在同 rule_code 的规则不覆盖，保留管理员的编辑结果）
        _seed_review_rules()

        _initialized = True


def _seed_review_rules() -> None:
    """内置风控规则种子数据入库（仅新增缺失规则）。"""
    from .modules.rules.seed_rules import BUILTIN_RULES

    exist_codes = {
        row["rule_code"] for row in query_all("SELECT rule_code FROM review_rules")
    }
    ts = now_str()
    to_insert = [r for r in BUILTIN_RULES if r["rule_code"] not in exist_codes]
    if not to_insert:
        return

    executemany(
        """
        INSERT INTO review_rules
            (rule_code, rule_name, risk_level, rule_status, match_mode,
             match_text, suggestion_text, remark, sort_no, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                r["rule_code"], r["rule_name"], r["risk_level"], r.get("rule_status", "enabled"),
                r["match_mode"], r["match_text"], r["suggestion_text"], r.get("remark", ""),
                r.get("sort_no", 0), ts, ts,
            )
            for r in to_insert
        ],
    )


def health_check() -> dict:
    """数据库健康检查。"""
    try:
        row = query_one("SELECT COUNT(*) AS c FROM review_rules")
        return {"status": "ok", "db_path": str(settings.DB_PATH), "rule_count": row["c"] if row else 0}
    except Exception as exc:  # noqa: BLE001 - 健康检查需要吞掉所有异常并如实上报
        return {"status": "error", "db_path": str(settings.DB_PATH), "error": str(exc)}
