# 发布验收清单（ACCEPTANCE_CHECKLIST）

> **目标**：把散落在 ARCHITECTURE / RELEASE_UPDATE_SOP / PROJECT_DEV 中的目标环境验收要求收敛为一份可执行、可留痕的清单。
> **适用版本**：v7.3.0 及之后的发布（v7.2.x 及更早版本可用降级模式部分执行）。
> **执行角色**：打包发布负责人（本机）+ 目标机验收人（域控账户）。
> **留痕要求**：每章执行后在 §9 记录表填写一行；发布类验收（§1/§3）结果回填到 [RELEASE_UPDATE_SOP.md](RELEASE_UPDATE_SOP.md) §8 发布记录模板。

---

## 1. 静态与自动化验收（发布前，本机）

| # | 项目 | 命令 / 判定 | 结果 |
|---|---|---|---|
| 1.1 | 五版本源一致 | `python scripts/build_syntec.py`（内含版本一致性校验） | ☐ |
| 1.2 | Python 测试 | `python -m pytest tests/ -q` 全绿（当前基线 165 条，以实测为准） | ☐ |
| 1.3 | Python 静态检查 | `python -m ruff check backend tests scripts` 零告警 | ☐ |
| 1.4 | 前端类型检查 | `npm --prefix web run typecheck` 零错误 | ☐ |
| 1.5 | 前端单测 | `npm --prefix web run test` 全绿（当前基线 8 条） | ☐ |
| 1.6 | 前端生产构建 | `npm --prefix web run build` 通过 | ☐ |
| 1.7 | CI 绿 | GitHub Actions Python + 前端两条 workflow 全绿 | ☐ |
| 1.8 | Release 资产核对 | `dist/SYNTEC-Invoice-Processor-vX.Y.Z.zip` 存在，`.sha256` 摘要与本地计算一致 | ☐ |

## 2. 目标机前置检查（安装前）

| # | 项目 | 判定 | 结果 |
|---|---|---|---|
| 2.1 | Windows 版本 | Windows 10/11（域控加入 SYNTEC 域） | ☐ |
| 2.2 | WebView2 Runtime | 注册表 `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}\pv` 存在且 ≥ 100.x | ☐ |
| 2.3 | 域控账户权限 | 当前账户可执行 EXE、可写安装目录与收件箱目录 | ☐ |
| 2.4 | 安装路径 | 纯英文、无空格路径（域控打包与运行合规要求） | ☐ |
| 2.5 | 无依赖前提 | 目标机**不需要** Node.js / Python / 浏览器（onedir 自带运行时 + 系统 WebView2） | ☐ |

## 3. 发布包启动冒烟（打包后，本机或目标机）

使用 [scripts/smoke_launch.py](../scripts/smoke_launch.py)：

```bash
# 完整模式：优先 dist EXE，自选端口 + 注入令牌
python scripts/smoke_launch.py --target exe

# 源码模式（无打包产物时）
python scripts/smoke_launch.py --target source

# 旧产物降级探活（v7.2.1 及更早不认识 PLATFORM_LOCAL_TOKEN，收到 401 即判定存活）
python scripts/smoke_launch.py --legacy-alive-only --target exe
```

| # | 项目 | 判定 | 结果 |
|---|---|---|---|
| 3.1 | health 就绪 | `status=ok` 且 `version` 与 `backend/invoice_processor/version.py` 一致 | ☐ |
| 3.2 | 日志生成 | EXE 同级 `logs/invoice.log` 生成，无 `CRITICAL` | ☐ |
| 3.3 | 干净退出 | WM_CLOSE 关窗后进程收敛、端口释放（脚本自动断言） | ☐ |
| 3.4 | CI 不跑冒烟 | 冒烟仅限交互式 Windows 桌面会话，不进 GitHub Actions | ☐ |

## 4. 桌面功能冒烟（目标机，人工 6 项）

