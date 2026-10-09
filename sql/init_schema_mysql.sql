-- ==============================================================================
-- 企业合同审批自动审查系统 —— 数据库初始化脚本（MySQL 8.0 版）
-- 版本：v1.0.0
-- 说明：与 init_schema.sql（SQLite 版）结构完全一致，仅做方言适配。
--       默认系统以 SQLite 运行，如需切换 MySQL，请把本脚本导入 MySQL，
--       并通过环境变量 DB_ENGINE=mysql 及 DB_DSN 指定连接串（详见 README.md）。
-- ==============================================================================

-- CREATE DATABASE IF NOT EXISTS contract_review DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_general_ci;
-- USE contract_review;

-- 1. approval_tasks 审批任务主表
CREATE TABLE IF NOT EXISTS approval_tasks (
    id                BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    approval_code     VARCHAR(64)  NOT NULL                COMMENT '审批编号（业务唯一标识，任务去重依据）',
    approval_title    VARCHAR(255) NOT NULL DEFAULT ''     COMMENT '审批标题',
    applicant_name    VARCHAR(64)  NOT NULL DEFAULT ''     COMMENT '申请人',
    task_status       VARCHAR(20)  NOT NULL DEFAULT 'pending' COMMENT '任务状态：pending/parsing/reviewing/blocked/done',
    write_status      VARCHAR(20)  NOT NULL DEFAULT 'not_written' COMMENT '评论回写状态：not_written/writing/success/failed',
    created_at        VARCHAR(32)  NOT NULL                COMMENT '创建时间',
    updated_at        VARCHAR(32)  NOT NULL                COMMENT '更新时间',
    apply_time        VARCHAR(32)  DEFAULT ''              COMMENT '[扩展] 申请时间',
    attachment_count  INT          DEFAULT 0               COMMENT '[扩展] 附件数量',
    current_handler   VARCHAR(64)  DEFAULT ''              COMMENT '[扩展] 当前处理人',
    form_data_json    TEXT                                 COMMENT '[扩展] 审批表单数据快照(JSON)',
    block_reason      VARCHAR(512) DEFAULT ''              COMMENT '[扩展] 阻塞原因',
    retry_count       INT          DEFAULT 0               COMMENT '[扩展] 人工重试次数',
    PRIMARY KEY (id),
    UNIQUE KEY uk_tasks_approval_code (approval_code),
    KEY idx_tasks_status (task_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审批任务主表';

-- 2. approval_attachments 附件表
CREATE TABLE IF NOT EXISTS approval_attachments (
    id               BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_id          BIGINT       NOT NULL                COMMENT '关联审批任务ID',
    file_name        VARCHAR(255) NOT NULL DEFAULT ''     COMMENT '文件名',
    file_type        VARCHAR(20)  NOT NULL DEFAULT ''     COMMENT '文件类型',
    file_path        VARCHAR(512) NOT NULL DEFAULT ''     COMMENT '本地存储路径',
    download_status  VARCHAR(20)  NOT NULL DEFAULT 'pending' COMMENT '下载状态：pending/success/failed',
    created_at       VARCHAR(32)  NOT NULL                COMMENT '创建时间',
    attachment_id    VARCHAR(64)  DEFAULT ''              COMMENT '[扩展] 外部审批系统附件编号',
    file_md5         VARCHAR(64)  DEFAULT ''              COMMENT '[扩展] 文件 MD5 校验值',
    file_size        BIGINT       DEFAULT 0               COMMENT '[扩展] 文件字节数',
    download_error   VARCHAR(512) DEFAULT ''              COMMENT '[扩展] 下载失败原因',
    updated_at       VARCHAR(32)  DEFAULT ''              COMMENT '[扩展] 更新时间',
    PRIMARY KEY (id),
    KEY idx_attach_task (task_id),
    UNIQUE KEY uk_attach_task_attid (task_id, attachment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审批单附件表';

-- 3. contract_parses 合同解析表
CREATE TABLE IF NOT EXISTS contract_parses (
    id                   BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_id              BIGINT      NOT NULL                COMMENT '关联审批任务ID',
    basic_info_json      LONGTEXT                            COMMENT '合同基本信息(JSON)',
    clause_info_json     LONGTEXT                            COMMENT '合同条款信息(JSON)',
    parse_status         VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '解析状态：pending/success/failed/blocked',
    parse_error          VARCHAR(1024) NOT NULL DEFAULT ''   COMMENT '解析失败原因',
    created_at           VARCHAR(32) NOT NULL                COMMENT '创建时间',
    full_text            LONGTEXT                            COMMENT '[扩展] 合同全文',
    segments_json        LONGTEXT                            COMMENT '[扩展] 分段定位结构(JSON)',
    page_count           INT         DEFAULT 0               COMMENT '[扩展] 页数',
    attachment_id        BIGINT      DEFAULT 0               COMMENT '[扩展] 主合同附件ID',
    document_detail_json LONGTEXT                            COMMENT '[扩展] 多附件解析明细(JSON)',
    updated_at           VARCHAR(32) DEFAULT ''              COMMENT '[扩展] 更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_parse_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合同解析表';

-- 4. review_rules 风控规则表
CREATE TABLE IF NOT EXISTS review_rules (
    id               BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    rule_code        VARCHAR(64)  NOT NULL                COMMENT '规则编码（唯一）',
    rule_name        VARCHAR(128) NOT NULL DEFAULT ''     COMMENT '规则名称',
    risk_level       VARCHAR(8)   NOT NULL DEFAULT '中'    COMMENT '风险等级：低/中/高',
    rule_status      VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启用状态：enabled/disabled',
    match_mode       VARCHAR(16)  NOT NULL DEFAULT 'keyword' COMMENT '匹配模式：keyword/regex/missing/logic',
    match_text       VARCHAR(1024) NOT NULL DEFAULT ''    COMMENT '匹配关键词或逻辑表达式',
    suggestion_text  VARCHAR(1024) NOT NULL DEFAULT ''    COMMENT '整改建议',
    updated_at       VARCHAR(32)  NOT NULL                COMMENT '更新时间',
    created_at       VARCHAR(32)  DEFAULT ''              COMMENT '[扩展] 创建时间',
    remark           VARCHAR(512) DEFAULT ''              COMMENT '[扩展] 规则说明/覆盖场景',
    sort_no          INT          DEFAULT 0               COMMENT '[扩展] 排序号',
    PRIMARY KEY (id),
    UNIQUE KEY uk_rules_code (rule_code),
    KEY idx_rules_status (rule_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='风控规则表';

-- 5. rule_hits 规则命中记录表
CREATE TABLE IF NOT EXISTS rule_hits (
    id                   BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_id              BIGINT      NOT NULL                COMMENT '关联审批任务ID',
    rule_id              BIGINT      NOT NULL                COMMENT '关联规则ID',
    evidence_text        TEXT                                COMMENT '命中证据原文',
    evidence_position    VARCHAR(512) NOT NULL DEFAULT ''    COMMENT '证据位置（页码/段落/行号/字符偏移）',
    hit_status           VARCHAR(16) NOT NULL DEFAULT 'hit'   COMMENT '命中状态：hit/ignored/confirmed',
    created_at           VARCHAR(32) NOT NULL                COMMENT '创建时间',
    rule_code            VARCHAR(64) DEFAULT ''              COMMENT '[扩展] 规则编码快照',
    rule_name            VARCHAR(128) DEFAULT ''             COMMENT '[扩展] 规则名称快照',
    risk_level           VARCHAR(8)  DEFAULT ''              COMMENT '[扩展] 风险等级快照',
    suggestion_text      VARCHAR(1024) DEFAULT ''            COMMENT '[扩展] 整改建议快照',
    review_id            BIGINT      DEFAULT 0               COMMENT '[扩展] 关联审查结果ID',
    evidence_detail_json TEXT                                COMMENT '[扩展] 结构化证据定位(JSON)',
    updated_at           VARCHAR(32) DEFAULT ''              COMMENT '[扩展] 更新时间',
    PRIMARY KEY (id),
    KEY idx_hits_task (task_id),
    KEY idx_hits_review (review_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='规则命中记录表';

-- 6. review_results 审查结果表
CREATE TABLE IF NOT EXISTS review_results (
    id                 BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_id            BIGINT      NOT NULL                COMMENT '关联审批任务ID',
    overall_risk_level VARCHAR(8)  NOT NULL DEFAULT '低'    COMMENT '总风险等级：低/中/高',
    summary_text       TEXT                                COMMENT '中文风险摘要',
    focus_points_json  TEXT                                COMMENT '审批关注点(JSON数组)',
    comment_text       TEXT                                COMMENT '待回写评论标准文本',
    created_at         VARCHAR(32) NOT NULL                COMMENT '创建时间',
    hit_count          INT         DEFAULT 0               COMMENT '[扩展] 命中规则总数',
    high_count         INT         DEFAULT 0               COMMENT '[扩展] 高风险命中数',
    medium_count       INT         DEFAULT 0               COMMENT '[扩展] 中风险命中数',
    low_count          INT         DEFAULT 0               COMMENT '[扩展] 低风险命中数',
    save_status        VARCHAR(16) DEFAULT 'saved'         COMMENT '[扩展] 保存状态',
    updated_at         VARCHAR(32) DEFAULT ''              COMMENT '[扩展] 更新时间',
    PRIMARY KEY (id),
    KEY idx_results_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审查结果表';

-- 7. comment_logs 评论回写日志表
CREATE TABLE IF NOT EXISTS comment_logs (
    id                  BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_id             BIGINT      NOT NULL                COMMENT '关联审批任务ID',
    write_status        VARCHAR(20) NOT NULL DEFAULT 'not_written' COMMENT '回写状态：not_written/writing/success/failed',
    write_response_text VARCHAR(2048) NOT NULL DEFAULT ''   COMMENT '回写响应结果',
    created_at          VARCHAR(32) NOT NULL                COMMENT '创建时间',
    review_id           BIGINT      DEFAULT 0               COMMENT '[扩展] 关联审查结果ID',
    comment_text        TEXT                                COMMENT '[扩展] 实际回写内容',
    http_status         INT         DEFAULT 0               COMMENT '[扩展] HTTP 响应码',
    request_payload     TEXT                                COMMENT '[扩展] 回写请求报文(JSON)',
    write_error         VARCHAR(1024) DEFAULT ''            COMMENT '[扩展] 回写失败原因',
    PRIMARY KEY (id),
    KEY idx_comment_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评论回写日志表';

-- 8. task_logs 系统任务日志表
CREATE TABLE IF NOT EXISTS task_logs (
    id          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_id     BIGINT      NOT NULL DEFAULT 0      COMMENT '关联审批任务ID（0=系统级日志）',
    log_level   VARCHAR(10) NOT NULL DEFAULT 'INFO' COMMENT '日志级别：INFO/WARN/ERROR',
    log_type    VARCHAR(20) NOT NULL DEFAULT 'OPERATION' COMMENT '日志类型',
    log_content TEXT                                COMMENT '日志内容',
    created_at  VARCHAR(32) NOT NULL                COMMENT '创建时间',
    trace_id    VARCHAR(64) DEFAULT ''              COMMENT '[扩展] 链路追踪号',
    cost_ms     INT         DEFAULT 0               COMMENT '[扩展] 步骤耗时(毫秒)',
    PRIMARY KEY (id),
    KEY idx_logs_task (task_id),
    KEY idx_logs_created (created_at),
    KEY idx_logs_level (log_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统任务日志表';
