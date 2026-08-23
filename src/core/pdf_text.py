"""PDF 文本提取与缓存

将「发票 PDF → 文本」的 I/O 与缓存逻辑从核心算法类中抽离为独立组件。
职责：
    - 原始文本提取（含加密 / 扫描件 / 损坏检测）
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
                    self._log_core(f"PDF 已加密，无法提取: {pdf_path}", level='warning')
                    with self._cache_lock:
                        self._raw_text_cache[pdf_path] = (None, 'encrypted')
                    return None, 'encrypted'
                pages_text = [page.extract_text() or '' for page in pdf.pages]
                text = '\n'.join(pages_text)
                # 检测扫描件（无文本内容）
                if not text.strip():
                    self._log_core(
                        f"PDF 无文本内容（可能是扫描件）: {pdf_path}",
                        level='warning',
                    )
                    with self._cache_lock:
                        self._raw_text_cache[pdf_path] = (None, 'empty')
                    return None, 'empty'
                with self._cache_lock:
                    self._raw_text_cache[pdf_path] = (text, None)
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
                f"PDF 文本提取失败 [{error_type}]: {pdf_path} - {e}",
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
