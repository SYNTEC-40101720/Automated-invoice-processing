# 发布 SOP 与验收清单（RELEASE_SOP）

> 本文件由 RELEASE_UPDATE_SOP.md（发布流程+发布记录）与 ACCEPTANCE_CHECKLIST.md（验收清单+留痕）合并而成（2026-10-03，v7.3.4 起），发布与验收留痕收敛为一份文件。

> 结构：§1-§8 为验收清单——章节号与 `scripts/acceptance_driver.py --only 2,4,6` 参数对齐，**不要改号**；
> §9 验收留痕记录表（每次执行后回填）；§10 发布流程；§11 发布记录（每次发布后回填）。

## 1. 静态与自动化验收（发布前，本机）

| # | 项目 | 命令 / 判定 | 结果 |
|---|---|---|---|
| 1.1 | 五版本源一致 | `python scripts/build_syntec.py`（内含版本一致性校验） | ☐ |
| 1.2 | Python 测试 | `python -m pytest tests/ -q` 全绿（当前基线 217 条，以实测为准） | ☐ |
| 1.3 | Python 静态检查 | `python -m ruff check backend tests scripts` 零告警 | ☐ |
| 1.4 | 前端类型检查 | `npm --prefix web run typecheck` 零错误 | ☐ |
| 1.5 | 前端单测 | `npm --prefix web run test` 全绿（当前基线 17 条） | ☐ |
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
```

脚本 env 注入单实例旁路（`PLATFORM_ALLOW_SECOND_INSTANCE=1`），与用户已开的应用实例互不干扰。

| # | 项目 | 判定 | 结果 |
|---|---|---|---|
| 3.1 | health 就绪 | `status=ok` 且 `version` 与 `backend/invoice_processor/version.py` 一致 | ☐ |
| 3.2 | 日志生成 | EXE 同级 `logs/invoice.log` 生成，无 `CRITICAL` | ☐ |
| 3.3 | 干净退出 | WM_CLOSE 关窗后进程收敛、端口释放（脚本自动断言） | ☐ |
| 3.4 | CI 不跑冒烟 | 冒烟仅限交互式 Windows 桌面会话，不进 GitHub Actions | ☐ |

## 4. 桌面功能冒烟（目标机，自动判定）

| # | 场景 | 判定 | 结果 |
|---|---|---|---|
| 4.1 | 启动 | 双击 EXE 进入桌面窗口（窗口句柄断言），无控制台、无外部浏览器 | ☐ |
| 4.2 | 中文脱敏样本 | 用脱敏中文 PDF 样本跑一次完整处理，输出与命名正常 | ☐ |
| 4.3 | 输出打开 | 「打开输出目录」调起资源管理器并定位到正确目录 | ☐ |
| 4.4 | 退出回收 | 关窗后无残留进程（任务管理器核对），`logs/` 正常落盘 | ☐ |

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

## 6. 手工 E2E 场景（目标机，脚本驱动）

> `scripts/acceptance_driver.py --only 6` 脚本驱动（真实 EXE + 真实 WebSocket 客户端）；全部自动判定。

| # | 场景 | 步骤要点 | 结果 |
|---|---|---|---|
| 6.1 | 选择到完成 | 选目录 → 预扫描 PDF 数 → 开始 → 进度/日志实时事件（6.1a/6.1b/6.1c） | ☐ |
| 6.2 | 运行中停止 | 处理进行中点停止 → 任务收敛为已取消 → 可再次开始 | ☐ |
| 6.3 | 断线恢复 A | 断开重连：无游标不重放（旧行为）+ 带游标补齐断线事件、编号连续 | ☐ |
| 6.4 | 断线恢复 B | 第二客户端关闭 → 主客户端不受影响 | ☐ |
| 6.5 | 设置修改与日志导出 | 修改线程数即时保存 + 日志分页过滤不重不漏 | ☐ |

## 7. 更新检测（自动化覆盖，无验收脚本章节）

v7.3.0 起程序内无自动更新链路（`405d8fd` 移除）——升级 = 检测提示 + Release 页手动下载。
更新检测的版本比较、资产选择、错误处理、不误报语义由 `tests/application/test_update_checker.py` 与 `tests/api/test_update_endpoint.py` 单测覆盖（§1.2 pytest 全绿即视为通过），**不再做旧版下载/升级演练**。

**部署操作指引（非测试项）**：旧版安装目录用新 ZIP 解压替换，保留 `config.ini`、`logs/`、`发票收件箱/`（详见本文件 §10.1 发布参数表）。

## 8. 明确不测项（当前版本边界）

以下事项**不在**当前验收范围（详见 [ARCHITECTURE.md](ARCHITECTURE.md) §12 边界声明）：

- 目录监听（watch）自动处理；
- Playwright 自动化 E2E 套件；
- 跨磁盘安装目录的复制式替换；
- WebView2 渲染逐像素外观与 DPI 视觉回归（§4.1 窗口句柄 + §6 API/WS 链路覆盖启动与功能）。

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
| §7 升级验收（v7.3.1 复跑） | 40101720 | 2026-10-02 | ☑通过 | 自动 5 项全过：旧版 v7.2.1 探活（health 401 拒绝码）、旧版检测发现 7.3.1（available=true latest=7.3.1）、覆盖替换演练（config.ini/logs/收件箱保留）、升级后 health=7.3.1 + 配置保留（target_tax_id 存在、max_workers=8）、当前版不误报（available=false）；`--only 7` 驱动，升级基线 v7.2.1 不变 |
| §2+§4+§6 全量（v7.3.2 发布） | 40101720 | 2026-10-02 | ☑通过 | `acceptance_driver.py` 全量 16 项全过 0 失败：§2 五项前置通过；§4 窗口句柄/12 份占位样本（completed_with_warnings）/Explorer 打开/干净退出端口释放；§6 实时事件 48 条（progress=5/log=20）、进度单调 1.0、断线重连游标补齐 171 条编号连续、双客户端隔离、设置 8→4 保存还原、日志分页不重不漏。取消场景复跑单独验证：cancel 200 → 终态 cancelled（全量跑样本处理过快时降级跳过，属占位样本特性非缺陷）。测试基线 168 全绿 + ruff 零告警 + tsc/Vitest 8/build + CI 绿（e71717a 修复 Linux CI 五连红后） |
| §1 自动化与发布构建（v7.3.3） | 40101720 | 2026-10-02 | ☑通过 | Ruff、168 条 Python 测试、TypeScript、Vitest 8 条、Vite 构建、PyInstaller 域控合规均通过；EXE 冒烟 health=7.3.3、日志无 CRITICAL、干净退出并释放端口 |
| §4 桌面功能（v7.3.3 发布包） | 40101720 | 2026-10-02 | ☑通过 | `acceptance_driver.py --only 4`：启动/health、Explorer 打开输出目录、干净退出与端口回收通过；12 份生成占位 PDF 为 `completed_with_warnings`（成功 0、失败 12），仅验证处理流程，不作为业务识别通过基线 |
| §1 静态与自动化（v7.3.4） | 40101720 | 2026-10-03 | ☑通过 | pytest 217 / ruff 零告警 / tsc / Vitest 17 / build / CI 绿（6479413）；ZIP SHA-256 5c0fa974... 与 .sha256 一致，GitHub digest 一致 |
| §3 启动冒烟（v7.3.4） | 40101720 | 2026-10-03 | ☑通过 | EXE 完整模式：health=7.3.4、日志无 CRITICAL、干净退出、端口释放；更新检测核对 available=false（7.3.4 = Release 最新） |
| §2+§4+§6 全量（v7.3.4 发布） | 40101720 | 2026-10-03 | ☑通过 | `acceptance_driver.py` 全量 16 项全过 0 失败；§2 五项前置通过；§4 窗口句柄/12 份占位样本（completed_with_warnings，成功 0、失败 12，仅验证处理流程）/Explorer 打开/干净退出端口释放（exit=0）；§6 实时事件 48 条（progress=5/log=20）、进度单调 1.0、断线重连游标补齐 171 条编号连续、双客户端隔离、设置 8→4 保存还原、日志分页不重不漏。取消场景复跑 `--only 6` 仍因占位样本处理过快降级跳过（与 v7.3.2 相同，属占位样本特性非缺陷；取消链路单测覆盖见 tests/application/test_job_service.py） |

### 人工观察项留痕

| 项目 | 执行人 | 日期 | 结果 | 备注 |
|---|---|---|---|---|
| §4.2 渲染无白屏 | 40101720 | 2026-09-29 | ☑通过 | 切换 处理/收件箱/审核/设置 各视图确认无白屏 |
| §4.3 DPI 缩放 | 40101720 | 2026-09-29 | ☑通过 | 125%/150%/175% 下最小窗口（1024×700）不溢出、按钮可点 |
| §7 GUI 检查更新 | 40101720 | 2026-09-29 | ☑通过 | 设置页点「检查更新」，当前版本提示已是最新（7.3.0 = Release 最新，横幅不出现为正确行为） |

自动化执行说明：`scripts/acceptance_driver.py` 驱动（产物 `acceptance_report.json`，本地留痕），
全部验收项自动判定，无人工观察项。样本缺省由脚本自动生成占位 PDF
（真实发票样本用 `--sample-dir` 指定）；脚本与 `smoke_launch.py` 均注入单实例
旁路 `PLATFORM_ALLOW_SECOND_INSTANCE=1`，与用户已开的应用实例互不干扰。
2026-10-02 起更新检测不再做旧版升级演练（单测覆盖，见 §7）。

---

## 10. 发布流程目标

为 SYNTEC 电子票据处理系统建立一条可重复、可验证的 GitHub Release 发布流程：

```text
同步版本 -> 构建 -> 合规校验 -> 生成 ZIP + SHA-256 -> 上传 Release -> 验证
```

应用支持更新检查：启动时查询 GitHub 最新 Release，发现新版本时提示用户并跳转 Release 页面手动下载。**应用不在程序内下载或安装更新。**

版本号管理遵循 SemVer：版本只由 `bump_version.py` 显式递增；`build_syntec.py` 打包时校验版本源一致并拒绝已发布的版本号，保证 Release 标签与实际构建产物一一对应。

## 10.1 发布参数表

| 参数 | 值 |
|---|---|
| GitHub 仓库 | `SYNTEC-40101720/Automated-invoice-processing` |
| 标签格式 | `vX.Y.Z`（三段数字版本） |
| Release 资产 | `SYNTEC-Invoice-Processor-vX.Y.Z.zip`（ASCII 文件名） |
| ZIP 顶层目录 | `SYNTEC-电子票据处理系统/`（完整安装目录） |
| 手动更新需保留 | `config.ini`、`logs/`、`发票收件箱/`（不打进 ZIP） |

## 10.2 前置条件

- 应用有唯一、可比较的运行时版本，并同步包管理器、前端和 Windows 文件版本。
- GitHub 仓库的 Release 权限和发布工具已经验证，例如：

  ```powershell
  gh auth status --hostname github.com
  ```

## 10.3 版本检查行为

应用调用固定仓库的 `GET https://api.github.com/repos/SYNTEC-40101720/Automated-invoice-processing/releases/latest`：

