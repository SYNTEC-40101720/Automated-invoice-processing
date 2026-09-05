"""集成测试：覆盖新增功能的端到端验证

运行方式: pytest tests/test_integration.py -v
"""
import re
import threading

from invoice_processor.config_manager import (
    get_max_workers,
    get_target_tax_id,
    load_config,
    set_business_config,
)
from invoice_processor.core.pdf_text import PdfTextExtractor
from invoice_processor.core.processor import _TYPE_REGISTRY, InvoiceProcessor

# ═══════════════════════════════════════════════════════════
# 改进 7: 内容哈希去重
# ═══════════════════════════════════════════════════════════

class TestContentHashDedup:
    """内容哈希去重集成测试"""

    def test_content_duplicate_detected(self):
        """相同内容的文件应被识别为重复"""
        proc = InvoiceProcessor()
        text = "发票号码：12345678 金额：100.00"
        # 首次：不重复
        assert proc._check_content_duplicate(text, "source1.pdf") is False
        # 第二次：重复
        assert proc._check_content_duplicate(text, "source2.pdf") is True

    def test_different_content_not_duplicate(self):
        """不同内容的文件不应被识别为重复"""
        proc = InvoiceProcessor()
        assert proc._check_content_duplicate("发票A", "source1.pdf") is False
        assert proc._check_content_duplicate("发票B", "source2.pdf") is False

    def test_reset_dedup_clears_content_hashes(self):
        """reset_dedup 应清空内容哈希记录"""
        proc = InvoiceProcessor()
        text = "相同内容"
        proc._check_content_duplicate(text, "source1.pdf")
        # 清空后，相同内容应不再被视为重复
        proc.reset_dedup()
        assert proc._check_content_duplicate(text, "source2.pdf") is False

    def test_content_dedup_thread_safety(self):
        """内容哈希去重应线程安全（基本验证）"""
        import threading
        proc = InvoiceProcessor()
        text = "并发测试内容"
        results = []
        results_lock = threading.Lock()

        def check():
            r = proc._check_content_duplicate(text, "concurrent.pdf")
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=check) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 10 个线程同时检查，应只有 1 个返回 False（首次），其余 True（重复）
        assert results.count(False) == 1
        assert results.count(True) == 9


# ═══════════════════════════════════════════════════════════
# 改进 8: 类型路由注册表
# ═══════════════════════════════════════════════════════════

class TestTypeRegistry:
    """类型路由注册表集成测试"""

    def test_registry_has_all_types(self):
        """注册表应包含所有 7 种发票类型"""
        registered_names = [name for _, name in _TYPE_REGISTRY]
        expected = [
            'process_zhejiang_invoice',
            'process_jiangsu_toll',
            'process_jiangsu_invoice',
            'process_highspeed_rail',
            'process_didi_trip',
            'process_toll_summary',
            'process_general_invoice',
        ]
        for name in expected:
            assert name in registered_names, f"缺少注册: {name}"

    def test_registry_order_specific_before_general(self):
        """具体类型应在通用 fallback 之前注册"""
        general_idx = None
        for i, (_, name) in enumerate(_TYPE_REGISTRY):
            if name == 'process_general_invoice':
                general_idx = i
                break
        assert general_idx is not None
        # 通用类型应在最后
        assert general_idx == len(_TYPE_REGISTRY) - 1

    def test_routing_returns_correct_handler(self):
        """注册表路由应返回正确的处理函数"""
        proc = InvoiceProcessor()
        # 江苏通行费行程单（不应被江苏通行费票据误匹配）
        handler = proc.determine_processor_type('江苏省车辆通行费电子票据行程单')
        assert handler == proc.process_jiangsu_invoice

    def test_routing_priority_zhejiang_over_general(self):
        """浙江发票应优先于通用发票匹配"""
        proc = InvoiceProcessor()
        text = '浙江通用（电子）发票 发票号码：123'
        handler = proc.determine_processor_type(text)
        assert handler == proc.process_zhejiang_invoice
        assert handler != proc.process_general_invoice


# ═══════════════════════════════════════════════════════════
# 改进 4: 配置外部化
# ═══════════════════════════════════════════════════════════

class TestConfigManager:
    """配置管理集成测试"""

    def test_load_config_returns_business_section(self):
        """load_config 应返回包含 business 段的配置"""
        cfg = load_config()
        assert cfg.has_section('business')
        assert cfg.has_option('business', 'target_tax_id')
        assert cfg.has_option('business', 'max_workers')

    def test_get_target_tax_id_returns_18_chars(self):
        """get_target_tax_id 应返回 18 位税号"""
        tax_id = get_target_tax_id()
        assert len(tax_id) == 18
        assert re.fullmatch(r'[A-Z0-9]{18}', tax_id)

    def test_get_max_workers_in_range(self):
        """get_max_workers 应返回 2-16 之间的整数"""
        workers = get_max_workers()
        assert 2 <= workers <= 16

    def test_set_and_read_back(self):
        """set_business_config 后应能读回新值"""
        original_tax = get_target_tax_id()
        original_workers = get_max_workers()
        try:
            set_business_config('ABCDEFGHIJKLMNOPQR', 4)
            assert get_target_tax_id() == 'ABCDEFGHIJKLMNOPQR'
            assert get_max_workers() == 4
        finally:
            # 恢复原值，避免污染其他测试
            set_business_config(original_tax, original_workers)

    def test_max_workers_clamped_to_range(self):
        """超出范围的线程数应被限制到 2-16"""
        original_tax = get_target_tax_id()
        original_workers = get_max_workers()
        try:
            set_business_config(original_tax, 100)
            assert get_max_workers() == 16
            set_business_config(original_tax, 0)
            assert get_max_workers() == 2
        finally:
            set_business_config(original_tax, original_workers)


