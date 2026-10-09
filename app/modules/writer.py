"""回写模块。

职责：
    1. 把审查结论智能拼接为可直接写入审批评论区的标准化文本；
    2. 调用企业审批系统评论接口完成回写；
    3. 全量记录回写日志（comment_logs + task_logs）；
    4. 回写失败时置任务为 blocked（触发阻塞场景：外部接口调用失败），支持人工重试。
"""

from __future__ import annotations

import json

import requests

from ..config import settings
from ..constants import LogType, WriteStatus
from ..database import execute, json_loads, now_str, query_all, query_one
from ..exceptions import ExternalApiError
from ..logger import log_error, log_info, log_warn

#: 评论正文中最多列出的风险条目数（超出部分引导到系统内查看）
MAX_HITS_IN_COMMENT = 15


# ======================================================================
# 一、审查意见文本拼接
# ======================================================================
def build_comment_text(task: dict, review: dict, hits: list[dict]) -> str:
    """把审查结果拼接为标准化中文评论文本。

    参数：
        task    审批任务记录（approval_tasks 行）
        review  审查结果记录（review_results 行）
        hits    命中规则列表（rule_hits 行快照）
    """
    focus_points = json_loads(review.get("focus_points_json"), []) or []
    overall = review.get("overall_risk_level", "低")

    high = sum(1 for h in hits if h.get("risk_level") == "高")
    medium = sum(1 for h in hits if h.get("risk_level") == "中")
    low = sum(1 for h in hits if h.get("risk_level") == "低")

    lines: list[str] = []
    lines.append("【智能合同审查意见（系统自动生成 · 仅辅助人工审批）】")
    lines.append("")
    lines.append("一、合同基本信息")
    lines.append(f"　　审批编号：{task.get('approval_code', '')}")
    lines.append(f"　　合同标题：{task.get('approval_title', '')}")
    lines.append(f"　　申 请 人：{task.get('applicant_name', '')}")
    lines.append(f"　　审查时间：{review.get('created_at') or now_str()}")
    lines.append("")
    lines.append(f"二、总体风险等级：{overall}")
    lines.append(f"　　命中风险规则 {len(hits)} 条（高 {high} 条 / 中 {medium} 条 / 低 {low} 条）")
    lines.append("")

    lines.append("三、风险明细")
    if hits:
        for idx, hit in enumerate(hits[:MAX_HITS_IN_COMMENT], start=1):
            lines.append(f"　{idx}. 【{hit.get('risk_level', '')}风险】{hit.get('rule_name', '')}"
                         f"（规则编码 {hit.get('rule_code', '')}）")
            lines.append(f"　　　命中证据：{_one_line(hit.get('evidence_text', ''))}")
            lines.append(f"　　　证据位置：{hit.get('evidence_position', '')}")
            lines.append(f"　　　处理建议：{_one_line(hit.get('suggestion_text', ''))}")
        if len(hits) > MAX_HITS_IN_COMMENT:
            lines.append(f"　（其余 {len(hits) - MAX_HITS_IN_COMMENT} 条风险明细请在审查系统中查看）")
    else:
        lines.append("　　未命中任何内置风控规则。")
    lines.append("")

    lines.append("四、审批关注点")
    if focus_points:
        for idx, point in enumerate(focus_points, start=1):
            lines.append(f"　{idx}. {_one_line(point)}")
    else:
        lines.append("　　无")
    lines.append("")

    lines.append("五、风险摘要")
    lines.append(f"　　{_one_line(review.get('summary_text', ''))}")
    lines.append("")
    lines.append("六、说明")
    lines.append("　　1. 本意见由「企业合同审批自动审查系统」基于内置风控规则自动生成，")
    lines.append("　　　 仅用于辅助人工审批，不构成最终审批结论，最终审批权归人工法务。")
    lines.append("　　2. 系统证据定位在扫描件（OCR）场景下可能存在少量偏差，请按位置标识核对原件。")
    lines.append("　　3. 如对审查结果有异议，可在审查系统中查看完整证据并标记忽略/确认。")

    return "\n".join(lines)


