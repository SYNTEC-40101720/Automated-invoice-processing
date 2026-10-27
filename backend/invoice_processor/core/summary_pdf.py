"""出差费用汇总清单 PDF 生成（v7.6.0 吸收同事版口径）

职责：
    - 按日期行生成 A5 横向「出差清单」，列：
      日期 / 大众运输 / 出租车 / 过路费 / 私车补贴 / 住宿费 / 住宿费税金 / 合计
    - 与费用汇总 Excel（excel_summary.generate_expense_summary）同源同口径：
      行数据直接复用 _collect_daily_rows 的聚合结果，不重复解析。

中文字体：使用 reportlab 内置 CID 字体 STSong-Light（无需携带字体文件，
打包体积零增量，域控环境无字型依赖）。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

SUMMARY_PDF_FILENAME = '出差清单.pdf'

# 每页行数上限（A5 横向，字号 7 下的可读行数）
_ROWS_PER_PAGE = 18

_HEADER_BG = colors.HexColor('#E9F3F9')
_HEADER_FG = colors.HexColor('#17324D')
_BODY_FG = colors.HexColor('#24384E')
_GRID = colors.HexColor('#9DB8CC')
_TOTAL_BG = colors.HexColor('#DDEBF5')

_TABLE_COLUMNS = ('日期', '大众运输', '出租车', '过路费', '私车补贴',
                  '住宿费', '住宿费税金', '合计')
# A5 横向可用宽约 499pt（210mm-2×20pt），列宽合计须≈可用宽
_TABLE_COL_WIDTHS = (76, 62, 55, 52, 58, 62, 62, 60)


def _fmt_money(value: float) -> str:
    """金额格式化：0 → 空串（同 Excel 口径，0 不显示），其余两位小数"""
    if not value:
        return ''
    return f'{value:,.2f}'


def _row_total(row: dict) -> float:
    return round(
        (row.get('rail_amount') or 0.0)
        + (row.get('taxi_amount') or 0.0)
        + (row.get('toll_amount') or 0.0)
        + (row.get('subsidy_amount') or 0.0)
        + (row.get('hotel_amount') or 0.0)
        + (row.get('hotel_tax') or 0.0),
        2,
    )


def _register_font() -> None:
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    except Exception:  # pragma: no cover - 注册失败时用默认字体兜底
        logger.warning('STSong-Light 字体注册失败，回退默认字体')


def _build_table_style(row_count: int, has_total: bool) -> TableStyle:
    commands = [
        ('FONTNAME', (0, 0), (-1, -1), 'STSong-Light'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('TEXTCOLOR', (0, 0), (-1, -1), _BODY_FG),
        ('GRID', (0, 0), (-1, -1), 0.4, _GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        # 表头
        ('BACKGROUND', (0, 0), (-1, 0), _HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), _HEADER_FG),
        ('FONTSIZE', (0, 0), (-1, 0), 7.5),
        ('FONTNAME', (0, 0), (-1, 0), 'STSong-Light'),
    ]
    if has_total and row_count > 0:
        last = row_count  # 含表头时合计行是最后一行
        commands.extend([
            ('BACKGROUND', (0, last), (-1, last), _TOTAL_BG),
            ('FONTNAME', (0, last), (-1, last), 'STSong-Light'),
        ])
    return TableStyle(commands)


def generate_summary_pdf(
    output_dir: str,
    rows: list[dict],
) -> str | None:
    """生成出差清单 PDF。

    Args:
        output_dir: 输出目录（PDF 写入该目录，文件名 出差清单.pdf）
        rows: 与 excel_summary._build_workbook 同构的按日行列表，每项含
            date / rail_amount / taxi_amount / toll_amount /
            subsidy_amount / hotel_amount / hotel_tax

    Returns:
        PDF 路径；rows 为空或写盘失败返回 None。
    """
    if not rows:
        logger.warning('无按日汇总数据，跳过出差清单 PDF 生成')
        return None

    try:
        _register_font()
        pdf_path = os.path.join(output_dir, SUMMARY_PDF_FILENAME)

        title = f'出差费用汇总清单（{rows[0]["date"]} ~ {rows[-1]["date"]}）'
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=landscape(A5),
            leftMargin=20,
            rightMargin=20,
            topMargin=24,
            bottomMargin=24,
            title=title,
            author='SYNTEC 电子票据处理系统',
        )

        story: list = []

        from reportlab.lib.styles import ParagraphStyle
        title_style = ParagraphStyle(
            'TitleStyle',
            fontName='STSong-Light',
            fontSize=13,
            leading=17,
            textColor=_HEADER_FG,
            alignment=1,  # center
            spaceAfter=8,
        )
        note_style = ParagraphStyle(
            'NoteStyle',
            fontName='STSong-Light',
            fontSize=6.5,
            leading=9,
            textColor=_BODY_FG,
        )

        # 分页：每页 ≤_ROWS_PER_PAGE 条数据行（表头每页重复）
        pages: list[list[dict]] = []
        for i in range(0, len(rows), _ROWS_PER_PAGE):
            pages.append(rows[i:i + _ROWS_PER_PAGE])

        for page_index, page_rows in enumerate(pages):
            if page_index > 0:
                story.append(PageBreak())
            story.append(Paragraph(title, title_style))
            data: list[list[str]] = [list(_TABLE_COLUMNS)]
            for row in page_rows:
                data.append([
                    str(row.get('date', '')),
                    _fmt_money(row.get('rail_amount') or 0.0),
                    _fmt_money(row.get('taxi_amount') or 0.0),
                    _fmt_money(row.get('toll_amount') or 0.0),
                    _fmt_money(row.get('subsidy_amount') or 0.0),
                    _fmt_money(row.get('hotel_amount') or 0.0),
                    _fmt_money(row.get('hotel_tax') or 0.0),
                    _fmt_money(_row_total(row)),
                ])

            # 最后一页尾接合计行
            if page_index == len(pages) - 1:
                totals = {
                    'rail_amount': sum(r.get('rail_amount') or 0.0 for r in rows),
                    'taxi_amount': sum(r.get('taxi_amount') or 0.0 for r in rows),
                    'toll_amount': sum(r.get('toll_amount') or 0.0 for r in rows),
                    'subsidy_amount': sum(r.get('subsidy_amount') or 0.0 for r in rows),
                    'hotel_amount': sum(r.get('hotel_amount') or 0.0 for r in rows),
                    'hotel_tax': sum(r.get('hotel_tax') or 0.0 for r in rows),
                }
                data.append([
                    '合计',
                    _fmt_money(totals['rail_amount']),
                    _fmt_money(totals['taxi_amount']),
                    _fmt_money(totals['toll_amount']),
                    _fmt_money(totals['subsidy_amount']),
                    _fmt_money(totals['hotel_amount']),
                    _fmt_money(totals['hotel_tax']),
                    _fmt_money(_row_total(totals)),
                ])

            table = Table(data, colWidths=_TABLE_COL_WIDTHS, repeatRows=1)
            table.setStyle(_build_table_style(len(data) - 1,
                                              page_index == len(pages) - 1))
            story.append(table)
            if page_index == len(pages) - 1:
                story.append(Spacer(1, 6))
                story.append(Paragraph(
                    '备注：交通费拆分为大众运输（高铁/火车）/出租车（滴滴）/'
                    '过路费（通行费）；私车补贴按行驶里程×1.5元/公里计算；'
                    f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                    note_style,
                ))

        doc.build(story)
        logger.info(f'出差清单已生成: {pdf_path}（{len(rows)} 个日期）')
        return pdf_path

    except Exception as e:
        logger.error(f'出差清单生成失败: {e}', exc_info=True)
        return None
