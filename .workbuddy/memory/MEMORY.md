# 项目长期记忆 - Automated-invoice-processing

## Git 仓库
- **远程**: github.com:SYNTEC-40101720/Automated-invoice-processing.git (main 分支)
- **协议**: origin 已切换为 SSH（git@github.com:...），因 HTTPS 在本机网络环境不稳定；SSH 认证用户 SYNTEC-40101720，密钥 ~/.ssh/id_ed25519
- **历史特点**: 本地曾为全新 git init（无共同祖先），2026-08-05 已整合——本地改动作为 commit 70076f7 叠加在远程 15 个历史 commit 之上

## 整合约定（2026-08-05 确立）
- 推送前务必确认 tests/data/ 下的运行产物（发票 PDF、行程单、合并结果、费用汇总 Excel）不被提交——含真实发票号/金额，敏感数据
- 本地 backup 分支 backup-local-20260805-053021 保留原始 init commit 及产物备份

## 运行环境与排查要点（2026-08-05 补充）
- **运行环境**: 用系统 Python 3.11.9（`C:\Users\40101720\AppData\Local\Programs\Python\Python311\python.exe`），依赖已装齐（PySide6 6.11.0 / pdfplumber 0.10.4 / pypdf 6.12.1 / openpyxl 3.1.5）。托管版 3.13.12 干净无依赖，勿用。
- **启动命令**: `python main.py`（PySide6 GUI，前台会阻塞，排查时后台启动）。
- **测试合成数据（内嵌 base64，2026-08-05 定稿）**: 原 `tests/data/output_test/<日期>/` 真实发票夹具已废弃。`TestRunLocalAuditIntegration` 的合成发票 PDF 已**一次性生成、以 base64 固化在 `tests/test_local_audit.py` 内**（`_SYNTH_TRIP_PDF_B64` / `_SYNTH_INV_PDF_B64`），运行时仅 `base64.b64decode` 写入 `tmp_path`，**不再依赖 reportlab 现生成、不入库、无真实数据**。`requirements-test.txt` 运行时依赖仅 `pytest`（reportlab 仅重新生成内嵌 PDF 时可选）。`tests/data/output_test` 残留目录（沙箱回收站不可用无法删除）内文件已 truncate 清空、无敏感数据，且已不被任何测试引用；临时生成脚本已移入 `tests/data/`（gitignore 忽略）。
- **启动零耦合测试（已验证 2026-08-05）**: `main.py` 与 `src/` 均不 import `tests`/`pytest`（仅文档与 pyproject.toml 提及 pytest）。运行程序完全不依赖测试代码或测试数据。
- **测试结果**: 全量 79 个测试通过（78 单元测试/集成 + 1 本地审核集成）。

## 项目结构要点
- 发票处理系统，PySide6 GUI，版本 6.2.0
- 核心模块: src/core/ (processor, ai_audit, email_pull, excel_summary, local_audit), src/secret_store.py
- UI: src/ui/ (app, components, settings_dialog, styles)
  - 2026-08-05：「墨韵」QSS 样式表集中在 `src/ui/styles.py`，`app.py` 与 `settings_dialog.py` 共用，保证主窗口和设置对话框风格一致。
- 输出目录"发票输出/"已在 .gitignore；"发票收件箱/"为本地数据目录（未跟踪）
