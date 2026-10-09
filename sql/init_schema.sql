-- ==============================================================================
-- 企业合同审批自动审查系统 —— 数据库初始化脚本（SQLite 版）
-- 版本：v1.0.0
-- 说明：
--   1) 本脚本幂等，可重复执行（CREATE TABLE IF NOT EXISTS）。
--   2) 8 张业务表的表名、必填字段、字段含义严格遵循《数据库表结构强制规范》。
--   3) 规范未列出的字段标记为「扩展字段」，均为支撑规范要求的必填返回值所必需
--      （例如：待办拉取工具必须返回"申请时间 / 附件数量"，
--        因此 approval_tasks 需要 apply_time / attachment_count 两列承载）。
--   4) 服务启动时 app/database.py 会自动执行本脚本，无需手工建库。
-- ==============================================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------------------
-- 1. approval_tasks 审批任务主表
--    【规范字段】id、approval_code、approval_title、applicant_name、task_status、write_status、created_at、updated_at
--    【扩展字段】apply_time 申请时间、attachment_count 附件数量、current_handler 当前处理人、
--               form_data_json 表单数据快照、block_reason 阻塞原因、retry_count 重试次数
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approval_tasks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,           -- 主键
    approval_code     TEXT    NOT NULL UNIQUE,                      -- 审批编号（业务唯一标识，任务去重依据）
    approval_title    TEXT    NOT NULL DEFAULT '',                  -- 审批标题
    applicant_name    TEXT    NOT NULL DEFAULT '',                  -- 申请人
    task_status       TEXT    NOT NULL DEFAULT 'pending',           -- 任务状态：pending/parsing/reviewing/blocked/done
    write_status      TEXT    NOT NULL DEFAULT 'not_written',       -- 评论回写状态：not_written/writing/success/failed
    created_at        TEXT    NOT NULL,                             -- 创建时间
    updated_at        TEXT    NOT NULL,                             -- 更新时间
    apply_time        TEXT    DEFAULT '',                           -- [扩展] 申请时间
    attachment_count  INTEGER DEFAULT 0,                            -- [扩展] 附件数量
    current_handler   TEXT    DEFAULT '',                           -- [扩展] 当前处理人
    form_data_json    TEXT    DEFAULT '{}',                         -- [扩展] 审批表单数据快照(JSON)
    block_reason      TEXT    DEFAULT '',                           -- [扩展] 阻塞原因
    retry_count       INTEGER DEFAULT 0                             -- [扩展] 人工重试次数
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_tasks_approval_code ON approval_tasks (approval_code);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON approval_tasks (task_status);


