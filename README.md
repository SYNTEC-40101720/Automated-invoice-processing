# 发票处理V6

## 项目介绍
发票处理V6 是一个基于 Python 3 和 Tkinter（搭配 sv_ttk 主题）开发的 Windows 桌面应用程序，采用 Material Design 风格界面，用于批量识别、重命名、校验与合并 PDF 电子发票。

## 功能特点
- 📋 自动识别多种类型的 PDF 电子发票（浙江/宁波通用、江苏通行费、江苏行程单、高铁票、滴滴行程单、通用电子发票等）
- 🔁 按规则提取发票号与金额，重命名输出文件
- 🔍 异常税号检测，自动归集到「税号异常」子目录
- 📑 将所有处理后的 PDF 合并为单个 PDF 文件
- 🧵 多线程并发处理，带进度条与彩色日志面板

## 环境要求
- Python 3.10+
- Windows 操作系统（代码使用 `os.startfile` 与 `ctypes.windll`）
- 依赖包详见 `requirements.txt`

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
发票处理/
├── main.py                       # 程序入口
├── requirements.txt              # 依赖包列表
├── version_info.txt              # PyInstaller Windows 版本信息资源
├── README.md                     # 项目说明
├── CODE_WIKI.md                  # 代码 Wiki 文档
├── src/                          # 源代码包
│   ├── __init__.py
│   ├── config.py                 # 集中配置（目标税号、线程数、窗口尺寸、字体）
│   ├── core/                     # 业务逻辑层
│   │   ├── __init__.py
│   │   └── processor.py          # InvoiceProcessor 发票处理核心类
│   └── ui/                       # 表现层与 UI 组件
│       ├── __init__.py
│       ├── app.py                # InvoiceApp 主窗口
│       ├── colors.py             # MDColors Material Design 色彩常量
│       └── components.py         # MDCard / MDButton / MDIconLabel / LogText
├── build/                        # PyInstaller 构建中间产物（自动生成）
└── dist/                         # PyInstaller 发布产物（自动生成）
    └── SYNTEC-发票处理系统/
```

## 模块职责
| 模块 | 职责 |
|---|---|
| `main.py` | 程序入口，创建 Tk 根窗口、设置 DPI 感知 |
| `src/config.py` | 集中存放可配置常量（目标税号、线程数、窗口尺寸、字体族） |
| `src/core/processor.py` | 发票处理核心算法：PDF 文本提取、类型路由、正则解析、重命名、税号校验、PDF 合并 |
| `src/ui/app.py` | 主窗口布局、样式、事件分发、并发调度、日志轮询 |
| `src/ui/colors.py` | Material Design 色彩规范常量 |
| `src/ui/components.py` | 可复用 UI 组件（卡片、按钮、图标标签、日志面板） |

## 配置说明
如需修改以下参数，编辑 `src/config.py`：
- `TARGET_TAX_ID`：税号校验目标税号（默认 `91320594688334374M`）
- `MAX_WORKERS`：并发处理线程数上限（默认 `min(8, cpu_count)`）
- `WINDOW_GEOMETRY`：主窗口初始尺寸
- `WINDOW_MIN_SIZE`：主窗口最小尺寸

## 版本信息
详细版本历史请查看 `version_info.txt` 文件（CompanyName: SYNTEC, Version: 1.0.0.0）

## 开发规范
- 模块化设计，逻辑与界面分离
- 业务层（`src/core/`）不依赖任何 tkinter 模块
- 代码遵循 PEP8 规范
- 所有注释使用中文
- 使用 Emoji 符号替代图片资源
