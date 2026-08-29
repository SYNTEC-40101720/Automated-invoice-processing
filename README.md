# SYNTEC 电子票据处理系统 v7.0.5

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
- 🔄 软件打开后自动检查 GitHub Release，可在设置页自动下载并安装新版本
- ⚙️ 配置 API 对敏感授权码和 API Key 只返回配置状态

## 环境要求

- Python 3.12+
- Windows 操作系统
- Node.js 18+ 与 npm（仅前端构建需要）
- 依赖包详见 [requirements.txt](requirements.txt)

## 安装步骤

1. 克隆或下载项目到本地
2. 安装 Python 依赖包：
   ```
   python -m pip install -r requirements.txt
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
5. 按 SYNTEC 域控规范打包（需安装 PyInstaller）：
   ```
   python build_syntec.py
   ```

## 项目结构

```
├── main.py                       # Web 桌面入口（FastAPI + pywebview）
├── build_syntec.py               # 前端构建、PyInstaller 打包和合规校验
├── bump_version.py               # 递增并同步发布版本号
├── requirements.txt              # 依赖包列表
├── version_info.txt              # PyInstaller Windows 版本信息资源
├── pyproject.toml                # 项目元数据与工具配置
├── config.ini                    # 运行时用户配置（不入库，首次运行自动生成）
├── README.md                     # 项目说明
├── PROJECT_DEV.md                # 开发文档（业务规则、架构、踩坑记录）
├── src/                          # 源代码包
│   ├── __init__.py
│   ├── config.py                 # 业务配置常量（税号、线程数）
│   ├── config_manager.py         # INI 配置读写（税号、线程数外部化）
│   ├── logger_config.py          # 日志配置（固定路径 + 轮转）
│   ├── domain/                   # 领域模型、状态机和错误码
│   ├── application/              # 任务编排、事件总线、文件服务和审核服务
│   ├── api/                      # FastAPI 路由、鉴权、静态资源和 WebSocket
│   ├── desktop/                  # pywebview 启动器和原生能力桥
│   └── core/                     # 可复用发票处理核心
│   │   ├── __init__.py
│   │   └── processor.py          # InvoiceProcessor 发票处理核心类
├── web/                          # React/Vite 工作台
│   ├── src/                      # 视图、API 客户端、状态和样式
│   └── package.json              # 前端脚本与依赖
└── tests/                        # 核心、应用层和 API 契约测试
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `main.py` | 桌面入口，启动本地 FastAPI 服务和 WebView2 |
| `src/desktop/` | 随机本地端口、token、桌面桥接、更新编排和退出清理 |
| `src/api/` | HTTP/WebSocket 契约、本地 token 和 React 静态资源 |
| `src/application/` | 任务状态、取消、日志、审核、归档和更新检查编排 |
| `src/domain/` | Job 状态机、事件和领域错误 |
| `src/config.py` | 集中存放业务配置常量（税号、线程数） |
| `src/config_manager.py` | INI 配置文件读写，运行时动态访问税号等 |
| `src/logger_config.py` | 日志持久化（RotatingFileHandler，1MB 轮转，5 备份） |
| `src/core/processor.py` | 发票处理核心算法：PDF 提取、类型路由、正则解析、重命名、税号校验、PDF 合并 |
| `web/src/` | React 工作台视图、服务端状态和实时事件 |

## 配置说明

业务配置（税号、线程数和 AI 审核）通过 Web 工作台「设置」视图修改；邮箱连接参数在「设置」视图维护，收件目录、自动收件开关和轮询间隔在「收件箱」视图设置并显示。所有配置保存至 `config.ini` 并立即生效，处理工作区的源文件目录由处理页单独选择。授权码和 API Key 由本地安全存储负责保存，API 响应只返回是否已配置。

业务配置默认值和动态读取逻辑见 [src/config.py](src/config.py) 与 [src/config_manager.py](src/config_manager.py)。

## 开发规范

