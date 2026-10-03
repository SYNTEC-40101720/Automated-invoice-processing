# SYNTEC 电子票据处理系统

基于 Python 3.12+、FastAPI 的业务底层、React/Vite Web 工作台和 pywebview/WebView2 桌面壳，用于批量识别、重命名、校验与合并 PDF 电子发票。当前版本 v7.3.7。

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

# 前端单测（Vitest）
npm --prefix web run test

# 发布包启动冒烟（仅交互式 Windows 桌面会话）
python scripts/smoke_launch.py --target source
```

当前 v7.3.7 发布基线已验证 Python 测试通过（228 条）、Ruff 静态检查通过，前端类型检查、Vitest 单测（17 条）和生产构建通过；DevBase 工具清单已提供 `invoice_processing` 任务入口。发布包启动冒烟使用 `python scripts/smoke_launch.py`；目标机验收按 `docs/RELEASE_SOP.md` 执行。

## 版本发布

版本源为 `backend/invoice_processor/version.py`，递增命令会同步 `pyproject.toml`、Web 包元数据和 PyInstaller 资源（`python scripts/bump_version.py [patch|minor|major]`）；打包脚本只校验五版本源一致并拒绝已发布版本号，不修改任何版本文件。

完整发布流程、验收清单与历史发布记录见 [docs/RELEASE_SOP.md](docs/RELEASE_SOP.md)（§9 验收留痕、§11 发布记录）与 GitHub Releases 页面。
