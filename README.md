# 企业合同审批自动审查系统

> **本系统仅辅助人工审批，绝不替代人工审核决策。**
> 系统自动完成合同拉取 → 附件下载 → 文档解析 / OCR 识别 → 规则风控 → 结果入库 → 评论回写全流程，
> 输出的风险结论与整改建议**仅供参考**，最终审批权归人工法务与审批人。

---

## 一、系统能力

| 能力 | 说明 |
| --- | --- |
| 待办拉取 | 对接企业审批系统，拉取待审审批单，按**审批编号**做业务维度去重，重复拉取只增量更新、绝不重复创建任务 |
| 附件管理 | 下载合同附件至本地存储，校验 MD5、文件大小，记录下载状态与失败原因 |
| 文档解析 | 支持 `.txt / .docx / .pdf / 图片扫描件`；扫描件走可插拔 OCR 引擎（Tesseract → PaddleOCR → 伴随文本降级） |
| 结构化提取 | 强制提取 **16 项必备字段**（8 项基础信息 + 8 项条款信息），每项均携带原文片段、页码/位置标识、提取状态；**解析失败记录具体失败原因，禁止空值返回** |
| 规则风控 | 内置 **16 条**风控规则，覆盖 **11 类必备风险场景**，支持 `keyword / regex / missing / logic` 四种匹配模式 |
| 结果入库 | 审查结果、命中规则、风险摘要、审批关注点完整落库，共 **8 张数据表** |
| 评论回写 | 生成六段式标准化中文审查意见，回写至审批系统评论区，记录回写状态与响应原文 |
| 异常阻塞 | 5 类阻塞场景自动拦截并记录阻塞原因，支持管理员单条 / 批量重试，重试前自动同步审批系统最新数据 |

---

## 二、快速开始

### 1. 环境要求

- Python **3.10+**（开发验证环境为 3.12.13）
- 无需数据库服务：默认使用 SQLite；生产可切换 MySQL（提供建表脚本）

### 2. 安装依赖

```powershell
cd D:\AI_20260413\vibe conding\项目实战文档\hetongshencha

# 方式一：使用 uv（推荐，本项目开发环境即使用该方式）
uv venv
uv pip install -r requirements.txt

# 方式二：使用 venv + pip
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

> 国内网络可加镜像源：`--index-url https://pypi.tuna.tsinghua.edu.cn/simple`

### 3. 一键启动

```powershell
.\.venv\Scripts\python run.py
```

`run.py` 会完成三件事：

1. 生成示例合同文件（`sample_contracts/`，已存在则跳过）
2. 初始化数据库与规则库（`data/contract_review.db`，含 16 条内置规则）
3. 启动服务：
   - 主审查服务 **http://127.0.0.1:8000**（调用端页面 `/`，接口文档 `/docs`）
   - 内置模拟审批系统 **http://127.0.0.1:9100**（演示用对接方）

### 4. 打开调用端页面

浏览器访问 <http://127.0.0.1:8000/> ，即可看到覆盖全流程五大模块的调用端展示页面。

### 5. 运行全流程闭环演示

```powershell
# 另开一个终端（保持 run.py 运行中）
.\.venv\Scripts\python scripts\demo_closed_loop.py --reset
```

详细操作步骤见 [docs/闭环演示操作指南.md](docs/闭环演示操作指南.md)。

---

## 三、目录结构

