"""费用汇总 Excel 生成模块

从已处理的 PDF 发票中提取费用数据，按日期归集生成 Excel 汇总表。
"""
import logging
import os
import re
from collections import defaultdict
from datetime import datetime

import openpyxl
from openpyxl.packaging.core import DocumentProperties
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

logger = logging.getLogger(__name__)

# ── 费用类别关键字 ──────────────────────────────────────
_HOTEL_KEYWORDS = ['住宿', '酒店', '宾馆', '客房', '入住', '房费', '住宿费']
_TRANSPORT_KEYWORDS = [
    '高铁', '乘车', '滴滴', '通行费', '火车', '高铁票', '行程单',
]
# 弱交通关键字：可能出现在住宿场景（如「商务出行」），排在住宿之后
_TRANSPORT_KEYWORDS_WEAK = ['出行']
# 交通子类别关键字（列拆口径：大众运输/出租车/过路费，吸收同事仓库汇总列）
# 大众运输 = 高铁/火车；出租车 = 滴滴行程单与滴滴发票；过路费 = 通行费发票
_RAIL_KEYWORDS = ['高铁', '火车', '乘车', '高铁票']
_TAXI_KEYWORDS = ['滴滴', '行程单', '出租']
_TOLL_KEYWORDS = ['通行费', '过路', '过桥']


def _determine_transport_kind(text: str, filename: str = '') -> str:
    """交通发票的子类别：rail=大众运输 / taxi=出租车 / toll=过路费。

    文件名优先（行程单/高铁票后缀是强信号），再按文本关键字判定；
    都不命中时默认大众运输（与旧口径「交通费」归集一致）。
    """
    if '行程单' in filename or any(k in filename for k in _TAXI_KEYWORDS):
        return 'taxi'
    if '高铁票' in filename or any(k in filename for k in _RAIL_KEYWORDS):
        return 'rail'
    if any(k in filename for k in _TOLL_KEYWORDS):
        return 'toll'
    if any(k in text for k in _TAXI_KEYWORDS):
        return 'taxi'
    if any(k in text for k in _RAIL_KEYWORDS):
        return 'rail'
    if any(k in text for k in _TOLL_KEYWORDS):
        return 'toll'
    return 'rail'

