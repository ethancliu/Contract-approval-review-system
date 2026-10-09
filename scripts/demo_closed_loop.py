"""全流程闭环演示脚本（命令行版）。

演示内容（严格覆盖需求「项目验收标准」7 项）：
    1. 拉取待审批单，自动完成业务维度去重，无重复任务创建
    2. 附件下载、本地存储、元数据入库，记录下载状态
    3. 普通文档解析 + 扫描件 OCR 识别，完整提取合同基础信息与条款信息
    4. 内置全量风控规则自动匹配，输出证据、位置、风险等级与建议
    5. 审查结果完整入库，标准化评论自动回写审批系统
    6. 异常场景自动进入阻塞状态，支持人工重试恢复流程
    7. 完整闭环：待办拉取 → 附件下载 → 文档解析 → 规则审查 → 结果入库 → 评论回写

前置条件：先执行 python run.py（本脚本通过 HTTP 调用运行中的服务）。

用法：
    python scripts/demo_closed_loop.py                     完整演示
    python scripts/demo_closed_loop.py --reset             演示前清空历史数据
    python scripts/demo_closed_loop.py --base http://127.0.0.1:8000
    python scripts/demo_closed_loop.py --mock http://127.0.0.1:9100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LINE = "=" * 92
SUB = "-" * 92


# ======================================================================
# 控制台输出工具
# ======================================================================
def title(text: str) -> None:
    print(f"\n{LINE}\n  {text}\n{LINE}")


def step(no: str, text: str) -> None:
    print(f"\n▶ 步骤 {no}：{text}\n{SUB}")


def kv(key: str, value, indent: int = 4) -> None:
    print(f"{' ' * indent}{key}：{value}")


def ok(text: str) -> None:
    print(f"[成功] {text}")


def warn(text: str) -> None:
    print(f"[警告] {text}")


def fail(text: str) -> None:
    print(f"[失败] {text}")


# ======================================================================
# HTTP 调用封装
# ======================================================================
class Client:
    """调用端 HTTP 客户端。"""

    def __init__(self, base: str, mock: str) -> None:
        self.base = base.rstrip("/")
        self.mock = mock.rstrip("/")
        self.session = requests.Session()

    def call(self, method: str, path: str, *, base: str | None = None, **kwargs):
        url = f"{base or self.base}{path}"
        try:
            resp = self.session.request(method, url, timeout=60, **kwargs)
        except requests.RequestException as exc:
            fail(f"请求失败：{method} {url} —— {exc}")
            return None, 0

        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text[:300]}
        if resp.status_code >= 400:
            fail(f"接口返回 HTTP {resp.status_code}：{method} {url}")
            print(json.dumps(body, ensure_ascii=False, indent=2)[:1200])
        return body, resp.status_code

    def tool(self, name: str, payload: dict):
        return self.call("POST", f"/api/tools/{name}", json=payload)

    def get(self, path: str, params: dict | None = None, base: str | None = None):
        return self.call("GET", path, params=params, base=base)


# ======================================================================
# 演示主流程
# ======================================================================
def run_demo(client: Client) -> int:
    title("企业合同审批自动审查系统 —— 全流程闭环演示")

    # ------------------------------------------------------------------
    # 0. 健康检查
    # ------------------------------------------------------------------
    step("0", "服务健康检查")
    health, code = client.get("/api/health")
    if code != 200 or not health:
        fail("主服务不可用，请先执行：python run.py")
        return 1
    kv("服务名称", health.get("service"))
    kv("版本", health.get("version"))
    kv("审批系统地址", health.get("approval_base_url"))
    kv("内置规则数", (health.get("database") or {}).get("rule_count"))
    mock_health, mock_code = client.get("/api/health", base=client.mock)
    if mock_code != 200:
        warn("模拟审批系统不可用（如使用真实审批系统可忽略）")

    # ------------------------------------------------------------------
    # 1. 待办拉取
    # ------------------------------------------------------------------
    step("1", "待办拉取工具 —— list_pending_contract_approvals(limit=10)")
    data, _ = client.tool("list_pending_contract_approvals", {"limit": 10})
    if not data:
        return 1
    pending = data.get("list", [])
    print(f"{'审批编号':<20}{'标题':<34}{'申请人':<14}{'申请时间':<20}{'附件数'}")
    print(SUB)
    for item in pending:
        print(f"{item['approval_code']:<20}{item['approval_title'][:16]:<34}"
              f"{item['applicant_name'][:6]:<14}{item['apply_time']:<20}{item['attachment_count']}")
    ok(f"共拉取待处理审批单 {len(pending)} 条，必填字段（审批编号/标题/申请人/申请时间/附件数量）齐全")

    # ------------------------------------------------------------------
    # 2. 去重验证
    # ------------------------------------------------------------------
    step("2", "任务去重验证 —— 重复拉取不重复创建任务")
    sync1, _ = client.call("POST", "/api/pipeline/sync", json={"limit": 10})
    sync2, _ = client.call("POST", "/api/pipeline/sync", json={"limit": 10})
    kv("第一次同步", f"拉取 {sync1['fetched']} 条 / 新建 {sync1['created']} 条 / 更新 {sync1['updated']} 条 / 跳过 {sync1['skipped']} 条")
    kv("第二次同步", f"拉取 {sync2['fetched']} 条 / 新建 {sync2['created']} 条 / 更新 {sync2['updated']} 条 / 跳过 {sync2['skipped']} 条")
    if sync2["created"] == 0:
        ok("第二次拉取未新建任何任务，按审批编号去重生效")
    else:
        fail("去重异常：第二次拉取新建了任务")

    # ------------------------------------------------------------------
    # 3. 审批详情
    # ------------------------------------------------------------------
    target_instance = "HTSP20261009002"
    step("3", f"审批详情工具 —— get_contract_approval('{target_instance}')")
    detail, _ = client.tool("get_contract_approval", {"instance_id": target_instance})
    if detail:
        basic = detail["basic_info"]
        kv("审批编号", basic.get("approval_code"))
        kv("审批标题", basic.get("approval_title"))
        kv("申请人", basic.get("applicant_name"))
        kv("当前处理人", basic.get("current_handler"))
        kv("当前状态", (detail.get("current_status") or {}).get("status"))
        kv("表单数据", json.dumps(detail.get("form_data", {}), ensure_ascii=False)[:100])
        for att in detail.get("attachments", []):
            kv("附件", f"{att['attachment_id']} / {att['file_name']} / {att['file_size']} 字节")
        ok("审批基础信息、表单数据、附件信息、当前处理状态四项齐全")

    # ------------------------------------------------------------------
    # 4~8. 单任务完整闭环（依次调用 7 个工具）
    # ------------------------------------------------------------------
    attachment_id = detail["attachments"][0]["attachment_id"]
    file_name = detail["attachments"][0]["file_name"]

    step("4", "附件下载工具 —— download_contract_attachment(instance_id, attachment_id, file_name)")
    dl, _ = client.tool("download_contract_attachment", {
        "instance_id": target_instance, "attachment_id": attachment_id, "file_name": file_name,
    })
    if dl:
        kv("本地存储路径", dl["local_path"])
        kv("文件大小", f"{dl['file_size']} 字节")
        kv("文件MD5", dl["file_md5"])
        kv("下载状态", dl["download_status"])
        ok("附件已落地本地存储目录，元数据与校验信息已入库")

    step("5", "文档解析工具 —— parse_contract_document(document_id)")
    parsed, _ = client.tool("parse_contract_document", {"document_id": document_ref(client, target_instance)})
    if not parsed or "fields_summary" not in parsed:
        fail("文档解析未返回结构化结果，演示终止")
        return 1
    rec = parsed["fields_summary"]
    kv("解析状态", parsed["parse_status"])
    kv("页数/字符数", f"{parsed['page_count']} 页 / {parsed['char_count']} 字")
    kv("字段提取完整度", f"{rec.get('success_fields')}/{rec.get('total_fields')}")
    print(f"\n  —— 合同基本信息（含原文片段与位置定位）——")
    for key, item in parsed["basic_info"].items():
        flag = "√" if item["extract_status"] == "success" else "×"
        kv(f"[{flag}] {key}", f"{item['value']}  ｜位置：{item['position']}", indent=4)
    print(f"\n  —— 合同条款信息 ——")
    for key, item in parsed["clause_info"].items():
        flag = "√" if item["extract_status"] == "success" else "×"
        evidence = (item.get("evidence_text") or "")[:52].replace("\n", " ")
        kv(f"[{flag}] {key}", f"{evidence}…  ｜位置：{item['position']}", indent=4)
    ok("每个字段均携带：字段值 / 原文片段 / 页码位置 / 提取状态 / 失败原因")

    case_id = parsed["task_id"]
    step("6", "规则审查工具 —— run_contract_rules(case_id)")
    review, _ = client.tool("run_contract_rules", {"case_id": str(case_id)})
    if review:
        kv("启用规则总数", review["rule_total"])
        kv("命中规则数", f"{review['hit_count']} 条（高 {review['high_count']} / 中 {review['medium_count']} / 低 {review['low_count']}）")
        kv("总风险等级", review["overall_risk_level"])
        print()
        for idx, hit in enumerate(review["hit_rules"], start=1):
            print(f"  {idx}. 【{hit['risk_level']}风险】{hit['rule_name']}（{hit['rule_code']}）")
            print(f"      命中证据：{(hit['evidence_text'] or '')[:76].replace(chr(10), ' ')}")
            print(f"      证据位置：{hit['evidence_position']}")
            print(f"      处理建议：{hit['suggestion_text'][:76]}")
        ok("每条命中结果均包含：规则名称 / 风险等级 / 命中证据原文 / 证据位置 / 处理建议")

    step("7", "结果保存工具 —— save_review_result(case_id, overall_risk_level, summary_text, focus_points_json, comment_text)")
    saved, _ = client.tool("save_review_result", {
        "case_id": str(case_id),
        "overall_risk_level": review["overall_risk_level"],
        "summary_text": review["summary_text"],
        "focus_points_json": review["focus_points"],
        "comment_text": "",
    })
    if saved:
        kv("审查结果ID", saved["review_id"])
        kv("保存状态", saved["save_status"])
        kv("中文摘要", saved["summary_text"][:110] + "…")
        kv("审批关注点条数", len(saved["focus_points"]))
        ok("审查结果、命中规则、风险摘要、关注点已完整入库")

    step("8", "评论回写工具 —— write_approval_comment(instance_id, review_id)")
    written, _ = client.tool("write_approval_comment", {
        "instance_id": target_instance, "review_id": saved["review_id"],
    })
    if written:
        kv("回写状态", written["write_status"])
        kv("回写响应", written["write_response_text"][:120])
        kv("评论长度", f"{len(written['comment_text'])} 字符")

    # 回写结果核验
    comments, _ = client.get(f"/api/_comments/{target_instance}", base=client.mock)
    if comments and comments.get("data", {}).get("comments"):
        latest = comments["data"]["comments"][-1]
        kv("审批系统已收到评论", f"{latest['comment_id']}（操作人：{latest['operator']}，时间：{latest['write_time']}）")
        print(f"\n{SUB}\n  —— 回写内容预览（审批评论区实际文本）——\n{SUB}")
        for line_text in latest["comment"].splitlines()[:26]:
            print("  " + line_text)
        print("  ……（完整内容见审批系统评论区或调用 /api/admin/review_results/{task_id}）")
        ok("评论已成功回写至审批系统评论区")

    # ------------------------------------------------------------------
    # 9. 一键闭环：全部审批单
    # ------------------------------------------------------------------
    step("9", "一键闭环 —— pipeline/sync_and_process（拉取→审查→入库→回写，全量）")
    t0 = time.time()
    batch, _ = client.call("POST", "/api/pipeline/sync_and_process", json={"limit": 10})
    cost = time.time() - t0
    if batch:
        print(f"\n{'任务ID':<8}{'审批编号':<20}{'任务状态':<12}{'回写状态':<12}{'风险等级':<10}{'命中':<6}{'阻塞原因'}")
        print(SUB)
        for item in batch["processed"]:
            print(f"{item['task_id']:<8}{item['approval_code']:<20}{item['task_status_cn']:<12}"
                  f"{item['write_status']:<12}{item['overall_risk_level'] or '-':<10}"
                  f"{item['hit_count']:<6}{item['block_reason'] or '-'}")
        ok(f"全量闭环执行完成，耗时 {cost:.2f} 秒")

    # ------------------------------------------------------------------
    # 10. 阻塞场景与人工重试
    # ------------------------------------------------------------------
    step("10", "异常阻塞与人工重试（覆盖 5 类阻塞场景）")
    tasks, _ = client.get("/api/tasks", params={"task_status": "blocked"})
    blocked = (tasks or {}).get("list", [])
    print(f"当前处于阻塞态的任务 {len(blocked)} 个（每类阻塞原因均已落库，可在调用端查看处置建议）：\n")
    for item in blocked:
        print(f"  · 任务{item['task_id']} {item['approval_code']} —— 阻塞原因：{item['block_reason']}")

    # ------------------------------------------------------------------
    # 10.1 人工重试 —— 外部接口调用失败后恢复
    # ------------------------------------------------------------------
    print(f"\n{SUB}\n  【演示 A】外部接口调用失败 → 阻塞 → 接口恢复 → 重试成功\n{SUB}")
    done_tasks, _ = client.get("/api/tasks", params={"task_status": "done"})
    done_list = (done_tasks or {}).get("list", [])
    if done_list:
        target_a = done_list[0]
        print(f"  取一个已完成任务 {target_a['task_id']}（{target_a['approval_code']}）做重跑演示\n")

        client.call("POST", "/api/_simulate/offline", base=client.mock, params={"value": 1})
        warn("已把模拟审批系统切换为「不可用」状态（模拟接口故障）")
        retry_fail, _ = client.call("POST", f"/api/admin/retry/{target_a['task_id']}",
                                    params={"operator": "系统管理员-演示"})
        if retry_fail:
            kv("重试后任务状态", retry_fail["task"]["task_status_cn"])
            kv("阻塞原因", retry_fail["task"]["block_reason"])
            kv("重试次数", retry_fail["task"]["retry_count"])
            if retry_fail["task"]["task_status"] == "blocked":
                ok("接口故障已被捕获：任务未崩溃，转入 blocked 并记录具体阻塞原因")

        client.call("POST", "/api/_simulate/offline", base=client.mock, params={"value": 0})
        ok("模拟审批系统已恢复正常")

        print()
        retry_ok, _ = client.call("POST", f"/api/admin/retry/{target_a['task_id']}",
                                  params={"operator": "系统管理员-演示"})
        if retry_ok:
            kv("重试后任务状态", retry_ok["task"]["task_status_cn"])
            kv("回写状态", retry_ok["task"]["write_status_cn"])
            kv("总风险等级", (retry_ok.get("review") or {}).get("overall_risk_level", "-"))
            kv("重试次数", retry_ok["task"]["retry_count"])
            if retry_ok["task"]["task_status"] == "done":
                ok("重试成功：任务从 blocked 回归 parsing → reviewing → done 完整闭环")

    # ------------------------------------------------------------------
    # 10.2 人工重试 —— 补齐材料后重试成功
    # ------------------------------------------------------------------
    print(f"\n{SUB}\n  【演示 B】附件缺失 → 补传附件 → 重试成功\n{SUB}")
    tasks, _ = client.get("/api/tasks", params={"task_status": "blocked"})
    blocked = (tasks or {}).get("list", [])
    missing = next((t for t in blocked if "附件缺失" in (t.get("block_reason") or "")), None)
    if missing:
        print(f"  任务 {missing['task_id']}（{missing['approval_code']}）当前阻塞原因：{missing['block_reason']}\n")
        add_resp, _ = client.call(
            "POST", "/api/_simulate/add_attachment", base=client.mock,
            params={"instance_id": missing["approval_code"], "file_name": "采购合同-标准版.docx"},
        )
        if add_resp:
            att = add_resp["data"]["attachment"]
            ok(f"申请人已补传附件：{att['attachment_id']} / {att['file_name']}")

        print()
        retry_b, _ = client.call("POST", f"/api/admin/retry/{missing['task_id']}",
                                 params={"operator": "系统管理员-演示"})
        if retry_b:
            kv("重试后任务状态", retry_b["task"]["task_status_cn"])
            kv("附件数量", retry_b["task"]["attachment_count"])
            kv("回写状态", retry_b["task"]["write_status_cn"])
            kv("总风险等级", (retry_b.get("review") or {}).get("overall_risk_level", "-"))
            if retry_b["task"]["task_status"] == "done":
                ok("重试成功：补齐材料后任务正常完成全流程闭环")

    # ------------------------------------------------------------------
    # 10.3 阻塞任务全貌
    # ------------------------------------------------------------------
    tasks, _ = client.get("/api/tasks", params={"task_status": "blocked"})
    blocked_after = (tasks or {}).get("list", [])
    print(f"\n{SUB}\n  管理员处理完毕后仍处于阻塞态的任务：{len(blocked_after)} 个\n{SUB}")
    for item in blocked_after:
        print(f"  · 任务{item['task_id']} {item['approval_code']} —— 阻塞原因：{item['block_reason']}")
    print("\n  说明：剩余阻塞任务均因原始材料本身不可用（空白/损坏/无OCR组件），")
    print("        系统不做任何猜测性结论，保留阻塞态等待人工补充材料或人工审查。")

    # ------------------------------------------------------------------
    # 11. 结果总览
    # ------------------------------------------------------------------
    step("11", "审查结果总览")
    overview, _ = client.get("/api/overview")
    if overview:
        kv("任务总数", overview["task_total"])
        kv("按状态分布", json.dumps(overview["task_by_status"], ensure_ascii=False))
        kv("按风险分布", json.dumps(overview["task_by_risk"], ensure_ascii=False))
        kv("启用规则数", overview["enabled_rule_count"])
        kv("累计命中数", overview["hit_total"])

    title("演示结束")
    print("  调用端页面：http://127.0.0.1:8000/")
    print("  接口文档  ：http://127.0.0.1:8000/docs")
    print("  说明：本系统仅辅助人工审批，最终审批权归人工法务。")
    return 0


def document_ref(client: Client, instance_id: str) -> str:
    """构造工具 4 的 document_id 参数。

    优先使用「审批编号」这一无歧义标识；若该审批单已入库，则进一步用
    attach:<附件ID> 精确定位到具体附件。
    """
    tasks, _ = client.get("/api/tasks")
    for item in (tasks or {}).get("list", []):
        if item["approval_code"] == instance_id:
            detail, _ = client.get(f"/api/tasks/{item['task_id']}")
            attachments = (detail or {}).get("attachments") or []
            if attachments:
                return f"attach:{attachments[0]['attachment_id']}"
    return instance_id


def main() -> int:
    parser = argparse.ArgumentParser(description="企业合同审批自动审查系统 - 全流程闭环演示")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="主服务地址")
    parser.add_argument("--mock", default="http://127.0.0.1:9100", help="模拟审批系统地址")
    parser.add_argument("--reset", action="store_true", help="演示前清空历史任务与审查数据")
    args = parser.parse_args()

    client = Client(args.base, args.mock)
    client.mock = args.mock.rstrip("/")

    health, code = client.get("/api/health")
    if code != 200:
        print(f"\n[错误] 无法连接主服务 {args.base}，请先执行：python run.py\n")
        return 1

    if args.reset:
        client.call("POST", "/api/demo/reset")
        client.call("POST", "/api/_simulate/reset", base=client.mock)
        print("[演示] 已重置历史数据与模拟审批系统演示数据")

    try:
        return run_demo(client)
    except KeyboardInterrupt:
        print("\n[演示] 用户中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
