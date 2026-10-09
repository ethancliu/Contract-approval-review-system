"""模拟审批系统的演示数据。

共 8 个待审审批单，覆盖：
    001 电子文档·标准合同        → 预期总风险【低】
    002 电子文档·风险合同        → 预期总风险【高】
    003 扫描件·OCR 识别          → 预期总风险【中】
    004 电子文档·要素缺失合同    → 预期总风险【高】
    005 无附件审批单             → 预期阻塞：附件缺失
    006 扫描件·未配置 OCR        → 预期阻塞：扫描件图片无法识别
    007 空白文档                 → 预期阻塞：文档内容为空
    008 损坏文档                 → 预期阻塞：文件解析异常

附件文件真实存放于项目 sample_contracts/ 目录，由 scripts/gen_samples.py 生成。
"""

from __future__ import annotations

from datetime import datetime

#: 演示用审批单数据（结构与企业审批系统详情接口保持一致）
APPROVALS: list[dict] = [
    {
        "instance_id": "HTSP20261009001",
        "approval_code": "HTSP20261009001",
        "title": "服务器设备采购合同审批",
        "applicant": "张伟（IT 基础架构部）",
        "apply_time": "2026-10-08 09:12:33",
        "status": "待法务审核",
        "current_handler": "法务部-李静",
        "department": "IT 基础架构部",
        "form_data": {
            "采购类别": "固定资产采购",
            "供应商名称": "上海云海电子设备有限公司",
            "预估金额（元）": "860000",
            "预算科目": "2026年度IT设备预算",
            "是否集采范围内": "否",
            "经办人": "张伟",
        },
        "attachments": [
            {
                "attachment_id": "ATT-20261009-001-1",
                "file_name": "采购合同-标准版.docx",
                "file_type": "docx",
                "file_size": 0,
                "upload_time": "2026-10-08 09:11:02",
            }
        ],
    },
    {
        "instance_id": "HTSP20261009002",
        "approval_code": "HTSP20261009002",
        "title": "核心系统运维技术服务合同审批",
        "applicant": "王芳（运维保障部）",
        "apply_time": "2026-10-08 10:35:07",
        "status": "待法务审核",
        "current_handler": "法务部-李静",
        "department": "运维保障部",
        "form_data": {
            "采购类别": "技术服务",
            "供应商名称": "深圳市智联信息技术有限公司",
            "预估金额（元）": "1200000",
            "服务期限": "2026-10-15 至 2027-10-14",
            "是否集采范围内": "否",
            "经办人": "王芳",
        },
        "attachments": [
            {
                "attachment_id": "ATT-20261009-002-1",
                "file_name": "技术服务合同-风险版.docx",
                "file_type": "docx",
                "file_size": 0,
                "upload_time": "2026-10-08 10:34:11",
            }
        ],
    },
    {
        "instance_id": "HTSP20261009003",
        "approval_code": "HTSP20261009003",
        "title": "客户管理系统开发合同审批（扫描件）",
        "applicant": "刘洋（数字化中心）",
        "apply_time": "2026-10-09 08:41:52",
        "status": "待法务审核",
        "current_handler": "法务部-赵刚",
        "department": "数字化中心",
        "form_data": {
            "采购类别": "软件研发",
            "供应商名称": "杭州云码软件有限公司",
            "预估金额（元）": "480000",
            "开发周期": "120 个日历日",
            "合同原件形式": "纸质扫描件",
            "经办人": "刘洋",
        },
        "attachments": [
            {
                "attachment_id": "ATT-20261009-003-1",
                "file_name": "软件开发合同-扫描件.png",
                "file_type": "png",
                "file_size": 0,
                "upload_time": "2026-10-09 08:40:20",
            }
        ],
    },
    {
        "instance_id": "HTSP20261009004",
        "approval_code": "HTSP20261009004",
        "title": "管理咨询框架合作协议审批",
        "applicant": "陈晨（战略发展部）",
        "apply_time": "2026-10-09 09:03:18",
        "status": "待法务审核",
        "current_handler": "法务部-赵刚",
        "department": "战略发展部",
        "form_data": {
            "采购类别": "咨询服务",
            "供应商名称": "上海恒信管理咨询有限公司",
            "预估金额（元）": "以服务确认单为准",
            "合作期限": "框架协议，长期有效",
            "经办人": "陈晨",
        },
        "attachments": [
            {
                "attachment_id": "ATT-20261009-004-1",
                "file_name": "框架合作协议-要素缺失版.docx",
                "file_type": "docx",
                "file_size": 0,
                "upload_time": "2026-10-09 09:02:40",
            }
        ],
    },
    {
        "instance_id": "HTSP20261009005",
        "approval_code": "HTSP20261009005",
        "title": "办公用品采购合同审批（附件待补充）",
        "applicant": "孙娜（行政部）",
        "apply_time": "2026-10-09 09:20:44",
        "status": "待法务审核",
        "current_handler": "法务部-李静",
        "department": "行政部",
        "form_data": {
            "采购类别": "低值易耗品",
            "供应商名称": "北京优品办公用品有限公司",
            "预估金额（元）": "36000",
            "备注": "经办人尚未上传合同附件",
            "经办人": "孙娜",
        },
        # 故意不提供附件：演示「附件缺失」阻塞场景
        "attachments": [],
    },
    {
        "instance_id": "HTSP20261009006",
        "approval_code": "HTSP20261009006",
        "title": "设备租赁合同审批（扫描件·未配置OCR）",
        "applicant": "周涛（生产制造部）",
        "apply_time": "2026-10-09 09:33:09",
        "status": "待法务审核",
        "current_handler": "法务部-赵刚",
        "department": "生产制造部",
        "form_data": {
            "采购类别": "设备租赁",
            "供应商名称": "天津恒力设备租赁有限公司",
            "预估金额（元）": "150000",
            "合同原件形式": "手机拍摄照片",
            "经办人": "周涛",
        },
        "attachments": [
            {
                "attachment_id": "ATT-20261009-006-1",
                "file_name": "设备租赁合同-无OCR配置.png",
                "file_type": "png",
                "file_size": 0,
                "upload_time": "2026-10-09 09:32:01",
            }
        ],
    },
    {
        "instance_id": "HTSP20261009007",
        "approval_code": "HTSP20261009007",
        "title": "临时服务协议审批（空白文档）",
        "applicant": "吴敏（市场部）",
        "apply_time": "2026-10-09 09:45:26",
        "status": "待法务审核",
        "current_handler": "法务部-李静",
        "department": "市场部",
        "form_data": {
            "采购类别": "市场活动服务",
            "供应商名称": "北京亮点文化传播有限公司",
            "预估金额（元）": "88000",
            "备注": "上传的文档打开后为空白",
            "经办人": "吴敏",
        },
        "attachments": [
            {
                "attachment_id": "ATT-20261009-007-1",
                "file_name": "临时服务协议-空白.docx",
                "file_type": "docx",
                "file_size": 0,
                "upload_time": "2026-10-09 09:44:50",
            }
        ],
    },
    {
        "instance_id": "HTSP20261009008",
        "approval_code": "HTSP20261009008",
        "title": "物流运输合同审批（文件损坏）",
        "applicant": "郑凯（供应链部）",
        "apply_time": "2026-10-09 09:58:12",
        "status": "待法务审核",
        "current_handler": "法务部-赵刚",
        "department": "供应链部",
        "form_data": {
            "采购类别": "物流服务",
            "供应商名称": "深圳市顺捷物流有限公司",
            "预估金额（元）": "260000",
            "备注": "合同文件下载后无法打开",
            "经办人": "郑凯",
        },
        "attachments": [
            {
                "attachment_id": "ATT-20261009-008-1",
                "file_name": "物流运输合同-损坏.docx",
                "file_type": "docx",
                "file_size": 0,
                "upload_time": "2026-10-09 09:57:30",
            }
        ],
    },
]

