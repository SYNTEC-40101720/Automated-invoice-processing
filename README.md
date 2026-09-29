# SYNTEC 电子票据处理系统 v7.1.3

基于 Python 3.12+、FastAPI 的业务底层、React/Vite Web 工作台和 pywebview/WebView2 桌面壳，用于批量识别、重命名、校验与合并 PDF 电子发票。

## 功能特点

- 📋 自动识别多种类型的 PDF 电子发票（浙江/宁波通用、江苏通行费、江苏行程单、高铁票、滴滴行程单、通用电子发票等）
- 🔁 按规则提取发票号与金额，重命名输出文件
- 🔍 发票异常税号检测，自动归集到「税号异常」子目录（行程单等凭证跳过）
- 📑 将所有处理后的 PDF 合并为单个 PDF 文件
- 🧵 多线程并发处理，带进度条与彩色日志面板
- 🖥️ Web 工作台支持处理概览、收件箱、审核和设置视图
- 📡 FastAPI + WebSocket 实时推送任务进度、日志和状态
- 📁 桌面壳提供目录选择、PDF 文件选择、日志导出和打开输出目录
- 🔄 软件启动时检查 GitHub Release；发现新版本后跳转 Release 页面手动下载和替换
- ⚙️ 配置 API 对敏感授权码和 API Key 只返回配置状态

## 环境要求

- Python 3.12+
- Windows 操作系统
- Node.js 18+ 与 npm（仅前端构建需要）
- 依赖详见 [pyproject.toml](pyproject.toml)

## 安装步骤

1. 克隆或下载项目到本地
2. 安装 Python 依赖包（含开发工具）：
   ```
   python -m pip install -e .[dev,build]
   ```
3. 安装并构建 Web 工作台：
   ```
   npm --prefix web install
   npm --prefix web run build
   ```
4. 运行桌面主程序：
   ```
   python main.py
   ```
5. 按 SYNTEC 域控规范打包：
   ```
   python scripts/build_syntec.py
   ```

## 项目结构

```
├── main.py                       # Web 桌面入口（FastAPI + pywebview）
├── pyproject.toml                # 项目元数据与工具配置
├── config.ini                    # 运行时用户配置（不入库，首次运行自动生成）
├── README.md                     # 项目说明
├── version_info.txt              # PyInstaller Windows 版本信息资源
├── docs/                         # 项目文档（架构、SOP、开发维护说明）
├── scripts/                     # 构建与工具脚本
│   ├── build_syntec.py           # 前端构建、PyInstaller 打包和合规校验
│   └── bump_version.py           # 递增并同步发布版本号
├── backend/
│   ├── devbase/                  # 通用桌面工具框架
│   │   ├── domain/               # 状态、事件、端口和资源
│   │   ├── application/          # JobRuntime、ToolRegistry、生命周期和更新检查
│   │   ├── api/                  # 安全 API 工厂和通用路由
│   │   └── desktop/              # 桌面壳、NativeBridge 和日志
│   └── invoice_processor/        # 发票业务包
│       ├── config.py             # 业务配置常量（税号、线程数）
│       ├── config_manager.py     # 发票业务配置读写
│       ├── domain/               # 发票领域模型、状态机和错误码
│       ├── application/          # 发票流水线、审核、邮箱和任务适配器
│       ├── api/                  # 发票路由、设置和 WebSocket
│       ├── desktop/              # 发票桌面扩展能力
│       └── core/                 # InvoiceProcessor 发票处理核心
├── web/                          # React/Vite 工作台
│   ├── src/                      # 视图、API 客户端、状态和样式
│   └── package.json              # 前端脚本与依赖
└── tests/                        # 核心、应用层和 API 契约测试
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `main.py` | 桌面入口，启动本地 FastAPI 服务和 WebView2 |
| `backend/devbase/` | 通用安全层、JobRuntime、ToolRegistry、生命周期、桌面壳和日志 |
| `backend/invoice_processor/desktop/` | 发票桌面扩展、随机端口、业务桥接和退出清理 |
| `backend/invoice_processor/api/` | 发票 HTTP/WebSocket 契约、设置、邮箱和业务兼容路由 |
| `backend/invoice_processor/application/` | 发票流水线、审核、归档、邮箱和 DevBase Task 适配 |
| `backend/invoice_processor/domain/` | 发票 Job 状态机、阶段、触发来源和领域错误 |
| `backend/invoice_processor/config_manager.py` | 发票业务 INI 配置和敏感字段读写 |
| `backend/invoice_processor/core/processor.py` | 发票处理核心算法：PDF 提取、类型路由、正则解析、重命名、税号校验、PDF 合并 |
| `web/src/` | React 工作台视图、服务端状态和实时事件 |

## DevBase 任务接口

当前已接入的通用任务契约：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/tools` | 返回已注册工具清单 |
| POST | `/api/v1/jobs/start` | 按 `kind` 启动 DevBase 任务，发票工具为 `invoice_processing`；启动前同步预检目录与触发来源，错误以 422 稳定错误码返回 |
| POST | `/api/v1/jobs/cancel` | 取消当前 DevBase 任务 |
| GET | `/api/v1/jobs/current` | 当前发票任务快照 |
| POST | `/api/v1/jobs/scan` | 预扫描目录顶层 PDF |
| GET | `/api/v1/jobs/{id}/logs` | 分页任务日志 |

