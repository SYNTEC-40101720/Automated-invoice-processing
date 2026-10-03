# 项目维护说明（PROJECT_DEV）

> 本文件记录发票处理系统的核心业务规则、技术约定与历史踩坑点。
> 当前交付基线：v7.3.4。
> **修改业务逻辑前，请先阅读本文件，避免重复踩坑。**

---

## 1. 项目概述

- **名称**：SYNTEC 发票处理系统
- **用途**：批量识别、重命名、校验与合并 PDF 电子发票
- **平台**：Windows 桌面应用
- **入口**：`main.py` → 本地 FastAPI/Uvicorn → pywebview/WebView2

## 2. 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 桌面 UI | pywebview + Edge WebView2 | 本地 FastAPI 服务承载 React 工作台 |
| Web UI | React 19 + TypeScript + Vite | 处理概览、收件箱、审核、设置 |
| API | FastAPI + Uvicorn | HTTP、WebSocket、本地静态资源 |
| 任务状态 | EventBus + ThreadPoolExecutor | 关键事件不丢失，进度事件可合并 |
| PDF 文本提取 | pdfplumber ≥0.11.x | 保留空白版本用 `_extract_raw_text` |
| PDF 合并 | pypdf（**非 PyPDF2**） | PyPDF2 已停止维护，禁止使用 |
| 并发 | ThreadPoolExecutor | 固定 8 线程（见 config.MAX_WORKERS） |
| 打包 | PyInstaller | `build_syntec.py`，`--onedir --windowed --noupx` |

## 3. 核心业务规则（**最重要，修改前必读**）

### 3.1 专票 / 高铁票合并双份 ⚠️

**规则**：增值税专用发票、高铁票在最终合并 PDF 中必须出现 **两份完整内容**（抵扣联 + 发票联）。

**实现位置**：[`_merge_classified_pdfs`](backend/invoice_processor/core/processor.py)
- 专票/高铁票：每个文件 `writer.append(reader)` **两遍**
- 普通发票：`writer.append(reader)` **一遍**

**分类判定**（文件名或文本含以下关键字）：
- `专用发票` / `高铁票`（文件名）
- `专用` / `增值税专用发票`（文本）

### 3.2 税号校验

**规则**：仅对发票校验购买方税号，且必须等于 `TARGET_TAX_ID`（`91320594688334374M`）；行程单、高铁票等非发票凭证不执行税号检查。不一致的发票移入「税号异常」子目录。

**实现位置**：[`_extract_buyer_tax_id`](backend/invoice_processor/core/processor.py)（静态方法）
- 在「销售方」关键字之前的文本中匹配第一个 18 位税号
- 长度固定 18 位，避免吞掉密码区数字
- 输出文件名含 `行程单` 或 `高铁票` 时跳过税号检查

**子目录处理**：
- `税号异常/`：异常文件移动（原件）
- `需人工处理/`：异常文件复制（保留原件）

### 3.3 金额标准化 ⚠️

**规则**：输出文件名中的金额必须为 **两位小数**（`{:.2f}`）。

**原因**：
1. `create_amount_mapping` 正则 `^(\d+\.\d{2})` 要求两位小数
2. 避免同一发票因 `771.8` 与 `771.80` 被当成两个文件

**实现位置**：[`_generate_output_file`](backend/invoice_processor/core/processor.py) 在生成文件名前用 `_normalize_amount()` 标准化。

### 3.4 重复文件去重 ⚠️

**规则**：源目录中可能存在内容相同的重复文件（如同一发票从不同渠道下载），处理后只保留一份。

**实现位置**：[`_generate_output_file`](backend/invoice_processor/core/processor.py)
- 用 `self._generated_names: set[str]` 记录已生成的文件名
- 用 `self._dedup_lock` 保证线程安全
- 目标文件名已存在时跳过，记录 warning 日志

### 3.5 发票类型路由

通过 `determine_processor_type(text)` 路由到对应处理器：

| 类型关键字 | 处理器 | 输出后缀 |
|---|---|---|
| 浙江通用（电子）发票 / 宁波通用 | `process_zhejiang_invoice` | `.pdf` |
| 江苏通行费行程单 | `process_jiangsu_invoice` | `行程单.pdf` |
| 滴滴行程单 | `process_didi_trip` | `行程单.pdf` |
| 收费公路汇总单 | `process_toll_summary` | `行程单.pdf` |
| 高铁票 | `process_train_ticket` | `高铁票.pdf` |
| 通用电子发票 | `process_general_invoice` | `.pdf` |

## 4. 进度报告约定

`post_process(progress_callback)` 支持细粒度进度回调：

