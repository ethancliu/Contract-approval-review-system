"""全局配置。

所有配置项均支持环境变量覆盖，便于在不同部署环境（开发/测试/生产）中切换。
用法示例：
    set APPROVAL_BASE_URL=http://10.0.0.9:9200
    set PAYMENT_PERIOD_DAYS_LIMIT=45
"""

from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default):
    """读取环境变量，未设置时返回默认值。"""
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    return str(_env(name, "1" if default else "0")).strip().lower() in ("1", "true", "yes", "on")


#: 项目根目录（app/config.py 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    """系统运行配置。"""

    def __init__(self) -> None:
        # ---------------- 基础信息 ----------------
        self.PROJECT_NAME = "企业合同审批自动审查系统"
        self.VERSION = "1.0.0"
        self.DESCRIPTION = (
            "面向企业合同审批场景的自动化风险审查工具服务："
            "自动拉取审批待办 → 下载合同附件 → 解析文档/扫描件OCR → 结构化提取 → "
            "风控规则审查 → 结果入库 → 评论回写。仅辅助人工审批，不替代人工决策。"
        )

        # ---------------- 本服务监听地址 ----------------
        self.APP_HOST = _env("APP_HOST", "127.0.0.1")
        self.APP_PORT = _env_int("APP_PORT", 8000)

        # ---------------- 模拟审批系统（演示用对接方）监听地址 ----------------
        self.MOCK_HOST = _env("MOCK_HOST", "127.0.0.1")
        self.MOCK_PORT = _env_int("MOCK_PORT", 9100)

        # ---------------- 外部审批系统接入配置 ----------------
        # 生产环境把该地址改为真实审批系统网关地址即可，其余代码无需改动。
        self.APPROVAL_BASE_URL = _env(
            "APPROVAL_BASE_URL", f"http://{self.MOCK_HOST}:{self.MOCK_PORT}"
        ).rstrip("/")
        self.APPROVAL_API_TIMEOUT = _env_float("APPROVAL_API_TIMEOUT", 15.0)
        self.APPROVAL_TOKEN = _env("APPROVAL_TOKEN", "demo-token-hetongshencha")
        self.APPROVAL_OPERATOR = _env("APPROVAL_OPERATOR", "合同智能审查机器人")

        # ---------------- 存储路径 ----------------
        self.DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "data" / "contract_review.db")))
        self.STORAGE_DIR = Path(_env("STORAGE_DIR", str(BASE_DIR / "storage")))
        self.SAMPLE_DIR = BASE_DIR / "sample_contracts"
        self.SQL_DIR = BASE_DIR / "sql"
        self.STATIC_DIR = BASE_DIR / "static"

        # ---------------- OCR 配置 ----------------
        # OCR_ENGINE: auto | tesseract | paddle | sidecar
        #   auto      —— 依次尝试 tesseract → paddleocr → sidecar，全部不可用则判定为「扫描件无法识别」并阻塞
        #   sidecar   —— 仅使用同名伴随文本（<图片全路径>.ocr.txt），适合未安装 OCR 组件的演示环境
        self.OCR_ENGINE = _env("OCR_ENGINE", "auto").strip().lower()
        self.OCR_LANG = _env("OCR_LANG", "chi_sim+eng")
        self.OCR_MIN_CHARS = _env_int("OCR_MIN_CHARS", 10)  # 识别结果少于该字数视为识别失败
        # 演示夹具目录：当下载到本地的扫描件旁缺少 <图片名>.ocr.txt 伴随文本时，
        # 允许到该目录按文件名回落查找（仅用于未安装 OCR 组件的演示环境）。
        # 生产环境请置为空字符串以彻底关闭该回落逻辑，强制使用真实 OCR 引擎。
        self.OCR_SIDECAR_FALLBACK_DIR = Path(
            _env("OCR_SIDECAR_FALLBACK_DIR", str(self.SAMPLE_DIR))
        )

        # ---------------- 风控阈值（供 logic 模式规则使用） ----------------
        self.PREPAY_RATIO_THRESHOLD = _env_float("PREPAY_RATIO_THRESHOLD", 0.30)  # 预付款比例上限 30%
        self.PAYMENT_PERIOD_DAYS_LIMIT = _env_int("PAYMENT_PERIOD_DAYS_LIMIT", 30)  # 付款周期上限 30 天

        # ---------------- 其他 ----------------
        self.MAX_EVIDENCE_CHARS = _env_int("MAX_EVIDENCE_CHARS", 300)  # 单条证据原文最大长度
        self.MAX_FOCUS_POINTS = _env_int("MAX_FOCUS_POINTS", 20)       # 关注点最大条数
        self.DEDUP_BY_APPROVAL_CODE = _env_bool("DEDUP_BY_APPROVAL_CODE", True)  # 按审批编号去重
        self.ENABLE_MOCK_SERVER = _env_bool("ENABLE_MOCK_SERVER", True)  # run.py 是否同进程拉起模拟审批系统

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------
    def ensure_dirs(self) -> None:
        """确保运行期所需目录存在。"""
        for path in (self.DB_PATH.parent, self.STORAGE_DIR):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def APPROVAL_MOCK_MODE(self) -> bool:
        """当前是否指向内置模拟审批系统（用于前端提示）。"""
        return f"{self.MOCK_HOST}:{self.MOCK_PORT}" in self.APPROVAL_BASE_URL

    def as_dict(self) -> dict:
        """导出可对外展示的配置快照（隐藏令牌）。"""
        return {
            "project_name": self.PROJECT_NAME,
            "version": self.VERSION,
            "app_host": self.APP_HOST,
            "app_port": self.APP_PORT,
            "approval_base_url": self.APPROVAL_BASE_URL,
            "approval_mock_mode": self.APPROVAL_MOCK_MODE,
            "db_path": str(self.DB_PATH),
            "storage_dir": str(self.STORAGE_DIR),
            "ocr_engine": self.OCR_ENGINE,
            "ocr_lang": self.OCR_LANG,
            "prepay_ratio_threshold": self.PREPAY_RATIO_THRESHOLD,
            "payment_period_days_limit": self.PAYMENT_PERIOD_DAYS_LIMIT,
        }


settings = Settings()
