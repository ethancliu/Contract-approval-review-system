"""核心工具接口（7 个）+ 全流程编排接口。

接口定义严格遵循需求文档，入参出参不可自定义修改：

    POST /api/tools/list_pending_contract_approvals   {limit}
    POST /api/tools/get_contract_approval             {instance_id}
    POST /api/tools/download_contract_attachment      {instance_id, attachment_id, file_name}
    POST /api/tools/parse_contract_document           {document_id}
    POST /api/tools/run_contract_rules                {case_id}
    POST /api/tools/save_review_result                {case_id, overall_risk_level, summary_text,
                                                       focus_points_json, comment_text}
    POST /api/tools/write_approval_comment            {instance_id, review_id}
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..constants import TaskStatus
from ..modules import pipeline, service
from ..modules.fetcher import get_task
from ..modules.parser.ocr_engine import ocr_engine

router = APIRouter(prefix="/api/tools", tags=["核心工具接口"])


# ======================================================================
# 请求模型（字段名与规范完全一致）
# ======================================================================
class ListPendingRequest(BaseModel):
    """工具 1 入参。"""
    limit: int = Field(default=10, ge=1, le=200, description="本次拉取的待办条数上限")


class GetApprovalRequest(BaseModel):
    """工具 2 入参。"""
    instance_id: str = Field(..., description="审批单实例编号（审批编号）")


class DownloadAttachmentRequest(BaseModel):
    """工具 3 入参。"""
    instance_id: str = Field(..., description="审批单实例编号")
    attachment_id: str = Field(..., description="附件编号")
    file_name: str = Field(..., description="附件文件名")


class ParseDocumentRequest(BaseModel):
    """工具 4 入参。"""
    document_id: str = Field(..., description="文档标识：附件ID（approval_attachments.id）或审批编号")


class RunRulesRequest(BaseModel):
    """工具 5 入参。"""
    case_id: str = Field(..., description="案件标识：任务ID（approval_tasks.id）或审批编号")


class SaveResultRequest(BaseModel):
    """工具 6 入参。"""
    case_id: str = Field(..., description="案件标识：任务ID或审批编号")
    overall_risk_level: str = Field(..., description="总风险等级：低/中/高")
    summary_text: str = Field(..., description="中文风险摘要")
    focus_points_json: list | str = Field(default_factory=list, description="审批关注点数组或JSON字符串")
    comment_text: str = Field(default="", description="待回写评论文本；为空时自动拼接标准模板")


class WriteCommentRequest(BaseModel):
    """工具 7 入参。"""
    instance_id: str = Field(..., description="审批单实例编号")
    review_id: int = Field(..., description="审查结果ID（review_results.id）")


# ======================================================================
# 工具 1：待办拉取
# ======================================================================
@router.post("/list_pending_contract_approvals", summary="工具1 待办拉取")
def tool_list_pending_contract_approvals(req: ListPendingRequest) -> dict:
    """返回待处理审批单列表。

    每项必含：审批编号 / 标题 / 申请人 / 申请时间 / 附件数量。
    """
    return service.list_pending_contract_approvals(req.limit)


# ======================================================================
# 工具 2：审批详情
# ======================================================================
@router.post("/get_contract_approval", summary="工具2 审批详情")
def tool_get_contract_approval(req: GetApprovalRequest) -> dict:
    """返回单个审批单完整详情：审批基础信息、表单数据、附件信息、当前处理状态。"""
    return service.get_contract_approval(req.instance_id)


# ======================================================================
# 工具 3：附件下载
# ======================================================================
@router.post("/download_contract_attachment", summary="工具3 附件下载")
def tool_download_contract_attachment(req: DownloadAttachmentRequest) -> dict:
    """下载合同附件，返回本地存储路径与文件校验信息（MD5 / 大小 / 下载状态）。"""
    return service.download_contract_attachment(req.instance_id, req.attachment_id, req.file_name)


# ======================================================================
# 工具 4：文档解析
# ======================================================================
@router.post("/parse_contract_document", summary="工具4 文档解析")
def tool_parse_contract_document(req: ParseDocumentRequest) -> dict:
    """解析本地已存合同文件，返回结构化字段、对应原文片段与内容位置定位信息。"""
    return service.parse_contract_document(req.document_id)


# ======================================================================
# 工具 5：规则审查
# ======================================================================
@router.post("/run_contract_rules", summary="工具5 规则审查")
def tool_run_contract_rules(req: RunRulesRequest) -> dict:
    """对解析结果执行全量规则匹配，返回风险等级、命中证据与标准化处理建议。"""
    return service.run_contract_rules(req.case_id)


# ======================================================================
# 工具 6：结果保存
# ======================================================================
@router.post("/save_review_result", summary="工具6 结果保存")
def tool_save_review_result(req: SaveResultRequest) -> dict:
    """持久化审查结果、命中规则、风险摘要与关注点。"""
    return service.save_review_result(
        req.case_id, req.overall_risk_level, req.summary_text,
        req.focus_points_json, req.comment_text,
    )


# ======================================================================
# 工具 7：评论回写
# ======================================================================
@router.post("/write_approval_comment", summary="工具7 评论回写")
def tool_write_approval_comment(req: WriteCommentRequest) -> dict:
    """自动拼接标准化审查意见并写回审批系统评论区，返回回写状态与响应结果。"""
    return service.write_approval_comment(req.instance_id, req.review_id)


# ======================================================================
# 附加：OCR 能力探测（便于调用端了解扫描件识别可用性）
# ======================================================================
@router.get("/ocr_status", summary="OCR 识别能力探测")
def tool_ocr_status() -> dict:
    """返回各 OCR 后端的可用性，便于判断扫描件是否可自动识别。"""
    return ocr_engine.describe()


# ======================================================================
# 全流程编排接口（闭环演示入口）
# ======================================================================
pipeline_router = APIRouter(prefix="/api/pipeline", tags=["全流程编排"])


class SyncRequest(BaseModel):
    """待办同步入参。"""
    limit: int = Field(default=10, ge=1, le=200)


class RunRequest(BaseModel):
    """单任务闭环执行入参。"""
    task_id: int | None = Field(default=None, description="任务主键")
    instance_id: str | None = Field(default=None, description="审批编号（与 task_id 二选一）")


@pipeline_router.post("/sync", summary="拉取待办并去重入库")
def pipeline_sync(req: SyncRequest) -> dict:
    """拉取待办审批单 → 按审批编号去重 → 新建/增量更新任务。"""
    from ..modules import fetcher  # noqa: PLC0415
    return fetcher.sync_pending_tasks(req.limit)


@pipeline_router.post("/run", summary="执行单任务完整闭环")
def pipeline_run(req: RunRequest) -> dict:
    """执行「下载 → 解析 → 审查 → 入库 → 回写」完整闭环。"""
    task_id = req.task_id
    if not task_id and req.instance_id:
        task = get_task_by_instance(req.instance_id)
        task_id = task["id"]
    if not task_id:
        return {"error": "必须提供 task_id 或 instance_id"}
    return pipeline.process_task(int(task_id), force=False)


@pipeline_router.post("/sync_and_process", summary="一键闭环：拉取→审查→回写")
def pipeline_sync_and_process(req: SyncRequest) -> dict:
    """演示用一键闭环：拉取待办、去重入库，并逐个执行完整审查闭环。"""
    return pipeline.sync_and_process(req.limit)


@pipeline_router.post("/retry/{task_id}", summary="管理员重试阻塞任务")
def pipeline_retry(task_id: int, operator: str = Query("系统管理员")) -> dict:
    """把 blocked 任务重置并重新走 parsing / reviewing / 回写流程。"""
    return pipeline.retry_task(int(task_id), operator)


# ======================================================================
# 任务查询接口（供调用端展示）
# ======================================================================
task_router = APIRouter(prefix="/api", tags=["任务查询"])


def get_task_by_instance(instance_id: str) -> dict:
    """按审批编号查询任务，不存在时先自动同步一次。"""
    from ..modules import fetcher  # noqa: PLC0415
    task = fetcher.get_task_by_code(instance_id)
    if task:
        return task
    detail = fetcher.get_contract_approval(instance_id)
    result = fetcher.create_or_update_task(detail)
    return fetcher.get_task(result["task_id"])


@task_router.get("/tasks", summary="任务列表")
def api_list_tasks(task_status: str | None = Query(None, description="按任务状态过滤"),
                   limit: int = Query(100, ge=1, le=500)) -> dict:
    """查询已入库的审批任务列表（含最新风险等级）。"""
    items = pipeline.list_task_summaries(task_status, limit)
    return {"total": len(items), "list": items, "task_status_cn": TaskStatus.CN}


@task_router.get("/tasks/{task_id}", summary="任务详情（全链路）")
def api_task_detail(task_id: int) -> dict:
    """聚合展示：任务 / 附件 / 解析结果 / 规则命中 / 审查结论 / 回写日志 / 运行日志。"""
    return pipeline.build_task_detail(int(task_id))


@task_router.get("/overview", summary="系统总览统计")
def api_overview() -> dict:
    """首页看板统计。"""
    return pipeline.system_overview()


@task_router.get("/config", summary="运行配置快照")
def api_config() -> dict:
    """返回当前运行配置（隐藏敏感令牌）。"""
    from ..config import settings  # noqa: PLC0415
    return settings.as_dict()


@task_router.post("/demo/reset", summary="重置演示数据")
def api_reset_demo() -> dict:
    """清空任务与审查数据（保留规则配置），用于重复演示。"""
    return pipeline.reset_pipeline_data()