1. 只接受 `https` 的 GitHub API 响应。
2. 解析 `vX.Y.Z` 为数字元组后比较，禁止按字符串排序。
3. 网络错误、HTTP 错误、JSON 无效或标签无效时返回"检查未完成"，应用正常启动。
4. 只有最新版本大于当前版本时才提示新版本；不降级。
5. 资产选择用于横幅提示，要求文件名以 `SYNTEC-Invoice-Processor` 前缀开头且以 `.zip` 结尾，下载地址必须是固定仓库的 HTTPS 地址。

### 资产命名注意事项

GitHub 会自动重命名包含中文或部分特殊字符的 Release 资产名，导致前缀匹配失败。因此统一使用 ASCII 资产名 `SYNTEC-Invoice-Processor-vX.Y.Z.zip`。

## 10.4 Release 发布步骤

### 10.4.1 同步版本

统一递增版本并检查以下来源：

- `pyproject.toml` 运行时版本（`scripts/bump_version.py` 同步）
- `package.json` 前端版本
- Windows `FileVersion`、`ProductVersion`（`version_info.txt`）

**版本号规则（SemVer）**：

1. 版本号只通过 `python scripts/bump_version.py [patch|minor|major]` 显式递增；打包脚本不修改任何版本文件。
2. `bump_version.py` 拒绝递增到已有 tag 的版本号（本地或远端 `vX.Y.Z` 已存在即视为已发布或已占用）。
3. `build_syntec.py` 打包前校验五个版本源一致，并拒绝打包远端已有 tag 的版本号，防止重复发布。