def _one_line(text: str, max_chars: int = 400) -> str:
    """把多行文本压成单行，避免评论排版错乱。"""
    text = (text or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= max_chars else text[:max_chars] + "……"


# ======================================================================
# 二、工具 7：评论回写
# ======================================================================
def write_approval_comment(instance_id: str, review_id: int, task_id: int | None = None) -> dict:
    """【工具接口 7】把审查意见回写到审批系统评论区。

    返回：
        write_status         回写状态：writing / success / failed
        write_response_text  回写响应结果
        comment_text         实际回写的内容
    """
    review = query_one("SELECT * FROM review_results WHERE id = ?", (int(review_id),))
    if not review:
        raise ValueError(f"审查结果不存在：review_id={review_id}")

    task = query_one("SELECT * FROM approval_tasks WHERE id = ?", (int(review["task_id"]),))
    if not task:
        raise ValueError(f"审批任务不存在：task_id={review['task_id']}")

    instance_id = instance_id or task["approval_code"]
    task_id = int(task["id"])
    hits = query_all(
        "SELECT * FROM rule_hits WHERE task_id = ? ORDER BY "
        "CASE risk_level WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END, id",
        (task_id,),
    )

    comment_text = review.get("comment_text") or build_comment_text(task, review, hits)

    # ---------------- 1) 置为「回写中」 ----------------
    execute("UPDATE approval_tasks SET write_status = ?, updated_at = ? WHERE id = ?",
            (WriteStatus.WRITING, now_str(), task_id))
    log_info(task_id, LogType.WRITE, f"开始回写审批评论：审批编号={instance_id}，评论长度={len(comment_text)} 字符")

    url = f"{settings.APPROVAL_BASE_URL}/api/comment/{instance_id}"
    payload = {
        "comment": comment_text,
        "operator": settings.APPROVAL_OPERATOR,
        "review_id": int(review_id),
    }
    headers = {
        "Authorization": f"Bearer {settings.APPROVAL_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }

    # ---------------- 2) 调用审批系统 ----------------
    http_status = 0
    response_text = ""
    try:
        resp = requests.post(url, json=payload, headers=headers,
                             timeout=settings.APPROVAL_API_TIMEOUT)
        http_status = resp.status_code
        response_text = resp.text[:2000]
        if resp.status_code >= 400:
            raise ExternalApiError(
                f"外部接口调用失败：评论回写返回 HTTP {resp.status_code}",
                detail=response_text,
            )
        try:
            body = resp.json()
            if body.get("code") not in (0, 200, None):
                raise ExternalApiError(
                    f"外部接口调用失败：评论回写业务错误 code={body.get('code')}",
                    detail=str(body.get("message") or body)[:500],
                )
        except ValueError:
            body = {"raw": response_text}
    except ExternalApiError as exc:
        return _finish_write(task_id, review_id, instance_id, WriteStatus.FAILED,
                             f"回写失败：{exc.message} {exc.detail}", comment_text,
                             http_status, payload, str(exc.detail))
    except requests.RequestException as exc:
        return _finish_write(task_id, review_id, instance_id, WriteStatus.FAILED,
                             f"回写失败：无法连接审批系统（{exc}）", comment_text,
                             http_status, payload, str(exc))

    # ---------------- 3) 回写成功 ----------------
    return _finish_write(
        task_id, review_id, instance_id, WriteStatus.SUCCESS,
        f"回写成功：HTTP {http_status}，响应={json.dumps(body, ensure_ascii=False)[:500]}",
        comment_text, http_status, payload, "",
    )


def _finish_write(task_id: int, review_id: int, instance_id: str, status: str,
                  response_text: str, comment_text: str, http_status: int,
                  payload: dict, error: str) -> dict:
    """回写结果落库（comment_logs + approval_tasks）并返回标准结果。"""
    ts = now_str()
    execute(
        """
        INSERT INTO comment_logs
            (task_id, write_status, write_response_text, created_at,
             review_id, comment_text, http_status, request_payload, write_error)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (task_id, status, response_text, ts, int(review_id), comment_text,
         int(http_status or 0), json.dumps(payload, ensure_ascii=False)[:4000], error[:1000]),
    )
    execute("UPDATE approval_tasks SET write_status = ?, updated_at = ? WHERE id = ?",
            (status, ts, task_id))

    if status == WriteStatus.SUCCESS:
        log_info(task_id, LogType.WRITE, response_text)
    else:
        log_warn(task_id, LogType.WRITE, response_text)

    return {
        "write_status": status,
        "write_response_text": response_text,
        "comment_text": comment_text,
        # ---- 辅助字段 ----
        "task_id": task_id,
        "review_id": int(review_id),
        "instance_id": instance_id,
        "http_status": http_status,
        "write_time": ts,
    }


def list_comment_logs(task_id: int | None = None, limit: int = 100) -> list[dict]:
    """查询评论回写日志（附带审批编号，便于调用端直接展示）。"""
    base_sql = (
        "SELECT c.*, t.approval_code AS approval_code "
        "FROM comment_logs c LEFT JOIN approval_tasks t ON t.id = c.task_id"
    )
    if task_id:
        return query_all(
            base_sql + " WHERE c.task_id = ? ORDER BY c.id DESC LIMIT ?",
            (int(task_id), int(limit)),
        )
    return query_all(base_sql + " ORDER BY c.id DESC LIMIT ?", (int(limit),))
