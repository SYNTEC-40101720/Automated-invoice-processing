"""InvoiceProcessor 核心逻辑单元测试

运行方式: pytest tests/test_processor.py -v
"""

import re
import threading

import pytest

# 静态方法可直接测试，无需实例化
from src.core.processor import _PREFIX_SUFFIX, InvoiceProcessor

# ═══════════════════════════════════════════════════════════
# 税号提取
# ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("text,expected", [
    # 正常：购买方税号在销售方之前
    ("纳税人识别号：91320594688334374M  销售方", "91320594688334374M"),
    ("统一社会信用代码:ABCDEFGHIJKLMNOPQR  名称:…  销售方", "ABCDEFGHIJKLMNOPQR"),
    (
        "纳税人识别号:123456789012345678  销售方  "
        "纳税人识别号:876543210987654321",
        "123456789012345678",
    ),
    # 没有销售方分隔符时匹配第一个
    (
        "统一社会信用代码:ABCDEFGHIJKLMNOPQR  "
        "纳税人识别号:123456789012345678",
        "ABCDEFGHIJKLMNOPQR",
    ),
])
def test_extract_buyer_tax_id_valid(text, expected):
    assert InvoiceProcessor._extract_buyer_tax_id(text) == expected


@pytest.mark.parametrize("text", [
    None,
    "",
    "销售方  纳税人识别号：123456789012345678",  # 只有销售方没有购买方
    "无税号发票内容",
])
def test_extract_buyer_tax_id_returns_none(text):
    assert InvoiceProcessor._extract_buyer_tax_id(text) is None


# ═══════════════════════════════════════════════════════════
# 发票类型识别
# ═══════════════════════════════════════════════════════════

class TestDetermineProcessorType:
    proc = InvoiceProcessor()  # 无 log_callback 不影响此测试

    def test_zhejiang(self):
        assert self.proc.determine_processor_type('浙江通用（电子）发票') is not None
        assert self.proc.determine_processor_type('宁波通用（电子）发票') is not None

    def test_jiangsu_toll(self):
        assert self.proc.determine_processor_type(
            '江苏省车辆通行费票据（电子）'
        ) is not None

    def test_jiangsu_itinerary(self):
        assert self.proc.determine_processor_type(
            '江苏省车辆通行费电子票据行程单'
        ) is not None

    def test_highspeed_rail(self):
        assert self.proc.determine_processor_type('中国铁路') is not None
        assert self.proc.determine_processor_type('二等座') is not None

    def test_didi(self):
        assert self.proc.determine_processor_type('滴滴出行-行程单') is not None

    def test_toll_summary(self):
        assert self.proc.determine_processor_type(
            '收费公路通行费电子票据汇总单'
        ) is not None

    def test_general_fallback(self):
        assert self.proc.determine_processor_type('电子发票') is not None
        assert self.proc.determine_processor_type('发票号码') is not None

    def test_unknown(self):
        assert self.proc.determine_processor_type('乱码文本') is None


# ═══════════════════════════════════════════════════════════
# 后缀映射
# ═══════════════════════════════════════════════════════════

def test_prefix_suffix_map():
    assert _PREFIX_SUFFIX["JS"] == "行程单.pdf"
    assert _PREFIX_SUFFIX["H"] == "高铁票.pdf"
    assert _PREFIX_SUFFIX.get("ZJ", ".pdf") == ".pdf"
    assert _PREFIX_SUFFIX.get("UNKNOWN", ".pdf") == ".pdf"


# ═══════════════════════════════════════════════════════════
# 金额映射
# ═══════════════════════════════════════════════════════════

def test_create_amount_mapping(tmp_path):
    proc = InvoiceProcessor()
    # 创建模拟输出文件（不会真的解析 PDF）
    files = [
        "ABC123456789-100.50.pdf",
        "DEF987654321-200.00行程单.pdf",
        "待搜索-50.00行程单.pdf",  # 应跳过
        "not-a-match.pdf",
    ]
    for f in files:
        (tmp_path / f).touch()
    mapping = proc.create_amount_mapping(str(tmp_path))
    assert mapping == {
        "100.50": "ABC123456789",
        "200.00": "DEF987654321",
    }