```
hetongshencha/
├── run.py                          # 一键启动入口（拉起模拟审批系统 + 主服务）
├── requirements.txt                # 依赖清单
├── README.md                       # 本文件
│
├── app/                            # 应用主体
│   ├── main.py                     # FastAPI 应用装配、异常处理、静态页面挂载
│   ├── config.py                   # 全局配置（全部支持环境变量覆盖）
│   ├── constants.py                # 全部受控词汇：任务状态 / 回写状态 / 风险等级 / 阻塞原因 …
│   ├── database.py                 # SQLite 连接与查询封装、初始化、健康检查
│   ├── logger.py                   # 全链路日志（永不抛异常，保证主流程不中断）
│   ├── exceptions.py               # 业务异常体系（阻塞型 / 接口型 / 解析型 …）
│   │
│   ├── modules/                    # ★ 业务模块（按职责解耦）
│   │   ├── fetcher.py              # 拉取模块：待办列表、审批详情、去重入库、重试前刷新
│   │   ├── attachment.py           # 附件模块：下载、MD5 校验、本地存储、元数据入库
│   │   ├── parser/                 # 解析模块
│   │   │   ├── document_parser.py  #   txt / docx / pdf / 图片 解析与分段
│   │   │   ├── ocr_engine.py       #   可插拔 OCR 引擎（多后端自动降级）
│   │   │   ├── extractor.py        #   16 项必备字段结构化提取
│   │   │   └── locator.py          #   内容位置定位（页码 / 段落 / 行 / 字符偏移）
│   │   ├── rules/                  # 规则模块
│   │   │   ├── seed_rules.py       #   内置 16 条风控规则（覆盖 11 类必备场景）
│   │   │   └── engine.py           #   规则引擎（4 种匹配模式 + logic 处理器注册表）
│   │   ├── writer.py               # 回写模块：评论生成、回写执行、回写日志
│   │   ├── service.py              # 服务层：7 个工具接口的业务实现
│   │   └── pipeline.py             # 流程编排：状态流转、阻塞、重试、任务详情聚合
│   │
│   ├── api/                        # HTTP 接口层
│   │   ├── tools.py                # 7 个核心工具接口 + 全流程编排接口
│   │   └── admin.py                # 管理接口：配置 / 规则 / 日志 / 阻塞重试 / 审查结果
│   │
│   └── mock_approval/              # 模拟企业审批系统（演示对接方，可整体替换）
│       ├── data.py                 #   8 个演示审批单，覆盖 5 类阻塞场景与低/中/高风险
│       └── server.py               #   与真实审批系统一致的 4 个业务接口
│
├── sql/
│   ├── init_schema.sql             # ★ SQLite 建表脚本（8 张表，含全部字段注释）
│   └── init_schema_mysql.sql       # ★ MySQL 8.0 建表脚本（每列均带 COMMENT）
│
├── scripts/
│   ├── gen_samples.py              # 示例合同生成（docx / 损坏文件 / 空白文档 / 扫描件）
│   └── demo_closed_loop.py         # ★ 全流程闭环演示脚本（HTTP 驱动，11 个步骤）
│
├── sample_contracts/               # ★ 示例合同文件（7 个，覆盖全部演示场景）
├── static/index.html               # ★ 调用端展示页面（覆盖全流程五大模块）
├── docs/                           # ★ 交付文档
│   ├── 工具调用说明文档.md
│   └── 闭环演示操作指南.md
│
├── storage/                        # 运行期：附件本地存储目录（按审批编号分子目录）
└── data/                           # 运行期：SQLite 数据库文件与运行日志
```

---

## 四、架构与数据流

```
                    ┌──────────────────────────────┐
                    │     企业审批系统（外部）       │
                    │  待办列表 / 详情 / 附件 / 评论 │
                    └───────┬──────────────▲───────┘
              ①拉取  ②详情  ③下载          ⑦回写
                    ┌───────▼──────────────┴───────┐
                    │  fetcher → attachment        │
                    │      ↓                       │
                    │  parser（解析 + OCR）          │   ← 16 项必备字段 + 原文片段 + 位置定位
                    │      ↓                       │
                    │  rules（规则引擎）             │   ← 16 条规则 / 11 类场景
                    │      ↓                       │
                    │  writer（评论生成与回写）       │   ← 六段式标准化审查意见
                    └───────┬──────────────────────┘
                            │ 全流程由 pipeline 编排
                            ▼
                    ┌──────────────────────────────┐
                    │  SQLite / MySQL（8 张数据表）  │
                    └──────────────────────────────┘
```