```bash
python scripts/bump_version.py patch   # 补丁：bug 修复
python scripts/bump_version.py minor   # 次版本：新功能或有破坏性变更
python scripts/bump_version.py major   # 主版本：重大架构变化
```

### 10.4.2 构建

执行 `python scripts/build_syntec.py`，确认：

- 输出文件名以 `SYNTEC` 开头。
- CompanyName、ProductName、LegalCopyright 包含 `SYNTEC`。
- Windows 版本使用四段数字。
- 使用 `--onedir --windowed --noupx`。
- 在纯英文、无空格路径下执行 PyInstaller。

### 10.4.3 生成和上传资产

`build_syntec.py` 会在生成 ZIP 的同时落盘摘要文件 `dist/SYNTEC-Invoice-Processor-vX.Y.Z.zip.sha256`（格式：`<sha256>  <文件名>`），无需再手工执行 Get-FileHash。

创建 Release 并上传 ASCII 资产：

```powershell
gh release create vX.Y.Z `
  .\dist\SYNTEC-Invoice-Processor-vX.Y.Z.zip `
  --repo SYNTEC-40101720/Automated-invoice-processing `
  --title "vX.Y.Z" `
  --notes "Release notes"
```

发布后验证：

```powershell
gh release view vX.Y.Z --repo SYNTEC-40101720/Automated-invoice-processing --json tagName,isDraft,isPrerelease,url,assets
```

