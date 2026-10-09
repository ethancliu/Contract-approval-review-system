"""全局状态机与枚举常量定义。

本模块集中定义任务状态、回写状态、风险等级等全部受控词表，
业务代码禁止散落硬编码字符串，确保状态流转口径统一。
"""

from __future__ import annotations


# ----------------------------------------------------------------------
# 一、任务核心状态
# ----------------------------------------------------------------------
class TaskStatus:
    """审批任务核心状态（严格按需求定义，共 5 种）。"""

    PENDING = "pending"        # 待处理
    PARSING = "parsing"        # 解析中
    REVIEWING = "reviewing"    # 规则审查中
    BLOCKED = "blocked"        # 异常阻塞
    DONE = "done"              # 处理完成

    ALL = (PENDING, PARSING, REVIEWING, BLOCKED, DONE)

    CN = {
        PENDING: "待处理",
        PARSING: "解析中",
        REVIEWING: "规则审查中",
        BLOCKED: "异常阻塞",
        DONE: "处理完成",
    }


# ----------------------------------------------------------------------
# 二、评论回写状态
# ----------------------------------------------------------------------
class WriteStatus:
    """审批评论回写状态（严格按需求定义，共 4 种）。"""

    NOT_WRITTEN = "not_written"    # 未回写
    WRITING = "writing"            # 回写中
    SUCCESS = "success"            # 回写成功
    FAILED = "failed"              # 回写失败

    ALL = (NOT_WRITTEN, WRITING, SUCCESS, FAILED)

    CN = {
        NOT_WRITTEN: "未回写",
        WRITING: "回写中",
        SUCCESS: "回写成功",
        FAILED: "回写失败",
    }


# ----------------------------------------------------------------------
# 三、风险等级
# ----------------------------------------------------------------------
class RiskLevel:
    """风险等级，仅「低 / 中 / 高」三档。"""

    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"

    ALL = (LOW, MEDIUM, HIGH)

    #: 等级排序权重，用于汇总时取最高等级
    ORDER = {LOW: 1, MEDIUM: 2, HIGH: 3}

    @classmethod
    def max_of(cls, levels) -> str:
        """返回一组风险等级中的最高等级；空集合返回「低」。"""
        valid = [lv for lv in levels if lv in cls.ORDER]
        if not valid:
            return cls.LOW
        return max(valid, key=lambda lv: cls.ORDER[lv])


# ----------------------------------------------------------------------
# 四、附件下载状态
# ----------------------------------------------------------------------
class DownloadStatus:
    PENDING = "pending"    # 待下载
    SUCCESS = "success"    # 下载成功
    FAILED = "failed"      # 下载失败

    ALL = (PENDING, SUCCESS, FAILED)
    CN = {PENDING: "待下载", SUCCESS: "下载成功", FAILED: "下载失败"}


# ----------------------------------------------------------------------
# 五、文档解析状态
# ----------------------------------------------------------------------
class ParseStatus:
    PENDING = "pending"    # 待解析
    SUCCESS = "success"    # 解析成功
    FAILED = "failed"      # 解析失败
    BLOCKED = "blocked"    # 解析阻塞（需人工介入）

    ALL = (PENDING, SUCCESS, FAILED, BLOCKED)
    CN = {PENDING: "待解析", SUCCESS: "解析成功", FAILED: "解析失败", BLOCKED: "解析阻塞"}


# ----------------------------------------------------------------------
# 六、字段提取状态
# ----------------------------------------------------------------------
class ExtractStatus:
    SUCCESS = "success"    # 提取成功
    MISSING = "missing"    # 原文中不存在该字段
    FAILED = "failed"      # 提取异常

    ALL = (SUCCESS, MISSING, FAILED)
    CN = {SUCCESS: "提取成功", MISSING: "未提取到", FAILED: "提取失败"}

    #: 字段值为空时对外展示的占位文本（规范要求禁止空值返回）
    PLACEHOLDER = "未识别"


