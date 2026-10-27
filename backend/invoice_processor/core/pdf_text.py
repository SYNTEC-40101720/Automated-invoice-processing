"""PDF 文本提取与缓存

将「发票 PDF → 文本」的 I/O 与缓存逻辑从核心算法类中抽离为独立组件。
职责：
    - 原始文本提取（含加密 / 扫描件 / 损坏检测）
    - OCR 级联（pdfplumber 抽不出文本或过短时，页转图 → RapidOCR）
    - 去空白文本提取（带缓存）
    - 双缓存（带并发 sentinel 防重复解析）
    - 缓存条目复制（文件 copy2 后避免重新解析）
    - 统一日志出口（写 logging + 回调外部 UI）
"""
import logging
import re
import threading

import pdfplumber

# 缓存 sentinel：标记"正在解析中"，避免并发重复解析
_PARSE_PENDING = object()

# OCR 级联触发阈值：pdfplumber 结果去空白后不足该字符数时进入 OCR（ADR D1）
_MIN_TEXT_CHARS = 10
# pypdfium2 页渲染缩放（scale=2.0 ≈ 144 DPI，识别精度与耗时的平衡）
_OCR_RENDER_SCALE = 2.0

# ── OCR 引擎（模块级单例懒加载，首次 OCR 才初始化） ─────
_OCR_ENGINE = None
_OCR_INIT_LOCK = threading.Lock()
_OCR_DISABLED = False


def _ensure_ocr_engine():
    """模块级 OCR 引擎单例懒加载（测试通过 monkeypatch 替换本函数）。

    首次 OCR 才初始化 RapidOCR；初始化失败捕获后永久禁用 OCR 并记
    warning，不让任务崩溃。双检锁保证并发下只初始化一次。
    """
    global _OCR_ENGINE, _OCR_DISABLED
    if _OCR_DISABLED:
        return None
    if _OCR_ENGINE is None:
        with _OCR_INIT_LOCK:
            if _OCR_ENGINE is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR

                    _OCR_ENGINE = RapidOCR()
                except Exception as exc:
                    _OCR_DISABLED = True
                    logging.warning(
                        'OCR 引擎初始化失败，已永久禁用 OCR 级联: %s', exc
                    )
    return _OCR_ENGINE


