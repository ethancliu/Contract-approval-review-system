"""附件模块。

职责：
    1. 根据「审批编号 + 附件编号 + 文件名」从审批系统下载合同附件；
    2. 落地到本地存储目录 storage/<审批编号>/<文件名>；
    3. 计算 MD5 与文件大小作为文件校验信息；
    4. 把本地路径、校验信息、下载状态持久化到 approval_attachments 表；
    5. 全部附件下载失败时抛出阻塞异常（附件缺失）。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import requests

from ..config import settings
from ..constants import DownloadStatus, LogType
from ..database import execute, now_str, query_all, query_one
from ..exceptions import AttachmentMissingError, ExternalApiError
from ..logger import log_api, log_error, log_info


# ======================================================================
# 工具函数
# ======================================================================
def _md5_of(path: Path, chunk_size: int = 1024 * 256) -> str:
    """计算文件 MD5。"""
    digest = hashlib.md5()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(name: str) -> str:
    """清理文件名中的非法路径字符，防止目录穿越。"""
    name = (name or "attachment.bin").replace("\\", "_").replace("/", "_")
    for ch in '<>:"|?*':
        name = name.replace(ch, "_")
    return name.strip() or "attachment.bin"


def task_storage_dir(approval_code: str) -> Path:
    """任务附件存储目录：storage/<审批编号>/。"""
    path = settings.STORAGE_DIR / _safe_name(approval_code)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_task_attachments(task_id: int) -> list[dict]:
    """查询任务下的全部附件记录。"""
    return query_all(
        "SELECT * FROM approval_attachments WHERE task_id = ? ORDER BY id",
        (int(task_id),),
    )


# ======================================================================
# 工具 3：附件下载
# ======================================================================
def download_contract_attachment(instance_id: str, attachment_id: str, file_name: str,
                                 task_id: int | None = None) -> dict:
    """【工具接口 3】下载合同附件并返回本地路径与校验信息。

    返回：
        local_path       本地存储路径
        file_md5         文件 MD5 校验值
        file_size        文件字节数
        download_status  下载状态（success / failed）
    """
    if not instance_id or not attachment_id or not file_name:
        raise ExternalApiError("外部接口调用失败：instance_id / attachment_id / file_name 均为必填参数")

    url = f"{settings.APPROVAL_BASE_URL}/api/attachment"
    params = {"instance_id": instance_id, "attachment_id": attachment_id, "file_name": file_name}
    headers = {"Authorization": f"Bearer {settings.APPROVAL_TOKEN}"}

    local_dir = task_storage_dir(instance_id)
    local_path = local_dir / _safe_name(file_name)

    start = time.time()
    try:
        with requests.get(url, params=params, headers=headers, stream=True,
                          timeout=settings.APPROVAL_API_TIMEOUT) as resp:
            if resp.status_code >= 400:
                raise ExternalApiError(
                    f"外部接口调用失败：附件下载返回 HTTP {resp.status_code}",
                    detail=f"附件：{file_name}；响应：{resp.text[:300]}",
                )
            with local_path.open("wb") as fp:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        fp.write(chunk)
    except ExternalApiError:
        _mark_failed(task_id, attachment_id, f"下载失败：审批系统返回异常")
        raise
    except requests.RequestException as exc:
        _mark_failed(task_id, attachment_id, f"下载失败：{exc}")
        raise ExternalApiError(
            "外部接口调用失败：附件下载连接失败",
            detail=f"附件：{file_name}；错误：{exc}",
        ) from exc
    cost_ms = int((time.time() - start) * 1000)
    log_api(task_id, f"附件下载完成：{file_name} → {local_path}（{cost_ms}ms）", cost_ms=cost_ms)

    # ---------------- 文件校验 ----------------
    if not local_path.exists() or local_path.stat().st_size <= 0:
        _mark_failed(task_id, attachment_id, "下载失败：落地文件为空")
        raise AttachmentMissingError(
            f"附件缺失：附件 {file_name} 下载后文件为空",
            detail=f"本地路径：{local_path}",
        )

    file_md5 = _md5_of(local_path)
    file_size = local_path.stat().st_size
    file_type = local_path.suffix.lstrip(".").lower()

    # ---------------- 元数据入库 ----------------
    if task_id:
        execute(
            """
            UPDATE approval_attachments
               SET file_path = ?, download_status = ?, file_md5 = ?, file_size = ?,
                   download_error = '', updated_at = ?
             WHERE task_id = ? AND attachment_id = ?
            """,
            (str(local_path), DownloadStatus.SUCCESS, file_md5, file_size, now_str(),
             int(task_id), str(attachment_id)),
        )
    log_info(task_id, LogType.ATTACHMENT,
             f"附件校验通过：{file_name}，大小 {file_size} 字节，MD5={file_md5}")

    return {
        "local_path": str(local_path),
        "file_md5": file_md5,
        "file_size": file_size,
        "download_status": DownloadStatus.SUCCESS,
        # ---- 辅助字段 ----
        "file_name": file_name,
        "file_type": file_type,
        "attachment_id": attachment_id,
        "instance_id": instance_id,
        "download_time": now_str(),
    }


def _mark_failed(task_id: int | None, attachment_id: str, error: str) -> None:
    """标记附件下载失败。"""
    if not task_id:
        return
    try:
        execute(
            """UPDATE approval_attachments
                  SET download_status = ?, download_error = ?, updated_at = ?
                WHERE task_id = ? AND attachment_id = ?""",
            (DownloadStatus.FAILED, error[:500], now_str(), int(task_id), str(attachment_id)),
        )
    except Exception as exc:  # noqa: BLE001
        log_error(task_id, LogType.ATTACHMENT, f"标记附件下载失败状态异常：{exc}")


# ======================================================================
# 批量下载（供流程编排调用）
# ======================================================================
def download_task_attachments(task: dict) -> list[dict]:
    """下载任务下的全部附件。

    返回已成功下载的附件记录列表；若一条成功的都没有，抛出 AttachmentMissingError
    （触发阻塞场景：附件缺失 / 外部接口调用失败）。
    """
    task_id = int(task["id"])
    approval_code = task["approval_code"]
    rows = list_task_attachments(task_id)

    if not rows:
        raise AttachmentMissingError(
            "附件缺失：该审批单未上传任何合同附件，无法执行审查",
            detail=f"审批编号：{approval_code}；请业务部门补充合同附件后由管理员重试。",
        )

    downloaded: list[dict] = []
    errors: list[str] = []
    for row in rows:
        # 已成功下载且本地文件仍存在 → 复用，避免重复下载
        if row["download_status"] == DownloadStatus.SUCCESS and row["file_path"]:
            if Path(row["file_path"]).exists() and Path(row["file_path"]).stat().st_size > 0:
                downloaded.append(row)
                log_info(task_id, LogType.ATTACHMENT, f"附件已存在，复用本地文件：{row['file_name']}")
                continue

        try:
            result = download_contract_attachment(
                approval_code, row["attachment_id"], row["file_name"], task_id=task_id
            )
            row = dict(row)
            row.update({
                "file_path": result["local_path"],
                "file_md5": result["file_md5"],
                "file_size": result["file_size"],
                "download_status": DownloadStatus.SUCCESS,
            })
            downloaded.append(row)
        except Exception as exc:  # noqa: BLE001 - 单个附件失败继续尝试其余附件
            errors.append(f"{row['file_name']}：{exc}")
            log_error(task_id, LogType.ATTACHMENT, f"附件下载失败：{row['file_name']} —— {exc}")

    if not downloaded:
        raise AttachmentMissingError(
            "附件缺失：全部合同附件均下载失败",
            detail="；".join(errors)[:800],
        )

    log_info(task_id, LogType.ATTACHMENT,
             f"附件下载完成：成功 {len(downloaded)} 个，失败 {len(errors)} 个")
    return downloaded