# ----------------------------------------------------------------------
# 七、规则相关枚举
# ----------------------------------------------------------------------
class RuleStatus:
    ENABLED = "enabled"      # 启用
    DISABLED = "disabled"    # 禁用

    ALL = (ENABLED, DISABLED)
    CN = {ENABLED: "启用", DISABLED: "禁用"}


class MatchMode:
    """规则匹配模式。match_text 的语义随本字段变化。"""

    KEYWORD = "keyword"    # match_text = "关键词1|关键词2|..."，命中任一即命中
    REGEX = "regex"        # match_text = 正则表达式，命中即命中
    MISSING = "missing"    # match_text = "field:字段A,字段B" 或 "clause:条款A"，缺失即命中
    LOGIC = "logic"        # match_text = "内置逻辑名:参数"，交给业务逻辑判定

    ALL = (KEYWORD, REGEX, MISSING, LOGIC)
    CN = {KEYWORD: "关键词匹配", REGEX: "正则匹配", MISSING: "缺失检测", LOGIC: "业务逻辑判定"}


class HitStatus:
    HIT = "hit"                # 命中
    IGNORED = "ignored"        # 人工已忽略
    CONFIRMED = "confirmed"    # 人工已确认

    ALL = (HIT, IGNORED, CONFIRMED)
    CN = {HIT: "命中", IGNORED: "已忽略", CONFIRMED: "人工已确认"}


# ----------------------------------------------------------------------
# 八、日志相关枚举
# ----------------------------------------------------------------------
class LogLevel:
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"

    ALL = (INFO, WARN, ERROR)


class LogType:
    FETCH = "FETCH"            # 拉取
    ATTACHMENT = "ATTACHMENT"  # 附件
    PARSE = "PARSE"            # 解析
    RULE = "RULE"              # 规则审查
    WRITE = "WRITE"            # 评论回写
    TASK = "TASK"              # 任务流转
    API = "API"                # 外部接口调用
    ERROR = "ERROR"            # 异常

    ALL = (FETCH, ATTACHMENT, PARSE, RULE, WRITE, TASK, API, ERROR)
    CN = {
        FETCH: "拉取", ATTACHMENT: "附件", PARSE: "解析", RULE: "规则审查",
        WRITE: "评论回写", TASK: "任务流转", API: "外部接口", ERROR: "异常",
    }


# ----------------------------------------------------------------------
# 九、阻塞原因（对应需求「触发阻塞场景」五项）
# ----------------------------------------------------------------------
class BlockReason:
    ATTACHMENT_MISSING = "附件缺失"              # 审批单无任何附件，或全部附件下载失败
    OCR_FAILED = "扫描件图片无法识别"            # OCR 引擎不可用或识别结果为空
    EMPTY_CONTENT = "文档内容为空"               # 解析后正文为空
    EXTERNAL_API_ERROR = "外部接口调用失败"      # 审批系统接口不可用 / 返回异常
    FILE_PARSE_ERROR = "文件解析异常"            # 文件损坏、格式不支持、解析组件缺失

    ALL = (ATTACHMENT_MISSING, OCR_FAILED, EMPTY_CONTENT, EXTERNAL_API_ERROR, FILE_PARSE_ERROR)

    #: 管理员人工重试后是否可从解析阶段继续（True=回到 parsing/reviewing 流程）
    RETRYABLE = True


# ----------------------------------------------------------------------
# 十、其他常量
# ----------------------------------------------------------------------
#: 支持直接文本解析的电子文档扩展名
TEXT_DOC_EXTS = (".docx", ".doc", ".pdf", ".txt", ".md", ".text")

#: 需要走 OCR 的扫描件/图片扩展名
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")

#: 主合同文件（用于抽取字段）优先级权重，数值越大越优先
FILE_PRIORITY = {
    "docx": 100, "doc": 95, "pdf": 90, "txt": 70, "md": 70,
    "png": 60, "jpg": 60, "jpeg": 60, "bmp": 60, "tif": 60, "tiff": 60, "webp": 60,
}
