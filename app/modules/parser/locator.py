"""原文位置定位工具。

「分段」是解析的最小定位单元，结构如下：
    {
        "page": 1,              # 页码（docx/txt 无分页信息时统一为 1）
        "block": 3,             # 段号（段落序号，从 1 开始）
        "line": 2,              # 段内行号（从 1 开始）
        "char_start": 128,      # 在全文中的起始字符偏移
        "char_end": 156,        # 在全文中的结束字符偏移
        "text": "……",           # 分段原文
        "source": "docx"        # 来源：docx/pdf/txt/ocr
    }

定位说明：
    - pdf 文档 page 为真实页码；
    - docx/txt 无可靠分页信息，page 统一记为 1，精确定位以「段号 + 行号 + 字符偏移」为准。
"""

from __future__ import annotations

from typing import Iterable, Optional


def position_of(seg: dict | None) -> str:
    """把分段结构格式化为人类可读的位置标识。"""
    if not seg:
        return "全文检索（未定位到具体位置）"
    page = seg.get("page", 1)
    block = seg.get("block", 0)
    line = seg.get("line", 0)
    start = seg.get("char_start", 0)
    end = seg.get("char_end", 0)
    source = seg.get("source", "")
    source_cn = {
        "docx": "Word文档", "pdf": "PDF文档", "txt": "文本文档",
        "md": "文本文档", "ocr": "扫描件OCR",
    }.get(source, source or "原文")
    return f"第{page}页 第{block}段 第{line}行（字符偏移 {start}-{end}，来源：{source_cn}）"


def locate(segments: Iterable[dict], needle: str) -> Optional[dict]:
    """在分段列表中查找包含指定文本的分段，返回第一个命中的分段。"""
    if not needle:
        return None
    for seg in segments:
        if needle in (seg.get("text") or ""):
            return seg
    return None


def locate_all(segments: Iterable[dict], needles: Iterable[str]) -> list[dict]:
    """查找包含任意关键词的全部分段（用于汇总多条证据）。"""
    seg_list = list(segments)
    hit: list[dict] = []
    for seg in seg_list:
        text = seg.get("text") or ""
        if any(n and n in text for n in needles):
            hit.append(seg)
    return hit


def snippet(text: str, max_chars: int = 300) -> str:
    """截取证据原文片段，过长时保留首尾并标注省略。"""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head - 3
    return f"{text[:head]}……{text[-tail:]}"


def best_segment(segments: Iterable[dict], needles: Iterable[str]) -> Optional[dict]:
    """返回包含关键词且文本最短的分段（通常是条款标题行，定位最为精准）。"""
    candidates = [s for s in locate_all(segments, needles) if (s.get("text") or "").strip()]
    if not candidates:
        return None
    return min(candidates, key=lambda s: len(s.get("text") or ""))


def join_text(segments: Iterable[dict], limit_chars: int = 300) -> str:
    """拼接连续分段的原文，用于构造条款全文证据。"""
    buf: list[str] = []
    total = 0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        buf.append(text)
        total += len(text)
        if total >= limit_chars:
            break
    return snippet("\n".join(buf), limit_chars)