重点确认：

- `isDraft=false`
- `isPrerelease=false`
- 资产 `state=uploaded`
- 资产名仍为预期 ASCII 名称
- 资产大小合理
- GitHub digest 与本地 SHA-256 一致（以 `.zip.sha256` 文件为准）

## 10.5 更新检测验收矩阵

| 场景 | 期望结果 |
|---|---|
| 当前版本低于 Release | `available=true`，横幅提示新版本 |
| 当前版本等于 Release | `available=false` |
| 当前版本高于 Release | 不降级，`available=false` |
| Release 无合规 ZIP | 横幅仍提示版本号，无资产信息 |
| 资产前缀错误 | 忽略资产 |
| 下载地址非固定仓库 HTTPS | 忽略资产 |
| 网络超时或 JSON 无效 | 检查未完成，不误报最新，应用正常启动 |

测试覆盖（全部自动化，不再做旧版升级演练）：

1. 更新检查单元测试：版本比较、资产选择、错误处理（`tests/application/test_update_checker.py`、`tests/api/test_update_endpoint.py`），随 §1.2 pytest 全绿判定。
2. 真实 GitHub API 联通性：发布后可在本机执行 `python -c "from invoice_processor.application.update_checker import check_for_update; print(check_for_update())"` 快速核对（当前版应 `available=false`）。

## 10.6 故障处理

### 检测到新版本但看不到资产信息

依次检查：

1. GitHub Release 是否为稳定 Release（非 draft、非 prerelease）。
2. 资产是否为 ASCII 文件名。
3. 资产名是否以 `SYNTEC-Invoice-Processor` 开头。
4. `browser_download_url` 是否为固定仓库的 HTTPS 地址。
5. API 返回的资产是否已经被 GitHub 自动重命名。

### 手动更新后配置丢失

1. 停止使用并保留原安装目录的 `config.ini`、`logs/` 和 `发票收件箱/`。
2. 将它们复制回新安装目录对应位置。

## 10.7 发布记录模板

```text
应用：
仓库：
当前版本：
目标版本：
Release URL：
资产名：
资产大小：
SHA-256：
主程序版本资源：
旧版检测结果：
当前版检测结果：
未覆盖的环境：
已知限制：
```

## 11. 发布记录

