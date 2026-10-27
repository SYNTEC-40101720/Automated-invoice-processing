"""私车公用登记：明细校验、补贴计算与财务模板导出。

口径（2026-10-27 用户确认，吸收同事仓库 v1.0.16 实现）：
    - 补贴单价 1.5 元/公里，按分四舍五入（ROUND_HALF_UP）；
    - 里程差 = 结束里程 - 出发里程，两值齐备才计算；
    - 过路（桥）费与停车费单独登记，不参与补贴计算；
    - 导出使用财务 Excel 模板（每页 8 条，A5 横向），模板原件永不修改。

登记行字段（11 列，与模板列序一致）：
    [日期, 使用人, 目的地, 起时间, 止时间, 起始里程, 结束里程,
     过路费, 停车费]
其中日期 yyyy-mm-dd、时间 H:mm、里程非负数字（最多三位小数）、
费用非负数字（最多两位小数）。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import tempfile
from copy import copy, deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

SUBSIDY_PER_KM = Decimal('1.5')
ROW_FIELDS = (
    'date', 'user', 'destination', 'start_time', 'end_time',
    'start_mileage', 'end_mileage', 'toll', 'parking',
)
_DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
_TIME_RE = re.compile(r'\d{1,2}:\d{2}')
_MILEAGE_RE = re.compile(r'\d+(?:\.\d{1,3})?')
_FEE_RE = re.compile(r'\d+(?:\.\d{1,2})?')
_MAX_MILEAGE = Decimal('999999999')

# 模板资产与导出文件名
TEMPLATE_ASSET = Path(__file__).resolve().parent / 'templates' / 'private_car_v1.xlsx'
TEMPLATE_FILE_NAME = '新代私车公用费用统计表_模板.xlsx'


def get_app_directory() -> Path:
    """软件目录：frozen 为 exe 同级，开发态为仓库根。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def get_private_car_template() -> Path:
    """模板固定保存在软件目录；首次从内置原件复制，以后不覆盖该副本。"""
    template = get_app_directory() / TEMPLATE_FILE_NAME
    if not template.is_file():
        if not TEMPLATE_ASSET.is_file():
            raise FileNotFoundError(f'未找到私车公用Excel模板：{TEMPLATE_ASSET}')
        try:
            with template.open('xb') as target, TEMPLATE_ASSET.open('rb') as source:
                shutil.copyfileobj(source, target)
        except FileExistsError:
            pass
    return template


def calculate_private_car_cost(
    start: str, end: str
) -> tuple[str, str, str]:
    """返回 (里程差文本, 补贴文本, 错误文本)；空值不计算，金额按分四舍五入。"""
    values: list[Decimal | None] = []
    for label, raw in (('出发里程数', start), ('结束里程数', end)):
        text = (raw or '').strip()
        if not text:
            values.append(None)
            continue
        if not _MILEAGE_RE.fullmatch(text):
            return '', '', f'{label}请输入非负数字（最多三位小数）'
        value = Decimal(text)
        if value > _MAX_MILEAGE:
            return '', '', '里程数不能超过 999999999'
        values.append(value)
    start_value, end_value = values
    if start_value is None or end_value is None:
        return '', '', ''
    if end_value < start_value:
        return '', '', '结束里程数不能小于出发里程数'
    distance = end_value - start_value
    subsidy = (distance * SUBSIDY_PER_KM).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    distance_text = format(distance, 'f')
    if '.' in distance_text:
        distance_text = distance_text.rstrip('0').rstrip('.')
    return distance_text, format(subsidy, '.2f'), ''


def validate_row(row: dict) -> str:
    """校验一条登记行；返回错误文本（'' 为通过）。

    必填：日期、使用人、目的地、起止时间、起止里程；
    可选：过路费、停车费（留空视为 0）。
    """
    for field in ('date', 'user', 'destination', 'start_time', 'end_time',
                  'start_mileage', 'end_mileage'):
        if not str(row.get(field) or '').strip():
            return '请完整填写日期、使用人、目的地、起止时间与起止里程'
    if not _DATE_RE.fullmatch(str(row['date']).strip()):
        return '日期格式应为 yyyy-mm-dd'
    for field in ('start_time', 'end_time'):
        text = str(row[field]).strip()
        if not _TIME_RE.fullmatch(text) or not 0 <= int(text.split(':')[0]) <= 23 \
                or not 0 <= int(text.split(':')[1]) <= 59:
            return '时间格式应为 H:mm（24 小时制）'
    _, _, error = calculate_private_car_cost(
        str(row['start_mileage']), str(row['end_mileage'])
    )
    if error:
        return error
    for field, label in (('toll', '过路费'), ('parking', '停车费')):
        text = str(row.get(field) or '').strip()
        if text and not _FEE_RE.fullmatch(text):
            return f'{label}请输入非负数字（最多两位小数）'
    return ''


def normalize_row(row: dict) -> dict:
    """规整登记行：去空白、时间补零两位、空费用归 ''。"""
    def _time(text: str) -> str:
        hh, mm = text.strip().split(':')
        return f'{int(hh):02d}:{mm}'

    return {
        'date': str(row['date']).strip(),
        'user': str(row['user']).strip(),
        'destination': str(row['destination']).strip(),
        'start_time': _time(str(row['start_time'])),
        'end_time': _time(str(row['end_time'])),
        'start_mileage': str(row['start_mileage']).strip(),
        'end_mileage': str(row['end_mileage']).strip(),
        'toll': str(row.get('toll') or '').strip(),
        'parking': str(row.get('parking') or '').strip(),
    }


