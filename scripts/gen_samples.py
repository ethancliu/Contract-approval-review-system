"""示例合同文件生成脚本。

生成 sample_contracts/ 目录下的全部演示文件：

    采购合同-标准版.docx           电子文档·标准合同（预期总风险：低）
    技术服务合同-风险版.docx       电子文档·风险合同（预期总风险：高）
    软件开发合同-扫描件.png        扫描件图片 + 同名 OCR 伴随文本（预期总风险：中）
    框架合作协议-要素缺失版.docx   电子文档·要素缺失（预期总风险：高）
    临时服务协议-空白.docx         空白文档（预期阻塞：文档内容为空）
    物流运输合同-损坏.docx         损坏文件（预期阻塞：文件解析异常）
    设备租赁合同-无OCR配置.png     扫描件（预期阻塞：扫描件图片无法识别）

用法：
    python scripts/gen_samples.py           仅补齐缺失文件
    python scripts/gen_samples.py --force   强制重新生成
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

# 允许以脚本方式直接运行（python scripts/gen_samples.py）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402


# ======================================================================
# 一、合同正文（按预期风险等级精心设计）
# ======================================================================
CONTRACT_STANDARD = [
    "服务器采购合同",
    "合同编号：CGHT-2026-1008-001",
    "甲方（采购方）：北京星辰科技有限公司",
    "乙方（供应商）：上海云海电子设备有限公司",
    "合同金额：人民币 860,000 元",
    "币种：人民币",
    "第一条 合同标的：甲方向乙方采购机架式服务器设备一批，具体型号、数量及配置以本合同附件《设备清单》为准。",
    "第二条 交付条款：乙方应于2026年11月30日前将全部设备交付至甲方指定地点（北京市海淀区），运输费用及运输风险由乙方承担，交付方式为送货上门，货物风险自甲方验收合格后转移至甲方。",
    "第三条 验收条款：甲方应于设备到货后15个工作日内按本合同附件《设备技术规格书》组织验收，验收标准以规格书约定的技术参数为准；验收不合格的，乙方应在5个工作日内免费更换。",
    "第四条 付款条款：本合同签订后15个工作日内，甲方支付合同金额的20%作为预付款；全部设备验收合格后15个工作日内，甲方支付合同金额的70%；质保期满12个月后支付剩余10%。付款方式为银行转账。",
    "第五条 违约条款：任何一方违反本合同约定，应向对方支付合同金额10%的违约金；因违约给对方造成损失的，还应赔偿实际损失。甲方逾期付款的，每逾期一日按未付金额的0.05%支付违约金；乙方逾期交付的，每逾期一日按合同金额的0.05%支付违约金。",
    "第六条 保密条款：双方对本合同内容及履行过程中知悉的对方商业秘密负有保密义务，未经对方书面同意不得向任何第三方披露，保密期限为合同终止后3年。",
    "第七条 数据条款：乙方在提供服务过程中接触到的甲方数据应严格保密，未经甲方书面授权不得向第三方披露或用于本合同以外的目的，并应采取加密存储与访问控制等安全措施。",
    "第八条 知识产权条款：甲方提供的资料及技术文件的知识产权归甲方所有；乙方交付设备所附随机软件的知识产权依原厂授权执行，乙方保证所交付产品不侵犯任何第三方知识产权。",
    "第九条 争议解决条款：因本合同发生的争议，双方应友好协商解决；协商不成的，任何一方均有权向甲方所在地有管辖权的人民法院提起诉讼。",
    "第十条 生效时间：本合同自2026年10月10日起生效，有效期至2027年10月9日。",
]

CONTRACT_RISKY = [
    "技术服务合同",
    "合同编号：JSFW-2026-1009-002",
    "甲方（委托方）：北京星辰科技有限公司",
    "乙方（受托方）：深圳市智联信息技术有限公司",
    "合同金额：人民币 1,200,000 元",
    "第一条 服务内容：乙方向甲方提供核心业务系统运维技术服务，具体服务范围以服务确认单为准。",
    "第二条 付款条款：本合同签订后5个工作日内，甲方向乙方支付合同总金额的50%作为预付款；服务期届满后，甲方应于收到发票后60个自然日内付清剩余款项。付款方式为银行转账。",
    "第三条 交付条款：乙方应于2026年11月15日前完成服务交付并提供服务报告。",
    "第四条 违约条款：乙方未按期完成服务的，应向甲方支付合同金额20%的违约金；乙方未按约定提供服务的，应赔偿由此给甲方造成的全部损失。",
    "第五条 数据条款：乙方在服务过程中将接触甲方客户信息与用户数据，并可能将部分数据传输至境外服务器进行处理。",
    "第六条 知识产权条款：基于本合同产生的全部技术成果、软件著作权及其他知识产权均归乙方所有。",
    "第七条 争议解决条款：因本合同发生的争议，双方协商不成的，任何一方均有权向乙方所在地有管辖权的人民法院提起诉讼。",
    "第八条 生效时间：本合同自2026年10月15日起生效，有效期至2027年10月14日。服务期满后，如双方均无异议则自动续约一年。",
]

CONTRACT_SCAN = [
    "软件开发合同",
    "合同编号：RJKF-2026-1009-003",
    "甲方（委托方）：北京星辰科技有限公司",
    "乙方（受托方）：杭州云码软件有限公司",
    "合同金额：人民币 480000 元",
    "第一条 开发内容：乙方为甲方开发客户关系管理系统，开发周期120个日历日。",
    "第二条 交付条款：乙方应于2026年12月31日前完成开发并交付源代码及部署文档，交付方式为线上交付。",
    "第三条 验收条款：甲方应在收到交付物后10个工作日内组织验收，验收标准以《需求规格说明书》为准。",
    "第四条 付款条款：合同签订后10个工作日内甲方支付合同金额的30%作为预付款；验收合格后45个工作日内支付剩余70%。",
    "第五条 保密条款：双方对履行本合同过程中知悉的对方商业秘密承担保密义务，保密期限为合同终止后2年。",
    "第六条 违约条款：甲方逾期付款的，每逾期一日按应付未付金额的0.05%支付违约金；乙方逾期交付的，每逾期一日按合同金额的0.05%支付违约金。",
    "第七条 知识产权条款：本项目的软件著作权归甲方所有，乙方不得将本合同项下开发成果用于其他项目，并保证交付成果不侵犯第三方知识产权。",
    "第八条 争议解决条款：因本合同发生的争议，双方协商不成的，任何一方均有权向甲方所在地有管辖权的人民法院提起诉讼。",
    "第九条 生效时间：本合同自2026年10月20日起生效，有效期至2027年10月19日。",
]

CONTRACT_MISSING = [
    "框架合作协议",
    "甲方（委托方）：北京星辰科技有限公司",
    "乙方（受托方）：上海恒信管理咨询有限公司",
    "第一条 合作内容：双方就企业管理咨询、专项培训及流程优化等事项开展合作，具体服务内容以双方另行签署的服务确认单为准。",
    "第二条 付款条款：具体项目费用以服务确认单约定为准，甲方应在收到乙方开具的发票后15个工作日内支付。",
    "第三条 交付条款：乙方应在服务确认单约定的期限内完成并交付服务成果。",
    "第四条 违约条款：任何一方违反本协议约定，应向对方承担违约责任并赔偿由此造成的实际损失。",
    "第五条 争议解决条款：因本协议发生的争议，双方协商不成的，任何一方均可向被告所在地人民法院提起诉讼。",
]

#: 扫描件图片上的文字（同时作为 OCR 伴随文本写入 .ocr.txt）
SCAN_TEXT = CONTRACT_SCAN


# ======================================================================
# 二、生成实现
# ======================================================================
def _write_docx(path: Path, lines: list[str], empty: bool = False) -> None:
    """生成 Word 文档。"""
    import docx  # noqa: PLC0415
    from docx.oxml.ns import qn  # noqa: PLC0415
    from docx.shared import Pt  # noqa: PLC0415

    document = docx.Document()
    style = document.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    if not empty:
        for i, line in enumerate(lines):
            para = document.add_paragraph()
            run = para.add_run(line)
            run.font.name = "宋体"
            run.font.size = Pt(14) if i == 0 else Pt(11)
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))


def _write_corrupt_docx(path: Path) -> None:
    """生成一个损坏的 docx（扩展名合法但内容非法，用于演示解析异常阻塞）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    random.seed(20261009)
    payload = bytes(random.getrandbits(8) for _ in range(2048))
    path.write_bytes(b"PK\x03\x04 corrupted-contract-payload \x00\x00" + payload)