### 状态机

```
任务状态：  pending ──→ parsing ──→ reviewing ──→ done
                │          │           │
                └──────────┴───────────┴──→ blocked ──(管理员重试)──→ pending（回归流程）

回写状态：  not_written ──→ writing ──→ success / failed
```

### 5 类阻塞场景

| 阻塞原因 | 触发条件 | 处置建议 |
| --- | --- | --- |
| 附件缺失 | 审批单未上传任何附件 | 通知申请人补传附件后重试 |
| 扫描件图片无法识别 | OCR 引擎全部不可用或识别结果为空 | 安装 OCR 组件 / 更换清晰扫描件后重试 |
| 文档内容为空 | 文档解析后无有效文本 | 更换有效版本合同后重试 |
| 外部接口调用失败 | 审批系统不可达 / 返回非 2xx / 业务错误码 | 确认审批系统可用后重试 |
| 文件解析异常 | 文件损坏或格式不支持 | 重新上传可正常打开的文件后重试 |

> 阻塞任务**不会产生任何猜测性结论**，始终保持阻塞态并记录具体原因，等待人工处理。

---

## 五、配置项

全部配置均支持**环境变量覆盖**，无需改动代码。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | 主服务监听地址 |
| `MOCK_HOST` / `MOCK_PORT` | `127.0.0.1` / `9100` | 模拟审批系统监听地址 |
| `APPROVAL_BASE_URL` | `http://127.0.0.1:9100` | **审批系统网关地址，生产环境改这里即可** |
| `APPROVAL_API_TIMEOUT` | `15.0` | 审批系统接口超时（秒） |
| `APPROVAL_TOKEN` | `demo-token-hetongshencha` | 审批系统访问令牌 |
| `APPROVAL_OPERATOR` | `合同智能审查机器人` | 回写评论时的操作人署名 |
| `DB_PATH` | `data/contract_review.db` | 数据库文件路径 |
| `STORAGE_DIR` | `storage/` | 附件本地存储根目录 |
| `OCR_ENGINE` | `auto` | `auto` / `tesseract` / `paddle` / `sidecar` |
| `OCR_LANG` | `chi_sim+eng` | Tesseract 识别语言 |
| `OCR_MIN_CHARS` | `10` | 识别结果少于该字数视为识别失败 |
| `OCR_SIDECAR_FALLBACK_DIR` | `sample_contracts/` | 伴随文本回落查找目录（演示用，生产置空即关闭） |
| `PREPAY_RATIO_THRESHOLD` | `0.30` | 预付款比例内控上限（logic 规则阈值） |
| `PAYMENT_PERIOD_DAYS_LIMIT` | `30` | 付款周期上限天数（logic 规则阈值） |
| `MAX_EVIDENCE_CHARS` | `300` | 单条证据原文最大长度 |
| `MAX_FOCUS_POINTS` | `20` | 审批关注点最大条数 |
| `ENABLE_MOCK_SERVER` | `true` | `run.py` 是否同进程拉起模拟审批系统 |

### 接入真实审批系统

只需修改一个环境变量，其余代码无需改动：

```powershell
$env:APPROVAL_BASE_URL = "http://真实审批系统网关:端口"
$env:APPROVAL_TOKEN    = "真实访问令牌"
.\.venv\Scripts\python run.py
```

对接所需实现的 4 个接口见 [docs/工具调用说明文档.md](docs/工具调用说明文档.md) 附录 A。

### 启用真实 OCR

```powershell
# 安装 Tesseract-OCR（勾选中文语言包 chi_sim）后：
.\.venv\Scripts\pip install pytesseract
$env:OCR_ENGINE = "tesseract"
```

