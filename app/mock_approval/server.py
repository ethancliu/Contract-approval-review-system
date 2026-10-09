"""模拟审批系统 HTTP 服务（演示用）。

对外暴露与企业审批系统一致的 4 个接口：

    GET  /api/pending?limit=N                     拉取待处理审批单列表
    GET  /api/approval/{instance_id}              查询审批单完整详情
    GET  /api/attachment                         下载合同附件（二进制流）
    POST /api/comment/{instance_id}               写入审批评论（回写）

另提供演示辅助接口：
    GET  /api/health                              健康检查
    POST /api/_simulate/offline?value=1|0         模拟审批系统不可用（演示「外部接口调用失败」阻塞）
    GET  /api/_comments/{instance_id}             查看已回写的评论（验证回写结果）
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..config import settings
from ..database import now_str
from . import data

app = FastAPI(title="模拟企业审批系统", version="1.0.0")

#: 演示开关：置为 True 时所有业务接口返回 503，用于演示「外部接口调用失败」阻塞场景
_state = {"offline": False}

#: 已写入的评论（内存态，演示用）
_comments: dict[str, list[dict]] = {}


def _guard_offline() -> None:
    if _state["offline"]:
        raise HTTPException(status_code=503, detail="模拟审批系统维护中（演示：外部接口调用失败）")


def _attachment_path(instance_id: str, file_name: str) -> Path:
    return settings.SAMPLE_DIR / file_name


def _ok(payload) -> JSONResponse:
    return JSONResponse({"code": 0, "message": "success", "data": payload})


# ======================================================================
# 业务接口
# ======================================================================
@app.get("/api/pending")
def api_pending(limit: int = Query(10, ge=1, le=200)):
    """拉取待处理审批单列表。"""
    _guard_offline()
    approvals = data.list_pending(limit)
    items = []
    for a in approvals:
        items.append({
            "instance_id": a["instance_id"],
            "approval_code": a["approval_code"],
            "approval_title": a["title"],
            "applicant_name": a["applicant"],
            "apply_time": a["apply_time"],
            "attachment_count": len(a.get("attachments", [])),
            "status": a.get("status", ""),
        })
    return _ok({"total": len(items), "list": items})


@app.get("/api/approval/{instance_id}")
def api_approval_detail(instance_id: str):
    """查询单个审批单完整详情。"""
    _guard_offline()
    approval = data.get_approval(instance_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"审批单不存在：{instance_id}")

    attachments = []
    for att in approval.get("attachments", []):
        path = _attachment_path(instance_id, att["file_name"])
        attachments.append({
            **att,
            "file_size": path.stat().st_size if path.exists() else 0,
            "file_exists": path.exists(),
        })

    return _ok({
        "instance_id": approval["instance_id"],
        "basic_info": {
            "approval_code": approval["approval_code"],
            "approval_title": approval["title"],
            "applicant_name": approval["applicant"],
            "apply_time": approval["apply_time"],
            "department": approval.get("department", ""),
            "current_handler": approval.get("current_handler", ""),
        },
        "form_data": approval.get("form_data", {}),
        "attachments": attachments,
        "current_status": {
            "status": approval.get("status", ""),
            "current_handler": approval.get("current_handler", ""),
            "comment_count": len(_comments.get(instance_id, [])),
        },
    })


@app.get("/api/attachment")
def api_download_attachment(
    instance_id: str = Query(...),
    attachment_id: str = Query(...),
    file_name: str = Query(...),
):
    """下载合同附件（二进制文件流）。"""
    _guard_offline()
    approval = data.get_approval(instance_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"审批单不存在：{instance_id}")

    target = next(
        (a for a in approval.get("attachments", []) if a["attachment_id"] == attachment_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail=f"附件不存在：{attachment_id}")
    if target["file_name"] != file_name:
        raise HTTPException(status_code=400, detail=f"附件文件名不匹配：期望 {target['file_name']}")

    path = _attachment_path(instance_id, file_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"附件文件在服务器上不存在：{file_name}")

    return FileResponse(path=str(path), filename=file_name, media_type="application/octet-stream")


class CommentBody(BaseModel):
    """评论回写请求体。"""
    comment: str
    operator: str = "合同智能审查机器人"
    review_id: int = 0


@app.post("/api/comment/{instance_id}")
def api_write_comment(instance_id: str, body: CommentBody):
    """写入审批评论（回写）。"""
    _guard_offline()
    approval = data.get_approval(instance_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"审批单不存在：{instance_id}")
    if not (body.comment or "").strip():
        raise HTTPException(status_code=400, detail="评论内容不能为空")

    record = {
        "comment_id": f"CMT-{instance_id}-{len(_comments.get(instance_id, [])) + 1}",
        "instance_id": instance_id,
        "operator": body.operator,
        "review_id": body.review_id,
        "comment": body.comment,
        "write_time": now_str(),
    }
    _comments.setdefault(instance_id, []).append(record)

    return _ok({
        "comment_id": record["comment_id"],
        "write_time": record["write_time"],
        "operator": record["operator"],
        "comment_length": len(body.comment),
        "received": True,
    })


@app.get("/api/_comments/{instance_id}")
def api_list_comments(instance_id: str):
    """查看已回写评论（验证回写结果用）。"""
    return _ok({"instance_id": instance_id, "comments": _comments.get(instance_id, [])})


# ======================================================================
# 演示辅助接口
# ======================================================================
@app.get("/api/health")
def api_health():
    return _ok({"status": "ok", "service": "mock-approval-system", "offline": _state["offline"]})


@app.post("/api/_simulate/offline")
def api_simulate_offline(value: int = Query(1, description="1=模拟不可用，0=恢复正常")):
    """切换「审批系统不可用」演示开关。"""
    _state["offline"] = bool(value)
    return _ok({"offline": _state["offline"], "tip": "已切换模拟审批系统可用性开关"})


@app.post("/api/_simulate/add_attachment")
def api_simulate_add_attachment(
    instance_id: str = Query(..., description="审批编号"),
    file_name: str = Query(..., description="补充上传的附件文件名（需存在于 sample_contracts/）"),
    file_type: str = Query("", description="文件类型，留空则按扩展名推断"),
):
    """给审批单补传一个附件（演示「补齐材料 → 重试成功」闭环）。"""
    record = data.add_attachment(instance_id, file_name, file_type)
    if not record:
        raise HTTPException(status_code=404, detail=f"审批单不存在：{instance_id}")
    exists = (settings.SAMPLE_DIR / file_name).exists()
    return _ok({
        "attachment": record,
        "file_exists_on_disk": exists,
        "tip": "已为审批单补传附件，可在调用端对该任务执行「管理员重试」",
    })


@app.post("/api/_simulate/reset")
def api_simulate_reset():
    """还原审批单初始演示数据（清除补传的附件）与评论记录。"""
    count = data.reset_approvals()
    _comments.clear()
    _state["offline"] = False
    return _ok({"approvals": count, "tip": "模拟审批系统数据已还原"})


@app.get("/")
def api_root():
    return _ok({
        "service": "模拟企业审批系统",
        "version": "1.0.0",
        "endpoints": [
            "GET  /api/pending?limit=N",
            "GET  /api/approval/{instance_id}",
            "GET  /api/attachment?instance_id=&attachment_id=&file_name=",
            "POST /api/comment/{instance_id}",
            "GET  /api/_comments/{instance_id}",
            "POST /api/_simulate/offline?value=1|0",
            "POST /api/_simulate/add_attachment?instance_id=&file_name=",
            "POST /api/_simulate/reset",
        ],
    })
