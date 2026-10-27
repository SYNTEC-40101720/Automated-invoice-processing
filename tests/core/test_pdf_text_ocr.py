"""OCR 级联测试（ADR 2026-10-27 D1：仅扫描件 fallback）。

覆盖：
    - 文本版 PDF 不触发 OCR（懒加载函数 raise 也不影响）
    - image-only PDF 走 OCR 路径并返回预置文本（真实引擎用替身跳过）
    - 阅读序拼装（y 排序 + 同行合并 + 行内 x 排序）
    - OCR 抛异常时返回 (None, 'empty')，与旧行为兼容（不 raise）
    - ocr_enabled=False 时不初始化引擎
真实 RapidOCR 模型调用不做单测，由 scripts/probe_ocr_cascade.py 人工验证。
"""
import pytest
from invoice_processor.core import pdf_text as pdf_text_module
from invoice_processor.core.pdf_text import PdfTextExtractor
from PIL import Image


def _make_image_only_pdf(path, pixel_size=(120, 60)):
    """生成一张纯图片页的 PDF（无文字层，pdfplumber 抽不出文本）。"""
    image = Image.new('RGB', pixel_size, 'white')
    image.save(path, 'PDF')


@pytest.fixture
def reset_ocr_singleton(monkeypatch):
    """隔离模块级 OCR 单例状态，测试结束还原。"""
    monkeypatch.setattr(pdf_text_module, '_OCR_ENGINE', None)
    monkeypatch.setattr(pdf_text_module, '_OCR_DISABLED', False)
    yield


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把 config.ini 定位到 tmp_path，并清空已缓存的 ConfigManager store。"""
    import invoice_processor.config_manager as cm

    config_path = tmp_path / 'config.ini'
    monkeypatch.setattr(cm, 'get_config_path', lambda: str(config_path))
    monkeypatch.setattr(cm, '_get_program_dir', lambda: str(tmp_path))
    monkeypatch.setattr(cm, '_CONFIG_STORES', {})
    yield tmp_path
    cm._CONFIG_STORES.clear()


class TestTextPdfSkipsOcr:
    def test_text_pdf_does_not_touch_ocr(self, tmp_path, monkeypatch):
        """① 文本版 PDF：pdfplumber 可抽出足量文本，OCR 路径不触发。

        把懒加载函数替换为 raise——若级联被误触发会直接炸出。
        """

        def _boom():
            raise AssertionError('文本版 PDF 不应初始化 OCR 引擎')

        monkeypatch.setattr(pdf_text_module, '_ensure_ocr_engine', _boom)

        class FakePage:
            def extract_text(self):
                return '江苏增值税专用发票 金额 1234.56 元'

        class FakePdf:
            is_encrypted = False
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        monkeypatch.setattr(
            pdf_text_module.pdfplumber, 'open', lambda _p: FakePdf()
        )
        pdf_path = tmp_path / 'text.pdf'
        extractor = PdfTextExtractor()
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert error is None
        assert text == '江苏增值税专用发票金额1234.56元'


class TestImageOnlyPdfOcr:
    def test_image_only_pdf_uses_ocr(
        self, tmp_path, monkeypatch, reset_ocr_singleton
    ):
        """② image-only PDF：pdfplumber 空 → OCR 替身返回预置文本。

        跳过真实引擎：替换 OCR 调用点 `_call_ocr`，断言文本与调用次数。
        """
        pdf_path = tmp_path / 'scan.pdf'
        _make_image_only_pdf(pdf_path)
        calls = []

        def fake_call_ocr(_self, rgb_array):
            calls.append(rgb_array.shape)
            box = [[0, 0], [10, 0], [10, 8], [0, 8]]
            # RapidOCR 返回形状：[[box, text, score], ...]
            result = [
                [box, '江苏增值税专用发票', '0.99'],
                [box, '金额1234.56元', '0.98'],
            ]
            return result, 0.1

        monkeypatch.setattr(PdfTextExtractor, '_call_ocr', fake_call_ocr)
        extractor = PdfTextExtractor()
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert error is None
        assert text == '江苏增值税专用发票金额1234.56元'
        assert calls, 'OCR 调用点未被触发'

    def test_image_only_pdf_merges_same_line(
        self, tmp_path, monkeypatch, reset_ocr_singleton
    ):
        """② 补充：同行（y 差 < 行高一半）合并、行内按 x 排序、跨行换行。"""
        pdf_path = tmp_path / 'scan.pdf'
        _make_image_only_pdf(pdf_path)

        def fake_call_ocr(_self, _rgb_array):
            # 两行：行 1 两个框（x 顺序颠倒），行 2 一个框
            result = [
                [[[100, 100], [110, 100], [110, 110], [100, 110]], '右侧', '0.9'],
                [[[0, 102], [8, 102], [8, 112], [0, 112]], '左侧', '0.9'],
                [[[0, 200], [8, 200], [8, 210], [0, 210]], '第二行', '0.9'],
            ]
            return result, 0.1

        monkeypatch.setattr(PdfTextExtractor, '_call_ocr', fake_call_ocr)
        extractor = PdfTextExtractor()
        # 断言原始文本（保留空白）：同一行的两个框用空格连接（ADR D1
        # 口径），跨行换行分隔；extract_pdf_text_with_error 会去空白
        raw, error = extractor._extract_raw_text(str(pdf_path))
        assert error is None
        assert raw == '左侧 右侧\n第二行'


class TestOcrFailureCompat:
    def test_ocr_exception_returns_empty_error(
        self, tmp_path, monkeypatch, reset_ocr_singleton
    ):
        """③ OCR 抛异常：返回 (None, 'empty')，与旧扫描件行为兼容。"""
        pdf_path = tmp_path / 'scan.pdf'
        _make_image_only_pdf(pdf_path)

        def broken_call_ocr(_self, _rgb_array):
            raise RuntimeError('OCR engine exploded')

        monkeypatch.setattr(PdfTextExtractor, '_call_ocr', broken_call_ocr)
        extractor = PdfTextExtractor()
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert text is None
        assert error == 'empty'

    def test_ocr_engine_init_failure_disables_and_returns_empty(
        self, tmp_path, monkeypatch, reset_ocr_singleton
    ):
        """③ 补充：引擎初始化失败 → 永久禁用并回 (None, 'empty')，不崩。"""

        class BrokenRapidOCR:
            def __init__(self):
                raise RuntimeError('no onnxruntime')

        monkeypatch.setattr(
            'rapidocr_onnxruntime.RapidOCR', BrokenRapidOCR
        )
        pdf_path = tmp_path / 'scan.pdf'
        _make_image_only_pdf(pdf_path)
        extractor = PdfTextExtractor()
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert text is None
        assert error == 'empty'
        # 永久禁用已生效（后续调用不再尝试初始化）
        assert pdf_text_module._OCR_DISABLED is True
        assert pdf_text_module._ensure_ocr_engine() is None

    def test_render_failure_returns_empty_error(
        self, tmp_path, monkeypatch, reset_ocr_singleton
    ):
        """③ 补充：pypdfium2 渲染失败也按旧扫描件语义处理，不崩。"""
        pdf_path = tmp_path / 'broken.pdf'
        pdf_path.write_bytes(b'%PDF-1.4 fake')

        class FakeRender:
            def to_pil(self):
                raise RuntimeError('render failed')

        class FakePage:
            def render(self, scale):
                return FakeRender()

        class FakeDoc:
            def __init__(self, _path):
                pass

            def __len__(self):
                return 1

            def __getitem__(self, _index):
                return FakePage()

            def close(self):
                pass

        import pypdfium2 as real_pdfium

        # pdfplumber 正常打开但抽不出文本（空页），随后 pdfium 渲染失败
        class EmptyPage:
            def extract_text(self):
                return ''

        class FakePdf:
            is_encrypted = False
            pages = [EmptyPage()]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        monkeypatch.setattr(
            pdf_text_module.pdfplumber, 'open', lambda _p: FakePdf()
        )
        monkeypatch.setattr(real_pdfium, 'PdfDocument', lambda _p: FakeDoc())
        extractor = PdfTextExtractor()
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert text is None
        assert error == 'empty'


class TestOcrDisabled:
    def test_ocr_disabled_skips_engine(
        self, tmp_path, monkeypatch, reset_ocr_singleton, isolated_config
    ):
        """④ ocr_enabled=False：不初始化引擎，回旧行为 (None, 'empty')。"""
        import invoice_processor.config_manager as cm

        monkeypatch.setattr(cm, 'is_ocr_enabled', lambda: False)

        def _boom():
            raise AssertionError('OCR 关闭时不应初始化引擎')

        monkeypatch.setattr(pdf_text_module, '_ensure_ocr_engine', _boom)
        pdf_path = tmp_path / 'scan.pdf'
        _make_image_only_pdf(pdf_path)
        extractor = PdfTextExtractor()
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert text is None
        assert error == 'empty'


class TestShortTextFallback:
    def test_short_text_kept_when_ocr_fails(
        self, tmp_path, monkeypatch, reset_ocr_singleton
    ):
        """pdfplumber 有过短文本 + OCR 失败 → 保留 pdfplumber 短文本。

        行为兼容口径：OCR 尝试失败不得把「pdfplumber 已成功」的文件
        降级为 (None, 'empty')（旧版短文本照常返回）。
        """

        def broken_call_ocr(_self, _rgb_array):
            raise RuntimeError('render exploded')

        monkeypatch.setattr(PdfTextExtractor, '_call_ocr', broken_call_ocr)

        class FakePage:
            def extract_text(self):
                return '发票 文本'

        class FakePdf:
            is_encrypted = False
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        monkeypatch.setattr(
            pdf_text_module.pdfplumber, 'open', lambda _p: FakePdf()
        )
        extractor = PdfTextExtractor()
        pdf_path = tmp_path / 'short.pdf'
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert error is None
        assert text == '发票文本'

    def test_short_text_upgraded_by_ocr(
        self, tmp_path, monkeypatch, reset_ocr_singleton
    ):
        """pdfplumber 过短 + OCR 成功 → OCR 文本胜出并进缓存。"""
        pdf_path = tmp_path / 'short.pdf'
        _make_image_only_pdf(pdf_path)

        def fake_call_ocr(_self, _rgb_array):
            box = [[0, 0], [10, 0], [10, 8], [0, 8]]
            return [[box, 'OCR长文本内容超过阈值字符数', '0.9']], 0.1

        monkeypatch.setattr(PdfTextExtractor, '_call_ocr', fake_call_ocr)

        class FakePage:
            def extract_text(self):
                return '短'

        class FakePdf:
            is_encrypted = False
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        monkeypatch.setattr(
            pdf_text_module.pdfplumber, 'open', lambda _p: FakePdf()
        )
        extractor = PdfTextExtractor()
        text, error = extractor.extract_pdf_text_with_error(str(pdf_path))
        assert error is None
        assert 'OCR长文本内容超过阈值字符数' in text


class TestOcrTextAssembly:
    def test_assemble_empty_and_none(self):
        """空结果 / None 结果返回空串。"""
        assert PdfTextExtractor._assemble_ocr_text([]) == ''
        assert PdfTextExtractor._assemble_ocr_text(None) == ''

    def test_assemble_reads_by_y_then_x(self):
        """先按 y 分行，行内按 x 排序空格连接。"""
        result = [
            [[[100, 100], [110, 100], [110, 110], [100, 110]], 'B', '0.9'],
            [[[0, 100], [10, 100], [10, 110], [0, 110]], 'A', '0.9'],
            [[[0, 200], [10, 200], [10, 210], [0, 210]], 'C', '0.9'],
        ]
        text = PdfTextExtractor._assemble_ocr_text(result)
        lines = text.split('\n')
        assert lines[0] == 'A B'
        assert lines[1] == 'C'


class TestConfigIntegration:
    def test_is_ocr_enabled_default_true(self, isolated_config):
        """未配置时默认开启（_DEFAULTS 注入 + bool 解析）。"""
        from invoice_processor import config_manager

        assert config_manager.is_ocr_enabled() is True

    def test_is_ocr_enabled_true_values(self, isolated_config):
        """'true'/'1'/'yes'/'on'（大小写不敏感）→ 开启。"""
        from invoice_processor import config_manager

        for raw in ('true', 'True', '1', 'yes', 'ON'):
            (isolated_config / 'config.ini').write_text(
                f'[ai]\nocr_enabled = {raw}\n', encoding='utf-8'
            )
            assert config_manager.is_ocr_enabled() is True, raw

    def test_is_ocr_enabled_false_values(self, isolated_config):
        """'false'/'0'/'no'/'off' 及非法值 → 关闭，不抛异常。"""
        from invoice_processor import config_manager

        for raw in ('false', 'False', '0', 'no', 'OFF', '随便写的'):
            (isolated_config / 'config.ini').write_text(
                f'[ai]\nocr_enabled = {raw}\n', encoding='utf-8'
            )
            assert config_manager.is_ocr_enabled() is False, raw