# ── 日期提取模式 ────────────────────────────────────────
# 优先匹配带特定前缀的日期字段，fallback 到通用日期
_DATE_PATTERNS = [
    # 特定前缀日期（乘车/入住/开票/行程）
    (r'(?:乘车|行程|入住|开票|开具|消费|记账|发票)'
     r'日期\s*[:：]?\s*(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?'),
    # 通用日期（作为 fallback）
    (r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?'),
]

# ── 金额提取模式 ────────────────────────────────────────
# 住宿发票：不含税金额
_HOTEL_AMOUNT_PATTERNS = [
    r'(?:金额|合计)(?:[（(]不含税[）)])?\s*[:：]?\s*[¥￥]?\s*([\d.]+)',
    r'不含税[金额]?\s*[:：]?\s*[¥￥]?\s*([\d.]+)',
]
# 住宿发票：税额/税金
_HOTEL_TAX_PATTERNS = [
    r'(?:税额|税金|税\s*额|税\s*金)\s*[:：]?\s*[¥￥]?\s*([\d.]+)',
    r'(?:税额|税金)[（(]小写[）)]\s*[:：]?\s*[¥￥]?\s*([\d.]+)',
]


def _determine_category(text: str) -> str:
    """根据文本内容判断费用类别

    返回: 'transport' | 'hotel' | 'unknown'

    三层判定：
    1. 强交通特征（高铁/乘车/滴滴/行程单等）优先——滴滴行程单的
       目的地可能含「酒店」，本质仍是交通费；
    2. 再查住宿关键字——住宿发票的收款银行常为「交通银行」，
       不能让裸「交通」这类过宽关键字先吞掉住宿发票；
    3. 最后查弱交通关键字（如「出行」，酒店场景也可能出现）。
    """
    for kw in _TRANSPORT_KEYWORDS:
        if kw in text:
            return 'transport'
    for kw in _HOTEL_KEYWORDS:
        if kw in text:
            return 'hotel'
    for kw in _TRANSPORT_KEYWORDS_WEAK:
        if kw in text:
            return 'transport'
    return 'unknown'


def _determine_category_from_filename(filename: str) -> str | None:
    """根据文件名判断费用类别（fallback）

    输出文件名后缀携带类型信息：
        *高铁票.pdf → transport
    """
    if '高铁票' in filename:
        return 'transport'
    if '行程单' in filename:
        return 'transport'
    return None


def _extract_date(text: str, category: str = 'unknown') -> str | None:
    """从发票文本中提取日期

    根据类别按优先级匹配日期字段：
    - transport: 乘车日期 > 行程日期 > 发车时间日期 > 开票日期 > 通用日期
    - hotel:     开票日期 > 入住日期 > 通用日期（报销口径记在离店/开票日）
    - unknown:   首个特定前缀日期 > 通用日期
    返回 'YYYY-MM-DD' 格式字符串，失败返回 None。
    """

    def _fmt(m: re.Match) -> str:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    if category == 'transport':
        # ① 优先匹配行程日期（乘车、行程），不匹配开票/发票日期。
        # 整段必须留在同一个 f-string 里：跨 raw 字符串拼接时 {{1,2}}
        # 不经 f-string 处理，字面量 `{` 会让分支永远匹配不上真实票据。
        for prefix in ('乘车', '行程'):
            m = re.search(
                rf'{prefix}日期\s*[:：]?\s*(\d{{4}})'
                rf'[年/-](\d{{1,2}})[月/-](\d{{1,2}})[日]?',
                text,
            )
            if m:
                return _fmt(m)
        # ② 高铁票发车时间格式：2026年07月22日 19:00开
        m = re.search(
            r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*\d{2}:\d{2}'
            r'开',
            text,
        )
        if m:
            return _fmt(m)
        # ③ fallback 到开票日期
        m = re.search(
            r'(?:开票|开具)日期\s*[:：]?\s*(\d{4})'
            r'[年/-](\d{1,2})[月/-](\d{1,2})[日]?',
            text,
        )
        if m:
            return _fmt(m)

    elif category == 'hotel':
        # ① 优先开票日期：报销把住宿记在最后一天（离店/合并开票当天）——
        #    用户口径 2026-11-15 确认「住宿我一般填到最后一天」；
        #    按入住日归集会把连住多晚的房费全压到行程第一天。
        #    改这里前先看技能 references/policy-allowance.md §2 口径记录。
        m = re.search(
            r'(?:开票|开具)日期\s*[:：]?\s*(\d{4})'
            r'[年/-](\d{1,2})[月/-](\d{1,2})[日]?',
            text,
        )
        if m:
            return _fmt(m)
        # ② fallback 到入住日期
        m = re.search(
            r'入住日期\s*[:：]?\s*(\d{4})'
            r'[年/-](\d{1,2})[月/-](\d{1,2})[日]?',
            text,
        )
        if m:
            return _fmt(m)

    # unknown 或以上 fallback 均未命中 → 所有特定前缀日期，取首个
    matches = list(re.finditer(_DATE_PATTERNS[0], text))
    if matches:
        return _fmt(matches[0])

    # 最终 fallback：通用日期，取最后一个
    matches = list(re.finditer(_DATE_PATTERNS[1], text))
    if matches:
        return _fmt(matches[-1])

    return None


def _extract_amount_from_filename(filename: str) -> float | None:
    """从文件名中提取金额（价税合计）

    文件名格式: {invoice_no}-{amount}.pdf 或 {invoice_no}-{amount}行程单.pdf
    """
    m = re.match(r'^[^-]+-(\d+\.\d{2})', filename)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _extract_hotel_amounts(text: str) -> tuple[float | None, float | None]:
    """从住宿发票文本中提取不含税金额和税金

    返回: (不含税金额, 税金)
    """
    amount = None
    tax = None

    # ① 优先匹配"合计 ¥613.21 ¥36.79"双金额格式（含税拆分）
    m = re.search(r'合计\s*[¥￥]?\s*(\d+\.\d{2})\s*[¥￥]?\s*(\d+\.\d{2})', text)
    if m:
        try:
            amount = float(m.group(1))
            tax = float(m.group(2))
            # 如果金额和税金都提取成功，直接返回
            if amount is not None and tax is not None:
                return amount, tax
        except ValueError:
            pass

    # ② 单独提取不含税金额
    for p in _HOTEL_AMOUNT_PATTERNS:
        m = re.search(p, text)
        if m:
            try:
                amount = float(m.group(1))
            except ValueError:
                pass
            break

    # ③ 单独提取税额
    for p in _HOTEL_TAX_PATTERNS:
        m = re.search(p, text)
        if m:
            try:
                tax = float(m.group(1))
            except ValueError:
                pass
            break

    return amount, tax


def _parse_didi_trip_details(raw_text: str) -> list[dict] | None:
    """解析滴滴行程单中的逐笔行程明细

    从原始文本（保留空白）中提取每笔行程的日期、时间、城市、路线与金额。
    返回: [{'date', 'time', 'city', 'route', 'mileage', 'amount'}, ...] 或 None

    保守原则（吸收同事仓库实测口径）：页头声明「共计 N 笔」时，解析出的
    笔数必须与 N 一致；不一致说明明细行解析不全（OCR 截断/版式变化），
    整体放弃逐笔拆分返回 None，回落到按发票金额单行归集——绝不部分拆分
    （部分拆分会把金额拆错日期，汇总与打印都会跟着错）。
    """
    # 提取起止日期的年份；跨年行程（如 2025-12-28 至 2026-01-05）
    # 取两个年份，按行程月份归属：月份小于起始月（12 月起的行程单里
    # 出现 01-02 月行程）→ 归终止年份，否则归起始年份。
    ym = re.search(
        r'行程起止日期.*?(\d{4})-(\d{2})-(\d{2})(?:.*?(\d{4})-\d{2}-\d{2})?',
        raw_text,
    )
    if not ym:
        return None
    start_year, start_month = ym.group(1), int(ym.group(2))
    end_year = ym.group(4) or start_year

    # 页头声明的行程笔数（旧版行程单可能没有该字段 → 不校验）
    declared = re.search(r'共计\s*(\d+)\s*笔', raw_text)

    def _trip_year(mm: str) -> str:
        return end_year if int(mm) < start_month else start_year

    trips = []
    for line in raw_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        # 行程行: 序号 车型 MM-DD HH:MM 星期 城市 起点|终点 ... 里程 金额
        m = re.match(
            r'^\d+\s+\S+\s+(\d{2})-(\d{2})\s+(\d{2}:\d{2})\s+\S+\s+(.+?)\s+(\d+\.\d+)\s+(\d+\.\d+)\s*$',
            line,
        )
        if not m:
            continue
        mm, dd, hhmm, route, mileage, amount = m.groups()
        city = route.split()[0] if route.split() else ''
        try:
            amount = float(amount)
            mileage = float(mileage)
        except ValueError:
            continue
        if amount > 0:
            trips.append({
                'date': f'{_trip_year(mm)}-{mm}-{dd}',
                'time': hhmm,
                'city': city,
                'route': route,
                'mileage': mileage,
                'amount': amount,
            })

    if not trips:
        return None
    if declared and len(trips) != int(declared.group(1)):
        logger.warning(
            '行程单笔数不符（声明 %s 笔，解析出 %d 笔），'
            '放弃逐笔拆分，按发票金额整单归集',
            declared.group(1),
            len(trips),
        )
        return None
    return trips


_INVOICE_TYPE_RULES = [
    ('增值税专用发票', '增值税专用发票'),
    ('专用发票', '增值税专用发票'),
    ('普通发票', '普通发票'),
    ('行程单', '行程单'),
    ('电子客票', '铁路电子客票'),
]


def _detect_invoice_type(text: str, filename: str = '') -> str:
    """判定票种，供填单时判断哪些税额要计入「增值税专用发票税金」。

    只有增值税专用发票（住宿）的税额进税金汇总；铁路电子客票没有税额栏，
    普通发票（打车）的税额不进（用户口径：只有专票才计算税金）。
    """
    for keyword, label in _INVOICE_TYPE_RULES:
        if keyword in text:
            return label
    if '行程单' in filename:
        return '行程单'
    return ''


def _parse_invoice(output_dir: str, filename: str, processor) -> list[dict] | None:
    """解析单个发票 PDF，返回结构化数据列表

    对于行程单（含逐笔明细），返回多行数据，每行一个日期一条金额；
    对于普通发票，返回单行数据。

    返回: [{
        'date': 'YYYY-MM-DD',
        'transport_amount': float | None,
        'hotel_amount': float | None,
        'hotel_tax': float | None,
        'category': 'transport' | 'hotel' | 'unknown',
    }, ...] 或 None
    """
    file_path = os.path.join(output_dir, filename)
    if not os.path.isfile(file_path):
        return None

    text, error_type = processor.extract_pdf_text_with_error(file_path)
    if not text:
        return None

    # 判断类别
    category = _determine_category(text)
    if category == 'unknown':
        category = _determine_category_from_filename(filename) or 'unknown'

    # 交通子类别（列拆口径：大众运输/出租车/过路费）
    transport_kind = (
        _determine_transport_kind(text, filename)
        if category == 'transport' else None
    )

    # 票种：只有增值税专用发票的税额才进填单税金栏
    invoice_type = _detect_invoice_type(text, filename)

    # ── 行程单：按天拆分逐笔行程 ──
    if '行程单' in filename and category == 'transport':
        # 用原始文本（保留空白）解析行程明细
        raw_text, _ = processor._extract_raw_text(file_path)
        if raw_text:
            trips = _parse_didi_trip_details(raw_text)
            if trips:
                return [
                    {
                        'date': t['date'],
                        'transport_amount': t['amount'],
                        'hotel_amount': None,
                        'hotel_tax': None,
                        'category': 'transport',
                        'transport_kind': transport_kind,
                        'invoice_type': invoice_type,
                        'time': t.get('time'),
                        'city': t.get('city'),
                        'route': t.get('route'),
                    }
                    for t in trips
                ]

    # ── 普通发票（含高铁票、住宿发票等） ──
    date = _extract_date(text, category)

    transport_amount = None
    hotel_amount = None
    hotel_tax = None
    extra: dict = {}

    if category == 'hotel':
        hotel_amount, hotel_tax = _extract_hotel_amounts(text)
    elif category == 'transport':
        transport_amount = _extract_amount_from_filename(filename)
        # 高铁票发车时间：2026年07月22日 19:00开
        m = re.search(r'\d{4}年\d{1,2}月\d{1,2}日\s*(\d{1,2}):(\d{2})\s*开', text)
        if m:
            extra['time'] = f'{int(m.group(1)):02d}:{m.group(2)}'
        # 高铁票座位等级：二等座 / 一等座 / 商务座。
        # 卧铺不在差标核查范围（用户口径：仅查高铁座位）。
        m = re.search(r'(一等座|二等座|商务座)', text)
        if m:
            extra['seat_class'] = m.group(1)

    if category == 'unknown':
        transport_amount = _extract_amount_from_filename(filename)

    if date is None:
        return None

    return [{
        'date': date,
        'transport_amount': transport_amount,
        'hotel_amount': hotel_amount,
        'hotel_tax': hotel_tax,
        'category': category,
        'transport_kind': transport_kind,
        'invoice_type': invoice_type,
        **extra,
    }]


# ── Excel 样式常量 ──────────────────────────────────────
_HEADER_FILL = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
_HEADER_FONT = Font(name='Microsoft YaHei UI', size=11, bold=True, color='FFFFFF')
_HEADER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)

