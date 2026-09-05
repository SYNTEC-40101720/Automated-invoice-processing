"""发票处理核心

`InvoiceProcessor` 是外观（facade）/ 编排者，组合以下独立组件：
    - PdfTextExtractor   : PDF 文本提取与缓存（纯 I/O，零业务）
    - InvoiceOutputWriter: 输出文件命名 / 去重 / 复制 / 税号异常归集
    - PdfMerger          : PDF 合并与分类
    - invoice_types      : 发票类型注册表与各类型处理逻辑

公共 API 与历史版本一致（含被测试 / UI 直接依赖的方法），内部实现委托给上述组件。
职责划分清晰后，本类只负责：构造组件、薄委托、以及 post_process 的编排。
"""
import os
import re
import shutil
from collections.abc import Callable
from datetime import datetime

from .. import config as _cfg
from .excel_summary import generate_expense_summary as _generate_excel
from .invoice_output import (
    _PREFIX_SUFFIX,
    InvoiceOutputWriter,
    _normalize_amount,
)
from .invoice_types import (
    _TYPE_REGISTRY,
    determine_processor_type,
    process_didi_trip,
    process_general_invoice,
    process_highspeed_rail,
    process_jiangsu_invoice,
    process_jiangsu_toll,
    process_toll_summary,
    process_zhejiang_invoice,
)
from .pdf_merge import MERGED_FILENAME, PdfMerger, classify_invoice
from .pdf_text import PdfTextExtractor

__all__ = ['InvoiceProcessor', '_PREFIX_SUFFIX', '_TYPE_REGISTRY']

_NON_INVOICE_MARKERS = ('行程单', '高铁票')

# ═══════════════════════════════════════════════════════════
# 发票处理核心：外观 / 编排者
# ═══════════════════════════════════════════════════════════

