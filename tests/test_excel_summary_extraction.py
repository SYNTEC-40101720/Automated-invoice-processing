"""excel_summary 提取逻辑单元测试：日期正则 / 类别判定 / 跨年行程 / 座位等级。

纯文本输入（FakeProcessor 替代 PDF 文本提取），不需要真实票据。

运行方式: pytest tests/test_excel_summary_extraction.py -v
"""
import unittest

import openpyxl
from invoice_processor.core.excel_summary import (
    _build_day_trips_sheet,
    _build_workbook,
    _detect_invoice_type,
    _determine_category,
    _extract_date,
    _parse_didi_trip_details,
    _parse_invoice,
    _summarize_invoice_item,
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


class TestWorkbookSubsidyColumn:
    """三条联动（v7.6.0）：补贴列落位与融合规则"""

    _BASE_ROWS = [
        {
            'date': '2026-07-01', 'rail_amount': 100.0, 'taxi_amount': 0.0,
            'toll_amount': 20.0, 'subsidy_amount': 0.0, 'hotel_amount': 0.0,
            'hotel_tax': 0.0,
        },
    ]

    def test_headers_six_columns_toll_separate(self):
        wb = _build_workbook(self._BASE_ROWS)
        ws = wb.active
        headers = [ws.cell(row=1, column=c).value for c in range(1, 7)]
        assert headers == [
            '日期', '大众运输', '过路费', '私车补贴',
            '住宿费', '住宿费税金',
        ]

    def test_transport_merges_rail_taxi_toll_separate(self):
        ws = _build_workbook(self._BASE_ROWS).active
        assert ws.cell(row=2, column=2).value == 100.0  # rail+taxi
        assert ws.cell(row=2, column=3).value == 20.0   # 过路费单列

    def test_subsidy_written_to_column_d(self):
        rows = [{**self._BASE_ROWS[0], 'subsidy_amount': 70.5}]
        ws = _build_workbook(rows).active
        assert ws.cell(row=2, column=4).value == 70.5

    def test_zero_subsidy_cell_empty(self):
        ws = _build_workbook(self._BASE_ROWS).active
        assert ws.cell(row=2, column=4).value is None

    def test_totals_row_includes_subsidy(self):
        rows = [
            self._BASE_ROWS[0],
            {
                'date': '2026-07-02', 'rail_amount': 0.0, 'taxi_amount': 0.0,
                'toll_amount': 0.0, 'subsidy_amount': 30.0,
                'hotel_amount': 0.0, 'hotel_tax': 0.0,
            },
        ]
        ws = _build_workbook(rows).active
        # 找合计行（A 列 = 合计）
        total_row = next(
            r for r in range(2, ws.max_row + 1)
            if ws.cell(row=r, column=1).value == '合计'
        )
        assert ws.cell(row=total_row, column=4).value == 30.0
        assert ws.cell(row=total_row, column=2).value == 100.0
        assert ws.cell(row=total_row, column=3).value == 20.0


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


class TestTripCountGate:
    """页头「共计 N 笔」与解析笔数一致性闸门（吸收同事仓库口径）"""

    _BASE = (
        '行程起止日期 2026-07-01 至 2026-07-05\n'
        '1 快享 12-28 09:30 星期日 杭州 A地|B地 5.3 25.10\n'
        '2 快享 01-03 18:00 星期六 杭州 C地|D地 8.0 30.00\n'
    )

    def _declared_text(self, declared):
        return f'共计 {declared} 笔\n' + self._BASE

    def test_declared_matches_parsed(self):
        trips = _parse_didi_trip_details(self._declared_text(2))
        assert trips is not None
        assert len(trips) == 2

    def test_declared_mismatch_discards_all(self):
        """声明 3 笔只解析出 2 笔 → 整体放弃，回落发票金额归集"""
        trips = _parse_didi_trip_details(self._declared_text(3))
        assert trips is None

    def test_no_declared_count_keeps_legacy(self):
        """旧版无「共计 N 笔」字段 → 不校验，行为不变"""
        trips = _parse_didi_trip_details(self._BASE)
        assert trips is not None


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


class TestHotelDatePreference:
    """住宿归集日：报销填最后一天，故开票日期优先于入住日期"""

    def test_invoice_date_wins_over_checkin(self):
        text = (
            '开票日期: 2026年11月14日 '
            '入住日期: 2026年11月10日 离店日期: 2026年11月14日'
        )
        assert _extract_date(text, 'hotel') == '2026-11-14'

    def test_checkin_used_when_no_invoice_date(self):
        text = '入住日期: 2026年11月10日 离店日期: 2026年11月14日'
        assert _extract_date(text, 'hotel') == '2026-11-10'


class TestSheetLayout:
    """sheet 布局口径：「按天汇总」已删除，按天口径只在技能 build_filing_table.py"""

    def test_daily_sheet_removed(self):
        wb = _build_workbook([
            {'date': '2026-11-10', 'rail_amount': 280.0, 'taxi_amount': 55.7,
             'toll_amount': 0.0, 'subsidy_amount': 0.0, 'hotel_amount': 0.0,
             'hotel_tax': 0.0},
        ])
        assert '按天汇总' not in wb.sheetnames


class TestInvoiceType:
    """票种判定：只有增值税专用发票的税额进填单的「增值税专用发票税金」"""

    def test_special_invoice(self):
        assert _detect_invoice_type(
            '电子发票（增值税专用发票）住宿服务') == '增值税专用发票'

    def test_normal_invoice(self):
        assert _detect_invoice_type('电子发票（普通发票）旅客运输服务') == '普通发票'

    def test_rail_e_ticket(self):
        assert _detect_invoice_type('电子客票 票价: 280.00') == '铁路电子客票'

    def test_trip_sheet_by_filename(self):
        text = '没有票种字样的文本'
        assert _detect_invoice_type(
            text, '26117000001815343296-118.90行程单.pdf') == '行程单'

    def test_unknown_type(self):
        assert _detect_invoice_type('随便一段文本') == ''


class TestSummarizeInvoiceItem:
    """行程单整张压成一行：金额合计、日期区间标注笔数"""

    def test_trip_sheet_aggregates_trips(self):
        results = [
            {'date': '2026-11-10', 'transport_amount': 8.8, 'hotel_amount': None,
             'hotel_tax': None, 'category': 'transport', 'invoice_type': '行程单'},
            {'date': '2026-11-14', 'transport_amount': 11.2, 'hotel_amount': None,
             'hotel_tax': None, 'category': 'transport', 'invoice_type': '行程单'},
        ]
        item = _summarize_invoice_item('x行程单.pdf', results)
        assert item['amount'] == 20.0
        assert item['tax'] == 0.0
        assert item['date'] == '2026-11-10 ~ 2026-11-14（2 笔）'

    def test_hotel_invoice_keeps_amount_and_tax(self):
        results = [{
            'date': '2026-11-14', 'transport_amount': None, 'hotel_amount': 1203.77,
            'hotel_tax': 72.23, 'category': 'hotel', 'invoice_type': '增值税专用发票',
        }]
        item = _summarize_invoice_item('26332000009878829916-1276.00.pdf', results)
        assert item['type'] == '增值税专用发票'
        assert item['amount'] == 1203.77
        assert item['tax'] == 72.23

    def test_time_span_multi_trip(self):
        results = [
            {'date': '2026-11-10', 'time': '17:35', 'city': '苏州',
             'route': 'a b', 'transport_amount': 10.0, 'hotel_amount': None,
             'hotel_tax': None, 'category': 'transport'},
            {'date': '2026-11-10', 'time': '08:06', 'city': '苏州',
             'route': 'c d', 'transport_amount': 20.0, 'hotel_amount': None,
             'hotel_tax': None, 'category': 'transport'},
        ]
        item = _summarize_invoice_item('x-行程单.pdf', results)
        assert item['time'] == '08:06 ~ 17:35'
        assert item['city'] == '苏州'
        assert item['route'] == 'a b；c d'  # 路线保持行程单原顺序


class TestDetailSheet:
    """「票据明细」sheet：一张票一行，标出票种与税额"""

    _ROWS = [{
        'date': '2026-11-14', 'rail_amount': 269.0, 'taxi_amount': 33.2,
        'toll_amount': 0.0, 'subsidy_amount': 0.0, 'hotel_amount': 1203.77,
        'hotel_tax': 72.23,
    }]

    _ITEMS = [
        {'file': '26332000009878829916-1276.00.pdf', 'type': '增值税专用发票',
         'category': 'hotel', 'date': '2026-11-14', 'time': '', 'city': '',
         'route': '', 'amount': 1203.77, 'tax': 72.23},
        {'file': '26329130530003442166-280.00高铁票.pdf', 'type': '铁路电子客票',
         'category': 'transport', 'date': '2026-11-10', 'time': '09:19',
         'city': '苏州', 'route': '苏州 → 温岭', 'amount': 280.0, 'tax': 0.0},
        {'file': '26117000001815343296-118.90行程单.pdf', 'type': '行程单',
         'category': 'transport', 'date': '2026-11-10 ~ 2026-11-14（10 笔）',
         'time': '08:06 ~ 17:35', 'city': '苏州', 'route': 'a；b',
         'amount': 118.9, 'tax': 0.0},
    ]

    def test_sheet_and_headers(self):
        wb = _build_workbook(self._ROWS, self._ITEMS)
        assert '票据明细' in wb.sheetnames
        ws = wb['票据明细']
        assert [ws.cell(row=1, column=c).value for c in range(1, 11)] == [
            '文件名', '票据类型', '类别', '归集日期', '时间', '城市', '路线',
            '金额', '税额', '价税合计',
        ]

    def test_only_special_invoice_shows_tax(self):
        ws = _build_workbook(self._ROWS, self._ITEMS)['票据明细']
        assert ws.cell(row=2, column=2).value == '增值税专用发票'
        assert round(ws.cell(row=2, column=9).value, 2) == 72.23
        assert ws.cell(row=3, column=2).value == '铁路电子客票'
        assert ws.cell(row=3, column=9).value is None
        assert round(ws.cell(row=3, column=10).value, 2) == 280.00
        # 行程时间/城市/路线进表，供填单差补与 BPM 抄录
        assert ws.cell(row=3, column=5).value == '09:19'
        assert ws.cell(row=4, column=5).value == '08:06 ~ 17:35'

    def test_total_row(self):
        ws = _build_workbook(self._ROWS, self._ITEMS)['票据明细']
        total_row = len(self._ITEMS) + 2
        assert ws.cell(row=total_row, column=1).value == '合计'
        assert round(ws.cell(row=total_row, column=8).value, 2) == 1602.67
        assert round(ws.cell(row=total_row, column=9).value, 2) == 72.23
        assert round(ws.cell(row=total_row, column=10).value, 2) == 1674.90

    def test_no_detail_sheet_without_items(self):
        assert '票据明细' not in _build_workbook(self._ROWS).sheetnames

class TestDayTripsSheet(unittest.TestCase):
    """「按日行程」sheet：一天一行首末行程，供填单差补与 BPM 抄写。"""

    def _trips(self):
        return [
            {'date': '2026-11-10', 'time': '09:19', 'route': '苏州|温岭'},
            {'date': '2026-11-10', 'time': '08:26', 'route': '唯亭街道|苏州站'},
            {'date': '2026-11-10', 'time': '17:35', 'route': '昌泓机器人|酒店'},
            {'date': '2026-11-11', 'time': '08:20', 'route': '文昌南路|客户'},
        ]

    def test_sheet_built_with_sorted_first_last(self):
        wb = openpyxl.Workbook()
        _build_day_trips_sheet(wb, self._trips())
        self.assertIn('按日行程', wb.sheetnames)
        ws = wb['按日行程']
        self.assertEqual([c.value for c in ws[1]],
                         ['日期', '首行程时间', '末行程时间',
                          '首行程起点', '末行程终点'])
        row2 = [c.value for c in ws[2]]
        self.assertEqual(row2[0], '2026-11-10')
        self.assertEqual(row2[1], '08:26')   # 首行程按时间排序
        self.assertEqual(row2[2], '17:35')   # 末行程为最晚时间
        self.assertEqual(row2[3], '唯亭街道')
        self.assertEqual(row2[4], '酒店')

    def test_place_falls_back_to_token_without_pipe(self):
        wb = openpyxl.Workbook()
        _build_day_trips_sheet(wb, [{'date': '2026-11-12',
                                     'time': '09:00',
                                     'route': '苏州园区站'}])
        ws = wb['按日行程']
        self.assertEqual(ws.cell(row=2, column=4).value, '苏州园区站')
        self.assertEqual(ws.cell(row=2, column=5).value, '苏州园区站')

    def test_no_trips_no_sheet(self):
        wb = openpyxl.Workbook()
        _build_day_trips_sheet(wb, [])
        self.assertNotIn('按日行程', wb.sheetnames)

    def test_entries_without_time_or_date_skipped(self):
        wb = openpyxl.Workbook()
        _build_day_trips_sheet(wb, [
            {'date': '2026-11-13', 'time': '', 'route': 'a|b'},
            {'date': '', 'time': '10:00', 'route': 'a|b'},
        ])
        self.assertNotIn('按日行程', wb.sheetnames)

    def test_time_only_rows_use_empty_place(self):
        wb = openpyxl.Workbook()
        _build_day_trips_sheet(wb, [{'date': '2026-11-14',
                                     'time': '15:37', 'route': ''}])
        ws = wb['按日行程']
        self.assertEqual(ws.cell(row=2, column=2).value, '15:37')
        self.assertEqual(ws.cell(row=2, column=3).value, '15:37')
        self.assertEqual(ws.cell(row=2, column=4).value, '')