| 阶段 | 进度区间 | 更新方式 |
|---|---|---|
| PDF 处理（worker 线程） | 0% → 70% | 按文件数线性 |
| 金额映射 | 70% → 71.5% | 单次 |
| 待搜索替换 | 71.5% → 73% | 单次 |
| 税号检查+分类 | 73% → 91% | 按文件数线性 |
| 人工处理扫描 | 91% → 92.5% | 单次 |
| PDF 合并 | 92.5% → 100% | 按文件数线性 |

**禁止**：用定时器假装推进进度。所有进度必须来自真实执行步骤。

## 5. 架构分层

```
backend/
├── devbase/            # 通用 JobRuntime、ToolRegistry、EventBus、API 安全层和桌面壳
└── invoice_processor/  # 发票业务包
	├── domain/         # Job、状态机和错误码
	├── application/    # JobService、文件服务、审核和任务适配（EventBus 在 devbase 侧）
	├── api/            # FastAPI 路由、token、静态资源和 WebSocket
	├── desktop/        # 发票桌面扩展和 NativeBridge
	└── core/           # 发票处理业务，不依赖 Web
web/
└── web/src/            # React 工作台和前端状态管理
```

**约束**：
- 业务层（`backend/invoice_processor/core/`）禁止 import 任何 Qt、FastAPI 或 React 模块
- 后台任务通过应用层事件总线发布事件，API 不直接操作 worker
- WebSocket 连接必须校验本地 token，HTTP API 使用 `X-Local-Token`
- 桌面服务只监听 `127.0.0.1`，退出时必须调用 `JobService.shutdown()`，并等待当前任务到达终态（上限 30s，`launcher._wait_job_terminal`），防止 post_process 的 Excel 写入被硬杀留截断文件
- 业务配置（税号、线程数）通过 `config_manager` 读写 INI，运行时用 `_cfg.TARGET_TAX_ID` 动态访问

## 6. 历史踩坑点 ⚠️

| # | 问题 | 根因 | 修复 | 检查点 |
|---|---|---|---|---|
| 1 | 合并 PDF 第二页空白 | 原作者把「双份 append」当 bug 改成 `add_blank_page` | 改回 append 两遍 | 合并后无空白页 |
| 2 | 同一发票被处理两次 | 金额格式不统一（771.8 vs 771.80） | 金额标准化 `{:.2f}` + 去重 | 输出无重名 |
| 3 | 进度卡在 90% 跳 100% | 后处理无进度回调，定时器爬升太慢 | `post_process` 加 `progress_callback` 按子步骤报告 | 进度全程线性 |
| 4 | PyPDF2 停止维护 | - | 迁移到 pypdf，API 兼容 | 禁用 PyPDF2 |
| 5 | 金额映射漏文件 | 正则要求 `\d{2}` 但金额是一位小数 | 金额标准化保证两位小数 | mapping 完整 |
| 6 | 日志丢失 + 路径漂移 | WARNING 级别 + 相对路径随 os.chdir 漂移 | `logger_config.py` 固定路径 + 轮转 + INFO 级别 | `logs/invoice.log` 有记录 |
| 7 | 停止按钮无效 | 只设标志位，已提交任务继续执行 | 取消未开始 future + 单文件开头检查 `is_processing` | 停止后无新文件处理 |
| 8 | PDF 异常不分类 | 裸 `except Exception` 统一归为"解析失败" | `_extract_raw_text` 返回 `(text, error_type)` | 日志显示加密/损坏/扫描件 |
| 9 | 内容相同不同名文件被重复处理 | 仅按文件名去重 | 新增 `_check_content_duplicate` 基于 MD5 哈希 | 内容重复有日志 |
| 10 | 配置硬编码 | 税号写死在 config.py | `config_manager.py` 读写 INI + Web 设置视图 | 修改税号后下次处理生效 |
| 11 | 类型路由 if-elif 难扩展 | 新增类型要改核心方法 | `@register_type` 装饰器 + `_TYPE_REGISTRY` 注册表 | 新增类型只加装饰器 |

## 7. 当前能力（v7.3.4）

| # | 改进 | 实现位置 | 说明 |
|---|---|---|---|
| 1 | 停止按钮中断任务 | `backend/invoice_processor/application/job_service.py` | 设置取消事件并让正在运行的任务收敛 |
| 2 | 日志持久化 | `logger_config.py` | RotatingFileHandler，1MB 轮转，5 备份 |
| 3 | PDF 异常分类 | `backend/invoice_processor/core/pdf_text.py` | 返回 encrypted/corrupted/empty/unknown |
| 4 | 配置外部化 | `config_manager.py` + API/Web 设置视图 | INI 读写和敏感值脱敏 |
| 5 | 日志导出 | `backend/invoice_processor/desktop/native_bridge.py` + Web 工作台 | 原生保存对话框和日志导出 |
| 6 | 目录选择与处理 | `backend/invoice_processor/desktop/native_bridge.py` + Web 处理视图 | 通过桌面桥接选择目录并启动任务 |
| 7 | 内容哈希去重 | `processor.py:_check_content_duplicate` | MD5 哈希，线程安全 |
| 8 | 类型路由注册表 | `processor.py:@register_type` | 装饰器注册，无需改 determine_processor_type |
| 9 | 集成测试 | `tests/test_integration.py` | 20 个集成测试覆盖新功能 |
| 10 | 合并性能评估 | `processor.py:_merge_classified_pdfs` | PdfWriter.append 已是推荐 API，无需优化 |
| 11 | 更新检查 | `update_checker.py` | 查询 GitHub Release 并提示新版本，跳转 Release 页面手动下载 |

