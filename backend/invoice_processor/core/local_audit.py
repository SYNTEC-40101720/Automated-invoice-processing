"""本地规则预检（确定性规则，不依赖 AI/网络）

在 AI 语义审核之前先跑一层确定性检查，覆盖：
- 同号发票金额不一致 / 疑似重复文件（仅凭文件名）
- 行程单合计 vs 发票价税合计
- 住宿税率合理性（3%/6%/9% 等）
- 打车单程超差标 / 高铁一等座（商务座）超差标

返回与 AI 审核一致的 findings 结构：
[{'file': str, 'type': 'extract|duplicate|other', 'issue': str, 'suggestion': str}]
"""
import logging
import os
import re
from collections import Counter, defaultdict

from .excel_summary import _parse_invoice

logger = logging.getLogger(__name__)

# 打车（滴滴行程单逐笔行程）单程差标；高铁座位差标只允许二等座
TAXI_TRIP_THRESHOLD = 100.0
RAIL_FLAGGED_SEATS = ('一等座', '商务座')
VALID_TAX_RATES = (0.01, 0.02, 0.03, 0.05, 0.06, 0.09, 0.10, 0.13)


def _suffix_of(filename: str) -> str:
    """文件名金额之后的后缀（'' / '行程单' / '高铁票'）"""
    m = re.match(r'^[^-]+-\d+\.\d{2}(.*)\.pdf$', filename)
    return m.group(1) if m else ''


def check_filenames(files: list[str]) -> list[dict]:
    """规则：同号金额不一致 / 疑似重复文件（仅凭文件名）"""
    findings: list[dict] = []
    by_inv: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for f in files:
        m = re.match(r'^([^-]+)-(\d+\.\d{2})', f)
        if not m:
            continue
        by_inv[m.group(1)].append((f, float(m.group(2)), _suffix_of(f)))

    for inv, items in by_inv.items():
        amounts = sorted({round(a, 2) for _, a, _ in items})
        if len(amounts) > 1:
            findings.append({
                'file': inv,
                'type': 'extract',
                'issue': f'同一发票号 {inv} 存在不一致金额：{amounts}',
                'suggestion': '人工核对原始发票',
            })
        # 同号同额同后缀多次出现 → 疑似重复
        counter = Counter((round(a, 2), s) for _, a, s in items)
        for (amt, suffix), cnt in counter.items():
            if cnt > 1:
                findings.append({
                    'file': inv,
                    'type': 'duplicate',
                    'issue': (
                        f'发票号 {inv} 金额 {amt:.2f}{suffix} 出现 {cnt} 次，'
                        '疑似重复下载'
                    ),
                    'suggestion': '确认是否为同一张发票重复',
                })
    return findings


def check_rows(rows_by_file: dict[str, list[dict]]) -> list[dict]:
    """规则：行程单合计 vs 发票金额 / 住宿税率 / 打车单程阈值 / 高铁座位等级"""
    findings: list[dict] = []

    for f, rows in rows_by_file.items():
        is_trip = '行程单' in f
        is_rail_ticket = '高铁票' in f
        # 行程单合计校验（文件名金额 = 发票价税合计）
        if is_trip:
            m = re.match(r'^[^-]+-(\d+\.\d{2})', f)
            expected = float(m.group(1)) if m else None
            total = round(sum(r.get('transport_amount') or 0 for r in rows), 2)
            if expected is not None and abs(total - expected) > 0.01:
                findings.append({
                    'file': f,
                    'type': 'extract',
                    'issue': f'行程单合计 {total} ≠ 发票价税合计 {expected}',
                    'suggestion': '核对行程单与发票是否配套',
                })
        for r in rows:
            amt = r.get('hotel_amount')
            tax = r.get('hotel_tax')
            if amt and tax and amt > 0:
                rate = round(tax / amt, 4)
                if not any(abs(rate - v) < 0.005 for v in VALID_TAX_RATES):
                    findings.append({
                        'file': f,
                        'type': 'extract',
                        'issue': f'住宿税率异常 {rate:.2%}（不含税 {amt}，税额 {tax}）',
                        'suggestion': '核对发票税率是否合理',
                    })
            # 打车单程超差标（仅滴滴行程单解析出的逐笔行程；
            # 通行费汇总行程单无逐笔明细，总额不适用单程规则）
            if is_trip and r.get('category') == 'transport' and (
                'route' in r or 'time' in r
            ):
                amt = r.get('transport_amount')
                if amt and amt > TAXI_TRIP_THRESHOLD:
                    route = r.get('route') or ''
                    suffix = f'（{route}）' if route else ''
                    findings.append({
                        'file': f,
                        'type': 'other',
                        'issue': (
                            f'打车单程 {amt:.2f} 元超过 '
                            f'{TAXI_TRIP_THRESHOLD:.0f} 元差标{suffix}'
                        ),
                        'suggestion': '确认是否需附超标说明',
                    })
            # 高铁座位等级超差标
            if is_rail_ticket or r.get('category') == 'transport':
                seat = r.get('seat_class')
                if seat in RAIL_FLAGGED_SEATS:
                    findings.append({
                        'file': f,
                        'type': 'other',
                        'issue': f'高铁票座位等级为{seat}，差标仅限二等座',
                        'suggestion': '确认是否需附超标说明或说明一等座事由',
                    })
    return findings


def run_local_audit(output_dir: str, processor) -> list[dict]:
    """对输出目录执行本地规则预检（解析复用 excel_summary，带缓存）"""
    try:
        files = [
            f for f in os.listdir(output_dir)
            if f.lower().endswith('.pdf') and f != '合并结果.pdf'
            and os.path.isfile(os.path.join(output_dir, f))
            and not f.startswith('待搜索')
        ]
    except OSError as e:
        logger.warning('本地规则预检读取目录失败: %s', e)
        return []

    findings = check_filenames(files)
    rows_by_file: dict[str, list[dict]] = {}
    for f in files:
        try:
            rows = _parse_invoice(output_dir, f, processor)
        except Exception as e:  # 单个文件解析失败不影响其他
            logger.warning('本地规则预检解析失败 %s: %s', f, e)
            rows = None
        if rows:
            rows_by_file[f] = rows
    findings.extend(check_rows(rows_by_file))
    return findings