#: 审批单索引（instance_id -> 审批单）
APPROVAL_INDEX: dict[str, dict] = {a["instance_id"]: a for a in APPROVALS}


#: 演示基线快照（用于 /api/_simulate/reset 还原审批单数据）
BASELINE: dict[str, list[dict]] = {k: [dict(a) for a in v.get("attachments", [])]
                                   for k, v in APPROVAL_INDEX.items()}


def get_approval(instance_id: str) -> dict | None:
    """按审批编号查询审批单。"""
    return APPROVAL_INDEX.get(instance_id)


def add_attachment(instance_id: str, file_name: str, file_type: str = "") -> dict | None:
    """给指定审批单追加一个附件（演示「补齐材料后重试成功」场景）。

    仅用于演示闭环中的「人工修复根因 → 重试」链路，真实审批系统的附件由申请人上传。
    """
    approval = APPROVAL_INDEX.get(instance_id)
    if not approval:
        return None
    suffix = file_type or (file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin")
    seq = len(approval["attachments"]) + 1
    stamp = datetime.now().strftime("%H%M%S")
    record = {
        "attachment_id": f"ATT-{instance_id[-3:]}-{seq}-{stamp}",
        "file_name": file_name,
        "file_type": suffix,
        "file_size": 0,
        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    approval.setdefault("attachments", []).append(record)
    return record


def remove_attachment(instance_id: str, attachment_id: str) -> bool:
    """移除指定附件（演示用）。"""
    approval = APPROVAL_INDEX.get(instance_id)
    if not approval:
        return False
    before = len(approval.get("attachments", []))
    approval["attachments"] = [
        a for a in approval.get("attachments", []) if a["attachment_id"] != attachment_id
    ]
    return len(approval["attachments"]) < before


def reset_approvals() -> int:
    """把全部审批单还原为初始演示数据，返回还原的审批单数量。"""
    for instance_id, attachments in BASELINE.items():
        APPROVAL_INDEX[instance_id]["attachments"] = [dict(a) for a in attachments]
    return len(BASELINE)


def list_pending(limit: int = 10) -> list[dict]:
    """查询待处理审批单列表。"""
    items = [a for a in APPROVALS if a.get("status", "").startswith("待")]
    return items[: max(0, int(limit))]