class InvoiceProcessor:
    """发票处理核心：组合提取 / 输出 / 合并能力并编排后处理流程"""

    def __init__(self, log_callback: Callable[[str, str], None] | None = None):
        self._extractor = PdfTextExtractor(log_callback)
        self._writer = InvoiceOutputWriter(self._extractor)
        self._merger = PdfMerger(self._extractor)
        self._log_callback = log_callback

    # ── 日志 / 缓存（委托提取器） ──────────────────────
    def _log_core(self, msg: str, level: str = 'warning') -> None:
        self._extractor._log_core(msg, level)

    def clear_cache(self) -> None:
        self._extractor.clear_cache()

    def reset_dedup(self) -> None:
        self._writer.reset_dedup()

    def check_content_duplicate(self, text: str, source_path: str) -> bool:
        """判断文本内容是否已处理过，供应用层编排使用。"""
        return self._writer._check_content_duplicate(text, source_path)

    # ── 文本提取（委托提取器） ────────────────────────
    def _extract_raw_text(self, pdf_path: str) -> tuple[str | None, str | None]:
        return self._extractor._extract_raw_text(pdf_path)

    def extract_pdf_text_with_error(
        self, pdf_path: str
    ) -> tuple[str | None, str | None]:
        return self._extractor.extract_pdf_text_with_error(pdf_path)

    def extract_pdf_text(self, pdf_path: str) -> str | None:
        return self._extractor.extract_pdf_text(pdf_path)

    def _copy_cache_entry(self, src_path: str, dest_path: str) -> None:
        self._extractor._copy_cache_entry(src_path, dest_path)

    # ── 纯函数静态方法（无状态，可独立测试） ──────────
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
        m = re.search(
            r'(?:纳税人识别号|统一社会信用代码)[:：]\s*'
            r'([A-Z0-9]{18})',
            buyer_text,
        )
        return m.group(1) if m else None

    @staticmethod
    def _requires_tax_id_check(filename: str) -> bool:
        """仅对发票执行购买方税号校验，行程单等凭证跳过。"""
        return not any(marker in filename for marker in _NON_INVOICE_MARKERS)

    _normalize_amount = staticmethod(_normalize_amount)

    _classify_invoice = staticmethod(classify_invoice)

    # ── 输出写入（委托写入器） ────────────────────────
    def _claim_output_name(
        self,
        filename: str,
        source_path: str,
        output_dir: str | None = None,
    ) -> bool:
        return self._writer._claim_output_name(filename, source_path, output_dir)

    def _check_content_duplicate(self, text: str, source_path: str) -> bool:
        return self._writer._check_content_duplicate(text, source_path)

    def _generate_output_file(self, source_path: str, output_dir: str,
                              invoice_no: str, amount: str, prefix: str) -> str | None:
        return self._writer._generate_output_file(
            source_path, output_dir, invoice_no, amount, prefix
        )

    def _collect_tax_issue(self, file_path: str, filename: str, tax_issue_dir: str,
                           *, copy_only: bool = False) -> str:
        return self._writer._collect_tax_issue(
            file_path, filename, tax_issue_dir, copy_only=copy_only
        )

    def _move_to_manual_review(self, file_path: str, filename: str,
                               output_dir: str) -> str:
        return self._writer._move_to_manual_review(file_path, filename, output_dir)

    def _process_invoice(
        self,
        source_path: str,
        output_dir: str,
        invoice_pattern: str,
        amount_pattern: str,
        prefix: str,
        amount_processor: Callable[[str], str] | None = None,
    ) -> str | None:
        return self._writer._process_invoice(
            self,
            source_path,
            output_dir,
            invoice_pattern,
            amount_pattern,
            prefix,
            amount_processor,
        )

    # ── 发票类型分发（委托 invoice_types） ────────────
    def determine_processor_type(self, text: str) -> Callable | None:
        """根据文本内容确定发票类型

        返回首个命中的处理方法（proc 上的方法对象，保持对象身份以便 == 比较）。
        """
        return determine_processor_type(self, text)

    # ── 各类型发票处理（薄委托方法，保持方法对象身份） ──
    # 逻辑实现见 invoice_types 模块；此处仅转发，确保
    # determine_processor_type 返回的 handler == proc.process_X。
    def process_zhejiang_invoice(self, source_path: str, output_dir: str) -> str | None:
        return process_zhejiang_invoice(self, source_path, output_dir)

    def process_jiangsu_toll(self, source_path: str, output_dir: str) -> str | None:
        return process_jiangsu_toll(self, source_path, output_dir)

    def process_jiangsu_invoice(self, source_path: str, output_dir: str) -> str | None:
        return process_jiangsu_invoice(self, source_path, output_dir)

    def process_highspeed_rail(self, source_path: str, output_dir: str) -> str | None:
        return process_highspeed_rail(self, source_path, output_dir)

    def process_didi_trip(self, source_path: str, output_dir: str) -> str | None:
        return process_didi_trip(self, source_path, output_dir)

    def process_toll_summary(self, source_path: str, output_dir: str) -> str | None:
        return process_toll_summary(self, source_path, output_dir)

    def process_general_invoice(self, source_path: str, output_dir: str) -> str | None:
        return process_general_invoice(self, source_path, output_dir)

    # ── 后处理：金额映射 / 占位替换 / 税号检查 / 合并 / 汇总 ──
    def post_process(self, output_dir: str,
                     progress_callback: Callable[[float], None] | None = None) -> dict:
        """后处理：金额映射 + 待搜索替换 + 税号检查 + 发票分类 + PDF 合并 + 费用汇总

        进度契约（供 UI 进度条使用，post_process 保证满足）：
            - 首条进度必为 0.0，末条进度必为 1.0；
            - 进度值单调不减，且始终落在 [0.0, 1.0]。
        各阶段的比例分配见 _phase_* 方法。

        返回: {'amount_map': dict, 'tax_issues': list[str],
               'merged': str|None, 'excel': str|None}
        """
        def _report(ratio: float) -> None:
            if progress_callback is not None:
                try:
                    progress_callback(ratio)
                except Exception:
                    pass  # 回调失败不影响主流程

        _report(0.00)
        # ① 金额映射（仅文件名解析，快）
        amount_map = self._phase_amount_mapping(output_dir)
        _report(0.05)
        # ② 待搜索替换（仅重命名/移动，快）
        self._phase_replace_placeholders(output_dir, amount_map)
        _report(0.10)
        # ③④ 单次遍历：税号检查 + 发票分类
        tax_issues, special_invoices, normal_files = self._phase_scan_and_classify(
            output_dir, _report
        )
        # ⑤ 扫描 需人工处理/ 子目录中的税号异常
        tax_issues += self._phase_scan_manual_dir(output_dir, _report)
        # ⑥ 合并分类后的 PDF（内部进度 0.75~0.98）
        merged = self._phase_merge(output_dir, special_invoices, normal_files, _report)
        # ⑦ 生成费用汇总 Excel；写盘完成后才报告最终进度
        excel = self.generate_expense_summary(output_dir)
        _report(1.00)
        return {'amount_map': amount_map, 'tax_issues': tax_issues,
                'merged': merged, 'excel': excel}

    # ── 后处理各阶段（Composed Method：每阶段单一职责，便于阅读与单测） ──
    def _phase_amount_mapping(self, output_dir: str) -> dict[str, str]:
        """阶段①：仅解析文件名，构建 金额→发票号 映射表"""
        return self.create_amount_mapping(output_dir)

    def _phase_replace_placeholders(
        self, output_dir: str, amount_map: dict[str, str]
    ) -> None:
        """阶段②：将「待搜索-金额.pdf」按映射表补全发票号，失败则移入 需人工处理/"""
        self.replace_placeholder_files(output_dir, amount_map)

    def _phase_scan_and_classify(self, output_dir: str,
                                 report: Callable[[float], None]
                                 ) -> tuple[list[str], list[str], list[str]]:
        """阶段③④：单次遍历输出目录，完成税号检查与发票分类

        返回 (tax_issues, special_invoices, normal_files)。
        进度从 0.10 线性增长至 0.70（按文件数）。
        """
        tax_issues: list[str] = []
        special_invoices: list[str] = []
        normal_files: list[str] = []
        tax_issue_dir = os.path.join(output_dir, '税号异常')

        # 先列出所有 PDF 用于按文件数报告进度
        all_pdfs = [f for f in os.listdir(output_dir)
                    if f.lower().endswith('.pdf')
                    and f != MERGED_FILENAME
                    and os.path.isfile(os.path.join(output_dir, f))]
        total_pdfs = len(all_pdfs)
        # 税号检查+分类阶段占 0.10 → 0.70
        for idx, filename in enumerate(all_pdfs):
            file_path = os.path.join(output_dir, filename)
            text = self.extract_pdf_text(file_path)
            should_classify = True
            # 税号检查仅针对发票，行程单/高铁票等凭证跳过
            if text and self._requires_tax_id_check(filename):
                tax_id = self._extract_buyer_tax_id(text)
                if tax_id is None:
                    self._move_to_manual_review(file_path, filename, output_dir)
                    should_classify = False
                    tax_issues.append(
                        f'购买方税号缺失: {filename}，已移到需人工处理文件夹'
                    )
                elif tax_id != _cfg.TARGET_TAX_ID:
                    self._collect_tax_issue(file_path, filename, tax_issue_dir)
                    should_classify = False
                    tax_issues.append(
                        f'税号异常: {filename} -> {tax_id}，已移动到税号异常文件夹'
                    )
            # 合并分类（统一走 _classify_invoice，避免规则漂移）
            if should_classify and self._classify_invoice(filename, text) == 'special':
                special_invoices.append(filename)
            elif should_classify:
                normal_files.append(filename)
            # 按文件数线性报告（0.10 → 0.70）
            if total_pdfs > 0:
                report(0.10 + 0.60 * (idx + 1) / total_pdfs)
        report(0.70)
        return tax_issues, special_invoices, normal_files

    def _phase_scan_manual_dir(self, output_dir: str,
                               report: Callable[[float], None]) -> list[str]:
        """阶段⑤：扫描 需人工处理/ 子目录，复制其中的税号异常文件

        返回新增的 tax_issues 条目。阶段结束回调 0.75。
        """
        tax_issues: list[str] = []
        manual_dir = os.path.join(output_dir, '需人工处理')
        if os.path.isdir(manual_dir):
            for filename in os.listdir(manual_dir):
                if not filename.lower().endswith('.pdf'):
                    continue
                file_path = os.path.join(manual_dir, filename)
                if not os.path.isfile(file_path):
                    continue
                if not self._requires_tax_id_check(filename):
                    continue
                text = self.extract_pdf_text(file_path)
                if not text:
                    continue
                tax_id_match = re.search(
                    r'(?:纳税人识别号|统一社会信用代码)[:：]\s*'
                    r'([A-Z0-9]{15,20})',
                    text,
                )
                if tax_id_match:
                    tax_id = tax_id_match.group(1)
                    if tax_id != _cfg.TARGET_TAX_ID:
                        self._collect_tax_issue(
                            file_path, filename,
                            os.path.join(output_dir, '税号异常'),
                            copy_only=True,
                        )
                        tax_issues.append(
                            f'税号异常: {filename} -> {tax_id}，'
                            '已复制到税号异常文件夹（原文件保留在需人工处理）'
                        )
        report(0.75)
        return tax_issues

    def _phase_merge(self, output_dir: str, special_invoices: list[str],
                     normal_files: list[str],
                     report: Callable[[float], None]) -> str | None:
        """阶段⑥：合并分类后的 PDF

        内部进度 0.0~1.0 映射到后处理进度 0.75~0.98，预留最后进度给 Excel 写盘。
        """
        def _on_merge_progress(ratio: float) -> None:
            # 合并内部进度 0.0~1.0 → 后处理进度 0.75~0.98
            report(0.75 + 0.23 * ratio)
        return self._merge_classified_pdfs(
            output_dir, special_invoices, normal_files,
            progress_callback=_on_merge_progress,
        )

    def generate_expense_summary(self, output_dir: str) -> str | None:
        """生成费用汇总 Excel（委托 excel_summary 模块）

        遍历输出目录中的 PDF，提取日期、类别、金额，按日期归集生成 Excel。
        """
        return _generate_excel(output_dir, self)

    def create_amount_mapping(self, folder_path: str) -> dict[str, str]:
        """创建金额映射表"""
        candidates: dict[str, set[str]] = {}
        for filename in os.listdir(folder_path):
            if filename.startswith('待搜索'):
                continue
            parts = filename.split('-', 1)
            if len(parts) >= 2:
                invoice_part, amount_part = parts
                amount_match = re.match(r'^(\d+\.\d{2})(?:行程单)?\.pdf$', amount_part)
                if amount_match:
                    amount = amount_match.group(1)
                    candidates.setdefault(amount, set()).add(invoice_part)
        return {
            amount: next(iter(invoice_numbers))
            for amount, invoice_numbers in candidates.items()
            if len(invoice_numbers) == 1
        }

    def replace_placeholder_files(
        self, folder_path: str, amount_map: dict[str, str]
    ) -> None:
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
                    os.makedirs(manual_dir, exist_ok=True)
                    manual_path = os.path.join(manual_dir, filename)
                    counter = 1
                    while os.path.exists(manual_path):
                        name, ext = os.path.splitext(filename)
                        manual_path = os.path.join(
                            manual_dir, f'{name}_{counter}{ext}'
                        )
                        counter += 1
                    shutil.move(old_path, manual_path)
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

    def create_output_directory(self, base_dir: str) -> str:
        """创建输出目录"""
        timestamp_dir = datetime.now().strftime('%Y%m%d_%H%M%S_%f')

        def _create_unique(root: str) -> str:
            os.makedirs(root, exist_ok=True)
            for counter in range(1000):
                suffix = '' if counter == 0 else f'_{counter}'
                output_dir = os.path.join(root, f'{timestamp_dir}{suffix}')
                try:
                    os.makedirs(output_dir, exist_ok=False)
                    return output_dir
                except FileExistsError:
                    continue
            raise FileExistsError(f'无法创建唯一输出目录: {root}')

        try:
            return _create_unique(base_dir)
        except PermissionError:
            return _create_unique(os.path.join(
                os.path.expanduser('~'), 'Desktop', '发票输出'
            ))

    # ── PDF 合并（委托合并器） ────────────────────────
    def _merge_classified_pdfs(
        self,
        output_dir: str,
        special_invoices: list[str],
        normal_files: list[str],
        progress_callback: Callable[[float], None] | None = None,
    ) -> str | None:
        return self._merger.merge_classified(
            output_dir, special_invoices, normal_files, progress_callback
        )

    def merge_pdfs(self, output_dir: str) -> str | None:
        """合并PDF文件（向后兼容包装：自行分类后委托合并器）"""
        return self._merger.merge_pdfs(self, output_dir)
