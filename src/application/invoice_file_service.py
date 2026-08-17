"""单个 PDF 文件的应用级处理服务。"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class FileProcessResult:
    filename: str
    output_path: str | None
    level: str
    message: str
    outcome: str


class InvoiceFileService:
    """把单文件处理从 UI/任务调度中隔离出来。"""

    _ERROR_LABELS = {
        'encrypted': 'PDF 已加密',
        'corrupted': 'PDF 文件损坏',
        'empty': 'PDF 无文本内容（可能是扫描件）',
        'unknown': 'PDF 解析失败',
    }

    def __init__(self, processor):
        self.processor = processor

    def process_file(
        self,
        filename: str,
        source_dir: str,
        output_dir: str,
        is_cancelled: Callable[[], bool],
    ) -> FileProcessResult:
        if is_cancelled():
            return FileProcessResult(
                filename, None, 'warning', f'已取消: {filename}', 'cancelled'
            )

        file_path = os.path.join(source_dir, filename)
        text, error_type = self.processor.extract_pdf_text_with_error(file_path)
        if not text:
            reason = self._ERROR_LABELS.get(error_type or 'unknown', 'PDF 解析失败')
            dest = self._move_to_manual_review(file_path, filename, output_dir)
            return FileProcessResult(
                filename, dest, 'error',
                f'{reason}，已归集到需人工处理: {filename}', 'failure'
            )

        if self.processor.check_content_duplicate(text, file_path):
            return FileProcessResult(
                filename, None, 'warning',
                f'内容重复已跳过（源文件保留）: {filename}', 'skipped'
            )

        processor_func = self.processor.determine_processor_type(text)
        if processor_func:
            result = processor_func(file_path, output_dir)
            if result:
                return FileProcessResult(
                    filename, result, 'success',
                    f'成功: {os.path.basename(result)}', 'success'
                )
            message = f'字段提取失败，已归集到需人工处理: {filename}'
        else:
            message = f'类型未识别，已归集到需人工处理: {filename}'

        dest = self._move_to_manual_review(file_path, filename, output_dir)
        return FileProcessResult(filename, dest, 'warning', message, 'failure')

    @staticmethod
    def _move_to_manual_review(file_path: str, filename: str, output_dir: str) -> str:
        manual_dir = os.path.join(output_dir, '需人工处理')
        os.makedirs(manual_dir, exist_ok=True)
        dest_path = os.path.join(manual_dir, filename)
        counter = 1
        while os.path.exists(dest_path):
            name, ext = os.path.splitext(filename)
            dest_path = os.path.join(manual_dir, f'{name}_{counter}{ext}')
            counter += 1
        shutil.copy2(file_path, dest_path)
        return dest_path