def _load_cjk_font(size: int):
    """加载中文字体（Windows 自带字体，多备选）。"""
    from PIL import ImageFont  # noqa: PLC0415

    candidates = [
        ("C:/Windows/Fonts/msyh.ttc", 0),
        ("C:/Windows/Fonts/simhei.ttf", 0),
        ("C:/Windows/Fonts/simsun.ttc", 0),
        ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ]
    for font_path, index in candidates:
        try:
            return ImageFont.truetype(font_path, size, index=index)
        except Exception:  # noqa: BLE001 - 依次尝试备选字体
            continue
    return ImageFont.load_default()


def _write_scan_png(path: Path, lines: list[str], with_sidecar: bool = True) -> None:
    """生成扫描件图片（白底黑字，模拟纸质合同扫描件）。"""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    width = 1240
    line_height = 42
    margin = 60
    height = margin * 2 + line_height * len(lines) + 40

    image = Image.new("RGB", (width, height), (252, 252, 250))
    draw = ImageDraw.Draw(image)
    font = _load_cjk_font(20)
    title_font = _load_cjk_font(28)

    y = margin
    for i, line in enumerate(lines):
        font_obj = title_font if i == 0 else font
        draw.text((margin, y), line, fill=(20, 20, 20), font=font_obj)
        y += line_height + (10 if i == 0 else 0)

    # 加一层轻微噪点，模拟真实扫描件质感
    noise = Image.new("L", (width, height), 0)
    nz = noise.load()
    random.seed(20261009)
    for _ in range(width * height // 40):
        nz[random.randrange(width), random.randrange(height)] = random.randint(0, 40)
    image = Image.composite(Image.new("RGB", (width, height), (200, 200, 200)), image, noise)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path), "PNG")

    if with_sidecar:
        sidecar = Path(str(path) + ".ocr.txt")
        sidecar.write_text("\n".join(lines), encoding="utf-8")


