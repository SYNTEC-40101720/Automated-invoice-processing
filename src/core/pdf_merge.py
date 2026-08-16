"""PDF 合并与发票分类

职责：
    - classify_invoice：判断发票属于「专票/高铁票」还是「普通发票」
    - PdfMerger：将分类后的 PDF 合并为 合并结果.pdf

分类规则原本在 post_process 与 merge_pdfs 中各自内联（关键字还不完全一致，
易漂移），统一在此维护。业务规则：专票/高铁票需双份（抵扣联+发票联），
每个文件 append 两遍；普通发票单份即可。
"""
import os
import logging
from collections.abc import Callable

from pypdf import PdfReader, PdfWriter

from .pdf_text import PdfTextExtractor


def classify_invoice(filename: str, text: str | None) -> str:
    """判断发票属于「专票/高铁票」还是「普通发票」

    分类规则（专票/高铁票需双份合并，普通单份）：
        - 文件名含「专用发票」或「高铁票」→ 专票类
        - 文本内容含「专用」或「增值税专用发票」→ 专票类
        - 其余 → 普通类

    返回 'special' 或 'normal'。
    """
    is_special = (
        ('专用发票' in filename or '高铁票' in filename)
        or bool(text and ('专用' in text or '增值税专用发票' in text))
    )
    return 'special' if is_special else 'normal'


class PdfMerger:
    """PDF 合并器：合并分类后的发票 PDF"""

    def __init__(self, extractor: PdfTextExtractor):
        self._extractor = extractor

    def merge_classified(self, output_dir: str, special_invoices: list[str],
                         normal_files: list[str],
                         progress_callback: Callable[[float], None] | None = None) -> str | None:
        """合并已分类的PDF文件

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
            self._extractor._log_core(f"PDF 合并失败: {output_dir}", level='error')
            return None

    def merge_pdfs(self, processor, output_dir: str) -> str | None:
        """合并PDF文件（向后兼容包装：自行分类后委托 merge_classified）"""
        special_invoices: list[str] = []
        normal_files: list[str] = []
        for filename in os.listdir(output_dir):
            if not filename.lower().endswith('.pdf'):
                continue
            file_path = os.path.join(output_dir, filename)
            if not os.path.isfile(file_path):
                continue
            text = processor.extract_pdf_text(file_path)
            if classify_invoice(filename, text) == 'special':
                special_invoices.append(filename)
            else:
                normal_files.append(filename)
        return self.merge_classified(output_dir, special_invoices, normal_files)