# ═══════════════════════════════════════════════════════════
# 改进 3: PDF 异常分类（集成验证）
# ═══════════════════════════════════════════════════════════

class TestPDFExceptionClassification:
    """PDF 异常分类集成测试"""

    def test_empty_file_returns_corrupted_or_unknown(self, tmp_path):
        """空文件应返回错误类型（corrupted 或 unknown）"""
        empty_pdf = tmp_path / "empty.pdf"
        empty_pdf.write_bytes(b"")
        proc = InvoiceProcessor()
        text, error_type = proc._extract_raw_text(str(empty_pdf))
        assert text is None
        assert error_type in ('corrupted', 'unknown')

    def test_non_pdf_file_returns_error(self, tmp_path):
        """非 PDF 文件应返回错误类型"""
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.write_bytes(b"This is not a PDF file content")
        proc = InvoiceProcessor()
        text, error_type = proc._extract_raw_text(str(fake_pdf))
        assert text is None
        assert error_type is not None

    def test_text_extraction_caches_result(self, tmp_path):
        """文本提取结果应被缓存（第二次调用命中缓存）"""
        # 用一个会失败的文件验证缓存
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.write_bytes(b"not a pdf")
        proc = InvoiceProcessor()
        # 第一次调用：解析并缓存
        text1, err1 = proc._extract_raw_text(str(fake_pdf))
        # 第二次调用：应命中缓存（返回相同结果）
        text2, err2 = proc._extract_raw_text(str(fake_pdf))
        assert text1 == text2
        assert err1 == err2


def test_pdf_cache_parses_same_path_once_concurrently(monkeypatch, tmp_path):
    import invoice_processor.core.pdf_text as pdf_text_module

    parse_started = threading.Event()
    release_parse = threading.Event()
    parse_calls = 0
    parse_calls_lock = threading.Lock()

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

    def fake_open(_):
        nonlocal parse_calls
        with parse_calls_lock:
            parse_calls += 1
        parse_started.set()
        release_parse.wait(timeout=5)
        return FakePdf()

    monkeypatch.setattr(pdf_text_module.pdfplumber, 'open', fake_open)
    extractor = PdfTextExtractor()
    pdf_path = str(tmp_path / 'invoice.pdf')
    results = []

    def extract():
        results.append(extractor.extract_pdf_text(pdf_path))

    first = threading.Thread(target=extract)
    first.start()
    assert parse_started.wait(timeout=5)
    others = [threading.Thread(target=extract) for _ in range(7)]
    for thread in others:
        thread.start()
    release_parse.set()
    first.join(timeout=5)
    for thread in others:
        thread.join(timeout=5)

    assert parse_calls == 1
    assert results == ['发票文本'] * 8


# ═══════════════════════════════════════════════════════════
# 改进 1: 停止中断 + 进度回调集成
# ═══════════════════════════════════════════════════════════

class TestProgressCallback:
    """进度回调集成测试"""

    def test_post_process_reports_progress(self, tmp_path):
        """post_process 应通过回调报告进度"""
        proc = InvoiceProcessor()
        # 创建空输出目录（无 PDF 文件）
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        progress_values = []
        proc.post_process(
            str(out_dir), progress_callback=lambda r: progress_values.append(r)
        )
        # 应至少报告 0.0 和 1.0
        assert len(progress_values) > 0
        assert progress_values[0] == 0.0
        assert progress_values[-1] == 1.0
        # 进度应单调递增
        for i in range(1, len(progress_values)):
            assert progress_values[i] >= progress_values[i - 1]

    def test_post_process_progress_in_range(self, tmp_path):
        """所有进度值应在 0.0-1.0 范围内"""
        proc = InvoiceProcessor()
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        progress_values = []
        proc.post_process(
            str(out_dir), progress_callback=lambda r: progress_values.append(r)
        )
        for v in progress_values:
            assert 0.0 <= v <= 1.0


# ═══════════════════════════════════════════════════════════
# 端到端：去重 + 金额标准化 + 输出文件生成
# ═══════════════════════════════════════════════════════════

class TestEndToEndDedup:
    """端到端去重测试：文件名去重 + 内容哈希去重协同工作"""

    def test_filename_and_content_dedup_independent(self, tmp_path):
        """文件名去重和内容去重应独立工作"""
        proc = InvoiceProcessor()
        src1 = tmp_path / "src1.pdf"
        src2 = tmp_path / "src2.pdf"
        src1.write_bytes(b"content A")
        src2.write_bytes(b"content B")
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        # 相同发票号+金额 → 文件名去重触发
        proc._generate_output_file(str(src1), str(out_dir), "INV001", "100.00", "ZJ")
        proc._generate_output_file(str(src2), str(out_dir), "INV001", "100.00", "ZJ")
        pdfs = [f.name for f in out_dir.iterdir() if f.suffix == '.pdf']
        assert pdfs == ["INV001-100.00.pdf"]

    def test_content_dedup_logs_warning(self, tmp_path, capsys):
        """内容重复应记录 warning 日志"""
        proc = InvoiceProcessor(
            log_callback=lambda msg, level: print(f"[{level}] {msg}")
        )
        text = "相同发票内容"
        proc._check_content_duplicate(text, "source1.pdf")
        proc._check_content_duplicate(text, "source2.pdf")
        captured = capsys.readouterr()
        assert "内容重复" in captured.out
        assert "source2.pdf" in captured.out
