"""业务异常定义。

异常分层：
    ReviewBaseError          所有业务异常基类
      ├─ BlockedError        需进入 blocked 阻塞态的异常（携带阻塞原因）
      ├─ ExternalApiError    外部审批系统调用失败
      ├─ ParseError          文档解析异常
      ├─ OcrError            OCR 识别异常
      └─ NotFoundError       业务对象不存在
"""

from __future__ import annotations

from .constants import BlockReason


class ReviewBaseError(Exception):
    """业务异常基类。"""

    #: 是否应将任务置为 blocked
    block_task = False
    #: 默认阻塞原因
    block_reason = ""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "detail": self.detail,
            "block_reason": self.block_reason,
        }


class BlockedError(ReviewBaseError):
    """触发阻塞场景的异常：附件缺失 / OCR 失败 / 内容为空 / 接口失败 / 解析异常。"""

    block_task = True

    def __init__(self, message: str, block_reason: str = BlockReason.FILE_PARSE_ERROR, detail: str = "") -> None:
        super().__init__(message, detail)
        self.block_reason = block_reason


class ExternalApiError(BlockedError):
    """外部审批系统接口调用失败。"""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message, BlockReason.EXTERNAL_API_ERROR, detail)


class AttachmentMissingError(BlockedError):
    """附件缺失。"""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message, BlockReason.ATTACHMENT_MISSING, detail)


class OcrError(BlockedError):
    """扫描件图片无法识别。"""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message, BlockReason.OCR_FAILED, detail)


class EmptyContentError(BlockedError):
    """文档内容为空。"""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message, BlockReason.EMPTY_CONTENT, detail)


class ParseError(BlockedError):
    """文件解析异常。"""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message, BlockReason.FILE_PARSE_ERROR, detail)


class NotFoundError(ReviewBaseError):
    """业务对象不存在（不触发阻塞，直接返回错误）。"""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message, detail)
