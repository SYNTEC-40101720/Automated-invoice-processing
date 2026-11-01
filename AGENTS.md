# Automated-invoice-processing-main（工作约定）

> 2026-10-18 由 DSH 会话创建；2026-11-01 重写为「软件 / 配套技能」两层结构。

## 两层职责（软件 vs 配套技能）

| 层 | 仓库 / 位置 | 内容 |
|---|---|---|
| **软件（本仓库）** | `SYNTEC-40101720/Automated-invoice-processing` | 发票处理引擎本体：`backend/invoice_processor/`（流水线、邮箱拉取、私车公用、台账）、`web/`（React 工作台）、打包与发布脚本。所有业务口径（识别规则、1.5 元/公里补贴、三条联动）的唯一真源在这里。 |
| **配套技能** | `SYNTEC-40101720/agent-skills` 的 `skills/invoice-processing/` | DSH 会话直调配方：不开桌面软件，进程内跑流水线/邮箱拉取/私车公用/设置读写。技能只提供调用配方，**不复制业务逻辑**。 |

- **改口径去本仓库改代码**；引擎契约变化（`run_job_sync` 签名、触发枚举、配置键）后需同步复核技能文档。
- 技能安装目标是 `~/.agents/skills/invoice-processing/`，由 `agent-skills` 仓库 `scripts/install_skills.py` 镜像，不要手改安装目标（DSH 会热加载，无需重启）。

## 架构与入口

- `run_job_sync` 是唯一生产入口（`backend/invoice_processor/application/job_service.py`）；legacy `start_job` 已移除。
- 触发枚举仅 `manual | inbox | email`（`domain/job.py` JobTrigger）。
- 技能直调驱动脚本必须放本仓库根运行：`config.ini` 按 `sys.argv[0]` 所在目录定位（`config_manager.py` `_get_program_dir()`），脚本放别处会读到空模板配置。
- `logs/job_history.jsonl` 与 `logs/duplicate_index.json` 永远在项目根 `logs/`，与脚本位置无关。

## 历史记忆

- 旧 Claude Code 项目记忆（12 个记忆文件）已随 2026-10-31 Claude Code 卸载归档：`D:\DSH\claude-archive\projects-full\D--FN-Automated-invoice-processing-main\memory\`；回顾历史结论读归档，不再有活目录。
- 项目特有结论沉淀到本文件；跨项目通用经验进 `~/.dsh/AGENTS.md`；客户现场结论走 notes-keeper 归档进笔记库，不要两处重复。