def test_create_amount_mapping_omits_ambiguous_amount(tmp_path):
    proc = InvoiceProcessor()
    (tmp_path / "ABC-100.00.pdf").touch()
    (tmp_path / "DEF-100.00.pdf").touch()

    assert proc.create_amount_mapping(str(tmp_path)) == {}


def test_create_output_directory_is_unique_within_same_timestamp(tmp_path):
    proc = InvoiceProcessor()

    first = proc.create_output_directory(str(tmp_path))
    second = proc.create_output_directory(str(tmp_path))

    assert first != second


# ═══════════════════════════════════════════════════════════
# 收窄后的 fallback 正则（通用发票）
# ═══════════════════════════════════════════════════════════

def test_general_invoice_fallback_pattern():
    """验证 fallback 只在金额关键字附近匹配，降低误匹配"""
    # 20位数字跟在金额关键字附近 → 应匹配
    assert re.search(r'(?:金额|合计|价税|小写).{0,30}(?<!\d)(\d{20})(?!\d)',
                     '小写 12345678901234567890')
    # 孤立的20位数字（无金额前缀）→ 不匹配
    assert not re.search(r'(?:金额|合计|价税|小写).{0,30}(?<!\d)(\d{20})(?!\d)',
                         '密码区 12345678901234567890')


# ═══════════════════════════════════════════════════════════
# 金额标准化
# ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    ("771.8", "771.80"),       # 一位小数 → 两位
    ("771.80", "771.80"),      # 已标准
    ("771", "771.00"),         # 整数 → 两位
    ("1234.5678", "1234.57"),  # 多位小数 → 四舍五入
    ("0.5", "0.50"),
    ("1,234.5", "1,234.5"),    # 含逗号，float 解析失败 → 原样返回
    ("abc", "abc"),            # 非数值 → 原样返回
    ("", ""),                  # 空串 → 原样返回
])
def test_normalize_amount(raw, expected):
    assert InvoiceProcessor._normalize_amount(raw) == expected


# ═══════════════════════════════════════════════════════════
# 重复文件去重
# ═══════════════════════════════════════════════════════════

def test_claim_output_name_first_call_succeeds():
    """首次占位应成功"""
    proc = InvoiceProcessor()
    assert proc._claim_output_name("INV001-771.80.pdf", "source1.pdf") is True


def test_claim_output_name_duplicate_skipped():
    """重复文件名应被跳过"""
    proc = InvoiceProcessor()
    assert proc._claim_output_name("INV001-771.80.pdf", "source1.pdf") is True
    assert proc._claim_output_name("INV001-771.80.pdf", "source2.pdf") is False


def test_claim_output_name_different_files_succeed():
    """不同文件名应分别成功"""
    proc = InvoiceProcessor()
    assert proc._claim_output_name("INV001-771.80.pdf", "source1.pdf") is True
    assert proc._claim_output_name("INV002-100.00.pdf", "source2.pdf") is True


def test_claim_output_name_is_thread_safe():
    proc = InvoiceProcessor()
    barrier = threading.Barrier(8)
    results = []
    results_lock = threading.Lock()

    def claim():
        barrier.wait()
        result = proc._claim_output_name('INV001-100.00.pdf', 'source.pdf')
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    assert results.count(False) == 7


def test_reset_dedup_clears_state():
    """reset_dedup 应清空去重记录"""
    proc = InvoiceProcessor()
    proc._claim_output_name("INV001-771.80.pdf", "source1.pdf")
    proc.reset_dedup()
    # 清空后，相同文件名应能再次占位
    assert proc._claim_output_name("INV001-771.80.pdf", "source2.pdf") is True


