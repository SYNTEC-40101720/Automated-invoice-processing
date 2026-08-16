"""发票输出文件生成与去重

封装「源 PDF → 命名输出文件」的逻辑：
    - 金额标准化（两位小数）
    - 输出文件名去重（基于标准化文件名，线程安全）
    - 内容哈希去重（基于 MD5）
    - 文件复制（copy2）
    - 税号异常文件归集（移动 / 复制，重名追加序号）
    - 通用发票处理（被各类型处理器复用）

依赖 PdfTextExtractor 完成缓存条目复制与日志出口。
"""
import os
import re
import shutil
import hashlib

from .pdf_text import PdfTextExtractor


# 各发票类型生成输出文件时的后缀映射
_PREFIX_SUFFIX: dict[str, str] = {
    "JS": "行程单.pdf",
    "H": "高铁票.pdf",
}


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


class InvoiceOutputWriter:
    """发票输出写入器：命名、去重、复制、税号异常归集"""

    def __init__(self, extractor: PdfTextExtractor):
        self._extractor = extractor
        # 输出文件去重：记录已生成的标准化文件名，避免重复源文件产生重复输出
        self._generated_names: set[str] = set()
        # 内容哈希去重：text_md5 → 首次出现的源文件名
        self._content_hashes: dict[str, str] = {}

    def reset_dedup(self) -> None:
        """清空输出去重记录（每次开始新一轮处理前调用）"""
        self._generated_names.clear()
        self._content_hashes.clear()

    # ── 输出文件名去重 ────────────────────────────────
    def _claim_output_name(self, filename: str, source_path: str) -> bool:
        """线程安全地占位一个输出文件名

        返回 True 表示首次占位成功（应继续复制），
        返回 False 表示已存在同名输出（应跳过，但源文件保留不动）。
        """
        if filename in self._generated_names:
            self._extractor._log_core(
                f"重复文件已跳过（源文件保留）: {os.path.basename(source_path)} → 输出 {filename}",
                level='warning',
            )
            return False
        self._generated_names.add(filename)
        return True

    # ── 内容哈希去重 ──────────────────────────────────
    def _check_content_duplicate(self, text: str, source_path: str) -> bool:
        """检查 PDF 文本内容是否重复（基于 MD5 哈希）

        返回 True 表示内容重复（应跳过），False 表示首次出现。
        源文件保留不动，仅记录日志。
        """
        content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        if content_hash in self._content_hashes:
            self._extractor._log_core(
                f"内容重复已跳过（源文件保留）: {os.path.basename(source_path)}"
                f"（与 {self._content_hashes[content_hash]} 内容相同）",
                level='warning',
            )
            return True
        self._content_hashes[content_hash] = os.path.basename(source_path)
        return False

    # ── 生成输出文件 ──────────────────────────────────
    def _generate_output_file(self, source_path: str, output_dir: str,
                              invoice_no: str, amount: str, prefix: str) -> str | None:
        """生成输出文件（invoice_no/amount 为已提取的字符串）

        - 金额标准化为两位小数
        - 同名输出文件去重（基于标准化文件名，线程安全）
        """
        try:
            suffix = _PREFIX_SUFFIX.get(prefix, ".pdf")
            normalized_amount = _normalize_amount(amount)
            new_filename = f"{invoice_no}-{normalized_amount}{suffix}"
            dest_path = os.path.join(output_dir, new_filename)

            # 线程安全去重：同名文件只生成一次
            if not self._claim_output_name(new_filename, source_path):
                return dest_path  # 返回目标路径，但不再复制

            shutil.copy2(source_path, dest_path)
            self._extractor._copy_cache_entry(source_path, dest_path)
            return dest_path
        except Exception:
            self._extractor._log_core(f"输出文件生成失败: {source_path}", level='warning')
            return None

    # ── 税号异常归集 ──────────────────────────────────
    def _collect_tax_issue(self, file_path: str, filename: str, tax_issue_dir: str,
                           *, copy_only: bool = False) -> str:
        """将税号异常文件移动或复制到异常目录，重名追加序号

        返回目标路径 dest_path。
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
        return dest_path

    # ── 通用发票处理（被各类型处理器复用） ────────────
    def _process_invoice(self, processor, source_path: str, output_dir: str,
                         invoice_pattern: str, amount_pattern: str,
                         prefix: str, amount_processor=None) -> str | None:
        """发票处理通用方法（processor 提供文本提取等能力）"""
        try:
            text = processor.extract_pdf_text(source_path)
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
            self._extractor._log_core(f"发票处理失败: {source_path}", level='warning')
            return None