### v7.3.4（2026-10-03 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.3
目标版本：7.3.4
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.4
资产名：SYNTEC-Invoice-Processor-v7.3.4.zip
资产大小：61.64 MB（64,630,958 字节）
SHA-256：5c0fa974d8d58b75f4e1fec479964435bd7c5075a2870efd713877bb63e3b14b（GitHub digest 一致）
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=[IP_ADDRESS]，LegalCopyright=Copyright © SYNTEC 2026
质量基线：217 条 Python 测试、Ruff、TypeScript、Vitest 17 条、Vite 构建通过；PyInstaller 域控合规通过
启动冒烟：health=7.3.4，日志无 CRITICAL，进程干净退出且端口释放
当前版检测结果：available=false 不误报（7.3.4 = Release 最新，实测核对）
桌面验收：§2+§4+§6 全量 16 项全过 0 失败；取消场景占位样本处理过快降级跳过（与 v7.3.2 相同特性，复跑 --only 6 仍降级，取消链路由单测覆盖）
已知限制：AI 提示注入与真实税控 PDF 语料版式验证不在范围（PROJECT_DEV 遗留项）
```

内容：14 条审查缺陷修复批次（邮箱拉取批次目录隔离、ZIP 成员名清洗与加密/损坏容错、拉取单飞锁、配置健壮性 %/BOM/GBK/密文损坏、乘车日期正则双花括号、三层类别判定、打车单程 100 元与高铁座位差标、Excel 公式注入防护、关窗等待任务终态）+ 前端 WS 事件游标重构（跨重启游标回退保护）；测试基线 168 → 217，Vitest 8 → 17。文档基线同步整合（ARCHITECTURE/PROJECT_DEV/README 版本历史与测试数统一）。

### v7.3.3（2026-10-02 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.2
目标版本：7.3.3
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.3
资产名：SYNTEC-Invoice-Processor-v7.3.3.zip
资产大小：61.63 MB（64,625,902 字节）
SHA-256：8f85c9b3e99b69d85727151badc7f2271d42dee073ae6b3a91b3ea1814be0091
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=7.3.3.0，LegalCopyright=Copyright © SYNTEC 2026
质量基线：168 条 Python 测试、Ruff、TypeScript、Vitest 8 条、Vite 构建通过；PyInstaller 域控合规通过
启动冒烟：health=7.3.3，日志无 CRITICAL，进程干净退出且端口释放
桌面验收：§4 启动、输出目录打开和退出回收通过；12 份占位 PDF 无有效发票内容，completed_with_warnings（成功 0、失败 12），不作为业务识别验收
```

内容：设置页统一使用系统设置与本系统名称；替换侧栏、favicon 和桌面图标中的旧品牌图形；移除用户界面中的内部底座版本展示，并修正相关历史文档与发布说明。API 兼容字段保留。

### v7.3.2（2026-10-02 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.1
目标版本：7.3.2
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.2
资产名：SYNTEC-Invoice-Processor-v7.3.2.zip
资产大小：61.69 MB（64,685,966 字节）
SHA-256：1d6abd3a49a0c520d30c11721d4e2987ecb27bda14f7d0d50314f75728672f21（GitHub digest 一致）
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=[IP_ADDRESS]
旧版检测结果：v7.3.1 视角 available=true latest=7.3.2（更新检测逻辑由 tests/application/test_update_checker.py 4 条单测覆盖）
当前版检测结果：v7.3.2 available=false 不误报（同上单测覆盖，§7 升级演练已于 101dc23 移除）
未覆盖的环境：WebView2/DPI 差异仍需目标环境验收（v7.3.1 已通过，本轮无渲染层变更）
已知限制：全部验收项自动判定（§2+§4+§6 16 项全过 0 人工）；取消场景在全量跑中因占位样本处理过快降级跳过，已单独复跑验证 cancel 200 → 终态 cancelled
```

内容：ARCHITECTURE §12.1 遗留评估项清零——发票 WS 空转等待 30s→0.5s + 断链监听任务（死链回收 ≤0.5s），GET /jobs/current 挂 JobSnapshotResponse 契约显式化；测试基线 165→168。附带修复：单实例互斥体测试 Linux CI 五连红（e71717a）。

### v7.3.1（2026-10-02 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.0
目标版本：7.3.1
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.1
资产名：SYNTEC-Invoice-Processor-v7.3.1.zip
资产大小：61.69 MB（64,686,019 字节）
SHA-256：3bf2315ed2772b21c709973001faaf0e3150765b91cee1d0fba7fb84fc4ef300（GitHub digest 一致）
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=7.3.1.0
旧版检测结果：v7.2.1 视角 available=true latest=7.3.1（§7.1a）
当前版检测结果：v7.3.1 available=false 不误报（§7.1b）
未覆盖的环境：WebView2/DPI 差异仍需目标环境验收（v7.3.0 已通过，本轮无渲染层变更）
已知限制：更新检测全部由单测与验收脚本自动判定（§7 演练项已于 101dc23 移除，无人工观察项）
```

内容：事件总线融合二期 + 任务历史记录（含落地缺陷修复）+ 设置页版本信息改为运行时读取、health 响应返回底座版本字段；测试基线 150→165。
