# 项目开发记录（PROJECT_DEV）

> 本文件记录发票处理系统的核心业务规则、技术约定与历史踩坑点。
> **修改业务逻辑前，请先阅读本文件，避免重复踩坑。**

---

## 1. 项目概述

- **名称**：SYNTEC 发票处理系统
- **用途**：批量识别、重命名、校验与合并 PDF 电子发票
- **平台**：Windows 桌面应用
- **入口**：`main.py` → `QApplication` → `InvoiceApp`

## 2. 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| UI | PySide6（Qt6） | 2026-07 从 Tkinter+sv_ttk 迁移而来 |
| PDF 文本提取 | pdfplumber ≥0.11.x | 保留空白版本用 `_extract_raw_text` |
| PDF 合并 | pypdf（**非 PyPDF2**） | PyPDF2 已停止维护，禁止使用 |
| 并发 | ThreadPoolExecutor | 固定 8 线程（见 config.MAX_WORKERS） |
| 打包 | PyInstaller | `--windowed` + `version_info.txt` |

## 3. 核心业务规则（**最重要，修改前必读**）

### 3.1 专票 / 高铁票合并双份 ⚠️

**规则**：增值税专用发票、高铁票在最终合并 PDF 中必须出现 **两份完整内容**（抵扣联 + 发票联）。

**实现位置**：[`_merge_classified_pdfs`](src/core/processor.py) 
- 专票/高铁票：每个文件 `writer.append(reader)` **两遍**
- 普通发票：`writer.append(reader)` **一遍**

**分类判定**（文件名或文本含以下关键字）：
- `专用发票` / `高铁票`（文件名）
- `专用` / `增值税专用发票`（文本）

### 3.2 税号校验

**规则**：购买方税号必须等于 `TARGET_TAX_ID`（`91320594688334374M`），不一致的文件移入「税号异常」子目录。

**实现位置**：[`_extract_buyer_tax_id`](src/core/processor.py)（静态方法）
- 在「销售方」关键字之前的文本中匹配第一个 18 位税号
- 长度固定 18 位，避免吞掉密码区数字

**子目录处理**：
- `税号异常/`：异常文件移动（原件）
- `需人工处理/`：异常文件复制（保留原件）

### 3.3 金额标准化 ⚠️

**规则**：输出文件名中的金额必须为 **两位小数**（`{:.2f}`）。

**原因**：
1. `create_amount_mapping` 正则 `^(\d+\.\d{2})` 要求两位小数
2. 避免同一发票因 `771.8` 与 `771.80` 被当成两个文件

**实现位置**：[`_generate_output_file`](src/core/processor.py) 在生成文件名前用 `_normalize_amount()` 标准化。

### 3.4 重复文件去重 ⚠️

**规则**：源目录中可能存在内容相同的重复文件（如同一发票从不同渠道下载），处理后只保留一份。

**实现位置**：[`_generate_output_file`](src/core/processor.py) 
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
src/
├── config.py          # 集中配置（业务配置从 config.ini 读取，UI 配置为常量）
├── config_manager.py  # INI 配置读写（税号、线程数外部化）
├── logger_config.py   # 日志配置（固定位置 + 轮转）
├── core/
│   └── processor.py   # 业务逻辑（不依赖 Qt）
└── ui/
    ├── app.py         # 主窗口 + Worker 线程 + 信号槽
    ├── colors.py      # 墨韵调色板
    ├── components.py  # 自定义组件（StatCard/AccentBar/LogView 等）
    └── settings_dialog.py  # 业务配置对话框（税号 + 线程数）
```

**约束**：
- 业务层（`src/core/`）禁止 import 任何 Qt 模块
- 跨线程通信必须用 Qt 信号槽（`QueuedConnection`），禁止直接操作 UI
- 日志通过 `log_callback` 回调到 UI，不直接调用 `print`
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
| 10 | 配置硬编码 | 税号写死在 config.py | `config_manager.py` 读写 INI + UI 设置入口 | 修改税号后下次处理生效 |
| 11 | 类型路由 if-elif 难扩展 | 新增类型要改核心方法 | `@register_type` 装饰器 + `_TYPE_REGISTRY` 注册表 | 新增类型只加装饰器 |

## 7. 已实施的改进（v6.2）

| # | 改进 | 实现位置 | 说明 |
|---|---|---|---|
| 1 | 停止按钮中断任务 | `app.py:_stop_processing` | 取消未开始 future + 单文件开头检查 |
| 2 | 日志持久化 | `logger_config.py` | RotatingFileHandler，1MB 轮转，5 备份 |
| 3 | PDF 异常分类 | `processor.py:_extract_raw_text` | 返回 encrypted/corrupted/empty/unknown |
| 4 | 配置外部化 | `config_manager.py` + `settings_dialog.py` | INI 读写 + UI 设置入口 |
| 5 | 日志导出 | `components.py:LogView.export_to_file` | 导出按钮 + 文件保存对话框 |
| 6 | 拖拽导入 | `app.py:dragEnterEvent/dropEvent` | 接受文件夹和 PDF 拖入 |
| 7 | 内容哈希去重 | `processor.py:_check_content_duplicate` | MD5 哈希，线程安全 |
| 8 | 类型路由注册表 | `processor.py:@register_type` | 装饰器注册，无需改 determine_processor_type |
| 9 | 集成测试 | `tests/test_integration.py` | 20 个集成测试覆盖新功能 |
| 10 | 合并性能评估 | `processor.py:_merge_classified_pdfs` | PdfWriter.append 已是推荐 API，无需优化 |

## 8. 开发检查清单

修改 `processor.py` 后请逐项确认：

- [ ] 专票/高铁票合并后是双份完整内容（非空白页）
- [ ] 普通发票合并后是单份
- [ ] 金额文件名为两位小数
- [ ] 重复源文件只输出一份
- [ ] 税号异常文件移入「税号异常」目录
- [ ] 进度从 0% 线性到 100%，无跳跃
- [ ] `pytest tests/ -q` 全部通过
- [ ] 业务层无 Qt 依赖

## 9. 测试

```bash
# 全部测试（单元 + 集成）
pytest tests/ -v

