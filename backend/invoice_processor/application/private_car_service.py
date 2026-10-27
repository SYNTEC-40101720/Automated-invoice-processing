"""私车公用登记服务（v7.6.0 吸收融合）。

登记数据持久化在 config.ini [private_car] 段（车牌/使用人自动记忆 +
登记行 JSON），导出与补贴计算复用 core/private_car.py 的同事版口径：
补贴 = 行驶里程 × 1.5 元/公里（ROUND_HALF_UP，两位小数）。

三条联动规则（与同事版一致，在 generate_expense_summary 后处理）：
1. 补贴+过路费只同步到日期完全相同的汇总行，不新增行；
2. 对应日期的过路费以私车表为准（防止通行费发票重复计）；
3. 停车费仅进私车 Excel，不进费用汇总。
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from .. import config_manager
from ..core.private_car import (
    calculate_private_car_cost,
    export_private_car_excel,
)

logger = logging.getLogger(__name__)

# 登记行 11 列字段（API 层命名；core/private_car.py 用 user/toll/parking，
# 服务层统一映射，避免前端与模板两套口径）
ROW_FIELDS = (
    'date',           # 0 日期 yyyy-MM-dd
    'user_name',      # 1 使用人（core 字段 user）
    'destination',    # 2 出差目的地
    'start_time',     # 3 开始时间 H:mm
    'end_time',       # 4 结束时间 H:mm
    'start_mileage',  # 5 出发里程数（A）
    'end_mileage',    # 6 结束里程数（B）
    'distance_text',  # 7 行驶里程数（B-A）——服务端计算，只读
    'subsidy_text',   # 8 补贴金额——服务端计算，只读
    'toll_fee',       # 9 过路（桥）费（core 字段 toll）
    'parking_fee',    # 10 停车费（core 字段 parking）
)

_DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


def _clean(value) -> str:
    return str(value or '').strip()


class PrivateCarService:
    """私车公用登记行的读写、校验与导出。

    行数据以 dict 列表形态存 config.ini（JSON 序列化）。distance/subsidy
    两列由里程实时计算落库（同事版在 UI 层计算，我们无常驻 UI，服务端算
    后随行保存，导出/联动直接取值）。
    """

    def __init__(self, source_directory_provider=None):
        # source_directory_provider: callable -> 导出用的"客户"目录名来源
        # （通常取最近一次任务的 source_dir；None 时用空串）
        self._source_directory_provider = source_directory_provider

    # ── 元信息（车牌/使用人） ─────────────────────────

    def get_meta(self) -> dict:
        return {
            'license_plate': config_manager.get_private_car_license_plate(),
            'user_name': config_manager.get_private_car_user_name(),
        }

    def set_meta(
        self, *, license_plate: str | None = None, user_name: str | None = None
    ) -> dict:
        values = {}
        if license_plate is not None:
            values['license_plate'] = _clean(license_plate)[:20]
        if user_name is not None:
            values['user_name'] = _clean(user_name)[:40]
        if values:
            config_manager.set_private_car_config(**values)
        return self.get_meta()

    # ── 登记行 ────────────────────────────────────────

    def get_rows(self) -> list[dict]:
        return config_manager.get_private_car_rows()

    def replace_rows(self, rows: list[dict]) -> list[dict]:
        """整体替换登记行（前端整表提交口径，与同事版表格一致）。

        每行只接受 ROW_FIELDS 字段；distance/subsidy 由里程实时计算，
        单行不完整（缺日期/里程/结束<出发）不抛错——保存是非破坏性的，
        完整校验在导出（strict）时进行，与同事版 collect_rows 口径一致。
        """
        normalized: list[dict] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            row = {field: _clean(raw.get(field)) for field in ROW_FIELDS}
            if not any(row[field] for field in ROW_FIELDS if field != 'user_name'):
                continue  # 空行过滤（除使用人外全空跳过）
            distance, subsidy, _error = calculate_private_car_cost(
                row['start_mileage'], row['end_mileage']
            )
            row['distance_text'] = distance
            row['subsidy_text'] = subsidy
            normalized.append(row)
        config_manager.set_private_car_config(rows_json=normalized)
        return normalized

    @staticmethod
    def _to_core_row(row: dict) -> dict:
        """API 行字段 → core/private_car.py 字段（user/toll/parking）。"""
        return {
            'date': row.get('date', ''),
            'user': row.get('user_name', ''),
            'destination': row.get('destination', ''),
            'start_time': row.get('start_time', ''),
            'end_time': row.get('end_time', ''),
            'start_mileage': row.get('start_mileage', ''),
            'end_mileage': row.get('end_mileage', ''),
            'toll': row.get('toll_fee', ''),
            'parking': row.get('parking_fee', ''),
        }

    # ── 联动数据源 ───────────────────────────────────

    def collect_daily_totals(self) -> dict[str, tuple[float, float]]:
        """按日期聚合 (补贴, 过路费)，供费用汇总同步（规则1/2）。

        只要求日期有效且金额可解析——不让停车费/时间的无效输入抹掉已算出
        的补贴（同事版 collect_daily_totals 非严格口径一致）。
        """
        totals: dict[str, tuple[Decimal, Decimal]] = {}
        for row in self.get_rows():
            date = _clean(row.get('date'))
            if not _DATE_RE.fullmatch(date):
                continue
            subsidy_text = _clean(row.get('subsidy_text'))
            toll_text = _clean(row.get('toll_fee'))
            if not subsidy_text and not toll_text:
                continue
            try:
                subsidy = Decimal(subsidy_text) if subsidy_text else Decimal('0')
            except InvalidOperation:
                subsidy = Decimal('0')
            try:
                toll = Decimal(toll_text) if toll_text else Decimal('0')
            except InvalidOperation:
                toll = Decimal('0')
            prev_subsidy, prev_toll = totals.get(date, (Decimal('0'), Decimal('0')))
            totals[date] = (prev_subsidy + subsidy, prev_toll + toll)
        return {
            date: (float(subsidy), float(toll))
            for date, (subsidy, toll) in totals.items()
        }

    # ── 导出 ─────────────────────────────────────────

    def export(
        self,
        *,
        rows: list[dict] | None = None,
        license_plate: str | None = None,
        source_directory: str | None = None,
        output_directory: str,
    ) -> str:
        """校验（strict）+导出私车 Excel，返回绝对路径字符串。

        rows 缺省时用已保存登记行；车牌缺省时用记忆值；source_directory
        缺省时用 provider（最近任务来源目录名，作为文件名客户段）。
        无有效行抛 ApplicationError（PRIVATE_CAR_NO_ROWS）。
        """
        from ..domain.errors import ApplicationError

        if rows is None:
            rows = self.get_rows()
        plate = license_plate if license_plate is not None else None
        plate = _clean(plate if plate is not None else '') or (
            config_manager.get_private_car_license_plate()
        )
        if source_directory is None:
            source_directory = (
                self._source_directory_provider() or ''
                if self._source_directory_provider
                else ''
            )
        # strict 校验：逐行完整，否则 4xx 报错（前端可直接展示）
        validated = self._validate_strict(rows)
        if not validated:
            raise ApplicationError(
                'PRIVATE_CAR_NO_ROWS',
                '私车公用表没有可导出的记录',
            )
        path = export_private_car_excel(
            validated,
            license_plate=plate,
            source_directory=source_directory or '',
            output_directory=output_directory,
        )
        logger.info('私车公用表已导出: %s', path)
        return str(path)

    def _validate_strict(self, rows: list[dict]) -> list[dict]:
        """导出前严格校验，返回 core/private_car.py 形态的登记行列表。

        复用 core.validate_row（同事版 collect_rows 同口径），错误带行号。
        """
        from ..core.private_car import normalize_row, validate_row

        errors: list[str] = []
        validated: list[dict] = []
        for index, raw in enumerate(rows, start=1):
            if not isinstance(raw, dict):
                continue
            row = {field: _clean(raw.get(field)) for field in ROW_FIELDS}
            if not any(row[field] for field in ROW_FIELDS if field != 'user_name'):
                continue
            core_row = self._to_core_row(row)
            error = validate_row(core_row)
            if error:
                errors.append(f'私车公用表第{index}行：{error}')
                continue
            validated.append(normalize_row(core_row))
        if errors:
            from ..domain.errors import ApplicationError

            raise ApplicationError(
                'PRIVATE_CAR_ROW_INVALID',
                '；'.join(errors),
            )
        return validated
