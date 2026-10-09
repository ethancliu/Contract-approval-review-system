"""扫描件图片 OCR 识别引擎。

支持三种可插拔实现，按 OCR_ENGINE 配置选择：

    1) tesseract  —— 依赖 pytesseract + Tesseract-OCR 可执行文件（生产推荐）
                     安装：https://github.com/UB-Mannheim/tesseract/wiki ，安装时勾选中文语言包 chi_sim
    2) paddle     —— 依赖 paddleocr（识别精度更高，依赖较重）
    3) sidecar    —— 读取同名伴随文本 <图片全路径>.ocr.txt（无 OCR 组件时的降级方案，便于演示）
                     若图片同目录下没有伴随文本，则回落到 OCR_SIDECAR_FALLBACK_DIR 目录按文件名查找；
                     该回落目录默认指向 sample_contracts（演示夹具），生产环境请置空以关闭。

OCR_ENGINE=auto（默认）时的探测顺序：tesseract → paddle → sidecar。
三者全部不可用时抛出 OcrError，任务进入 blocked 状态并记录阻塞原因「扫描件图片无法识别」，
由管理员安装识别组件后手动重试。
"""

from __future__ import annotations

from pathlib import Path

from ...config import settings
from ...exceptions import OcrError

#: 伴随文本文件后缀（sidecar 模式）
SIDECAR_SUFFIX = ".ocr.txt"