| # | 场景 | 判定 | 结果 |
|---|---|---|---|
| 4.1 | 启动 | 双击 EXE 进入桌面窗口，无控制台、无外部浏览器 | ☐ |
| 4.2 | WebView2 渲染 | 工作台各视图（处理/收件箱/审核/设置）正常渲染，无白屏 | ☐ |
| 4.3 | DPI 缩放 | 125% / 150% / 175% @ 1024×700 最小窗口不溢出、按钮可点 | ☐ |
| 4.4 | 中文脱敏样本 | 用脱敏中文 PDF 样本跑一次完整处理，输出与命名正常 | ☐ |
| 4.5 | 输出打开 | 「打开输出目录」调起资源管理器并定位到正确目录 | ☐ |
| 4.6 | 退出回收 | 关窗后无残留进程（任务管理器核对），`logs/` 正常落盘 | ☐ |

## 5. 业务规则不可回归（12 条，自动化覆盖为准）

发布前 `pytest tests/ -q` 全绿即视为通过；目标机抽检可对照下列测试文件：

| # | 规则 | 主要测试 |
|---|---|---|
| 5.1 | 专票/高铁票双份、普票一份 | `tests/test_processor.py`、`tests/test_integration.py` |
| 5.2 | 金额固定两位小数 | `tests/test_processor.py` |
| 5.3 | 文件名+内容哈希双去重线程安全 | `tests/test_processor.py`、`tests/test_integration.py` |
| 5.4 | 税号异常文件移动/复制路径正确 | `tests/test_processor.py` |
| 5.5 | PDF 错误四分类（加密/损坏/无文本/未知） | `tests/test_processor.py` |
| 5.6 | 进度真实单调到 100% | `tests/application/test_job_service.py` |
| 5.7 | 停止后取消未开始任务 | `tests/application/test_job_service.py` |
| 5.8 | 本地审核必执行、AI 审核失败不阻断 | `tests/test_local_audit.py`、`tests/test_ai_audit.py` |
| 5.9 | 邮件 BODY.PEEK + 附件/Message-ID 去重 | `tests/test_email_pull.py` |
| 5.10 | 仅邮箱来源触发归档，手动不归档 | `tests/application/test_job_service.py` |
| 5.11 | DPAPI 密钥存储、日志无明文 | `tests/test_secret_store.py`、`tests/api/test_api_contract.py` |
| 5.12 | 业务核心零 UI 依赖 | `tests/test_processor.py`（导入边界断言） |

## 6. 手工 E2E 场景（目标机，人工 5 场景）

> 可由 `scripts/acceptance_driver.py --only 6` 脚本驱动（真实 EXE + 真实 WebSocket 客户端）；
> 人工执行时按下列步骤。

| # | 场景 | 步骤要点 | 结果 |
|---|---|---|---|
| 6.1 | 选择到完成 | 选目录 → 预扫描 PDF 数 → 开始 → 进度/日志实时 → 完成提示 → 打开输出 | ☐ |
| 6.2 | 运行中停止 | 处理进行中点停止 → 任务收敛为已取消 → 可再次开始新任务 | ☐ |
| 6.3 | 断线恢复 A | 任务运行中在 WebView 内按 F5 整页重载 → 自动重连 → 游标续传、快照校准、无重复事件 | ☐ |
| 6.4 | 断线恢复 B | 第二个客户端（另一浏览器标签/窗口连同一端口）关闭 → 主客户端不受影响 | ☐ |
| 6.5 | 设置修改与日志导出 | 修改税号/线程数即时保存 → 日志面板导出日志文件 | ☐ |

## 7. 旧版升级验收（有旧安装时）

> v7.3.0 起程序内无自动更新链路（`405d8fd` 移除）——升级 = 检测提示 + Release 页手动下载。
> 因此本章只验收**软件行为**（7.1/7.2 检测与版本），覆盖替换是部署操作指引而非测试项。
> 可由 `scripts/acceptance_driver.py --only 7` 脚本驱动。

| # | 项目 | 判定 | 结果 |
|---|---|---|---|
| 7.1 | 更新检测 | 旧版本点「检查更新」能发现新版并提示前往 Release 页（见 [RELEASE_UPDATE_SOP.md](RELEASE_UPDATE_SOP.md) §6 验收矩阵）；当前版不误报 | ☐ |
| 7.2 | 版本核对 | 升级后 health 返回新版本号（`GET /api/v1/system/health`） | ☐ |

**部署操作指引（非测试项）**：旧版安装目录用新 ZIP 解压替换，保留 `config.ini`、
`logs/`、`发票收件箱/`；替换后设置页税号/线程数/邮箱配置应与升级前一致
（不一致时按 RELEASE_UPDATE_SOP.md §7 故障处理恢复）。