任务启动/取消已统一为 DevBase 契约；设置、邮箱和日志接口由发票侧保留。

## 配置说明

业务配置（税号、线程数和 AI 审核）通过 Web 工作台「设置」视图修改；邮箱连接参数在「设置」视图维护，收件目录在「收件箱」视图设置并显示。邮箱附件仅在用户手动拉取时下载，不会后台自动轮询或自动启动处理任务。所有配置保存至 `config.ini` 并立即生效，处理工作区的源文件目录由处理页单独选择。授权码和 API Key 由本地安全存储负责保存，API 响应只返回是否已配置。

详细架构和开发规范见 [docs/](docs/) 目录。

业务配置默认值和动态读取逻辑见 [backend/invoice_processor/config.py](backend/invoice_processor/config.py) 与 [backend/invoice_processor/config_manager.py](backend/invoice_processor/config_manager.py)。

## 开发规范

- 模块化设计，领域层、应用层、API 和界面分离
- `backend/invoice_processor/core/` 只承载发票处理业务，不依赖 Web 或 Qt
- 后台任务通过应用层事件总线向 API 和 WebSocket 推送状态
- 桌面能力只能通过 `backend/invoice_processor/desktop/native_bridge.py` 暴露；通用能力来自 DevBase
- 代码遵循 PEP8 规范
- 所有注释使用中文

## 测试

```bash
# 全部测试
python -m pytest tests/ -v

# 仅单元测试
python -m pytest tests/test_processor.py -v

# 仅集成测试
python -m pytest tests/test_integration.py -v

# Python 静态检查
python -m ruff check backend tests
```

当前 v7.1.3 发布基线已验证 Python 测试通过（137 条）、Ruff 静态检查通过，前端类型检查和生产构建通过；DevBase 工具清单已提供 `invoice_processing` 任务入口。旧版 EXE 实际启动、干净域控账户启动和目标机 WebView2 验收仍需单独执行。

## 版本发布

版本源为 `backend/invoice_processor/version.py`，递增命令会同步 `pyproject.toml`、Web 包元数据和 PyInstaller 资源：

```bash
python scripts/bump_version.py patch   # 7.0.5 → 7.0.6
python scripts/bump_version.py minor   # 7.0.5 → 7.1.0
python scripts/bump_version.py major   # 7.0.5 → 8.0.0
```

普通测试不会自动修改版本；打包脚本 `build_syntec.py` 同样**不修改任何版本文件**——它只校验五个版本源一致，并拒绝打包远端已有 `vX.Y.Z` tag 的版本号。

## 手动邮箱收件

收件箱支持手动拉取邮箱 PDF/ZIP 附件、指定收件目录，并可在设置中维护邮箱连接与白名单。当前版本仅在用户点击「手动拉取」时连接邮箱；后台自动轮询和拉取后自动启动处理任务已停用。

