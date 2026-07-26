import os
import re
import shutil
import hashlib
import threading
import logging
from datetime import datetime
from collections.abc import Callable

import pdfplumber
from pypdf import PdfReader, PdfWriter

from .. import config as _cfg


# ═══════════════════════════════════════════════════════════
# 发票处理核心算法类
# ═══════════════════════════════════════════════════════════

# 各发票类型生成输出文件时的后缀映射
_PREFIX_SUFFIX: dict[str, str] = {
    "JS": "行程单.pdf",
    "H": "高铁票.pdf",
}

# 缓存 sentinel：标记"正在解析中"，避免并发重复解析
_PARSE_PENDING = object()

# 发票类型注册表：[(keywords, method_name), ...]
# 顺序敏感 —— 越具体越靠前，通用 fallback 放最后
_TYPE_REGISTRY: list[tuple[tuple[str, ...], str]] = []


def register_type(*keywords: str):
    """装饰器：注册发票类型处理器及其匹配关键字

    用法：
        @register_type('浙江通用（电子）发票', '宁波通用（电子）发票')
        def process_zhejiang_invoice(self, source_path, output_dir): ...
    """
    def deco(fn):
        _TYPE_REGISTRY.append((keywords, fn.__name__))
        return fn
    return deco


class InvoiceProcessor:
    """发票处理核心算法类"""

    def __init__(self, log_callback: Callable[[str, str], None] | None = None):
        self._text_cache: dict[str, str] = {}
        self._raw_text_cache: dict[str, str] = {}
        self._cache_lock = threading.Lock()
        self._log_callback = log_callback
        # 输出文件去重：记录已生成的标准化文件名，避免重复源文件产生重复输出
        self._generated_names: set[str] = set()
        # 内容哈希去重：text_md5 → 首次出现的源文件名
        self._content_hashes: dict[str, str] = {}
        self._dedup_lock = threading.Lock()

    # ── 内部日志辅助 ──────────────────────────────────────
    def _log_core(self, msg: str, level: str = 'warning') -> None:
        """统一日志出口：写 logging + 回调外部（UI）

        注意：不使用 exc_info=True，因为在无活跃异常时会打印 `NoneType: None`。
        错误信息已包含在 msg 中；需要堆栈时由调用方在 except 块内显式记录。
        """
        log_level = {'info': logging.INFO, 'success': logging.INFO,
                     'warning': logging.WARNING, 'error': logging.ERROR}.get(level, logging.WARNING)
        logging.log(log_level, msg)
        if self._log_callback:
            self._log_callback(msg, level)

    def reset_dedup(self) -> None:
        """清空输出去重记录（每次开始新一轮处理前调用）"""
        with self._dedup_lock:
            self._generated_names.clear()
            self._content_hashes.clear()

    # ── 税号提取 ──────────────────────────────────────────
    @staticmethod
    def _extract_buyer_tax_id(text: str | None) -> str | None:
        """提取购买方税号（统一社会信用代码，固定 18 位）

        发票文本含购买方与销售方两个「纳税人识别号」字段，购买方在前。
        策略: 在「销售方」关键字之前的文本中匹配第一个税号，避免误取销售方税号。
        长度固定 18 位，避免吞掉紧随其后的密码区数字。
        """
        if not text:
            return None
        buyer_text = re.split(r'销\s*售\s*方', text, maxsplit=1)[0]
        m = re.search(r'(?:纳税人识别号|统一社会信用代码)[:：]\s*([A-Z0-9]{18})', buyer_text)
        return m.group(1) if m else None

    def _extract_raw_text(self, pdf_path: str) -> tuple[str | None, str | None]:
        """提取 PDF 原始文本（保留空白，带缓存 + sentinel 防并发重复解析）

        返回 (text, error_type)：
            - 成功：(text, None)
            - 失败：(None, error_type)，error_type ∈ {'encrypted','corrupted','empty','unknown'}
        """
        with self._cache_lock:
            val = self._raw_text_cache.get(pdf_path)
            if val is not None:
                if val is _PARSE_PENDING:
                    return None, None  # 正在解析中（其他线程会填充）
                # 缓存值是 (text, error_type) 元组
                return val if isinstance(val, tuple) else (val, None)
            # 标记为解析中，阻止其他线程重复解析
            self._raw_text_cache[pdf_path] = _PARSE_PENDING
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
                    self._log_core(f"PDF 无文本内容（可能是扫描件）: {pdf_path}", level='warning')
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
            self._log_core(f"PDF 文本提取失败 [{error_type}]: {pdf_path} - {e}", level='warning')
            with self._cache_lock:
                self._raw_text_cache[pdf_path] = (None, error_type)
            return None, error_type

    def extract_pdf_text_with_error(self, pdf_path: str) -> tuple[str | None, str | None]:
        """提取 PDF 文本内容（去空白，带缓存），并返回错误类型

        返回 (text, error_type)，error_type 为 None 表示成功。
        """
        with self._cache_lock:
            if pdf_path in self._text_cache:
                cached = self._text_cache[pdf_path]
                # 缓存值可能是 (text, error_type) 元组或旧格式 str
                if isinstance(cached, tuple):
                    return cached
                return cached, None
        raw, error_type = self._extract_raw_text(pdf_path)
        if raw is None:
            with self._cache_lock:
                self._text_cache[pdf_path] = (None, error_type)
            return None, error_type
        result = re.sub(r'\s+', '', raw)
        with self._cache_lock:
            self._text_cache[pdf_path] = (result, None)
        return result, None

    def extract_pdf_text(self, pdf_path: str) -> str | None:
        """提取 PDF 文件文本内容（去空白，带缓存）

        向后兼容接口：只返回文本，不返回错误类型。
        """
        text, _ = self.extract_pdf_text_with_error(pdf_path)
        return text

    def _copy_cache_entry(self, src_path: str, dest_path: str) -> None:
        """复制缓存条目（文件 copy2 后调用，避免对新路径重新解析 PDF）"""
        with self._cache_lock:
            if src_path in self._text_cache:
                self._text_cache[dest_path] = self._text_cache[src_path]
            if src_path in self._raw_text_cache:
                src_val = self._raw_text_cache[src_path]
                if src_val is not _PARSE_PENDING:
                    self._raw_text_cache[dest_path] = src_val

    def clear_cache(self) -> None:
        """清除文本缓存"""
        with self._cache_lock:
            self._text_cache.clear()
            self._raw_text_cache.clear()

    @register_type('浙江通用（电子）发票', '宁波通用（电子）发票')
    def process_zhejiang_invoice(self, source_path, output_dir):
        """处理浙江/宁波通用电子发票"""
        return self._process_invoice(
            source_path, output_dir,
            r'发票号码[:：]\s*(\d+)',
            r'（小写）\s+([\d.]+)',
            "ZJ"
        )

    @register_type('江苏省车辆通行费票据（电子）')
    def process_jiangsu_toll(self, source_path, output_dir):
        """处理江苏通行费票据"""
        return self._process_invoice(
            source_path, output_dir,
            r'票据号码[：:]\s*(\d{10})',
            r'（小写）\s*([\d.]+\d{2})',
            "JST"
        )

    @register_type('江苏省车辆通行费电子票据行程单')
    def process_jiangsu_invoice(self, source_path, output_dir):
        """处理江苏车辆通行费电子票据行程单"""
        return self._process_invoice(
            source_path, output_dir,
            r'发票号码\s+(\d+)',
            r'累计金额\(元\)\s+([\d.]+)',
            "JS"
        )

    @register_type('中国铁路', '二等座', '一等座')
    def process_highspeed_rail(self, source_path, output_dir):
        """处理高铁票"""
        return self._process_invoice(
            source_path, output_dir,
            r'(?:电子发票号码|发票号码)[\s:：]*([A-Z0-9]{20})',
            r'(?:金额|￥)\s*([\d,.]+)',
            "H",
            lambda x: x.replace(',', '')
        )

    @register_type('滴滴出行-行程单', '—行程单')
    def process_didi_trip(self, source_path, output_dir):
        """处理滴滴行程单"""
        try:
            text = self.extract_pdf_text(source_path)
            amount_match = re.search(r'合计([\d.,]+)元', text)
            if amount_match:
                clean_amount = "{:.2f}".format(float(amount_match.group(1).replace(',', '')))
                new_filename = f"待搜索-{clean_amount}行程单.pdf"
                dest_path = os.path.join(output_dir, new_filename)
                if not self._claim_output_name(new_filename, source_path):
                    return dest_path  # 重复，跳过
                shutil.copy2(source_path, dest_path)
                self._copy_cache_entry(source_path, dest_path)
                return dest_path
            else:
                return None
        except Exception:
            self._log_core(f"滴滴行程单处理失败: {source_path}", level='warning')
            return None

    @register_type('收费公路通行费电子票据汇总单')
    def process_toll_summary(self, source_path, output_dir):
        """处理收费公路通行费电子票据汇总单（按行程索引）

        提取第一张票据的号码和含税金额，命名为 {票据号码}-{金额}行程单.pdf
        支持两种票据格式:
        - 传统票据: 12位票据代码 + 8位票据号码 + 金额
        - 数电发票: * + 20位发票号码 + 金额
        注意: 此类汇总单字段间靠空格分隔，需保留空白，故使用 _extract_raw_text 而非去空白的 extract_pdf_text。
        """
        try:
            text, _ = self._extract_raw_text(source_path)
            if not text:
                return None
            # 在 "票据信息" 锚点后, 优先匹配传统票据(12位代码 + 8位号码 + 金额)
            m = re.search(r'票据信息.*?(\d{12})\s+(\d{8})\s+([\d.]+)', text, re.DOTALL)
            if m:
                invoice_no = m.group(2)
                amount = m.group(3)
            else:
                # 数电发票格式: * + 20位号码 + 金额
                m = re.search(r'票据信息.*?\*\s*(\d{20})\s+([\d.]+)', text, re.DOTALL)
                if m:
                    invoice_no = m.group(1)
                    amount = m.group(2)
                else:
                    return None
            new_filename = f"{invoice_no}-{self._normalize_amount(amount)}行程单.pdf"
            dest_path = os.path.join(output_dir, new_filename)
            if not self._claim_output_name(new_filename, source_path):
                return dest_path  # 重复，跳过
            shutil.copy2(source_path, dest_path)
            self._copy_cache_entry(source_path, dest_path)
            return dest_path
        except Exception:
            self._log_core(f"通行费汇总单处理失败: {source_path}", level='warning')
            return None

    @register_type('电子发票', '电 子 发 票', '发票号码', '票据号码')
    def process_general_invoice(self, source_path, output_dir):
        """处理通用电子发票（fallback）"""
        try:
            text = self.extract_pdf_text(source_path)
            if not text:
                return None
            pattern1 = re.search(r'(?:发票号码|发\s*票\s*号\s*码)[\s:：]*(\d{8,20})', text)
            # fallback: 在金额关键字附近匹配 20 位连续数字，降低误匹配概率
            pattern2 = re.search(r'(?:金额|合计|价税|小写).{0,30}(?<!\d)(\d{20})(?!\d)', text)
            invoice_match = pattern1 if pattern1 else pattern2
            amount_match = re.search(r'[（(]\s*小写\s*[）)]\s*[:：]?\s*[¥￥]?\s*([\d.]+)', text)
            if not (invoice_match and amount_match):
                return None
            return self._generate_output_file(
                source_path, output_dir,
                invoice_match.group(1), amount_match.group(1), "F"
            )
        except Exception:
            self._log_core(f"通用发票处理失败: {source_path}", level='warning')
            return None

    def _process_invoice(self, source_path, output_dir, invoice_pattern, amount_pattern, prefix, amount_processor=None):
        """发票处理通用方法"""
        try:
            text = self.extract_pdf_text(source_path)
            if not text:
                return None
            invoice_match = re.search(invoice_pattern, text)
            amount_match = re.search(amount_pattern, text)
            if not (invoice_match and amount_match):
                return None
            invoice_no = invoice_match.group(1)
            amount = amount_match.group(1)
            if amount_processor:
                amount = amount_processor(amount)
            return self._generate_output_file(source_path, output_dir, invoice_no, amount, prefix)
        except Exception:
            self._log_core(f"发票处理失败: {source_path}", level='warning')
            return None

    @staticmethod
    def _normalize_amount(amount: str) -> str:
        r"""金额标准化为两位小数字符串

        保证 create_amount_mapping 正则 ^(\d+\.\d{2}) 能匹配，
        同时避免同一发票因 771.8 / 771.80 产生两个文件。
        非数值金额（理论上不会出现）原样返回。
        """
        try:
            return "{:.2f}".format(float(amount))
        except (ValueError, TypeError):
            return amount

    def _claim_output_name(self, filename: str, source_path: str) -> bool:
        """线程安全地占位一个输出文件名

        返回 True 表示首次占位成功（应继续复制），
        返回 False 表示已存在同名输出（应跳过，但源文件保留不动）。
        """
        with self._dedup_lock:
            if filename in self._generated_names:
                self._log_core(
                    f"重复文件已跳过（源文件保留）: {os.path.basename(source_path)} → 输出 {filename}",
                    level='warning',
                )
                return False
            self._generated_names.add(filename)
            return True

    def _check_content_duplicate(self, text: str, source_path: str) -> bool:
        """检查 PDF 文本内容是否重复（基于 MD5 哈希）

        返回 True 表示内容重复（应跳过），False 表示首次出现。
        源文件保留不动，仅记录日志。
        """
        content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        with self._dedup_lock:
            if content_hash in self._content_hashes:
                self._log_core(
                    f"内容重复已跳过（源文件保留）: {os.path.basename(source_path)}"
                    f"（与 {self._content_hashes[content_hash]} 内容相同）",
                    level='warning',
                )
                return True
            self._content_hashes[content_hash] = os.path.basename(source_path)
            return False

    def _generate_output_file(self, source_path: str, output_dir: str,
                              invoice_no: str, amount: str, prefix: str) -> str | None:
        """生成输出文件（invoice_no/amount 为已提取的字符串）

        - 金额标准化为两位小数
        - 同名输出文件去重（基于标准化文件名，线程安全）
        """
        try:
            suffix = _PREFIX_SUFFIX.get(prefix, ".pdf")
            normalized_amount = self._normalize_amount(amount)
            new_filename = f"{invoice_no}-{normalized_amount}{suffix}"
            dest_path = os.path.join(output_dir, new_filename)

            # 线程安全去重：同名文件只生成一次
            if not self._claim_output_name(new_filename, source_path):
                return dest_path  # 返回目标路径，但不再复制

            shutil.copy2(source_path, dest_path)
            self._copy_cache_entry(source_path, dest_path)
            return dest_path
        except Exception:
            self._log_core(f"输出文件生成失败: {source_path}", level='warning')
            return None

    def _collect_tax_issue(self, file_path: str, filename: str, tax_issue_dir: str,
                           *, copy_only: bool = False, folder_created: bool = False) -> tuple[str, bool]:
        """将税号异常文件移动或复制到异常目录，重名追加序号

        返回 (dest_path, folder_created)。
        copy_only=True 时使用 copy2 保留原文件，否则用 move。
        """
        os.makedirs(tax_issue_dir, exist_ok=True)
        dest_path = os.path.join(tax_issue_dir, filename)
        counter = 1
        while os.path.exists(dest_path):
            name, ext = os.path.splitext(filename)
            dest_path = os.path.join(tax_issue_dir, f'{name}_{counter}{ext}')
            counter += 1
        if copy_only:
            shutil.copy2(file_path, dest_path)
        else:
            shutil.move(file_path, dest_path)
        return dest_path, True  # folder_created 始终为 True（os.makedirs 保证）

    def create_amount_mapping(self, folder_path: str) -> dict[str, str]:
        """创建金额映射表"""
        amount_map: dict[str, str] = {}
        for filename in os.listdir(folder_path):
            if filename.startswith('待搜索'):
                continue
            parts = filename.split('-', 1)
            if len(parts) >= 2:
                invoice_part, amount_part = parts
                amount_match = re.match(r'^(\d+\.\d{2})(?:行程单)?\.pdf$', amount_part)
                if amount_match:
                    amount = amount_match.group(1)
                    amount_map[amount] = invoice_part
        return amount_map

    def post_process(self, output_dir: str, progress_callback: Callable[[float], None] | None = None) -> dict:
        """后处理：金额映射 + 待搜索替换 + 税号检查 + PDF 合并（单次文本遍历）

        Args:
            output_dir: 输出目录
            progress_callback: 后处理进度回调，参数为 0.0~1.0 的进度比例
                - 0.00: 开始
                - 0.05: 金额映射完成
                - 0.10: 待搜索替换完成
                - 0.10~0.70: 税号检查+分类（按文件数线性）
                - 0.75: 人工处理扫描完成
                - 0.75~0.95: PDF 合并（按文件数线性）
                - 1.00: 全部完成

        返回: {'amount_map': dict, 'tax_issues': list[str], 'merged': str|None}
        """
        def _report(ratio: float) -> None:
            if progress_callback is not None:
                try:
                    progress_callback(ratio)
                except Exception:
                    pass  # 回调失败不影响主流程

        _report(0.00)
        # ① 金额映射（仅文件名解析，快）
        amount_map = self.create_amount_mapping(output_dir)
        _report(0.05)
        # ② 待搜索替换（仅重命名/移动，快）
        self.replace_placeholder_files(output_dir, amount_map)
        _report(0.10)
        # ③④ 单次遍历：税号检查 + 合并分类
        tax_issues: list[str] = []
        special_invoices: list[str] = []
        normal_files: list[str] = []
        tax_issue_dir = os.path.join(output_dir, '税号异常')
        folder_created = False

        # 先列出所有 PDF 用于按文件数报告进度
        all_pdfs = [f for f in os.listdir(output_dir)
                    if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(output_dir, f))]
        total_pdfs = len(all_pdfs)
        # 税号检查+分类阶段占 0.10 → 0.70
        for idx, filename in enumerate(all_pdfs):
            file_path = os.path.join(output_dir, filename)
            text = self.extract_pdf_text(file_path)
            # 税号检查（命中缓存，无额外解析开销）
            if text:
                tax_id = self._extract_buyer_tax_id(text)
                if tax_id and tax_id != _cfg.TARGET_TAX_ID:
                    _, folder_created = self._collect_tax_issue(
                        file_path, filename, tax_issue_dir, folder_created=folder_created,
                    )
                    tax_issues.append(
                        f'税号异常: {filename} -> {tax_id}，已移动到税号异常文件夹'
                    )
                    continue  # 异常文件不参与合并
            # 合并分类
            if ('专用发票' in filename or '高铁票' in filename) or \
               (text and ('专用' in text or '增值税专用发票' in text)):
                special_invoices.append(filename)
            else:
                normal_files.append(filename)
            # 按文件数线性报告（0.10 → 0.70）
            if total_pdfs > 0:
                _report(0.10 + 0.60 * (idx + 1) / total_pdfs)
        _report(0.70)

        # 扫描 需人工处理/ 子目录（异常文件复制，保留原文件）
        manual_dir = os.path.join(output_dir, '需人工处理')
        if os.path.isdir(manual_dir):
            for filename in os.listdir(manual_dir):
                if not filename.lower().endswith('.pdf'):
                    continue
                file_path = os.path.join(manual_dir, filename)
                if not os.path.isfile(file_path):
                    continue
                text = self.extract_pdf_text(file_path)
                if not text:
                    continue
                tax_id_match = re.search(r'(?:纳税人识别号|统一社会信用代码)[:：]\s*([A-Z0-9]{15,20})', text)
                if tax_id_match:
                    tax_id = tax_id_match.group(1)
                    if tax_id != _cfg.TARGET_TAX_ID:
                        _, folder_created = self._collect_tax_issue(
                            file_path, filename, tax_issue_dir,
                            copy_only=True, folder_created=folder_created,
                        )
                        tax_issues.append(
                            f'税号异常: {filename} -> {tax_id}，已复制到税号异常文件夹（原文件保留在需人工处理）'
                        )
        _report(0.75)

        # ⑤ 合并（0.75 → 1.00，按文件数线性）
        def _on_merge_progress(ratio: float) -> None:
            # 合并内部进度 0.0~1.0 → 后处理进度 0.75~1.00
            _report(0.75 + 0.25 * ratio)
        _report(0.75)
        merged = self._merge_classified_pdfs(
            output_dir, special_invoices, normal_files,
            progress_callback=_on_merge_progress,
        )
        _report(1.00)
        return {'amount_map': amount_map, 'tax_issues': tax_issues, 'merged': merged}

    def replace_placeholder_files(self, folder_path, amount_map):
        """替换待搜索文件（匹配失败的移动到 需人工处理/ 子目录）"""
        manual_dir = os.path.join(folder_path, '需人工处理')
        for filename in os.listdir(folder_path):
            if not filename.startswith('待搜索'):
                continue
            parts = filename.split('-', 1)
            if len(parts) < 2:
                continue
            _, remainder = parts
            amount_match = re.match(r'^(\d+\.\d{2})(?:行程单)?\.pdf$', remainder)
            if not amount_match:
                continue
            amount = amount_match.group(1)
            invoice_no = amount_map.get(amount)
            old_path = os.path.join(folder_path, filename)
            if invoice_no:
                new_name = f"{invoice_no}-{remainder}"
                new_path = os.path.join(folder_path, new_name)
                if not os.path.exists(new_path):
                    os.rename(old_path, new_path)
            else:
                # 匹配失败: 移动到需人工处理子目录
                os.makedirs(manual_dir, exist_ok=True)
                new_path = os.path.join(manual_dir, filename)
                counter = 1
                while os.path.exists(new_path):
                    name, ext = os.path.splitext(filename)
                    new_path = os.path.join(manual_dir, f'{name}_{counter}{ext}')
                    counter += 1
                shutil.move(old_path, new_path)

    def determine_processor_type(self, text):
        """根据文本内容确定发票类型（注册表模式）

        遍历 _TYPE_REGISTRY，按注册顺序匹配关键字，返回首个命中的处理器。
        新增类型只需用 @register_type 装饰对应方法，无需修改本方法。
        """
        for keywords, method_name in _TYPE_REGISTRY:
            if any(kw in text for kw in keywords):
                return getattr(self, method_name)
        return None

    def create_output_directory(self, base_dir):
        """创建输出目录"""
        timestamp_dir = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.join(base_dir, timestamp_dir)
        try:
            os.makedirs(output_dir, exist_ok=True)
            return output_dir
        except PermissionError:
            output_dir = os.path.join(os.path.expanduser('~'), 'Desktop', '发票输出', timestamp_dir)
            os.makedirs(output_dir, exist_ok=True)
            return output_dir

    def _merge_classified_pdfs(self, output_dir, special_invoices, normal_files,
                                progress_callback: Callable[[float], None] | None = None):
        """合并已分类的PDF文件

        业务规则：专票/高铁票需双份（抵扣联+发票联），每个文件 append 两遍；
        普通发票单份即可。

        Args:
            progress_callback: 合并进度回调，参数为 0.0~1.0
        """
        def _report(ratio: float) -> None:
            if progress_callback is not None:
                try:
                    progress_callback(ratio)
                except Exception:
                    pass

        try:
            writer = PdfWriter()
            # 计算总工作量：专票双份 + 普通单份
            total_work = len(special_invoices) * 2 + len(normal_files)
            done = 0

            # 专票/高铁票：每个文件 append 两遍（双份）
            for filename in special_invoices:
                file_path = os.path.join(output_dir, filename)
                with open(file_path, 'rb') as f:
                    reader = PdfReader(f)
                    writer.append(reader)
                    writer.append(reader)  # 第二份
                done += 2
                if total_work > 0:
                    _report(done / total_work * 0.7)  # 合并占 0~70%，写入占 30%

            # 普通发票：单份
            for filename in normal_files:
                file_path = os.path.join(output_dir, filename)
                with open(file_path, 'rb') as f:
                    writer.append(PdfReader(f))
                done += 1
                if total_work > 0:
                    _report(done / total_work * 0.7)

            _report(0.7)  # 所有文件已追加
            merged_path = os.path.join(output_dir, '合并结果.pdf')
            with open(merged_path, 'wb') as f:
                writer.write(f)
            writer.close()
            _report(1.0)
            return merged_path
        except Exception:
            self._log_core(f"PDF 合并失败: {output_dir}", level='error')
            return None

    def merge_pdfs(self, output_dir):
        """合并PDF文件（向后兼容包装：自行分类后委托 _merge_classified_pdfs）"""
        special_invoices = []
        normal_files = []
        for filename in os.listdir(output_dir):
            if not filename.lower().endswith('.pdf'):
                continue
            file_path = os.path.join(output_dir, filename)
            if not os.path.isfile(file_path):
                continue
            text = self.extract_pdf_text(file_path)
            if ('专用发票' in filename or '高铁票' in filename) or (text and ('专用' in text or '增值税专用发票' in text)):
                special_invoices.append(filename)
            else:
                normal_files.append(filename)
        return self._merge_classified_pdfs(output_dir, special_invoices, normal_files)
