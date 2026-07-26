# SYNTEC 电子票据处理系统 v6.2

基于 Python 3 和 PySide6（Qt6）开发的 Windows 桌面应用程序，用于批量识别、重命名、校验与合并 PDF 电子发票。

## 功能特点

- 📋 自动识别多种类型的 PDF 电子发票（浙江/宁波通用、江苏通行费、江苏行程单、高铁票、滴滴行程单、通用电子发票等）
- 🔁 按规则提取发票号与金额，重命名输出文件
- 🔍 异常税号检测，自动归集到「税号异常」子目录
- 📑 将所有处理后的 PDF 合并为单个 PDF 文件
- 🧵 多线程并发处理，带进度条与彩色日志面板
- 🖱️ 支持拖拽导入文件夹和 PDF 文件
- ⚙️ 可视化设置对话框（税号、线程数可配置）

## 环境要求

- Python 3.10+
- Windows 操作系统
- 依赖包详见 [requirements.txt](requirements.txt)

## 安装步骤

1. 克隆或下载项目到本地
2. 安装依赖包：
   ```
   pip install -r requirements.txt
   ```
3. 运行主程序：
   ```
   python main.py
   ```
4. 打包成可执行文件（可选，需自行安装 PyInstaller）：
   ```
   pyinstaller --noconfirm --windowed --name "SYNTEC-发票处理系统" --version-file version_info.txt main.py
   ```

## 项目结构

```
├── main.py                       # 程序入口，DPI 感知设置
├── requirements.txt              # 依赖包列表
├── version_info.txt              # PyInstaller Windows 版本信息资源
├── pyproject.toml                # 项目元数据与工具配置
├── config.ini                    # 运行时用户配置（不入库，首次运行自动生成）
├── README.md                     # 项目说明
├── PROJECT_DEV.md                # 开发文档（业务规则、架构、踩坑记录）
├── src/                          # 源代码包
│   ├── __init__.py
│   ├── config.py                 # 集中配置常量（窗口尺寸、字体等）
│   ├── config_manager.py         # INI 配置读写（税号、线程数外部化）
│   ├── logger_config.py          # 日志配置（固定路径 + 轮转）
│   ├── core/                     # 业务逻辑层
│   │   ├── __init__.py
│   │   └── processor.py          # InvoiceProcessor 发票处理核心类
│   └── ui/                       # 表现层与 UI 组件
│       ├── __init__.py
│       ├── app.py                # InvoiceApp 主窗口 + Worker 线程
│       ├── colors.py             # 墨韵调色板
│       ├── components.py         # 自定义组件（StatCard/LogView 等）
│       └── settings_dialog.py    # 业务配置对话框
└── tests/                        # 测试
    ├── test_processor.py         # 单元测试（33 个）
    └── test_integration.py       # 集成测试（20 个）
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `main.py` | 程序入口，设置 DPI 感知、启动 QApplication |
| `src/config.py` | 集中存放可配置常量（窗口尺寸、字体族、颜色） |
| `src/config_manager.py` | INI 配置文件读写，运行时动态访问税号等 |
| `src/logger_config.py` | 日志持久化（RotatingFileHandler，1MB 轮转，5 备份） |
| `src/core/processor.py` | 发票处理核心算法：PDF 提取、类型路由、正则解析、重命名、税号校验、PDF 合并 |
| `src/ui/app.py` | 主窗口布局、事件分发、并发调度、拖拽支持 |
| `src/ui/colors.py` | 墨韵调色板色彩常量 |
| `src/ui/components.py` | 可复用 UI 组件（StatCard、AccentBar、LogView 等） |
| `src/ui/settings_dialog.py` | 业务配置对话框（税号、线程数设置） |

## 配置说明

业务配置（税号、线程数）通过程序内「设置」对话框修改，保存至 `config.ini`，下次处理生效。

UI 常量（窗口尺寸、字体等）见 [src/config.py](src/config.py)。

## 开发规范

- 模块化设计，逻辑与界面分离
- 业务层（`src/core/`）不依赖任何 Qt 模块
- 跨线程通信使用 Qt 信号槽（`QueuedConnection`）
- 代码遵循 PEP8 规范
- 所有注释使用中文

## 测试

```bash
# 全部测试
pytest tests/ -v

# 仅单元测试
pytest tests/test_processor.py -v

# 仅集成测试
pytest tests/test_integration.py -v
```

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v6.2 | 2026-07 | 停止按钮、日志持久化、PDF 异常分类、配置外部化、拖拽导入、内容去重、类型路由注册表、集成测试 |
| v6.1 | 2026-07 | 域控规范支持、PySide6 迁移、墨韵主题 |
| v6.0 | 2026-07 | 初始版本 |

详细变更见 [PROJECT_DEV.md](PROJECT_DEV.md)。