未安装 OCR 组件时，`auto` 模式会自动降级到伴随文本（`<图片名>.ocr.txt`），
演示环境因此仍可完整跑通扫描件解析链路。

---

## 六、数据库

### SQLite（默认，开箱即用）

启动时自动执行 `sql/init_schema.sql` 建表并写入 16 条内置规则，无需手工操作。

### MySQL（生产可选）

```powershell
mysql -u root -p < sql/init_schema_mysql.sql
```

8 张数据表：

| 表名 | 用途 |
| --- | --- |
| `approval_tasks` | 审批任务主表（按 `approval_code` 唯一去重） |
| `approval_attachments` | 附件元数据与下载状态 |
| `contract_parses` | 解析结果（16 项字段 + 原文片段 + 位置定位 + 全文分段） |
| `review_rules` | 风控规则库 |
| `rule_hits` | 规则命中明细（证据、位置、建议） |
| `review_results` | 审查结论快照（风险等级、摘要、关注点、评论全文） |
| `comment_logs` | 评论回写日志（状态、响应、请求报文） |
| `task_logs` | 全链路运行日志 |

> 说明：`rule_hits` 保存的是任务**当前有效**的命中明细；规则审查是幂等重算，重跑时先清空该任务
> 历史命中再整体写入，历史结论由 `review_results` 快照与 `comment_logs` 完整保留，避免重复计数。

---

## 七、交付物索引

| 交付物 | 路径 |
| --- | --- |
| 可运行完整工具服务 | 本工程（`python run.py` 一键启动） |
| 数据库初始化 SQL 脚本 | [sql/init_schema.sql](sql/init_schema.sql)（SQLite）、[sql/init_schema_mysql.sql](sql/init_schema_mysql.sql)（MySQL） |
| 示例合同文件 | [sample_contracts/](sample_contracts/)（7 个，覆盖标准 / 风险 / 扫描件 / 要素缺失 / 空白 / 损坏 / 无 OCR） |
| 工具调用说明文档 | [docs/工具调用说明文档.md](docs/工具调用说明文档.md) |
| 全流程闭环演示操作指南 | [docs/闭环演示操作指南.md](docs/闭环演示操作指南.md) |
| 调用端展示页面 | [static/index.html](static/index.html) → <http://127.0.0.1:8000/> |
| 闭环演示脚本 | [scripts/demo_closed_loop.py](scripts/demo_closed_loop.py) |

---

## 八、常见问题

**Q：端口被占用怎么办？**

```powershell
$env:APP_PORT = "8100"; $env:MOCK_PORT = "9200"
$env:APPROVAL_BASE_URL = "http://127.0.0.1:9200"
.\.venv\Scripts\python run.py
```

**Q：扫描件任务一直阻塞「扫描件图片无法识别」？**
说明当前环境没有可用的 OCR 组件。三选一：安装 Tesseract-OCR + pytesseract；
安装 paddleocr；或为图片提供同名伴随文本 `<图片名>.png.ocr.txt`。

**Q：想重新演示一遍？**

```powershell
# 重置业务数据（保留规则配置）
curl -X POST http://127.0.0.1:8000/api/demo/reset
# 同时还原模拟审批系统的演示数据
curl -X POST http://127.0.0.1:9100/api/_simulate/reset
# 或直接用：python scripts\demo_closed_loop.py --reset
```

**Q：为什么某些字段显示「未识别」？**
合同原文中确实未包含该要素（如未约定验收标准）。系统按规范填占位值并记录**具体失败原因**，
绝不返回空值，该字段也会参与规则命中（如触发「验收标准缺失」规则）。

---

## 九、合规声明

1. 本系统**仅辅助人工审批**，不替代人工审核决策，全部输出内容均标注「仅供参考」。
2. 系统对无法可靠识别的材料**一律阻塞**，不做猜测性推断，不产生误导性结论。
3. 全部审查过程与结论均落库留痕（`task_logs` / `comment_logs` / `review_results`），可完整追溯。
