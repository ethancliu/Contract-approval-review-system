"""拉取模块。

职责：
    1. 调用企业审批系统接口，拉取待处理审批单列表；
    2. 拉取单个审批单完整详情（基础信息 + 表单数据 + 附件信息 + 当前处理状态）；
    3. 按「审批编号」做业务维度去重：已存在的任务只做增量更新，绝不重复创建；
    4. 同步附件元数据到 approval_attachments 表（下载状态置为 pending）。
"""

from __future__ import annotations

import time

import requests

from ..config import settings
from ..constants import DownloadStatus, LogType, TaskStatus, WriteStatus
from ..database import execute, json_dumps, now_str, query_all, query_one
from ..exceptions import ExternalApiError
from ..logger import log_api, log_error, log_info


# ======================================================================
# 一、外部接口调用封装
# ======================================================================
def _api_request(method: str, path: str, *, params: dict | None = None,
                 json_body: dict | None = None, timeout: float | None = None,
                 task_id: int | None = None) -> dict:
    """统一的外部审批系统 HTTP 调用（含超时、异常包装与接口日志）。"""
    url = f"{settings.APPROVAL_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {settings.APPROVAL_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    cost_ms = 0
    start = time.time()
    try:
        resp = requests.request(
            method, url,
            params=params, json=json_body, headers=headers,
            timeout=timeout or settings.APPROVAL_API_TIMEOUT,
        )
        cost_ms = int((time.time() - start) * 1000)
    except requests.RequestException as exc:
        cost_ms = int((time.time() - start) * 1000)
        log_api(task_id, f"调用审批系统接口失败：{method} {url} —— {exc}", "ERROR", cost_ms)
        raise ExternalApiError(
            "外部接口调用失败：无法连接企业审批系统",
            detail=f"{method} {url}；错误：{exc}",
        ) from exc

    log_api(task_id, f"{method} {url} → HTTP {resp.status_code}", cost_ms=cost_ms)
    if resp.status_code >= 400:
        raise ExternalApiError(
            f"外部接口调用失败：审批系统返回 HTTP {resp.status_code}",
            detail=f"{method} {url}；响应：{resp.text[:500]}",
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise ExternalApiError(
            "外部接口调用失败：审批系统返回内容不是合法 JSON",
            detail=f"{method} {url}；响应片段：{resp.text[:300]}",
        ) from exc

    if payload.get("code") not in (0, 200, None):
        raise ExternalApiError(
            f"外部接口调用失败：审批系统业务错误 code={payload.get('code')}",
            detail=str(payload.get("message") or payload)[:500],
        )
    return payload.get("data") or {}


# ======================================================================
# 二、工具 1：待办拉取
# ======================================================================
def list_pending_contract_approvals(limit: int = 10) -> list[dict]:
    """【工具接口 1】拉取待处理审批单列表。

    返回数组，每项必含字段：
        approval_code    审批编号
        approval_title   审批标题
        applicant_name   申请人
        apply_time       申请时间
        attachment_count 附件数量
    """
    limit = int(limit or 10)
    data = _api_request("GET", "/api/pending", params={"limit": limit})
    items = (data or {}).get("list") or []

    result: list[dict] = []
    for item in items:
        result.append({
            "approval_code": item.get("approval_code") or item.get("instance_id", ""),
            "approval_title": item.get("approval_title", ""),
            "applicant_name": item.get("applicant_name", ""),
            "apply_time": item.get("apply_time", ""),
            "attachment_count": int(item.get("attachment_count") or 0),
            # ---- 以下为辅助字段，便于调用方直接串联后续接口 ----
            "instance_id": item.get("instance_id", ""),
            "status": item.get("status", ""),
        })
    log_info(0, LogType.FETCH, f"拉取待处理审批单 {len(result)} 条（limit={limit}）")
    return result


# ======================================================================
# 三、工具 2：审批详情
# ======================================================================
def get_contract_approval(instance_id: str) -> dict:
    """【工具接口 2】查询单个审批单完整详情。

    返回：
        basic_info      审批基础信息
        form_data       表单数据
        attachments     附件信息列表
        current_status  当前处理状态
    """
    if not instance_id:
        raise ExternalApiError("外部接口调用失败：审批编号不能为空")
    data = _api_request("GET", f"/api/approval/{instance_id}")
    return {
        "instance_id": instance_id,
        "basic_info": data.get("basic_info", {}),
        "form_data": data.get("form_data", {}),
        "attachments": data.get("attachments", []),
        "current_status": data.get("current_status", {}),
    }


# ======================================================================
# 四、任务库操作（去重核心）
# ======================================================================
def get_task_by_code(approval_code: str) -> dict | None:
    """按审批编号查询任务。"""
    return query_one("SELECT * FROM approval_tasks WHERE approval_code = ?", (approval_code,))


def get_task(task_id: int) -> dict | None:
    """按主键查询任务。"""
    return query_one("SELECT * FROM approval_tasks WHERE id = ?", (int(task_id),))


def list_tasks(task_status: str | None = None, limit: int = 100) -> list[dict]:
    """查询任务列表。"""
    sql = "SELECT * FROM approval_tasks WHERE 1=1"
    params: list = []
    if task_status:
        sql += " AND task_status = ?"
        params.append(task_status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return query_all(sql, params)


def create_or_update_task(detail: dict) -> dict:
    """按审批编号去重创建 / 增量更新任务。

    返回：{"task_id": int, "action": "created" | "updated"}
    """
    basic = detail.get("basic_info", {}) or {}
    approval_code = basic.get("approval_code") or detail.get("instance_id", "")
    if not approval_code:
        raise ExternalApiError("外部接口调用失败：审批详情缺少审批编号")

    title = basic.get("approval_title", "")
    applicant = basic.get("applicant_name", "")
    apply_time = basic.get("apply_time", "")
    handler = basic.get("current_handler", "") or (detail.get("current_status", {}) or {}).get("current_handler", "")
    attachments = detail.get("attachments", []) or []
    form_data_json = json_dumps(detail.get("form_data", {}))
    ts = now_str()

    existing = get_task_by_code(approval_code)

    if existing:
        # ---------- 增量更新：仅刷新业务字段，不重置任务状态，避免重复处理 ----------
        execute(
            """
            UPDATE approval_tasks
               SET approval_title = ?, applicant_name = ?, apply_time = ?,
                   current_handler = ?, attachment_count = ?, form_data_json = ?, updated_at = ?
             WHERE id = ?
            """,
            (title, applicant, apply_time, handler, len(attachments), form_data_json, ts, existing["id"]),
        )
        task_id = int(existing["id"])
        action = "updated"
        log_info(task_id, LogType.FETCH,
                 f"任务已存在（按审批编号 {approval_code} 去重），执行增量更新："
                 f"标题={title}，附件数={len(attachments)}，任务状态保持 {existing['task_status']}")
    else:
        task_id = int(execute(
            """
            INSERT INTO approval_tasks
                (approval_code, approval_title, applicant_name, task_status, write_status,
                 apply_time, attachment_count, current_handler, form_data_json,
                 block_reason, retry_count, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,'',0,?,?)
            """,
            (approval_code, title, applicant, TaskStatus.PENDING, WriteStatus.NOT_WRITTEN,
             apply_time, len(attachments), handler, form_data_json, ts, ts),
        ))
        action = "created"
        log_info(task_id, LogType.FETCH,
                 f"创建新任务：审批编号={approval_code}，标题={title}，申请人={applicant}，附件数={len(attachments)}")

    _sync_attachments(task_id, attachments)
    return {"task_id": task_id, "action": action}


def refresh_task_from_approval(task_id: int) -> dict:
    """重新拉取审批单最新详情并同步到本地任务（管理员重试前调用）。

    重试的业务含义是「根因已修复，请重新执行」。根因往往就在审批系统一侧——
    申请人刚补齐了附件、重新上传了可识别版本的扫描件。因此重试前必须重新拉一次详情，
    否则本地附件清单永远停留在首次拉取时的状态，「附件缺失」类阻塞将无法恢复。

    注意：附件只做新增 / 更新，不删除本地已有记录，避免影响其它任务的引用；
    任务状态由调用方（retry_task）控制，此处不重置。
    """
    task = get_task(task_id)
    if not task:
        from ..exceptions import NotFoundError  # noqa: PLC0415 - 避免顶层循环依赖
        raise NotFoundError(f"未找到对应审批任务：task_id={task_id}")

    instance_id = task["approval_code"]
    detail = get_contract_approval(instance_id)
    result = create_or_update_task(detail)
    fresh = get_task(task_id) or task
    attachments = detail.get("attachments", []) or []
    log_info(task_id, LogType.FETCH,
             f"重试前刷新审批单详情：审批编号={instance_id}，"
             f"审批系统最新附件数={len(attachments)}，本地任务附件数={fresh['attachment_count']}")
    return {
        "task_id": result["task_id"],
        "action": result["action"],
        "attachment_count": fresh["attachment_count"],
        "attachments": attachments,
    }


def _sync_attachments(task_id: int, attachments: list[dict]) -> None:
    """同步附件元数据（按 task_id + attachment_id 去重）。"""
    ts = now_str()
    for att in attachments:
        attachment_id = str(att.get("attachment_id", ""))
        file_name = att.get("file_name", "")
        file_type = (att.get("file_type") or file_name.rsplit(".", 1)[-1] or "").lower()

        exists = query_one(
            "SELECT id FROM approval_attachments WHERE task_id = ? AND attachment_id = ?",
            (task_id, attachment_id),
        )
        if exists:
            execute(
                """UPDATE approval_attachments
                      SET file_name = ?, file_type = ?, updated_at = ?
                    WHERE id = ?""",
                (file_name, file_type, ts, exists["id"]),
            )
            continue

        execute(
            """
            INSERT INTO approval_attachments
                (task_id, file_name, file_type, file_path, download_status, created_at,
                 attachment_id, file_md5, file_size, download_error, updated_at)
            VALUES (?,?,?,'',?,?,?, '',0,'',?)
            """,
            (task_id, file_name, file_type, DownloadStatus.PENDING, ts, attachment_id, ts),
        )
    if attachments:
        log_info(task_id, LogType.ATTACHMENT, f"同步附件元数据 {len(attachments)} 条（下载状态：待下载）")


# ======================================================================
# 五、待办拉取 + 去重入库（拉取模块主入口）
# ======================================================================
def sync_pending_tasks(limit: int = 10) -> dict:
    """拉取待办审批单并完成去重入库。

    返回：
        {
          "fetched": 拉取条数,
          "created": 新建任务数,
          "updated": 更新任务数,
          "skipped": 跳过数,
          "tasks":   [任务摘要列表],
          "errors":  [异常信息列表]
        }
    """
    pending = list_pending_contract_approvals(limit)
    created, updated, skipped = 0, 0, 0
    tasks: list[dict] = []
    errors: list[str] = []

    for item in pending:
        approval_code = item["approval_code"]
        try:
            existing = get_task_by_code(approval_code)
            # 附件数量未变化且任务已入库 → 只更新列表字段，无需拉详情，减少接口压力
            if existing and int(existing.get("attachment_count") or 0) == int(item.get("attachment_count") or 0):
                ts = now_str()
                execute(
                    """UPDATE approval_tasks
                          SET approval_title = ?, applicant_name = ?, apply_time = ?, updated_at = ?
                        WHERE id = ?""",
                    (item["approval_title"], item["applicant_name"], item["apply_time"], ts, existing["id"]),
                )
                skipped += 1
                log_info(existing["id"], LogType.FETCH,
                         f"待办重复拉取，任务数据无实质变化，仅刷新列表字段（去重生效）")
                tasks.append(_task_brief(existing["id"]))
                continue

            detail = get_contract_approval(item["instance_id"] or approval_code)
            result = create_or_update_task(detail)
            if result["action"] == "created":
                created += 1
            else:
                updated += 1
            tasks.append(_task_brief(result["task_id"]))
        except Exception as exc:  # noqa: BLE001 - 单个审批单失败不阻断其余审批单
            msg = f"审批单 {approval_code} 拉取失败：{exc}"
            errors.append(msg)
            log_error(0, LogType.FETCH, msg)

    log_info(0, LogType.FETCH,
             f"待办同步完成：拉取 {len(pending)} 条，新建 {created} 条，更新 {updated} 条，跳过 {skipped} 条，失败 {len(errors)} 条")
    return {
        "fetched": len(pending),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "tasks": [t for t in tasks if t],
    }


def _task_brief(task_id: int) -> dict | None:
    task = get_task(task_id)
    if not task:
        return None
    return {
        "task_id": task["id"],
        "approval_code": task["approval_code"],
        "approval_title": task["approval_title"],
        "applicant_name": task["applicant_name"],
        "apply_time": task["apply_time"],
        "attachment_count": task["attachment_count"],
        "task_status": task["task_status"],
        "write_status": task["write_status"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }
