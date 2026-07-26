# 项目审核报告 — 发票处理系统 V6

> 审核日期：2026-07-26 | 审核范围：全项目

---

## 一、项目概况

| 项目 | 详情 |
|------|------|
| 代码规模 | 14 个源文件，~850 行核心代码 |
| 技术栈 | Python 3 + Tkinter + sv_ttk + pdfplumber + pypdf |
| 架构 | 三层分离：入口 (`main.py`) → UI (`src/ui/`) → 核心 (`src/core/`) |
| 设计风格 | Material Design（自建色彩系统 + 自定义组件） |

---

## 二、严重问题（建议优先修复）

### 1. DPI 感知设置使用了已弃用的 API

- **文件**：[main.py:15](main.py#L15)
- **问题**：`SetProcessDpiAwareness(1)` 使用的是 `PROCESS_SYSTEM_DPI_AWARE`，该值在 Windows 10 1809+ 已被标记为弃用，窗口拖动到不同 DPI 的显示器时会出现模糊。
- **建议**：改为 `PROCESS_PER_MONITOR_DPI_AWARE_V2` (值 `2`)：

```python
# main.py
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    pass
```

### 2. 日志系统未初始化 — GUI 用户完全看不到错误

- **文件**：[src/core/processor.py](src/core/processor.py)（全文件散布 `logging.warning` / `logging.error`）
- **问题**：`logging` 模块的默认行为是输出到 stderr，但 `pyinstaller --windowed` 打包后 stderr 被丢弃。核心层的所有异常日志对最终用户不可见。
- **建议**：在 `main.py` 入口处初始化日志到文件，或在 GUI 层桥接日志到界面面板：

```python
# main.py 或 src/config.py 中添加
import logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('invoice_processor.log', encoding='utf-8'),
    ]
)
```

### 3. 使用了中文变量名

- **文件**：[src/core/processor.py:260](src/core/processor.py#L260)
- **问题**：

```python
异常_dir = os.path.join(output_dir, '税号异常')  # 中文变量名
```

虽然 Python 3 支持 Unicode 标识符，但违反 PEP 8、IDE 补全体验差、linter 可能报 warning。同一方法中英文 `tax_issues` 与中文 `异常_dir` 混用更显不一致。

- **建议**：改为 `tax_issue_dir`。

---

## 三、中等问题

### 4. `post_process` 中存在大量重复代码

- **文件**：[src/core/processor.py:260-316](src/core/processor.py#L260-L316)
- **问题**：将文件移动到「税号异常」文件夹的逻辑在"主目录遍历"和"需人工处理子目录遍历"两处写了几乎相同的代码（各 ~10 行），仅 `shutil.move` vs `shutil.copy2` 不同。
- **建议**：抽取为独立方法：

```python
def _collect_tax_issue(self, file_path, filename, issue_dir, *, copy_only=False):
    """将税号异常文件移动或复制到异常目录，重名追加序号"""
    os.makedirs(issue_dir, exist_ok=True)
    dest_path = os.path.join(issue_dir, filename)
    counter = 1
    while os.path.exists(dest_path):
        name, ext = os.path.splitext(filename)
        dest_path = os.path.join(issue_dir, f'{name}_{counter}{ext}')
        counter += 1
    if copy_only:
        shutil.copy2(file_path, dest_path)
    else:
        shutil.move(file_path, dest_path)
    return dest_path
```

### 5. `MDCard` 组件定义了但从未使用

- **文件**：[src/ui/components.py:12-74](src/ui/components.py#L12-L74)
- **问题**：`MDCard` 类实现了完整的阴影 + 圆角卡片效果，但 `app.py` 中所有卡片都是手动用普通 `Frame` 搭建的。这是死代码，占用维护成本。
- **建议**：二选一 —
  - 在 `app.py` 中将各卡片区域迁移到 `MDCard`（提升视觉一致性）
  - 删除 `MDCard` 类（减少维护负担）

### 6. `MDButton` 样式与 `app.py` 强耦合

- **文件**：[src/ui/components.py:96-108](src/ui/components.py#L96-L108)
- **问题**：`MDButton` 的 hover/press 事件引用了 `Accent.TButton.Hover` 等样式名，但这些样式定义在 `InvoiceApp._setup_styles()` 中。如果 `MDButton` 实例化早于样式注册就会报错。且 `variant='outline'` 分支引用 `TButton.Hover`（默认样式名），行为不可预期。
- **建议**：要么将样式定义提升到 `components.py`（模块级注册），要么在 `MDButton.__init__` 中自注册样式，消除外部依赖。

### 7. 核心层与 UI 层日志双轨运行、互不连通

- **文件**：[src/core/processor.py](src/core/processor.py) + [src/ui/app.py](src/ui/app.py)
- **问题**：
  - `processor.py` 使用 `logging.warning()` → 输出到 stderr
  - `app.py` 使用 `self._log()` → 写入 `log_queue` → 显示在 GUI 面板
  - 两者完全独立。核心层出错时 GUI 面板静默，用户只能看到"处理失败"的结果，无法追溯原因。
- **建议**：在 `InvoiceProcessor` 中注入日志回调，或使用 `logging.Handler` 将核心日志桥接到 GUI 日志队列。

```python
# processor.py 改造示例
class InvoiceProcessor:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback or (lambda msg, level: None)
    
    def _log(self, msg, level='warning'):
        logging.log(getattr(logging, level.upper(), logging.WARNING), msg)
        self.log_callback(msg, level)
```

### 8. 缺少单元测试

- **文件**：整个项目无 `tests/` 目录
- **问题**：核心正则匹配逻辑（`_extract_buyer_tax_id`、`determine_processor_type`、各 `process_*` 方法）严重依赖 PDF 文本格式，一个格式微调就可能导致静默失败。没有测试意味着每次修改都是盲改。
- **建议**：至少为核心方法添加参数化测试：

```python
# tests/test_processor.py
import pytest
from src.core.processor import InvoiceProcessor

@pytest.mark.parametrize("text,expected", [
    ("纳税人识别号：91320594688334374M  销售方", "91320594688334374M"),
    ("统一社会信用代码:ABCDEFGHIJKLMNOPQR  销售方", "ABCDEFGHIJKLMNOPQR"),
    ("销售方  纳税人识别号：123456789012345678", None),  # 销售方税号应过滤
])
def test_extract_buyer_tax_id(text, expected):
    processor = InvoiceProcessor()
    assert processor._extract_buyer_tax_id(text) == expected
```

---

## 四、轻微问题

### 9. 线程缓存可能存在重复解析

- **文件**：[src/core/processor.py:42-49](src/core/processor.py#L42-L49)
- **问题**：缓存的"检查-设置"不是原子操作。两个线程同时请求同一未缓存 PDF 时，都会进入 PDF 解析，浪费 CPU。虽然实际场景中每个文件只处理一次，但使用 sentinel 值标记"正在解析中"可以彻底避免这个隐患：

```python
_SENTINEL = object()

def _extract_raw_text(self, pdf_path):
    with self._cache_lock:
        if pdf_path in self._raw_text_cache:
            val = self._raw_text_cache[pdf_path]
            if val is not _SENTINEL:
                return val
            # 其他线程已在解析，等它完成
            # （简化方案：直接让第二个线程也解析一次，开销可接受）
    ...
```

### 10. `_generate_output_file` 后缀逻辑可用字典简化

- **文件**：[src/core/processor.py:211-227](src/core/processor.py#L211-L227)
- **建议**：

```python
_SUFFIX_MAP = {"JS": "行程单.pdf", "H": "高铁票.pdf"}

def _generate_output_file(self, source_path, output_dir, invoice_no, amount, prefix):
    suffix = _SUFFIX_MAP.get(prefix, ".pdf")
    new_filename = f"{invoice_no}-{amount}{suffix}"
    ...
```

### 11. `_poll_log_queue` 空闲时浪费 CPU

- **文件**：[src/ui/app.py:648-656](src/ui/app.py#L648-L656)
- **问题**：日志轮询固定 100ms 间隔，即使队列一直为空也持续消耗 CPU。GUI 空闲时 ~10Hz 的无效轮询对电池和整体体验不利。
- **建议**：动态调整间隔 —— 队列有数据时保持 100ms，连续 10 次空队列后延长到 500ms：

```python
self._idle_polls = 0
# ... 在 poll 中:
if empty:
    self._idle_polls += 1
    interval = 500 if self._idle_polls > 10 else 100
else:
    self._idle_polls = 0
    interval = 100
self.root.after(interval, self._poll_log_queue)
```

### 12. 缺少类型注解

- **文件**：全项目
- **问题**：Python 3.10+ 原生支持 `X | None` 联合类型语法，但项目完全没有使用。对于多线程 + 文件路径传递 + 缓存管理这种容易出错的场景，类型注解价值很大。
- **建议**：至少为核心模块添加关键方法签名：

```python
from typing import Callable

def extract_pdf_text(self, pdf_path: str) -> str | None: ...
def determine_processor_type(self, text: str) -> Callable | None: ...
def create_amount_mapping(self, folder_path: str) -> dict[str, str]: ...
```

### 13. 项目缺少 `pyproject.toml`

- **问题**：只有 `requirements.txt`，没有现代化的 `pyproject.toml`。后者可以集中管理：项目元数据、依赖声明、linter 配置（ruff/mypy）、pytest 配置。
- **建议**：创建最小化的 `pyproject.toml`：

```toml
[project]
name = "invoice-processor"
version = "6.0.0"
requires-python = ">=3.10"
dependencies = [
    "pdfplumber>=0.11.0",
    "pypdf>=4.0",
    "sv_ttk>=2.0.0",
]

[project.scripts]
invoice-processor = "main:main"

[tool.ruff]
target-version = "py310"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

### 14. `process_general_invoice` 的 fallback 正则太宽松

- **文件**：[src/core/processor.py:107](src/core/processor.py#L107)
- **问题**：

```python
pattern2 = re.search(r'(?<!\d)(\d{20})(?!\d)', text)
```

这个 fallback 匹配任意 20 位连续数字，可能误匹配密码区数字、校验码等非发票号内容。
- **建议**：限制 fallback 匹配上下文 —— 只在与金额关键字同行或临近的位置匹配：

```python
# 只在金额相关内容附近匹配，降低误匹配风险
pattern2 = re.search(r'(?:金额|合计|价税).{0,30}(?<!\d)(\d{20})(?!\d)', text)
```

### 15. `post_process` 行末注释使用了中文引号格式不一致

- **文件**：[src/core/processor.py:244-316](src/core/processor.py#L244-L316)
- **问题**：同方法内注释混用了 `①` `②` `③④`（带圈数字）和普通编号，视觉上不统一。

---

## 五、改进优先级建议

| 优先级 | 改进项 | 预估工作量 | 影响范围 |
|--------|--------|-----------|---------|
| 🔴 P0 | 初始化日志配置 | 5 分钟 | 全局 |
| 🔴 P0 | 修复 DPI API | 2 分钟 | `main.py` |
| 🟡 P1 | 消除重复代码 | 15 分钟 | `processor.py` |
| 🟡 P1 | 桥接核心层与 UI 层日志 | 20 分钟 | `processor.py` + `app.py` |
| 🟡 P1 | 添加核心逻辑单元测试 | 1-2 小时 | `tests/` |
| 🟢 P2 | 清理死代码 (MDCard) 或启用 | 10 分钟 | `components.py` |
| 🟢 P2 | 添加类型注解 | 30 分钟 | 全项目 |
| 🟢 P2 | 创建 `pyproject.toml` | 5 分钟 | 项目根目录 |
| 🟢 P3 | 优化日志轮询间隔 | 5 分钟 | `app.py` |
| 🟢 P3 | 收紧 fallback 正则 | 10 分钟 | `processor.py` |

---

## 六、整体评价

**优点**：
- 三层架构清晰，业务逻辑与 UI 严格分离
- 多线程并发设计基本正确（缓存锁、UI 节流、future 管理）
- Material Design 色彩系统独立为常量类，便于主题切换
- 代码注释详尽（中文），对团队新人友好
- README 文档完整，包含安装步骤与项目结构图

**短板**：
- 工程化程度不足（无测试、无日志初始化、无类型注解）
- 存在少量死代码和重复逻辑
- 核心算法层完全依赖正则匹配 PDF 文本，容错能力有限（PDF 格式微调即可能失效）

**总体**：作为一个内部工具，代码质量和架构设计都在可用线以上。补上测试和日志初始化后即可作为稳定版本发布。