# ======================================================================
# 三、对外入口
# ======================================================================
#: 需要生成的文件清单：(文件名, 生成函数, 说明)
SAMPLES: list[tuple[str, str, str]] = [
    ("采购合同-标准版.docx", "docx_standard", "电子文档·标准合同（预期总风险：低）"),
    ("技术服务合同-风险版.docx", "docx_risky", "电子文档·风险合同（预期总风险：高）"),
    ("软件开发合同-扫描件.png", "png_scan", "扫描件 + OCR 伴随文本（预期总风险：中）"),
    ("框架合作协议-要素缺失版.docx", "docx_missing", "电子文档·要素缺失（预期总风险：高）"),
    ("临时服务协议-空白.docx", "docx_empty", "空白文档（预期阻塞：文档内容为空）"),
    ("物流运输合同-损坏.docx", "docx_corrupt", "损坏文件（预期阻塞：文件解析异常）"),
    ("设备租赁合同-无OCR配置.png", "png_no_ocr", "扫描件无 OCR 配置（预期阻塞：扫描件图片无法识别）"),
]

_GENERATORS = {
    "docx_standard": lambda p: _write_docx(p, CONTRACT_STANDARD),
    "docx_risky": lambda p: _write_docx(p, CONTRACT_RISKY),
    "docx_missing": lambda p: _write_docx(p, CONTRACT_MISSING),
    "docx_empty": lambda p: _write_docx(p, [], empty=True),
    "docx_corrupt": _write_corrupt_docx,
    "png_scan": lambda p: _write_scan_png(p, SCAN_TEXT, with_sidecar=True),
    "png_no_ocr": lambda p: _write_scan_png(p, CONTRACT_SCAN[:4], with_sidecar=False),
}


def ensure_samples(force: bool = False) -> list[str]:
    """生成（或补齐）示例合同文件，返回本次新建的文件名列表。"""
    settings.SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for file_name, kind, _desc in SAMPLES:
        path = settings.SAMPLE_DIR / file_name
        sidecar = Path(str(path) + ".ocr.txt")
        exists = path.exists() and (kind != "png_scan" or sidecar.exists())
        if exists and not force:
            continue
        try:
            _GENERATORS[kind](path)
            created.append(file_name)
        except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响其他文件
            print(f"[gen_samples] 生成 {file_name} 失败：{exc}", file=sys.stderr)

    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="生成示例合同文件")
    parser.add_argument("--force", action="store_true", help="强制重新生成（覆盖已有文件）")
    args = parser.parse_args()

    created = ensure_samples(force=args.force)
    if created:
        print(f"已生成 {len(created)} 个文件：")
        for name in created:
            print(f"  - {settings.SAMPLE_DIR / name}")
    else:
        print("示例文件已全部存在，无需生成（如需重建请加 --force）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