### 更新检查发布约定

- 应用仅查询 GitHub Releases API 检测新版本，在横幅和设置页提示并提供 Release 页面链接；**不提供程序内下载或安装**，用户手动下载 ZIP 并替换安装目录。
- `scripts/build_syntec.py` 在主程序构建、合规验证通过后生成 `dist/SYNTEC-Invoice-Processor-v{version}.zip`；Release 资产名使用 ASCII，避免 GitHub 自动重命名中文文件名。
- ZIP 必须保留顶层 `SYNTEC-电子票据处理系统/` 目录，并包含主程序和完整 `_internal/`。
- 应用只接受目标 GitHub 仓库中版本更高的 Release；Release 标签必须为 `vX.Y.Z` 格式。
- 替换安装目录时保留 `config.ini`、`logs/` 和 `发票收件箱/`（它们不打进 ZIP）。

## 8. 维护回归清单

修改 `processor.py` 后请逐项确认：

- [ ] 专票/高铁票合并后是双份完整内容（非空白页）
- [ ] 普通发票合并后是单份
- [ ] 金额文件名为两位小数
- [ ] 重复源文件只输出一份
- [ ] 税号异常文件移入「税号异常」目录
- [ ] 进度从 0% 线性到 100%，无跳跃
- [ ] `python -m pytest tests/ -q` 全部通过
- [ ] 业务层无 Qt 依赖

## 9. 测试与打包

```bash
# 全部 Python 测试
python -m pytest tests/ -q

# Python 静态检查
python -m ruff check backend tests

# 前端类型检查和生产构建
npm --prefix web run typecheck
npm --prefix web run build

# 前端单测（Vitest）
npm --prefix web run test

# 生成并验证桌面发布包
python scripts/build_syntec.py

# 发布包启动冒烟（仅交互式 Windows 桌面会话）
python scripts/smoke_launch.py --target exe

```

截至 v7.3.4，本机 Windows 环境已验证：217 条 Python 测试通过（含任务历史 10 条、单实例 3 条、历史路由契约 2 条、WS 心跳/断链回收 2 条、`/jobs/current` 响应模型 1 条、邮件拉取批次隔离与 ZIP 容错、配置健壮性 9 条、提取正则 17 条、审核报告防注入 6 条、关窗等待 3 条），Ruff、前端 typecheck/build、Vitest（17 条：store 层 8 + 事件游标 9）和 SYNTEC PyInstaller 域控合规检查通过；发布包启动冒烟（`scripts/smoke_launch.py`）通过，更新检测由 `test_update_checker.py` 单测覆盖。目标机验收（真实浏览器 WebSocket 断线恢复、干净 Windows/域控账户）按 `docs/RELEASE_SOP.md` 在目标环境执行（全自动判定，无人工观察项）。

测试文件：
- `tests/test_processor.py`：核心逻辑单元测试
- `tests/application/`：任务服务、事件总线和文件服务测试
- `tests/api/`：HTTP、WebSocket、设置脱敏和静态资源契约测试
- `tests/test_integration.py`：核心处理集成测试
- `web/tests/`：前端 store 层 Vitest 单测

---

## 10. 手动邮箱收件（v6.3）

### 功能
- 从邮箱（默认 QQ 邮箱 `imap.qq.com:993`）拉取发票附件到本地「发票收件箱」目录
- **批次隔离**：每次拉取自动创建独立批次子目录 `拉取_YYYYMMDD_HHMMSS`，本次附件全部保存在该目录，多次拉取互不混放；无新附件时不留空目录。`session_dir` 随拉取结果返回，收件页展示本次批次目录
- 过滤：发件方白名单（12306/滴滴/网约车/华住/通行费）或主题含「发票/行程单/报销」
- 附件：下载 PDF/ZIP，ZIP 自动解压只留 PDF（成员名清洗 Windows 非法字符；加密/损坏成员跳过并在结果 errors 上报，邮件不写入去重记录、下次拉取重试）；按 `message_id` 去重（`processed_messages.json` 在收件根目录，跨批次生效）
- Web 工作台：收件箱页面可独立指定并显示收件目录，提供手动拉取邮箱附件；当前不启动后台自动轮询，也不会在拉取后自动创建处理任务
- 通过 `inbox`/`email` trigger 启动的处理任务完成后归档源 PDF；当前手动拉取邮箱只保存附件，不会自动启动任务