def _set_text(cell, value: str) -> None:
    # 姓名、目的地、车牌均是文字，不应被 Excel 当作公式执行。
    cell.value = value
    cell.data_type = 's'


def _set_number(cell, value: str, *, money: bool = False) -> None:
    number = Decimal(value)
    cell.value = float(number)
    # Excel 的 0.### 会把整数显示成 “10.”；整数必须用无小数点格式。
    cell.number_format = (
        '0' if number == number.to_integral_value()
        else ('0.00' if money else '0.###')
    )


def _fee_text(value: str) -> str:
    if not value:
        return ''
    number = Decimal(value)
    return format(
        number, '.0f' if number == number.to_integral_value() else '.2f'
    )


def export_private_car_excel(
    rows: list[dict],
    *,
    license_plate: str,
    source_directory: str,
    output_directory: str,
    template_path: Path | None = None,
) -> Path:
    """按财务模板导出私车公用费用统计表（每页 8 条，A5 横向）。

    rows 为 normalize_row 产出的登记行（已校验）。返回导出文件路径；
    模板原件永不修改（临时副本填写 + os.replace 原子替换）。
    里程差与补贴由本模块计算写入（模板 I/J 列无公式）。
    """
    if not rows:
        raise ValueError('私车公用表没有可导出的记录')
    template = template_path or get_private_car_template()
    if not template.is_file():
        raise FileNotFoundError(f'未找到私车公用Excel模板：{template}')

    # 模板列序（表头第 3 行）：B=日期 C=使用人 D=出差目的地 E/F=起止时间
    #   G=出发里程数(A) H=结束里程数(B) I=行驶里程数(B-A) J=补贴金额
    #   K2=车牌，K 明细行=过路（桥）费/停车费文字说明
    values_rows = []
    for row in rows:
        distance_text, subsidy_text, error = calculate_private_car_cost(
            row['start_mileage'], row['end_mileage']
        )
        if error:
            raise ValueError(error)
        values_rows.append([
            row['date'], row['user'], row['destination'],
            row['start_time'], row['end_time'],
            row['start_mileage'], row['end_mileage'],
            distance_text, subsidy_text,
            row['toll'], row['parking'],
        ])

    dates = sorted({row['date'] for row in rows})
    date_part = dates[0] if len(dates) == 1 else f'{dates[0]}至{dates[-1]}'
    customer = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(source_directory).name)
    customer = customer.strip(' .')[:80].rstrip(' .') or '客户'
    target = Path(output_directory) / (
        f'新代私车公用费用统计表_{date_part}_{customer}.xlsx'
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    workbook = None
    temporary_path: Path | None = None
    try:
        # 先复制完整模板，在这份副本中填写；模板原件始终不修改。
        with tempfile.NamedTemporaryFile(
            dir=target.parent, suffix='.xlsx', delete=False
        ) as stream:
            temporary_path = Path(stream.name)
        shutil.copyfile(template, temporary_path)
        workbook = load_workbook(temporary_path)
        original = workbook.active
        sheets = [original]
        for page in range(1, (len(values_rows) + 7) // 8):
            sheet = workbook.copy_worksheet(original)
            # openpyxl 复制工作表不复制图片；独立复制 SYNTEC 标志与锚点。
            for image in original._images:
                sheet.add_image(deepcopy(image))
            sheets.append(sheet)
        for page, sheet in enumerate(sheets):
            sheet.title = f'私车公用{page + 1}'
            # 包括未填写的明细行，统一宋体 10pt，保留边框/对齐格式。
            for cells in sheet.iter_rows(min_row=4, max_row=19, min_col=2, max_col=11):
                for cell in cells:
                    font = copy(cell.font)
                    font.name, font.sz = '宋体', 10
                    cell.font = font
            plate_font = copy(sheet['K2'].font)
            plate_font.name, plate_font.sz = '宋体', 12
            sheet['K2'].font = plate_font
            _set_text(sheet['K2'], license_plate.strip())
            for offset, values in enumerate(values_rows[page * 8:(page + 1) * 8]):
                row = 4 + offset * 2
                sheet.cell(
                    row, 2, datetime.strptime(values[0], '%Y-%m-%d').date()
                ).number_format = 'yyyy-mm-dd'
                for col in (1, 2):
                    _set_text(sheet.cell(row, col + 2), values[col])
                for col in (3, 4):
                    if values[col]:
                        sheet.cell(
                            row, col + 2,
                            datetime.strptime(values[col], '%H:%M').time()
                        ).number_format = 'h:mm'
                for col in (5, 6, 7, 8):
                    _set_number(
                        sheet.cell(row, col + 2), values[col], money=col == 8
                    )
                _set_text(
                    sheet.cell(row, 11),
                    '过路（桥）费：' + _fee_text(values[9]),
                )
                _set_text(
                    sheet.cell(row + 1, 11),
                    '停车费：' + _fee_text(values[10]),
                )
            sheet.print_area = 'B1:K26'
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A5
            sheet.page_setup.orientation = 'landscape'
            sheet.page_setup.scale = None
            sheet.page_setup.fitToWidth = 1
            sheet.page_setup.fitToHeight = 1
            sheet.sheet_properties.pageSetUpPr.fitToPage = True
        # 先完整写入临时文件，再替换目标，避免失败时破坏已确认文件。
        workbook.save(temporary_path)
        os.replace(str(temporary_path), str(target))
        logger.info('私车公用表已导出: %s', target)
        return target
    finally:
        if workbook is not None:
            workbook.close()
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