-- ------------------------------------------------------------------------------
-- 2. approval_attachments 附件表
--    【规范字段】id、task_id、file_name、file_type、file_path、download_status、created_at
--    【扩展字段】attachment_id 外部附件编号、file_md5/file_size 文件校验信息、
--               download_error 下载失败原因、updated_at 更新时间
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approval_attachments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,            -- 主键
    task_id          INTEGER NOT NULL,                             -- 关联审批任务ID -> approval_tasks.id
    file_name        TEXT    NOT NULL DEFAULT '',                  -- 文件名
    file_type        TEXT    NOT NULL DEFAULT '',                  -- 文件类型：docx/pdf/txt/png/jpg...
    file_path        TEXT    NOT NULL DEFAULT '',                  -- 本地存储路径
    download_status  TEXT    NOT NULL DEFAULT 'pending',           -- 下载状态：pending/success/failed
    created_at       TEXT    NOT NULL,                             -- 创建时间
    attachment_id    TEXT    DEFAULT '',                           -- [扩展] 外部审批系统附件编号
    file_md5         TEXT    DEFAULT '',                           -- [扩展] 文件 MD5 校验值
    file_size        INTEGER DEFAULT 0,                            -- [扩展] 文件字节数
    download_error   TEXT    DEFAULT '',                           -- [扩展] 下载失败原因
    updated_at       TEXT    DEFAULT '',                           -- [扩展] 更新时间
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_attach_task ON approval_attachments (task_id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_attach_task_attid ON approval_attachments (task_id, attachment_id);


-- ------------------------------------------------------------------------------
-- 3. contract_parses 合同解析表
--    【规范字段】id、task_id、basic_info_json、clause_info_json、parse_status、parse_error、created_at
--    【扩展字段】full_text 全文、segments_json 分段定位信息、page_count 页数、
--               attachment_id 主合同附件、document_detail_json 多附件解析明细、updated_at
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contract_parses (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,        -- 主键
    task_id              INTEGER NOT NULL,                         -- 关联审批任务ID -> approval_tasks.id
    basic_info_json      TEXT    NOT NULL DEFAULT '{}',            -- 合同基本信息(JSON，含原文/位置/提取状态)
    clause_info_json     TEXT    NOT NULL DEFAULT '{}',            -- 合同条款信息(JSON，含原文/位置/提取状态)
    parse_status         TEXT    NOT NULL DEFAULT 'pending',       -- 解析状态：pending/success/failed/blocked
    parse_error          TEXT    NOT NULL DEFAULT '',              -- 解析失败原因
    created_at           TEXT    NOT NULL,                         -- 创建时间
    full_text            TEXT    DEFAULT '',                       -- [扩展] 合同全文（OCR/文档抽取后的纯文本）
    segments_json        TEXT    DEFAULT '[]',                     -- [扩展] 分段定位结构（页码/段号/行号/字符偏移）
    page_count           INTEGER DEFAULT 0,                        -- [扩展] 页数（图片数）
    attachment_id        INTEGER DEFAULT 0,                        -- [扩展] 主合同附件ID -> approval_attachments.id
    document_detail_json TEXT    DEFAULT '[]',                     -- [扩展] 多附件逐一解析明细(JSON)
    updated_at           TEXT    DEFAULT '',                       -- [扩展] 更新时间
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_parse_task ON contract_parses (task_id);


-- ------------------------------------------------------------------------------
-- 4. review_rules 风控规则表
--    【规范字段】id、rule_code、rule_name、risk_level、rule_status、match_mode、match_text、suggestion_text、updated_at
--    【扩展字段】created_at 创建时间、remark 备注、sort_no 排序号
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_rules (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,            -- 主键
    rule_code        TEXT    NOT NULL UNIQUE,                      -- 规则编码（唯一）
    rule_name        TEXT    NOT NULL DEFAULT '',                  -- 规则名称
    risk_level       TEXT    NOT NULL DEFAULT '中',                -- 风险等级：低/中/高
    rule_status      TEXT    NOT NULL DEFAULT 'enabled',           -- 启用状态：enabled 启用 / disabled 禁用
    match_mode       TEXT    NOT NULL DEFAULT 'keyword',           -- 匹配模式：keyword/regex/missing/logic
    match_text       TEXT    NOT NULL DEFAULT '',                  -- 匹配关键词或逻辑表达式
    suggestion_text  TEXT    NOT NULL DEFAULT '',                  -- 整改建议
    updated_at       TEXT    NOT NULL,                             -- 更新时间
    created_at       TEXT    DEFAULT '',                           -- [扩展] 创建时间
    remark           TEXT    DEFAULT '',                           -- [扩展] 规则说明/覆盖场景
    sort_no          INTEGER DEFAULT 0                             -- [扩展] 展示排序号
);

CREATE INDEX IF NOT EXISTS idx_rules_status ON review_rules (rule_status);


-- ------------------------------------------------------------------------------
-- 5. rule_hits 规则命中记录表
--    【规范字段】id、task_id、rule_id、evidence_text、evidence_position、hit_status、created_at
--    【扩展字段】rule_code/rule_name/risk_level/suggestion_text 冗余快照、
--               review_id 关联审查结果、evidence_detail_json 结构化位置、updated_at
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rule_hits (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,       -- 主键
    task_id               INTEGER NOT NULL,                        -- 关联审批任务ID -> approval_tasks.id
    rule_id               INTEGER NOT NULL,                        -- 关联规则ID -> review_rules.id
    evidence_text         TEXT    NOT NULL DEFAULT '',             -- 命中证据原文
    evidence_position     TEXT    NOT NULL DEFAULT '',             -- 证据位置（页码/段落/行号/字符偏移）
    hit_status            TEXT    NOT NULL DEFAULT 'hit',          -- 命中状态：hit 命中 / ignored 已忽略 / confirmed 人工已确认
    created_at            TEXT    NOT NULL,                        -- 创建时间
    rule_code             TEXT    DEFAULT '',                      -- [扩展] 规则编码快照
    rule_name             TEXT    DEFAULT '',                      -- [扩展] 规则名称快照
    risk_level            TEXT    DEFAULT '',                      -- [扩展] 风险等级快照
    suggestion_text       TEXT    DEFAULT '',                      -- [扩展] 整改建议快照
    review_id             INTEGER DEFAULT 0,                       -- [扩展] 关联审查结果ID -> review_results.id
    evidence_detail_json  TEXT    DEFAULT '{}',                    -- [扩展] 结构化证据定位信息(JSON)
    updated_at            TEXT    DEFAULT '',                      -- [扩展] 更新时间
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY (rule_id) REFERENCES review_rules (id)
);

CREATE INDEX IF NOT EXISTS idx_hits_task ON rule_hits (task_id);
CREATE INDEX IF NOT EXISTS idx_hits_review ON rule_hits (review_id);


-- ------------------------------------------------------------------------------
-- 6. review_results 审查结果表
--    【规范字段】id、task_id、overall_risk_level、summary_text、focus_points_json、comment_text、created_at
--    【扩展字段】hit_count/high_count/medium_count/low_count 命中数量统计、save_status、updated_at
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,          -- 主键
    task_id            INTEGER NOT NULL,                           -- 关联审批任务ID -> approval_tasks.id
    overall_risk_level TEXT    NOT NULL DEFAULT '低',              -- 总风险等级：低/中/高
    summary_text       TEXT    NOT NULL DEFAULT '',                -- 中文风险摘要
    focus_points_json  TEXT    NOT NULL DEFAULT '[]',              -- 审批关注点(JSON数组)
    comment_text       TEXT    NOT NULL DEFAULT '',                -- 待回写评论标准文本
    created_at         TEXT    NOT NULL,                           -- 创建时间
    hit_count          INTEGER DEFAULT 0,                          -- [扩展] 命中规则总数
    high_count         INTEGER DEFAULT 0,                          -- [扩展] 高风险命中数
    medium_count       INTEGER DEFAULT 0,                          -- [扩展] 中风险命中数
    low_count          INTEGER DEFAULT 0,                          -- [扩展] 低风险命中数
    save_status        TEXT    DEFAULT 'saved',                    -- [扩展] 保存状态：saved/failed
    updated_at         TEXT    DEFAULT '',                         -- [扩展] 更新时间
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_results_task ON review_results (task_id);


-- ------------------------------------------------------------------------------
-- 7. comment_logs 评论回写日志表
--    【规范字段】id、task_id、write_status、write_response_text、created_at
--    【扩展字段】review_id 关联审查结果、comment_text 回写内容、http_status 响应码、
--               request_payload 请求报文、write_error 错误信息
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comment_logs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,        -- 主键
    task_id              INTEGER NOT NULL,                         -- 关联审批任务ID -> approval_tasks.id
    write_status         TEXT    NOT NULL DEFAULT 'not_written',   -- 回写状态：not_written/writing/success/failed
    write_response_text  TEXT    NOT NULL DEFAULT '',              -- 回写响应结果
    created_at           TEXT    NOT NULL,                         -- 创建时间
    review_id            INTEGER DEFAULT 0,                        -- [扩展] 关联审查结果ID -> review_results.id
    comment_text         TEXT    DEFAULT '',                       -- [扩展] 实际回写内容
    http_status          INTEGER DEFAULT 0,                        -- [扩展] HTTP 响应码
    request_payload      TEXT    DEFAULT '',                       -- [扩展] 回写请求报文(JSON)
    write_error          TEXT    DEFAULT '',                       -- [扩展] 回写失败原因
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comment_task ON comment_logs (task_id);


-- ------------------------------------------------------------------------------
-- 8. task_logs 系统任务日志表
--    【规范字段】id、task_id、log_level、log_type、log_content、created_at
--    【扩展字段】trace_id 链路追踪号、cost_ms 耗时
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,                -- 主键
    task_id      INTEGER NOT NULL DEFAULT 0,                       -- 关联审批任务ID（0 表示系统级日志）
    log_level    TEXT    NOT NULL DEFAULT 'INFO',                  -- 日志级别：INFO/WARN/ERROR
    log_type     TEXT    NOT NULL DEFAULT 'OPERATION',             -- 日志类型：FETCH/ATTACHMENT/PARSE/RULE/WRITE/TASK/API/ERROR
    log_content  TEXT    NOT NULL DEFAULT '',                      -- 日志内容
    created_at   TEXT    NOT NULL,                                 -- 创建时间
    trace_id     TEXT    DEFAULT '',                               -- [扩展] 链路追踪号
    cost_ms      INTEGER DEFAULT 0                                 -- [扩展] 步骤耗时(毫秒)
);

CREATE INDEX IF NOT EXISTS idx_logs_task ON task_logs (task_id);
CREATE INDEX IF NOT EXISTS idx_logs_created ON task_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_logs_level ON task_logs (log_level);
