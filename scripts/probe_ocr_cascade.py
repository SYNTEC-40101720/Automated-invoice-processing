"""OCR 级联真实探测（人工验证脚本，不进 pytest）。

对 build/ocr_probe/scan.pdf（image-only 扫描件）全链路验证 ADR D1：
    1. pdfplumber 直接抽取 → 应为空（证明走了级联）
    2. PdfTextExtractor.extract_pdf_text_with_error → OCR 级联
       应输出含「江苏增值税专用发票金额1234.56元」的文本，日志标注来源
    3. 逐页来源打印（文本来源: pdfplumber / 文本来源: OCR）

用法（项目根）：
    python -X utf8 scripts/probe_ocr_cascade.py [pdf_path]
"""
import logging
import os
import sys

_DEFAULT_PDF = os.path.join('build', 'ocr_probe', 'scan.pdf')
_EXPECTED_MARK = '江苏增值税专用发票金额1234.56元'


def _probe_pdfplumber_only(pdf_path: str) -> str:
    """第 1 步：pdfplumber 直接抽取（验证原路径抽不出）。"""
    import re

    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        raw = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    stripped = re.sub(r'\s+', '', raw)
    print(f'[1] pdfplumber 直抽: 去空白长度 = {len(stripped)}'
          + ('（空，符合扫描件预期）' if not stripped else f'，内容: {stripped[:50]}'))
    return stripped


def _probe_extractor_cascade(pdf_path: str) -> tuple[str | None, str | None]:
    """第 2 步：走 PdfTextExtractor 完整级联（含 config 开关与缓存）。"""
    from invoice_processor.core.pdf_text import PdfTextExtractor

    logs: list[tuple[str, str]] = []
    extractor = PdfTextExtractor(
        log_callback=lambda msg, level: logs.append((level, msg))
    )
    text, error = extractor.extract_pdf_text_with_error(pdf_path)
    print(f'[2] 级联提取: text = {text!r}')
    print(f'    error = {error!r}')
    for level, msg in logs:
        print(f'    [log:{level}] {msg}')
    return text, error


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_PDF
    if not os.path.isfile(pdf_path):
        print(f'探测文件不存在: {pdf_path}')
        return 1
    print(f'探测文件: {pdf_path}')
    print('OCR 配置开关: 看 [2] 日志（ocr_enabled 读取异常按开启处理）')

    stripped = _probe_pdfplumber_only(pdf_path)
    text, error = _probe_extractor_cascade(pdf_path)

    print('─── 判定 ───')
    ok = True
    if stripped:
        print('[X] pdfplumber 直抽非空，探测对象不是 image-only 扫描件')
        ok = False
    else:
        print('[OK] pdfplumber 直抽为空（级联前置条件成立）')
    if text and _EXPECTED_MARK in text.replace(' ', ''):
        print(f'[OK] OCR 级联输出含预期文本「{_EXPECTED_MARK}」')
    else:
        print(f'[X] OCR 级联输出未含预期文本「{_EXPECTED_MARK}」')
        ok = False
    print('结论: 全链路验证通过' if ok else '结论: 探测未通过，检查上方日志')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