- 模块化设计，领域层、应用层、API 和界面分离
- `src/core/` 只承载发票处理业务，不依赖 Web 或 Qt
- 后台任务通过应用层事件总线向 API 和 WebSocket 推送状态
- 桌面能力只能通过 `src/desktop/native_bridge.py` 暴露
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
python -m ruff check src tests
```

当前 Windows 开发环境已验证 Python 测试 143 条通过、编译和依赖检查通过，前端类型检查与生产构建通过，`build_syntec.py` 可生成并完成 SYNTEC 域控合规校验，本机正式发布包启动冒烟通过。真实浏览器 E2E、干净域控账户启动和目标机 WebView2 验收仍需单独执行。

## 版本发布

版本源为 `src/version.py`，递增命令会同步 `pyproject.toml`、Web 包元数据和 PyInstaller 资源：

```bash
python bump_version.py patch   # 7.0.5 → 7.0.6
python bump_version.py minor   # 7.0.5 → 7.1.0
python bump_version.py major   # 7.0.5 → 8.0.0
```

普通测试和打包不会自动修改版本；正式发布前执行一次递增命令，再运行 `python build_syntec.py`。打包脚本会拒绝不一致的版本配置。

## 自动更新检查

应用每次打开工作台时，会通过本地 API 查询 GitHub 的最新稳定 Release。设置页也提供「检查更新」按钮。查询使用仓库
[`SYNTEC-40101720/Automated-invoice-processing`](https://github.com/SYNTEC-40101720/Automated-invoice-processing)
的公开 Releases API；网络不可用或 GitHub 暂时无法访问时，应用仍会正常启动。

发现比当前版本更高且包含可安装 ZIP 的 Release 后，工作台顶部会提示更新，设置页会出现「立即更新」。点击后程序会在后台下载 ZIP，校验 GitHub 提供的 SHA-256 摘要（Release 未提供摘要时使用 HTTPS 和包结构校验），然后关闭当前窗口，由独立更新器替换安装目录并启动新版本。`config.ini`、`logs/` 和默认收件箱会从旧版本保留。

支持自动安装的第一版需要先人工部署一次，因为旧版本安装目录中没有独立更新器；从该版本开始，后续 Release 可以完全免人工下载。安装目录还必须对当前用户可写，否则更新器无法替换文件。

发布新版本时保持版本号一致：

1. 执行 `python bump_version.py patch`（或 `minor`、`major`）。
2. 执行 `python build_syntec.py`，生成新的 `dist/SYNTEC-电子票据处理系统/` 打包目录，其中包含主程序和 `SYNTEC-电子票据更新器.exe`。
3. 将整个 `dist/SYNTEC-电子票据处理系统/` 目录压缩为以 `SYNTEC-电子票据处理系统` 开头、以 `.zip` 结尾的文件。
4. 在 GitHub 创建 Release，标签使用 `v7.0.5` 这类格式，上传该 ZIP 并发布。
5. 发布 Release 后，用户在设置页点击「检查更新」即可下载并完成更新；Release 标签版本必须高于软件当前版本。

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v7.0.5 | 2026-08-29 | 清理发布产物和冗余配置入口，补齐 README/版本信息并完成发布前静态验证与打包路径整理 |
| v7.0.4 | 2026-08-23 | 收件箱独立指定并显示收件目录，增加自动收件开关与轮询间隔控制；处理工作区目录不再被替换；非发票凭证跳过税号校验，并补充 API 与处理器测试 |
| v7.0.3 | 2026-08-23 | 清理未使用占位视图、孤立样式和空目录；更新运行时版本显示并完成发布验证 |
| v7.0.2 | 2026-08 | 仅支持 Python 3.12，移除 Python 3.10 兼容层和 tomli 依赖 |
| v7.0.1 | 2026-08 | 统一运行时、前端和 EXE 版本信息，增加发布版本递增与一致性校验 |
| v7.0.0 | 2026-08 | FastAPI + React 工作台、任务服务、邮箱自动轮询、统一设置、日志恢复、Native Bridge 安全边界和域控打包 |
| v6.2 | 2026-07 | 停止按钮、日志持久化、PDF 异常分类、配置外部化、拖拽导入、内容去重、类型路由注册表、集成测试 |
| v6.1 | 2026-07 | 域控规范支持、桌面界面迁移、墨韵主题 |
| v6.0 | 2026-07 | 初始版本 |

详细变更见 [PROJECT_DEV.md](PROJECT_DEV.md)。
