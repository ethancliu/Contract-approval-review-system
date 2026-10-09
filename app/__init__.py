"""企业合同审批自动审查系统 —— 应用包。

分层结构：
    app/config.py        全局配置
    app/constants.py     状态机 / 枚举常量
    app/database.py      数据访问层（连接、初始化、通用 DAO）
    app/logger.py        日志模块（task_logs 全链路落库）
    app/schemas.py       接口出入参模型
    app/modules/         业务模块（拉取/附件/解析/规则/回写/编排）
    app/api/             工具接口与管理员接口
    app/mock_approval/   模拟审批系统（演示用对接方）
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