class OcrEngine:
    """OCR 识别引擎（多后端自动降级）。"""

    def __init__(self, engine: str | None = None, lang: str | None = None) -> None:
        self.engine = (engine or settings.OCR_ENGINE or "auto").lower()
        self.lang = lang or settings.OCR_LANG
        self.min_chars = settings.OCR_MIN_CHARS

    # ------------------------------------------------------------------
    # 后端探测
    # ------------------------------------------------------------------
    @staticmethod
    def _tesseract_ready() -> tuple[bool, str]:
        """探测 Tesseract 是否可用。"""
        try:
            import pytesseract  # noqa: PLC0415
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            return False, "未安装 pytesseract 依赖（pip install pytesseract）"
        try:
            version = pytesseract.get_tesseract_version()
            return True, f"Tesseract {version}"
        except Exception as exc:  # noqa: BLE001 - 未安装 tesseract.exe 等
            return False, f"Tesseract 可执行文件不可用：{exc}"

    @staticmethod
    def _paddle_ready() -> tuple[bool, str]:
        """探测 PaddleOCR 是否可用。"""
        try:
            import paddleocr  # noqa: F401,PLC0415
            return True, "PaddleOCR 已安装"
        except ImportError:
            return False, "未安装 paddleocr 依赖（pip install paddleocr）"
        except Exception as exc:  # noqa: BLE001
            return False, f"PaddleOCR 初始化失败：{exc}"

    @staticmethod
    def find_sidecar(image_path: Path) -> Path | None:
        """查找扫描件的同名伴随文本。

        查找顺序：
            1) 与图片同目录的 <图片全路径>.ocr.txt（生产/常规场景）
            2) 配置项 OCR_SIDECAR_FALLBACK_DIR 下的 <图片名>.ocr.txt
               （演示夹具目录，未安装 OCR 组件的环境使用；置空即彻底关闭）
        """
        candidates = [Path(str(image_path) + SIDECAR_SUFFIX)]
        fallback_dir = getattr(settings, "OCR_SIDECAR_FALLBACK_DIR", None)
        if fallback_dir:
            candidates.append(Path(fallback_dir) / f"{image_path.name}{SIDECAR_SUFFIX}")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    @classmethod
    def _sidecar_ready(cls, image_path: Path) -> tuple[bool, str]:
        """探测是否存在同名伴随文本。"""
        sidecar = cls.find_sidecar(image_path)
        if sidecar:
            return True, f"伴随文本 {sidecar.name}"
        return False, "未找到同名伴随文本"

    def describe(self) -> dict:
        """返回各后端的可用性快照（供 /api/tools/ocr_status 展示）。"""
        tes_ok, tes_msg = self._tesseract_ready()
        pad_ok, pad_msg = self._paddle_ready()
        return {
            "engine_config": self.engine,
            "lang": self.lang,
            "tesseract": {"available": tes_ok, "message": tes_msg},
            "paddleocr": {"available": pad_ok, "message": pad_msg},
            "sidecar": {"available": True, "message": "同目录 <图片名>.ocr.txt 伴随文本"},
            "effective_engine": self._pick_engine(None)[0],
        }

    def _pick_engine(self, image_path: Path | None) -> tuple[str, str]:
        """按配置决定实际使用的后端，返回 (引擎名, 说明)。"""
        if self.engine == "tesseract":
            ok, msg = self._tesseract_ready()
            return ("tesseract", msg) if ok else ("__fail__", msg)
        if self.engine == "paddle":
            ok, msg = self._paddle_ready()
            return ("paddle", msg) if ok else ("__fail__", msg)
        if self.engine == "sidecar":
            ok, msg = self._sidecar_ready(image_path) if image_path else (True, "sidecar 模式")
            return ("sidecar", msg) if ok else ("__fail__", msg)

        # auto：依次探测
        ok, msg = self._tesseract_ready()
        if ok:
            return "tesseract", msg
        last_msg = msg
        ok, msg = self._paddle_ready()
        if ok:
            return "paddle", msg
        last_msg = f"{last_msg}；{msg}"
        if image_path is not None:
            ok, msg = self._sidecar_ready(image_path)
            if ok:
                return "sidecar", msg
            last_msg = f"{last_msg}；{msg}"
        return "__fail__", last_msg

    # ------------------------------------------------------------------
    # 识别入口
    # ------------------------------------------------------------------
    def recognize(self, image_path: str | Path, page: int = 1) -> dict:
        """识别单张图片，返回 {provider, text, lines, page}。

        识别失败（引擎不可用 / 结果为空）时抛出 OcrError，由上层置任务为 blocked。
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise OcrError(f"扫描件文件不存在：{image_path}", detail=str(image_path))

        provider, note = self._pick_engine(image_path)
        if provider == "__fail__":
            raise OcrError(
                "扫描件图片无法识别：未检测到可用的 OCR 识别组件",
                detail=f"文件：{image_path.name}；探测结果：{note}。"
                       f"请安装 Tesseract-OCR 与 pytesseract（或 python -m pip install paddleocr），"
                       f"或将 OCR_ENGINE 配置为 sidecar 并提供 {image_path.name}{SIDECAR_SUFFIX} 伴随文本。",
            )

        if provider == "tesseract":
            lines = self._run_tesseract(image_path)
        elif provider == "paddle":
            lines = self._run_paddle(image_path)
        else:
            lines = self._run_sidecar(image_path)

        lines = [ln.strip() for ln in lines if ln and ln.strip()]
        text = "\n".join(lines)
        if len(text.strip()) < self.min_chars:
            raise OcrError(
                "扫描件图片无法识别：识别结果为空或过短",
                detail=f"文件：{image_path.name}；引擎：{provider}；有效字符数：{len(text.strip())}"
                       f"（阈值 {self.min_chars}）。建议改用更清晰的扫描件或人工录入后重试。",
            )

        return {"provider": provider, "note": note, "text": text, "lines": lines, "page": page}

    # ------------------------------------------------------------------
    # 各后端实现
    # ------------------------------------------------------------------
    @staticmethod
    def _run_tesseract(image_path: Path) -> list[str]:
        import pytesseract  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        with Image.open(image_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            raw = pytesseract.image_to_string(img, lang=settings.OCR_LANG)
        return raw.splitlines()

    @staticmethod
    def _run_paddle(image_path: Path) -> list[str]:
        from paddleocr import PaddleOCR  # noqa: PLC0415

        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = ocr.ocr(str(image_path), cls=True)
        lines: list[str] = []
        for page in result or []:
            for item in page or []:
                try:
                    lines.append(item[1][0])
                except (IndexError, TypeError):
                    continue
        return lines

    @classmethod
    def _run_sidecar(cls, image_path: Path) -> list[str]:
        sidecar = cls.find_sidecar(image_path)
        if not sidecar:
            return []
        for encoding in ("utf-8", "utf-8-sig", "gbk"):
            try:
                return sidecar.read_text(encoding=encoding).splitlines()
            except UnicodeDecodeError:
                continue
        return []


#: 模块级单例（无状态，可安全复用）
ocr_engine = OcrEngine()
