"""InvoiceProcessor 核心逻辑单元测试

运行方式: pytest tests/test_processor.py -v
"""

import re
import pytest

# 静态方法可直接测试，无需实例化
from src.core.processor import InvoiceProcessor, _PREFIX_SUFFIX


# ═══════════════════════════════════════════════════════════
# 税号提取
# ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("text,expected", [
    # 正常：购买方税号在销售方之前
    ("纳税人识别号：91320594688334374M  销售方", "91320594688334374M"),
    ("统一社会信用代码:ABCDEFGHIJKLMNOPQR  名称:…  销售方", "ABCDEFGHIJKLMNOPQR"),
    ("纳税人识别号:123456789012345678  销售方  纳税人识别号:876543210987654321", "123456789012345678"),
    # 没有销售方分隔符时匹配第一个
    ("统一社会信用代码:ABCDEFGHIJKLMNOPQR  纳税人识别号:123456789012345678", "ABCDEFGHIJKLMNOPQR"),
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
        assert self.proc.determine_processor_type('江苏省车辆通行费票据（电子）') is not None

    def test_jiangsu_itinerary(self):
        assert self.proc.determine_processor_type('江苏省车辆通行费电子票据行程单') is not None

    def test_highspeed_rail(self):
        assert self.proc.determine_processor_type('中国铁路') is not None
        assert self.proc.determine_processor_type('二等座') is not None

    def test_didi(self):
        assert self.proc.determine_processor_type('滴滴出行-行程单') is not None

    def test_toll_summary(self):
        assert self.proc.determine_processor_type('收费公路通行费电子票据汇总单') is not None

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
