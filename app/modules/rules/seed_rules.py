"""内置风控规则种子数据。

规则基础字段（每条必填）：
    rule_code        规则编码
    rule_name        规则名称
    risk_level       风险等级（低/中/高）
    rule_status      启用状态（enabled/disabled）
    match_mode       匹配模式（keyword/regex/missing/logic）
    match_text       匹配关键词或逻辑表达式
    suggestion_text  整改建议

match_text 语义（随 match_mode 变化）：
    keyword : "关键词1|关键词2"，命中任一即命中
    regex   : 正则表达式
    missing : "field:字段名,字段名" 或 "clause:条款名"，缺失即命中
    logic   : "内置逻辑函数名:参数"，由 engine.py 中的逻辑处理器判定

覆盖场景（需求强制要求全部内置）：
    预付款比例异常、付款周期不合理、合同自动续约风险、违约责任缺失/不均、
    管辖地风险、签约主体信息缺失、合同金额缺失、保密条款缺失、
    数据处理合规风险、知识产权归属风险、验收标准缺失
"""

from __future__ import annotations

BUILTIN_RULES: list[dict] = [
    # ================= 合同基本信息类 =================
    {
        "rule_code": "R-BASE-001",
        "rule_name": "签约主体信息缺失",
        "risk_level": "高",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "field:签约主体,对方名称",
        "suggestion_text": "合同缺少签约主体/对方主体名称，无法确认交易对手身份。请业务部门补充完整签约双方全称，并附营业执照等主体资格材料后重新提交审批。",
        "remark": "覆盖场景：签约主体信息缺失",
        "sort_no": 10,
    },
    {
        "rule_code": "R-BASE-002",
        "rule_name": "合同金额缺失",
        "risk_level": "高",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "field:合同金额",
        "suggestion_text": "合同未载明合同总金额或价款，存在结算争议与内控失控风险。请补充明确的合同金额（含币种、含税/不含税口径）后重新提交。",
        "remark": "覆盖场景：合同金额缺失",
        "sort_no": 20,
    },
    {
        "rule_code": "R-BASE-003",
        "rule_name": "合同编号缺失",
        "risk_level": "低",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "field:合同编号",
        "suggestion_text": "合同未标注合同编号，不利于归档与后续履约跟踪。建议按公司合同管理制度补充唯一合同编号。",
        "remark": "覆盖场景：合同要素完整性",
        "sort_no": 30,
    },
    {
        "rule_code": "R-BASE-004",
        "rule_name": "合同期限缺失",
        "risk_level": "低",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "field:生效时间,到期时间",
        "suggestion_text": "合同未明确生效时间或到期时间，可能导致权利义务期间不清晰。建议补充合同生效日期与终止日期。",
        "remark": "覆盖场景：合同要素完整性",
        "sort_no": 40,
    },

    # ================= 付款类 =================
    {
        "rule_code": "R-PAY-001",
        "rule_name": "预付款比例异常",
        "risk_level": "高",
        "rule_status": "enabled",
        "match_mode": "logic",
        "match_text": "prepay_ratio_over:0.30",
        "suggestion_text": "预付款比例超过公司内控上限（30%），资金占用与履约风险高。建议下调预付款比例至30%以内，或要求对方提供同等金额的银行保函/履约担保后再付款。",
        "remark": "覆盖场景：预付款比例异常",
        "sort_no": 50,
    },
    {
        "rule_code": "R-PAY-002",
        "rule_name": "付款周期不合理",
        "risk_level": "中",
        "rule_status": "enabled",
        "match_mode": "logic",
        "match_text": "payment_period_over:30",
        "suggestion_text": "合同约定付款周期偏长（超过30日），存在应收账款账期过长、回款风险。建议缩短付款周期或在合同中增加逾期付款违约金条款。",
        "remark": "覆盖场景：付款周期不合理",
        "sort_no": 60,
    },
    {
        "rule_code": "R-PAY-003",
        "rule_name": "付款条款缺失",
        "risk_level": "高",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "clause:付款条款",
        "suggestion_text": "合同未约定付款条款，缺少付款方式、付款节点与付款条件，履约与结算依据不足。请补充完整付款条款后重新提交审批。",
        "remark": "覆盖场景：付款条款缺失（付款类兜底）",
        "sort_no": 70,
    },

    # ================= 条款风险类 =================
    {
        "rule_code": "R-TERM-001",
        "rule_name": "合同自动续约风险",
        "risk_level": "中",
        "rule_status": "enabled",
        "match_mode": "keyword",
        "match_text": "自动续约|自动延期|自动展期|期满自动顺延|无异议则自动|自动延长|自动续签",
        "suggestion_text": "合同存在自动续约/自动顺延表述，可能在未重新审批的情况下延续义务。建议改为「到期前30日双方书面确认续约」，并明确任何一方可提前书面通知不再续约。",
        "remark": "覆盖场景：合同自动续约风险",
        "sort_no": 80,
    },
    {
        "rule_code": "R-BREACH-001",
        "rule_name": "违约责任缺失或不对等",
        "risk_level": "高",
        "rule_status": "enabled",
        "match_mode": "logic",
        "match_text": "breach_unbalanced",
        "suggestion_text": "违约责任条款缺失或双方责任不对等，将导致我方追责困难。建议补充对等的违约责任条款，明确违约金标准、损失赔偿范围及解除权。",
        "remark": "覆盖场景：违约责任缺失/不均",
        "sort_no": 90,
    },
    {
        "rule_code": "R-LEGAL-001",
        "rule_name": "管辖地风险",
        "risk_level": "中",
        "rule_status": "enabled",
        "match_mode": "keyword",
        "match_text": "乙方所在地|对方所在地|供方所在地|卖方所在地|受托方所在地|供应商所在地|承包方所在地",
        "suggestion_text": "争议解决管辖地约定在对方所在地，将显著提高我方维权成本。建议修改为「我方所在地有管辖权的人民法院」或约定贸仲/上仲等中立仲裁机构。",
        "remark": "覆盖场景：管辖地风险",
        "sort_no": 100,
    },
    {
        "rule_code": "R-CONF-001",
        "rule_name": "保密条款缺失",
        "risk_level": "中",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "clause:保密条款",
        "suggestion_text": "合同未约定保密条款，商业秘密与客户信息存在泄露风险。建议补充保密义务、保密期限、保密信息范围及违约赔偿条款。",
        "remark": "覆盖场景：保密条款缺失",
        "sort_no": 110,
    },
    {
        "rule_code": "R-DATA-001",
        "rule_name": "数据处理合规风险",
        "risk_level": "高",
        "rule_status": "enabled",
        "match_mode": "logic",
        "match_text": "data_compliance_risk",
        "suggestion_text": "合同涉及个人信息/重要数据的处理，但缺少数据安全与合规保障安排，可能违反《个人信息保护法》《数据安全法》。建议补充数据处理的合法性基础、最小必要原则、加密与访问控制、数据泄露通知及禁止违规出境等条款，并完成数据合规评估。",
        "remark": "覆盖场景：数据处理合规风险",
        "sort_no": 120,
    },
    {
        "rule_code": "R-IP-001",
        "rule_name": "知识产权归属风险",
        "risk_level": "高",
        "rule_status": "enabled",
        "match_mode": "logic",
        "match_text": "ip_ownership",
        "suggestion_text": "知识产权归属约定存在风险（未约定归属，或约定成果全部归对方所有）。建议明确约定「我方提供资料及既有知识产权归我方所有，新产生成果归我方所有或双方共有」，并要求对方保证交付物不侵犯第三方知识产权。",
        "remark": "覆盖场景：知识产权归属风险",
        "sort_no": 130,
    },
    {
        "rule_code": "R-ACCEPT-001",
        "rule_name": "验收标准缺失",
        "risk_level": "中",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "clause:验收条款",
        "suggestion_text": "合同未约定验收标准与验收流程，将导致付款条件无法触发、交付质量难以界定。建议补充验收标准、验收期限、验收不通过的整改与拒收处理机制。",
        "remark": "覆盖场景：验收标准缺失",
        "sort_no": 140,
    },
    {
        "rule_code": "R-DELIV-001",
        "rule_name": "交付条款缺失",
        "risk_level": "中",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "clause:交付条款",
        "suggestion_text": "合同未约定交付条款，交付时间、地点、方式与风险转移节点不明确。建议补充完整交付条款。",
        "remark": "覆盖场景：交付条款缺失",
        "sort_no": 150,
    },
    {
        "rule_code": "R-DISPUTE-001",
        "rule_name": "争议解决条款缺失",
        "risk_level": "中",
        "rule_status": "enabled",
        "match_mode": "missing",
        "match_text": "clause:争议解决条款",
        "suggestion_text": "合同未约定争议解决方式，发生纠纷时管辖与救济路径不明。建议补充诉讼/仲裁二选一的争议解决条款并明确管辖机构。",
        "remark": "覆盖场景：争议解决条款缺失",
        "sort_no": 160,
    },
]