def test_generate_output_file_dedup(tmp_path):
    """_generate_output_file 应对重复源文件只生成一份输出"""
    proc = InvoiceProcessor()
    # 创建两个内容相同的源文件
    src1 = tmp_path / "src1.pdf"
    src2 = tmp_path / "src2.pdf"
    src1.write_bytes(b"fake pdf content")
    src2.write_bytes(b"fake pdf content")
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    # 同一发票号+金额（不同格式）应只生成一个输出文件
    proc._generate_output_file(str(src1), str(out_dir), "INV001", "771.8", "ZJ")
    proc._generate_output_file(str(src2), str(out_dir), "INV001", "771.80", "ZJ")

    # 应只有一个标准化文件名 771.80
    pdfs = [f.name for f in out_dir.iterdir() if f.suffix == '.pdf']
    assert pdfs == ["INV001-771.80.pdf"]


def test_generate_output_file_amount_normalization(tmp_path):
    """_generate_output_file 应将金额标准化为两位小数"""
    proc = InvoiceProcessor()
    src = tmp_path / "src.pdf"
    src.write_bytes(b"fake pdf content")
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    proc._generate_output_file(str(src), str(out_dir), "INV001", "100.5", "ZJ")
    pdfs = [f.name for f in out_dir.iterdir() if f.suffix == '.pdf']
    assert pdfs == ["INV001-100.50.pdf"]


def test_generate_output_file_skips_existing_output(tmp_path):
    proc = InvoiceProcessor()
    src = tmp_path / "src.pdf"
    src.write_bytes(b"new content")
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    existing = out_dir / "INV001-100.00.pdf"
    existing.write_bytes(b"existing content")

    proc._generate_output_file(str(src), str(out_dir), "INV001", "100", "ZJ")

    assert existing.read_bytes() == b"existing content"


def test_missing_buyer_tax_id_is_sent_to_manual_review(tmp_path, monkeypatch):
    proc = InvoiceProcessor()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    invoice = output_dir / "INV001-100.00.pdf"
    invoice.write_bytes(b"pdf")
    monkeypatch.setattr(proc, "extract_pdf_text", lambda _: "电子发票 金额 100.00")

    tax_issues, special, normal = proc._phase_scan_and_classify(
        str(output_dir), lambda _: None,
    )

    assert not special
    assert not normal
    assert any("购买方税号缺失" in issue for issue in tax_issues)
    assert not invoice.exists()
    assert (output_dir / "需人工处理" / invoice.name).is_file()


def test_itinerary_without_buyer_tax_id_is_not_sent_to_manual_review(
    tmp_path, monkeypatch
):
    proc = InvoiceProcessor()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    itinerary = output_dir / "INV001-100.00行程单.pdf"
    itinerary.write_bytes(b"pdf")
    monkeypatch.setattr(
        proc,
        "extract_pdf_text",
        lambda _: "滴滴出行-行程单 合计100.00元",
    )

    tax_issues, special, normal = proc._phase_scan_and_classify(
        str(output_dir), lambda _: None,
    )

    assert tax_issues == []
    assert not special
    assert normal == [itinerary.name]
    assert itinerary.is_file()
    assert not (output_dir / "需人工处理").exists()


def test_itinerary_in_manual_review_is_not_rechecked_for_tax_id(tmp_path, monkeypatch):
    proc = InvoiceProcessor()
    output_dir = tmp_path / "output"
    manual_dir = output_dir / "需人工处理"
    manual_dir.mkdir(parents=True)
    itinerary = manual_dir / "INV001-100.00行程单.pdf"
    itinerary.write_bytes(b"pdf")
    monkeypatch.setattr(
        proc,
        "extract_pdf_text",
        lambda _: "行程单 纳税人识别号：000000000000000000",
    )

    tax_issues = proc._phase_scan_manual_dir(str(output_dir), lambda _: None)

    assert tax_issues == []
    assert itinerary.is_file()
    assert not (output_dir / "税号异常").exists()