## 自动更新检查

应用每次打开工作台时，会通过本地 API 查询 GitHub 的最新稳定 Release。设置页也提供「检查更新」按钮。查询使用仓库
[`SYNTEC-40101720/Automated-invoice-processing`](https://github.com/SYNTEC-40101720/Automated-invoice-processing)
的公开 Releases API；网络不可用或 GitHub 暂时无法访问时，应用仍会正常启动。

发现比当前版本更高的 Release 后，工作台顶部会提示新版本，并提供「前往下载」链接跳转到 Release 页面；设置页同样提供「检查更新」和 Release 链接。应用**不在程序内下载或安装更新**：用户需在 Release 页面手动下载 `SYNTEC-Invoice-Processor-vX.Y.Z.zip`，解压并替换安装目录（`config.ini`、`logs/` 和默认收件箱不打进 ZIP，替换时保留即可）。

发布新版本时保持版本号一致：

1. 执行 `python scripts/bump_version.py patch`（或 `minor`、`major`）递增版本号；若目标版本号已有 tag（已发布或已占用），命令会拒绝递增。
2. 执行 `python scripts/build_syntec.py`，生成新的 `dist/SYNTEC-电子票据处理系统/` 打包目录（主程序 + `_internal/`）。已发布过的版本号会被拒绝打包。
3. `build_syntec.py` 会生成 `dist/SYNTEC-Invoice-Processor-vX.Y.Z.zip`，直接使用该 ASCII 文件名作为资产。
4. 在 GitHub 创建 Release，标签使用 `vX.Y.Z` 格式，上传该 ZIP 并发布。
5. 发布 Release 后，旧版本在设置页点击「检查更新」即可发现新版本并跳转 Release 页面手动下载。

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v7.1.3 | 2026-09-05 | 目录规范化（docs/、scripts/、pyproject 统一依赖）、默认打开「发票收取」、修复窄视口侧边栏错位并简化 main.py 入口 |
| v7.1.1 | 2026-09-05 | DevBase 框架迁移：任务运行时、更新安全、生命周期复用 DevBase；工作台外壳对齐 DevBase 侧边栏与导航；邮箱收件箱简化并新增打开目录 API；清理死代码（171 条测试通过，域控打包合规验证通过） |
| v7.0.12 | 2026-09-01 | 完善自动更新启动确认、回滚保护、安装包完整性校验和发布前冒烟验证；隔离测试构建产物 |
| v7.0.11 | 2026-08-31 | 完善 GitHub Release 自动更新的包完整性校验、启动确认、回滚保护和本地成功/失败冒烟验证 |
| v7.0.5 | 2026-08-29 | 清理发布产物和冗余配置入口，补齐 README/版本信息并完成发布前静态验证与打包路径整理 |
| v7.0.4 | 2026-08-23 | 收件箱独立指定并显示目录；处理工作区源目录与收件箱分离；非发票凭证跳过税号校验，并补充 API 与处理器测试 |
| v7.0.3 | 2026-08-23 | 清理未使用占位视图、孤立样式和空目录；更新运行时版本显示并完成发布验证 |
| v7.0.2 | 2026-08 | 仅支持 Python 3.12，移除 Python 3.10 兼容层和 tomli 依赖 |
| v7.0.1 | 2026-08 | 统一运行时、前端和 EXE 版本信息，增加发布版本递增与一致性校验 |
| v7.0.0 | 2026-08 | FastAPI + React 工作台、任务服务、邮箱手动拉取、统一设置、日志恢复、Native Bridge 安全边界和域控打包 |
| v6.2 | 2026-07 | 停止按钮、日志持久化、PDF 异常分类、配置外部化、拖拽导入、内容去重、类型路由注册表、集成测试 |
| v6.1 | 2026-07 | 域控规范支持、桌面界面迁移、墨韵主题 |
| v6.0 | 2026-07 | 初始版本 |

详细变更见 [docs/PROJECT_DEV.md](docs/PROJECT_DEV.md)。