# 仅单元测试
pytest tests/test_processor.py -v

# 仅集成测试
pytest tests/test_integration.py -v

# 实测报销目录（需手动清理输出目录）
python -c "from src.core.processor import InvoiceProcessor; ..."
```

测试文件：
- `tests/test_processor.py`：核心逻辑单元测试（33 个）
- `tests/test_integration.py`：集成测试，覆盖新功能（20 个）
- `tests/test_email_pull.py`：邮箱拉取模块单元测试（9 个，不联网）

---

## 10. 邮箱自动拉取（v6.3）

### 功能
- 从邮箱（默认 QQ 邮箱 `imap.qq.com:993`）拉取发票附件到本地「发票收件箱」目录
- 过滤：发件方白名单（12306/滴滴/网约车/华住/通行费）或主题含「发票/行程单/报销」
- 附件：下载 PDF/ZIP，ZIP 自动解压只留 PDF；按 `message_id` 去重（`processed_messages.json`）
- UI：新增「拉取邮箱发票」按钮；`poll_minutes` 可配置定时轮询；收件箱目录被 `QFileSystemWatcher` 监听，新 PDF 自动触发处理
- 处理完成后源文件自动归档到 `收件箱/已处理`，避免重复处理

### 配置（config.ini `[email]` 段）
以上配置均可在程序「设置」对话框（业务配置 + 邮箱自动拉取）直接填写，含「测试连接」按钮；
保存后自动写入 config.ini 并即时生效（收件箱监听目录、轮询间隔实时更新，无需重启）。
```ini
[email]
enabled = true                 # 启用开关
imap_host = imap.qq.com
imap_port = 993
username = 你的邮箱@qq.com
auth_code = IMAP授权码          # QQ邮箱设置→账户→开启IMAP后生成，非登录密码
inbox_dir = 发票收件箱          # 相对程序目录或绝对路径
days_back = 30                 # 只拉最近 N 天
poll_minutes = 0               # 自动轮询分钟数，0 = 关闭（仅手动拉取）
```

### 实现位置
- `src/core/email_pull.py`：IMAP 拉取纯逻辑（不依赖 Qt），入口 `pull_invoices()`
- `src/config_manager.py`：`get_email_*` / `set_email_config` / `get_inbox_dir`
- `src/ui/app.py`：`_pull_invoices` / `_on_pull_done` / `_on_inbox_changed` / `_archive_inbox_files`

### 注意
- 拉取默认不修改邮件状态（`BODY.PEEK` 读取），如需标记已读用 `mark_seen`
- 授权码属敏感信息，写在 config.ini（已被 .gitignore 排除），勿提交仓库
- 发票收件箱目录内不要手动放非发票 PDF（会一并处理）

---

## 11. 发票审核（v6.3：本地规则预检 + AI 语义审核）

### 功能
处理完成后（post_process 之后）执行**双层审核**，结果只写日志提示（warning），**不阻断处理流程**。**审核重点是金额错误，行程只做简易核对（避免填错），不做复杂的时间/城市推理**：
- **第一层 · 本地规则预检**（总是执行，确定性、零成本）：同号发票金额不一致 / 疑似重复文件（文件名规则）、行程单合计 ≠ 发票价税合计、住宿税率合理性（3%/6%/9% 等）、单日交通费超 500 元差标
- **第二层 · AI 语义审核**（`[ai] enabled` 开关控制，DeepSeek）：重点查金额/票据异常（发票号、价税合计、税额、税率、行程合计一致性、金额异常高），行程仅做简单核对（日期矛盾、同日同路线重复、行程单与发票不配套）
- **审核报告回填**：本地 + AI 问题合并写入 `费用汇总.xlsx` 的「审核报告」工作表（来源/文件/类型/问题/建议）

### 配置（config.ini `[ai]` 段，也可在「设置」对话框填写）
```ini
[ai]
enabled = true
api_key = sk-xxxx            # https://platform.deepseek.com 申请
api_base = https://api.deepseek.com
model = DeepSeek-V4-Flash
timeout = 60
```

### 实现位置
- `src/core/local_audit.py`：`check_filenames` / `check_rows`（纯规则，可单测）/ `run_local_audit`
- `src/core/ai_audit.py`：`build_prompt` / `parse_findings`（宽容解析 JSON）/ `audit_records`（urllib 调用，无新增依赖）/ `write_audit_report`（回填 Excel）
- `src/core/excel_summary.py`：`_parse_didi_trip_details` 增强——行程行提取 `time / city / route / mileage`；高铁票提取发车时间；审核与汇总共用同一套解析
- `src/ui/app.py`：`_run_ai_audit`；`_process_files` 中本地预检总是执行、AI 按开关执行，结果合并写回 Excel
- `src/ui/settings_dialog.py`：AI 设置区（启用勾选 / API Key 密码框 / 接口地址 / 模型），整个对话框已包进 QScrollArea
- `src/ui/components.py`：`ToggleSwitch` 滑动开关（自绘轨道+滑块+动画）；主窗口操作栏「AI 审核」开关点击即时写入 config.ini

### 注意
- API Key / 邮箱授权码属敏感信息，写入 config.ini（不入库），UI 用密码框显示
- 审核数据来自 `excel_summary._parse_invoice`，含每文件行明细（日期/时间/城市/路线/类别/金额/税额）
- 网络调用在 worker 线程执行，失败仅告警不影响处理结果