## 8. 明确不测项（当前版本边界）

以下事项**不在**当前验收范围（详见 [ARCHITECTURE.md](ARCHITECTURE.md) §12 边界声明）：

- 单实例锁（多实例互斥）；
- 目录监听（watch）自动处理；
- Playwright 自动化 E2E 套件；
- 跨磁盘安装目录的复制式替换。

## 9. 验收留痕记录表

每次发布/验收执行后填写：

| 章节 | 执行人 | 日期 | 结果 | 备注 |
|---|---|---|---|---|
| §1 静态与自动化 | 40101720 | 2026-09-29 | ☑通过 | pytest 144 / ruff 零告警 / tsc / Vitest 8 / build / CI 绿；ZIP SHA-256 47aa1759... 与 .sha256 一致 |
| §2 目标机前置 | 40101720 | 2026-09-29 | ☑通过 | 本机即域控目标机（SYNTEC.COM 域，Windows 11 build 26200）；WebView2 154.0.4258.37；账户可写、路径纯英文；`scripts/acceptance_driver.py --only 2` |
| §3 启动冒烟 | 40101720 | 2026-09-29 | ☑通过 | v7.3.0 EXE 完整模式（health 7.3.0、日志无 CRITICAL、干净退出、端口释放）；源码模式通过；v7.2.1 旧产物 --legacy-alive-only 探活通过 |
| §4 桌面功能 | 40101720 | 2026-09-29 | ☑通过 | 自动 4 项 + 人工 2 项全通过：窗口句柄/中文样本 10 份（9 成功，1 扫描件按规则归集需人工处理）/Explorer 打开/退出回收；渲染无白屏与 DPI 缩放由 40101720 人工确认通过（2026-09-29） |
| §5 业务规则 | 40101720 | 2026-09-29 | ☑通过 | pytest 144 条全绿即视为通过（12 条规则对应测试见 §5 表） |
| §6 手工 E2E | 40101720 | 2026-09-29 | ☑通过 | 5 场景脚本驱动真机 EXE + 真实 WS 客户端通过：实时事件（progress/log 各 19 条）、进度单调 1.0、取消收敛、断线重连快照校准、双客户端隔离、设置 8→4 保存还原、日志分页不重不漏 |
| §6 手工 E2E（v7.3.1 融合二期复跑） | 40101720 | 2026-09-30 | ☑通过 | 7 项全过（含新增游标重放断言）：实时事件 28 条（progress 3/log 11）、进度单调 1.0、取消收敛（轮询 running 后 cancel 200→cancelled）、断线重连带游标补齐 88 条且编号连续、无游标重连不重放、双客户端隔离、设置 8→4 保存还原、日志分页不重不漏；样本为程序生成占位 PDF（3 份） |
| §7 升级验收 | 40101720 | 2026-09-29 | ☑通过 | 软件行为两项通过：v7.2.1 视角检测发现 7.3.0 + 当前版不误报（自动化）；GUI「检查更新」横幅人工确认通过。覆盖替换演练（部署指引）同步验证：config.ini/logs/收件箱保留、health 7.3.0 |

### 人工观察项留痕

| 项目 | 执行人 | 日期 | 结果 | 备注 |
|---|---|---|---|---|
| §4.2 渲染无白屏 | 40101720 | 2026-09-29 | ☑通过 | 切换 处理/收件箱/审核/设置 各视图确认无白屏 |
| §4.3 DPI 缩放 | 40101720 | 2026-09-29 | ☑通过 | 125%/150%/175% 下最小窗口（1024×700）不溢出、按钮可点 |
| §7 GUI 检查更新 | 40101720 | 2026-09-29 | ☑通过 | 设置页点「检查更新」，当前版本提示已是最新（7.3.0 = Release 最新，横幅不出现为正确行为） |

自动化执行说明：`scripts/acceptance_driver.py` 驱动（产物 `acceptance_report.json`，本地留痕），
2026-09-29 全量执行 21 项自动判定全通过；3 个人工观察项同日由 40101720 确认通过。
`python scripts/smoke_launch.py --target exe --hold 120` 可随时重新拉起窗口复检。