### 配置（config.ini `[email]` 段）
邮箱连接参数可在 Web 工作台「设置」视图填写，含「测试连接」按钮；收件目录在「收件箱」视图设置并显示。邮箱附件仅在用户手动拉取时下载；处理工作区的源文件目录仍由处理页单独选择，不会被收件箱目录替换。
```ini
[email]
imap_host = imap.qq.com
imap_port = 993
username = 你的邮箱@qq.com
auth_code = IMAP授权码          # QQ邮箱设置→账户→开启IMAP后生成，非登录密码
inbox_dir = 发票收件箱          # 相对程序目录或绝对路径
days_back = 30                 # 只拉最近 N 天
```

### 实现位置
- `backend/invoice_processor/core/email_pull.py`：IMAP 拉取纯逻辑（不依赖 Qt），入口 `pull_invoices()`
- `backend/invoice_processor/config_manager.py`：`get_email_*` / `set_email_config` / `get_inbox_dir`
- v7 API：`backend/invoice_processor/api/routes/email.py`；Web：`web/src/features/InboxView.tsx`

### 注意
- 拉取默认不修改邮件状态（`BODY.PEEK` 读取），如需标记已读用 `mark_seen`
- 授权码属敏感信息，写在 config.ini（已被 .gitignore 排除），勿提交仓库
- 发票收件箱目录内不要手动放非发票 PDF（会一并处理）；处理某次拉取的发票时，在处理页选择对应 `拉取_*` 批次目录作为源目录

---

## 11. 发票审核（v6.3：本地规则预检 + AI 语义审核）

### 功能
处理完成后（post_process 之后）执行**双层审核**，结果只写日志提示（warning），**不阻断处理流程**。**审核重点是金额错误，行程只做简易核对（避免填错），不做复杂的时间/城市推理**：
- **第一层 · 本地规则预检**（总是执行，确定性、零成本）：同号发票金额不一致 / 疑似重复文件（文件名规则）、行程单合计 ≠ 发票价税合计、住宿税率合理性（3%/6%/9% 等）、打车单程超 100 元差标（仅滴滴行程单逐笔行程，不做单日累计）、高铁一等座/商务座超差标
- **第二层 · AI 语义审核**（`[ai] enabled` 开关控制，DeepSeek）：重点查金额/票据异常（发票号、价税合计、税额、税率、行程合计一致性、金额异常高），行程仅做简单核对（日期矛盾、同日同路线重复、行程单与发票不配套）
- **审核报告回填**：本地 + AI 问题合并写入 `费用汇总.xlsx` 的「审核报告」工作表（来源/文件/类型/问题/建议）；写入前对单元格值做公式注入防护（`= + - @` 开头加 `'` 前缀转文本）

### 配置（config.ini `[ai]` 段，也可在 Web「设置」视图填写）
```ini
[ai]
enabled = true
api_key = sk-xxxx            # https://platform.deepseek.com 申请
api_base = https://api.deepseek.com
model = deepseek-v4-flash
timeout = 60
```

### 实现位置
- `backend/invoice_processor/core/local_audit.py`：`check_filenames` / `check_rows`（纯规则，可单测）/ `run_local_audit`
- `backend/invoice_processor/core/ai_audit.py`：`build_prompt` / `parse_findings`（宽容解析 JSON）/ `audit_records`（urllib 调用，无新增依赖）/ `write_audit_report`（回填 Excel）
- `backend/invoice_processor/core/excel_summary.py`：`_parse_didi_trip_details` 增强——行程行提取 `time / city / route / mileage`；高铁票提取发车时间；审核与汇总共用同一套解析
- v7 API：`backend/invoice_processor/api/routes/settings.py`；Web：`web/src/features/AuditView.tsx` / `web/src/features/SettingsView.tsx`

### 注意
- API Key / 邮箱授权码属敏感信息，写入 config.ini（不入库），UI 用密码框显示
- 审核数据来自 `excel_summary._parse_invoice`，含每文件行明细（日期/时间/城市/路线/类别/金额/税额）
- 网络调用在 worker 线程执行，失败仅告警不影响处理结果
- **遗留（有意不修）**：AI 审核系统提示词可能被 PDF 文本操纵（提示注入）——影响仅限产生提示性 findings，不阻断流程、不外传数据；彻底修复需重构提示词结构。真实税控 PDF 语料（千分位等版式）的提取正则未验证，目前只用合成文本测过。