_DATA_FONT = Font(name='Microsoft YaHei UI', size=10)
_DATA_ALIGN = Alignment(horizontal='center', vertical='center')
_NUM_ALIGN = Alignment(horizontal='right', vertical='center')

_TOTAL_FILL = PatternFill(start_color='D6E4F0', end_color='D6E4F0', fill_type='solid')
_TOTAL_FONT = Font(name='Microsoft YaHei UI', size=10, bold=True)

_THIN_BORDER = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin'),
)

_NOTE_FONT = Font(name='Microsoft YaHei UI', size=9, color='666666')


def _build_workbook(
    rows: list[dict], invoice_items: list[dict] | None = None,
) -> openpyxl.Workbook:
    """构建 Excel 工作簿

    rows: 按日期排序的字典列表，每项含:
        date, rail_amount, taxi_amount, toll_amount, subsidy_amount,
        hotel_amount, hotel_tax
    invoice_items: 票据明细（一张票一行），有则追加「票据明细」工作表
    """
    wb = openpyxl.Workbook()
    # 文档属性统一为本项目标识：openpyxl 默认 creator 会留下第三方工具痕迹
    wb.properties = DocumentProperties(
        creator='SYNTEC', lastModifiedBy='SYNTEC',
        title='费用汇总', created=datetime.now(),
    )
    ws = wb.active
    ws.title = '费用汇总'

    # 列宽
    ws.column_dimensions['A'].width = 14   # 日期
    ws.column_dimensions['B'].width = 14   # 大众运输
    ws.column_dimensions['C'].width = 14   # 过路费
    ws.column_dimensions['D'].width = 14   # 私车补贴
    ws.column_dimensions['E'].width = 14   # 住宿费
    ws.column_dimensions['F'].width = 14   # 住宿费税金

    # ── 表头 ──
    headers = [
        '日期', '大众运输', '过路费', '私车补贴',
        '住宿费', '住宿费税金',
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
        cell.border = _THIN_BORDER

    # ── 数据行 ──
    total_transport = 0.0
    total_toll = 0.0
    total_subsidy = 0.0
    total_hotel = 0.0
    total_hotel_tax = 0.0

    for i, row_data in enumerate(rows, 2):
        date_str = row_data['date']
        # 大众运输 = 高铁 + 打车（过路费单列，用户口径 2026-11-15）
        transport_amt = (
            (row_data.get('rail_amount') or 0.0)
            + (row_data.get('taxi_amount') or 0.0)
        )
        toll_amt = row_data.get('toll_amount') or 0.0
        subsidy_amt = row_data.get('subsidy_amount') or 0.0
        hotel_amt = row_data['hotel_amount'] or 0.0
        hotel_tax = row_data['hotel_tax'] or 0.0

        total_transport += transport_amt
        total_toll += toll_amt
        total_subsidy += subsidy_amt
        total_hotel += hotel_amt
        total_hotel_tax += hotel_tax

        # 日期
        c = ws.cell(row=i, column=1, value=date_str)
        c.font = _DATA_FONT
        c.alignment = _DATA_ALIGN
        c.border = _THIN_BORDER

        # 大众运输 / 过路费 / 私车补贴
        for col, amt in (
            (2, transport_amt), (3, toll_amt), (4, subsidy_amt),
        ):
            c = ws.cell(row=i, column=col, value=amt if amt > 0 else None)
            c.font = _DATA_FONT
            c.alignment = _NUM_ALIGN
            c.border = _THIN_BORDER
            c.number_format = '0.00'

        # 住宿费
        c = ws.cell(row=i, column=5, value=hotel_amt if hotel_amt > 0 else None)
        c.font = _DATA_FONT
        c.alignment = _NUM_ALIGN
        c.border = _THIN_BORDER
        c.number_format = '0.00'

        # 住宿费税金
        c = ws.cell(row=i, column=6, value=hotel_tax if hotel_tax > 0 else None)
        c.font = _DATA_FONT
        c.alignment = _NUM_ALIGN
        c.border = _THIN_BORDER
        c.number_format = '0.00'

    # ── 合计行 ──
    total_row = len(rows) + 2
    c = ws.cell(row=total_row, column=1, value='合计')
    c.fill = _TOTAL_FILL
    c.font = _TOTAL_FONT
    c.alignment = _DATA_ALIGN
    c.border = _THIN_BORDER

    for col, val in [
        (2, total_transport), (3, total_toll), (4, total_subsidy),
        (5, total_hotel), (6, total_hotel_tax),
    ]:
        c = ws.cell(row=total_row, column=col, value=round(val, 2))
        c.fill = _TOTAL_FILL
        c.font = _TOTAL_FONT
        c.alignment = _NUM_ALIGN
        c.border = _THIN_BORDER
        c.number_format = '0.00'

    # ── 备注 ──
    note_row = total_row + 2
    notes = [
        '备注：',
        '1. 大众运输 = 高铁/火车 + 打车合并一列（价税合计；高铁按乘车日期、'
        '打车按行程日期归集）；过路费 = 通行费发票（按开票日期归集）',
        '2. 私车补贴按行驶里程×1.5元/公里计算（按行程日期归集，与私车公用登记表联动）',
        '3. 住宿费 = 不含税金额，住宿费税金 = 税额'
        '（记在开票日；合并开票即离店/最后一天）',
        f'4. 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
    ]
    for j, note in enumerate(notes):
        c = ws.cell(row=note_row + j, column=1, value=note)
        c.font = _NOTE_FONT

    # ── 票据明细（票种 / 税额，填单时判专票用） ──
    if invoice_items:
        _build_detail_sheet(wb, invoice_items)

    return wb


# 「按天汇总」sheet 已删除（2026-11-15 用户决定）：与技能 build_filing_table.py
# 生成的「填单用」完全重叠，按天口径只维护技能脚本一份。


def _summarize_invoice_item(filename: str, results: list[dict]) -> dict:
    """把单张票的解析结果压成票据明细的一行（金额/税额按整张票合计）"""
    amount = 0.0
    tax = 0.0
    for r in results:
        amount += (r.get('transport_amount') or 0.0) + (r.get('hotel_amount') or 0.0)
        tax += r.get('hotel_tax') or 0.0
    dates = sorted({r['date'] for r in results if r.get('date')})
    if len(dates) > 1:
        date_text = f'{dates[0]} ~ {dates[-1]}（{len(results)} 笔）'
    else:
        date_text = dates[0] if dates else ''
    first = results[0] if results else {}
    # 行程时间/城市/路线：多笔行程单取首末时间跨度，单笔直接取；
    # 填单差补小时数与 BPM 表单的起止信息从这里抄。
    times = sorted(r['time'] for r in results if r.get('time'))
    if not times:
        time_text = ''
    elif len(times) == 1:
        time_text = times[0]
    else:
        time_text = f'{times[0]} ~ {times[-1]}'
    return {
        'file': filename,
        'type': first.get('invoice_type') or '',
        'category': first.get('category') or '',
        'date': date_text,
        'time': time_text,
        'city': ' '.join(sorted({r.get('city') for r in results if r.get('city')})),
        'route': '；'.join(r.get('route') for r in results if r.get('route')),
        'amount': round(amount, 2),
        'tax': round(tax, 2),
    }


def _build_detail_sheet(wb, items: list[dict]) -> None:
    """追加「票据明细」工作表：一张票一行，标出票种与税额。

    填单时只有增值税专用发票的税额要填进「增值税专用发票税金」，
    以前需逐张打开 PDF 确认票种；这里一次列清。
    """
    ws = wb.create_sheet('票据明细')
    headers = [
        '文件名', '票据类型', '类别', '归集日期', '时间', '城市', '路线',
        '金额', '税额', '价税合计',
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
        cell.border = _THIN_BORDER

    category_label = {'transport': '交通', 'hotel': '住宿', 'unknown': '其他'}
    total_amount = 0.0
    total_tax = 0.0
    for i, item in enumerate(items, 2):
        amount = round(item.get('amount') or 0.0, 2)
        tax = round(item.get('tax') or 0.0, 2)
        total_amount += amount
        total_tax += tax
        values = [
            item.get('file', ''),
            item.get('type') or '未识别',
            category_label.get(item.get('category', ''), item.get('category', '')),
            item.get('date', ''),
            item.get('time', ''),
            item.get('city', ''),
            item.get('route', ''),
            amount,
            tax if tax > 0 else None,
            round(amount + tax, 2),
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.font = _DATA_FONT
            cell.border = _THIN_BORDER
            if col >= 8:
                cell.alignment = _NUM_ALIGN
                cell.number_format = '0.00'
            else:
                cell.alignment = _DATA_ALIGN

    total_row = len(items) + 2
    cell = ws.cell(row=total_row, column=1, value='合计')
    cell.fill = _TOTAL_FILL
    cell.font = _TOTAL_FONT
    cell.alignment = _DATA_ALIGN
    cell.border = _THIN_BORDER
    for col, val in [(8, total_amount), (9, total_tax), (10, total_amount + total_tax)]:
        cell = ws.cell(row=total_row, column=col, value=round(val, 2))
        cell.fill = _TOTAL_FILL
        cell.font = _TOTAL_FONT
        cell.alignment = _NUM_ALIGN
        cell.border = _THIN_BORDER
        cell.number_format = '0.00'

    for col, width in zip('ABCDEFGHIJ', (46, 16, 8, 26, 14, 14, 30, 12, 10, 12)):
        ws.column_dimensions[col].width = width

    notes = [
        '备注：',
        '1. 一张票一行；行程单整张汇总成一行（逐笔行程见「费用汇总」按行程日期拆分）。',
        '2. 只有「增值税专用发票」的税额计入填单的「增值税专用发票税金」；'
        '普通发票（打车）、铁路电子客票的税额不填。',
        '3. 住宿专票：金额 = 不含税金额，税额 = 税额，价税合计 = 发票总额。',
    ]
    note_row = total_row + 2
    for j, note in enumerate(notes):
        cell = ws.cell(row=note_row + j, column=1, value=note)
        cell.font = _NOTE_FONT


def _build_day_trips_sheet(wb, trips: list[dict]) -> None:
    """追加「按日行程」工作表：一天一行，当天首末行程时间与起止地点。

    数据源是逐笔行程（含高铁发车时间），供填单差补小时数与 BPM 表单的
    开始/结束时间地点直接抄写。单点时间（高铁）首末相同，不虚构到达时间。
    """
    by_date: dict[str, list[dict]] = {}
    for t in trips:
        if t.get('date') and t.get('time'):
            by_date.setdefault(t['date'], []).append(t)
    if not by_date:
        return

    def minutes(hhmm: str) -> int:
        h, m = hhmm.split(':')
        return int(h) * 60 + int(m)

    ws = wb.create_sheet('按日行程')
    headers = ['日期', '首行程时间', '末行程时间', '首行程起点', '末行程终点']
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
        cell.border = _THIN_BORDER

    for i, d in enumerate(sorted(by_date), 2):
        day_trips = sorted(by_date[d], key=lambda t: minutes(t['time']))
        first, last = day_trips[0], day_trips[-1]
        start_place = ''
        if first.get('route'):
            token = first['route'].split()[0]
            start_place = token.split('|')[0] if '|' in token else token
        end_place = ''
        if last.get('route'):
            token = last['route'].split()[-1]
            end_place = token.split('|')[-1] if '|' in token else token
        values = [d, first['time'], last['time'], start_place, end_place]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.font = _DATA_FONT
            cell.border = _THIN_BORDER
            if col in (2, 3):
                cell.alignment = _DATA_ALIGN
            else:
                cell.alignment = _DATA_ALIGN

    for col, width in zip('ABCDE', (14, 12, 12, 24, 24)):
        ws.column_dimensions[col].width = width


def generate_expense_summary(
    output_dir: str,
    processor,
    daily_manual_totals: dict[str, tuple[float, float]] | None = None,
) -> str | None:
    """生成费用汇总 Excel 文件

    遍历输出目录中的 PDF，提取日期、类别、金额，按日期归集后生成 Excel。

    三条联动（v7.6.0，私车公用登记 → 费用汇总）：
        ① 补贴+过路费只同步到日期完全相同的汇总行，不新增行；
        ② 对应日期过路费以私车登记表为准（防止通行费发票重复计）；
        ③ 停车费仅进私车 Excel，不进汇总。

    Args:
        output_dir: 处理后的输出目录（包含 PDF 文件）
        processor: InvoiceProcessor 实例（用于文本提取缓存）
        daily_manual_totals: 私车公用按日合计 {日期: (补贴, 过路费)}，
            来自 PrivateCarService.collect_daily_totals；None 表示无私车数据

    Returns:
        Excel 文件路径，失败返回 None
    """
    try:
        pdf_files = []
        for f in os.listdir(output_dir):
            if not f.lower().endswith('.pdf'):
                continue
            # 跳过子目录中的文件
            if not os.path.isfile(os.path.join(output_dir, f)):
                continue
            # 跳过合并结果（合并后的 PDF 包含所有发票，单独处理会导致重复）
            if f == '合并结果.pdf':
                continue
            pdf_files.append(f)

        # 去重：同号发票同时存在 *.pdf 和 *行程单.pdf 时，只保留行程单
        # 行程单包含详细行程日期，比正式发票更准确
        inv_set: dict[str, list[str]] = {}
        for f in pdf_files:
            inv_no = f.split('-')[0]  # 发票号在第一个 - 之前
            inv_set.setdefault(inv_no, []).append(f)

        skip_set: set[str] = set()
        for inv_no, names in inv_set.items():
            has_trip = any('行程单' in n for n in names)
            if has_trip and len(names) > 1:
                # 有行程单版本，跳过非行程单版本
                for n in names:
                    if '行程单' not in n:
                        skip_set.add(n)

        if not pdf_files:
            logger.warning('输出目录中无 PDF 文件，无法生成费用汇总')
            return None

        # 逐文件解析
        data_by_date: dict[str, dict] = defaultdict(
            lambda: {
                'rail_amount': 0.0, 'taxi_amount': 0.0, 'toll_amount': 0.0,
                'subsidy_amount': 0.0, 'hotel_amount': 0.0, 'hotel_tax': 0.0,
            }
        )
        parsed_count = 0
        skipped_count = 0
        invoice_items: list[dict] = []
        all_trips: list[dict] = []   # 逐笔 (date, time, route) → 按日行程

        for filename in pdf_files:
            if filename in skip_set:
                skipped_count += 1
                continue

            results = _parse_invoice(output_dir, filename, processor)
            if results is None:
                continue

            parsed_count += 1
            invoice_items.append(_summarize_invoice_item(filename, results))

            for result in results:
                if result.get('time'):
                    all_trips.append({
                        'date': result['date'],
                        'time': result['time'],
                        'route': result.get('route') or '',
                    })
                date = result['date']
                if result['transport_amount'] is not None:
                    kind = result.get('transport_kind') or 'rail'
                    data_by_date[date][f'{kind}_amount'] += result['transport_amount']
                if result['hotel_amount'] is not None:
                    data_by_date[date]['hotel_amount'] += result['hotel_amount']
                if result['hotel_tax'] is not None:
                    data_by_date[date]['hotel_tax'] += result['hotel_tax']

        if not data_by_date:
            logger.warning('未能从任何 PDF 中提取到有效数据')
            return None

        # 三条联动：融合私车公用按日合计（补贴 / 过路费）
        # ① 只同步日期完全相同的行（不新增行）；② 同日过路费以私车表为准
        manual = daily_manual_totals or {}
        for d, values in data_by_date.items():
            subsidy_amt, toll_amt = manual.get(d, (0.0, 0.0))
            if subsidy_amt:
                values['subsidy_amount'] = float(subsidy_amt)
            if toll_amt:
                values['toll_amount'] = float(toll_amt)

        # 按日期排序
        sorted_dates = sorted(data_by_date.keys())
        rows = [
            {
                'date': d,
                'rail_amount': data_by_date[d]['rail_amount'],
                'taxi_amount': data_by_date[d]['taxi_amount'],
                'toll_amount': data_by_date[d]['toll_amount'],
                'subsidy_amount': data_by_date[d].get('subsidy_amount', 0.0),
                'hotel_amount': data_by_date[d]['hotel_amount'],
                'hotel_tax': data_by_date[d]['hotel_tax'],
            }
            for d in sorted_dates
        ]

        # 生成 Excel
        wb = _build_workbook(rows, invoice_items)
        _build_day_trips_sheet(wb, all_trips)
        excel_path = os.path.join(output_dir, '费用汇总.xlsx')
        wb.save(excel_path)
        logger.info(
            f'费用汇总已生成: {excel_path}'
            f'（{parsed_count} 个文件，{len(rows)} 个日期'
            f'{f"，跳过 {skipped_count} 个重复发票" if skipped_count else ""}）'
        )

        return excel_path

    except Exception as e:
        logger.error(f'费用汇总生成失败: {e}', exc_info=True)
        return None
