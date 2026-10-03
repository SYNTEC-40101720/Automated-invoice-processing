"""excel_summary 提取逻辑单元测试：日期正则 / 类别判定 / 跨年行程 / 座位等级。

纯文本输入（FakeProcessor 替代 PDF 文本提取），不需要真实票据。

运行方式: pytest tests/test_excel_summary_extraction.py -v
"""
from invoice_processor.core.excel_summary import (
    _determine_category,
    _extract_date,
    _parse_didi_trip_details,
    _parse_invoice,
)


class FakeProcessor:
    """替身：extract_pdf_text_with_error / _extract_raw_text 返回预置文本"""

    def __init__(self, text, raw_text=None):
        self.text = text
        self.raw_text = raw_text if raw_text is not None else text

    def extract_pdf_text_with_error(self, path):
        return self.text, None

    def _extract_raw_text(self, path):
        return self.raw_text, None


class TestDetermineCategory:
    def test_hotel_invoice_with_bank_of_communications(self):
        """住宿发票含「交通银行」→ hotel（不再被裸「交通」关键字误判）"""
        text = '某某酒店 住宿费 抵押品价值 交通银行 收款'
        assert _determine_category(text) == 'hotel'

    def test_didi_trip_with_hotel_destination(self):
        """滴滴行程单目的地含酒店 → transport（行程单特征仍优先命中交通）"""
        text = '滴滴出行 行程单 目的地：某某酒店公寓'
        assert _determine_category(text) == 'transport'

    def test_rail_ticket(self):
        assert _determine_category('电子客票 高铁 G7325') == 'transport'

    def test_unknown(self):
        assert _determine_category('无关文本') == 'unknown'


class TestExtractDate:
    def test_ride_date_iso(self):
        """乘车日期 ISO 格式（修复前 {{1,2}} 字面量导致永不匹配）"""
        assert _extract_date('乘车日期: 2026-07-22', 'transport') == '2026-07-22'

    def test_ride_date_chinese(self):
        """乘车日期中文格式"""
        assert (
            _extract_date('乘车日期：2026年07月22日', 'transport')
            == '2026-07-22'
        )

    def test_ride_date_single_digit_month_day(self):
        """单位数月/日（{{1,2}} 量词生效的回归证据）"""
        assert (
            _extract_date('行程日期: 2026年7月2日', 'transport') == '2026-07-02'
        )

    def test_trip_date_iso(self):
        assert _extract_date('行程日期: 2026-07-22', 'transport') == '2026-07-22'

    def test_depart_time_fallback(self):
        """高铁票发车时间格式：2026年07月22日 19:00开"""
        assert (
            _extract_date('车次 G7325 2026年07月22日 19:00开', 'transport')
            == '2026-07-22'
        )


class TestParseDidiTrips:
    def _trips_text(self, start='2025-12-28', end='2026-01-05'):
        return (
            f'行程起止日期 {start} 至 {end}\n'
            '1 快享 12-28 09:30 星期日 杭州 A地|B地 5.3 25.10\n'
            '2 快享 01-03 18:00 星期六 杭州 C地|D地 8.0 30.00\n'
        )

    def test_cross_year_trips(self):
        """跨年行程：12 月行程归起始年，01 月行程归终止年"""
        trips = _parse_didi_trip_details(self._trips_text())
        assert trips is not None
        assert [t['date'] for t in trips] == ['2025-12-28', '2026-01-03']

    def test_same_year_trips(self):
        """同年内行程（起止单年份或同双年份）不受影响"""
        trips = _parse_didi_trip_details(self._trips_text('2026-07-01', '2026-07-05'))
        assert trips is not None
        assert [t['date'] for t in trips] == ['2026-12-28', '2026-01-03']

    def test_legacy_single_date(self):
        """旧版式只写起止同一天（单年份）→ 行为与现状一致"""
        trips = _parse_didi_trip_details(self._trips_text('2026-03-01', '2026-03-01'))
        assert trips is not None
        assert [t['date'] for t in trips] == ['2026-12-28', '2026-01-03']

    def test_amounts_parsed(self):
        trips = _parse_didi_trip_details(self._trips_text())
        assert [t['amount'] for t in trips] == [25.10, 30.00]


class TestSeatClassExtraction:
    def _rail_invoice(self, tmp_path, seat):
        filename = 'X123-500.00高铁票.pdf'
        (tmp_path / filename).write_bytes(b'%PDF-1.4 fake')
        text = f'电子客票 乘车日期: 2026-07-22 {seat} 07车12F号'
        proc = FakeProcessor(text)
        return _parse_invoice(str(tmp_path), filename, proc)

    def test_second_class_extracted(self, tmp_path):
        rows = self._rail_invoice(tmp_path, '二等座')
        assert rows and rows[0].get('seat_class') == '二等座'

    def test_first_class_extracted(self, tmp_path):
        rows = self._rail_invoice(tmp_path, '一等座')
        assert rows and rows[0].get('seat_class') == '一等座'

    def test_sleeper_not_extracted(self, tmp_path):
        """卧铺不在座位等级提取范围（用户口径：仅查高铁座位）"""
        rows = self._rail_invoice(tmp_path, '硬卧')
        assert rows and 'seat_class' not in rows[0]

    def test_business_class_extracted(self, tmp_path):
        rows = self._rail_invoice(tmp_path, '商务座')
        assert rows and rows[0].get('seat_class') == '商务座'