class PdfTextExtractor:
    """PDF 文本提取器：封装所有文本相关 I/O 与缓存"""

    def __init__(self, log_callback=None):
        self._text_cache: dict[str, tuple[str | None, str | None]] = {}
        self._raw_text_cache: dict[str, object] = {}
        self._raw_parse_events: dict[str, threading.Event] = {}
        self._cache_lock = threading.Lock()
        self._log_callback = log_callback

    # ── 统一日志出口 ──────────────────────────────────
    def _log_core(self, msg: str, level: str = 'warning') -> None:
        """统一日志出口：写 logging + 回调外部（UI）

        注意：不使用 exc_info=True，因为在无活跃异常时会打印 `NoneType: None`。
        错误信息已包含在 msg 中；需要堆栈时由调用方在 except 块内显式记录。
        """
        log_level = {
            'info': logging.INFO,
            'success': logging.INFO,
            'warning': logging.WARNING,
            'error': logging.ERROR,
        }.get(level, logging.WARNING)
        logging.log(log_level, msg)
        if self._log_callback:
            self._log_callback(msg, level)

    def clear_cache(self) -> None:
        """清除文本缓存"""
        with self._cache_lock:
            self._text_cache.clear()
            self._raw_text_cache = {
                path: value
                for path, value in self._raw_text_cache.items()
                if value is _PARSE_PENDING
            }

    # ── OCR 级联（仅扫描件 fallback，ADR D1） ─────────
    def _ocr_enabled(self) -> bool:
        """config [ai] ocr_enabled 开关（容错；读取异常按开启处理）。"""
        try:
            from ..config_manager import is_ocr_enabled

            return is_ocr_enabled()
        except Exception as exc:
            logging.warning(f'读取 ocr_enabled 配置失败，按开启处理: {exc}')
            return True

    def _try_ocr(self, pdf_path: str) -> str | None:
        """尝试 OCR 级联，返回 OCR 文本；未启用 / 失败 / 无文本返回 None。

        异常一律在此捕获（记 warning），不改变上层原有 error 语义：
        调用方在 OCR 无效时回退 pdfplumber 原始结果（旧行为兼容）。
        """
        if not self._ocr_enabled():
            return None
        try:
            ocr_text = self._extract_text_via_ocr(pdf_path)
        except Exception as exc:
            self._log_core(f'OCR 级联失败: {pdf_path} - {exc}')
            return None
        if not ocr_text.strip():
            return None
        self._log_core(f'文本来源: OCR {pdf_path}', level='info')
        return ocr_text

    def _extract_text_via_ocr(self, pdf_path: str) -> str:
        """逐页渲染（pypdfium2）→ RapidOCR → 按阅读序拼接全文。

        渲染 / OCR 异常逐页捕获，失败页记 warning；任一页成功即算
        成功，全部失败返回 ''。加密 / 损坏导致整体打不开时向上抛。
        """
        import pypdfium2 as pdfium

        texts: list[str] = []
        doc = pdfium.PdfDocument(pdf_path)
        try:
            for index in range(len(doc)):
                page = doc[index]
                try:
                    page_text = self._ocr_single_page(page)
                except Exception as exc:
                    self._log_core(f'OCR 单页处理失败: {pdf_path} - {exc}')
                    continue
                if page_text.strip():
                    texts.append(page_text)
        finally:
            doc.close()
        return '\n'.join(texts)

    def _ocr_single_page(self, page) -> str:
        """单页 → 渲染 → OCR → 阅读序文本。异常向上抛给调用方。"""
        import numpy as np

        pil_image = page.render(scale=_OCR_RENDER_SCALE).to_pil()
        rgb_array = np.asarray(pil_image.convert('RGB'))
        ocr_result, _elapsed = self._call_ocr(rgb_array)
        return self._assemble_ocr_text(ocr_result)

    def _call_ocr(self, rgb_array):
        """调用 RapidOCR 引擎（独立方法，测试以替身替换本调用点）。"""
        engine = _ensure_ocr_engine()
        if engine is None:
            raise RuntimeError('OCR 引擎不可用（初始化失败或已禁用）')
        return engine(rgb_array)

    @staticmethod
    def _assemble_ocr_text(ocr_result) -> str:
        """RapidOCR 结果按阅读序拼装：先按 y 排序，同一行空格连接。

        同一行判定：中心 y 与当前行锚点（行首项中心 y）之差小于
        行高中位数的一半。行内按 x 排序后用空格连接，行间换行。
        """
        if not ocr_result:
            return ''
        items = []
        for box, text, _score in ocr_result:
            if not text:
                continue
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            items.append((min(ys), max(ys), min(xs), str(text)))
        if not items:
            return ''
        items.sort(key=lambda item: item[0])
        heights = [max(bottom - top, 1.0) for top, bottom, _x, _t in items]
        median_height = sorted(heights)[len(heights) // 2]
        lines: list[list[tuple[float, str]]] = []
        current: list[tuple[float, str]] = []
        current_center = 0.0
        for top, bottom, left, text in items:
            center = (top + bottom) / 2
            if current and center - current_center >= median_height / 2:
                lines.append(current)
                current = []
            if not current:
                current_center = center
            current.append((left, text))
        if current:
            lines.append(current)
        assembled_lines = []
        for line in lines:
            line.sort(key=lambda item: item[0])
            # 同一行用空格连接（ADR D1 阅读序口径）；下游去空白消费方
            # 不受影响，行程明细等原文解析按行处理
            assembled_lines.append(' '.join(t for _left, t in line))
        return '\n'.join(assembled_lines)

    # ── 原始文本提取（保留空白） ──────────────────────
    def _extract_raw_text(self, pdf_path: str) -> tuple[str | None, str | None]:
        """提取 PDF 原始文本（保留空白，带缓存 + sentinel 防并发重复解析）

        返回 (text, error_type)：
            - 成功：(text, None)
            - 失败：(None, error_type)，error_type ∈
                {'encrypted','corrupted','empty','unknown'}
        """
        while True:
            with self._cache_lock:
                val = self._raw_text_cache.get(pdf_path)
                if val is None:
                    parse_event = threading.Event()
                    self._raw_parse_events[pdf_path] = parse_event
                    self._raw_text_cache[pdf_path] = _PARSE_PENDING
                    break
                if val is not _PARSE_PENDING:
                    # 缓存值是 (text, error_type) 元组
                    return val if isinstance(val, tuple) else (val, None)
                parse_event = self._raw_parse_events.get(pdf_path)
            if parse_event is not None:
                parse_event.wait()
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # 检测加密 PDF
                if hasattr(pdf, 'is_encrypted') and pdf.is_encrypted:
                    self._log_core(
                        f'PDF 已加密，无法提取: {pdf_path}', level='warning'
                    )
                    with self._cache_lock:
                        self._raw_text_cache[pdf_path] = (None, 'encrypted')
                    return None, 'encrypted'
                pages_text = [page.extract_text() or '' for page in pdf.pages]
                text = '\n'.join(pages_text)
                stripped_len = len(re.sub(r'\s+', '', text))
                if stripped_len == 0:
                    # 完全无文本（扫描件）→ OCR 级联；OCR 未启用或失败
                    # 维持旧扫描件语义 (None, 'empty')，不中断任务
                    ocr_text = self._try_ocr(pdf_path)
                    if ocr_text:
                        with self._cache_lock:
                            self._raw_text_cache[pdf_path] = (ocr_text, None)
                        return ocr_text, None
                    self._log_core(
                        f'PDF 无文本内容（可能是扫描件）: {pdf_path}',
                        level='warning',
                    )
                    with self._cache_lock:
                        self._raw_text_cache[pdf_path] = (None, 'empty')
                    return None, 'empty'
                if stripped_len < _MIN_TEXT_CHARS:
                    # 文本过短（疑似劣质文字层）→ 尝试 OCR 升级；OCR
                    # 不可用时保留 pdfplumber 短文本（旧行为，不降级丢弃）
                    ocr_text = self._try_ocr(pdf_path)
                    if ocr_text:
                        with self._cache_lock:
                            self._raw_text_cache[pdf_path] = (ocr_text, None)
                        return ocr_text, None
                    self._log_core(
                        f'PDF 文本过短（{stripped_len} < {_MIN_TEXT_CHARS}），'
                        f'保留 pdfplumber 文本: {pdf_path}',
                        level='warning',
                    )
                with self._cache_lock:
                    self._raw_text_cache[pdf_path] = (text, None)
                self._log_core(f'文本来源: pdfplumber {pdf_path}', level='info')
                return text, None
        except Exception as e:
            err_str = str(e).lower()
            if 'encrypt' in err_str or 'password' in err_str:
                error_type = 'encrypted'
            elif 'syntax' in err_str or 'parse' in err_str or 'eof' in err_str:
                error_type = 'corrupted'
            else:
                error_type = 'unknown'
            self._log_core(
                f'PDF 文本提取失败 [{error_type}]: {pdf_path} - {e}',
                level='warning',
            )
            with self._cache_lock:
                self._raw_text_cache[pdf_path] = (None, error_type)
            return None, error_type
        finally:
            with self._cache_lock:
                parse_event = self._raw_parse_events.pop(pdf_path, None)
            if parse_event is not None:
                parse_event.set()

    # ── 去空白文本提取（带缓存） ──────────────────────
    def extract_pdf_text_with_error(
        self, pdf_path: str
    ) -> tuple[str | None, str | None]:
        """提取 PDF 文本内容（去空白，带缓存），并返回错误类型

        返回 (text, error_type)，error_type 为 None 表示成功。
        """
        with self._cache_lock:
            if pdf_path in self._text_cache:
                return self._text_cache[pdf_path]
        raw, error_type = self._extract_raw_text(pdf_path)
        if raw is None:
            result: tuple[str | None, str | None] = (None, error_type)
        else:
            result = (re.sub(r'\s+', '', raw), None)
        with self._cache_lock:
            self._text_cache[pdf_path] = result
        return result

    def extract_pdf_text(self, pdf_path: str) -> str | None:
        """提取 PDF 文件文本内容（去空白，带缓存）

        向后兼容接口：只返回文本，不返回错误类型。
        """
        text, _ = self.extract_pdf_text_with_error(pdf_path)
        return text

    # ── 缓存条目复制 ──────────────────────────────────
    def _copy_cache_entry(self, src_path: str, dest_path: str) -> None:
        """复制缓存条目（文件 copy2 后调用，避免对新路径重新解析 PDF）"""
        with self._cache_lock:
            if src_path in self._text_cache:
                self._text_cache[dest_path] = self._text_cache[src_path]
            if src_path in self._raw_text_cache:
                src_val = self._raw_text_cache[src_path]
                if src_val is not _PARSE_PENDING:
                    self._raw_text_cache[dest_path] = src_val
