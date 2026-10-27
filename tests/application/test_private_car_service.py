"""私车公用登记服务测试（v7.6.0）。

config.ini 通过 PLATFORM_CONFIG_PATH 环境变量隔离到临时目录
（config_manager 首次调用时读取）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from invoice_processor.application.private_car_service import PrivateCarService
from invoice_processor.domain.errors import ApplicationError


@pytest.fixture
def car_service(tmp_path, monkeypatch) -> PrivateCarService:
    monkeypatch.setenv('PLATFORM_CONFIG_PATH', str(tmp_path / 'config.ini'))
    import invoice_processor.config_manager as cm

    monkeypatch.setattr(cm, 'get_config_path', lambda: tmp_path / 'config.ini')
    return PrivateCarService(source_directory_provider=lambda: '客户甲')


def _valid_row(**overrides) -> dict:
    row = {
        'date': '2026-10-23',
        'user_name': '张三',
        'destination': '上海出差',
        'start_time': '9:00',
        'end_time': '17:00',
        'start_mileage': '44118',
        'end_mileage': '44165',
        'toll_fee': '88',
        'parking_fee': '10',
    }
    row.update(overrides)
    return row


class TestMeta:
    def test_set_and_get(self, car_service):
        meta = car_service.set_meta(license_plate='苏U930FQ', user_name='张三')
        assert meta == {'license_plate': '苏U930FQ', 'user_name': '张三'}
        assert car_service.get_meta() == {
            'license_plate': '苏U930FQ',
            'user_name': '张三',
        }

    def test_partial_update_keeps_other(self, car_service):
        car_service.set_meta(license_plate='苏U930FQ')
        car_service.set_meta(user_name='李四')
        assert car_service.get_meta() == {
            'license_plate': '苏U930FQ',
            'user_name': '李四',
        }

    def test_trims_and_caps_length(self, car_service):
        meta = car_service.set_meta(
            license_plate='  苏U930FQ  ', user_name='x' * 50
        )
        assert meta['license_plate'] == '苏U930FQ'
        assert len(meta['user_name']) == 40


class TestRows:
    def test_replace_rows_computes_distance_and_subsidy(self, car_service):
        rows = car_service.replace_rows([_valid_row()])
        assert len(rows) == 1
        assert rows[0]['distance_text'] == '47'
        assert rows[0]['subsidy_text'] == '70.50'

    def test_empty_rows_are_filtered(self, car_service):
        rows = car_service.replace_rows(
            [_valid_row(), {'user_name': '张三'}, {}]
        )
        assert len(rows) == 1

    def test_rows_persist_across_service_instances(self, car_service, tmp_path):
        car_service.replace_rows([_valid_row()])
        # 新实例从 config.ini 读取（路径注入同一临时目录）
        other = PrivateCarService()
        assert other.get_rows() == car_service.get_rows()

    def test_time_normalization_saved_as_is(self, car_service):
        # 服务层不补零（core.normalize_row 在导出 strict 路径才做）
        rows = car_service.replace_rows([_valid_row(start_time='9:00')])
        assert rows[0]['start_time'] == '9:00'

    def test_replace_rows_rejects_over_cap(self, car_service):
        from invoice_processor.application.private_car_service import MAX_ROWS

        with pytest.raises(ApplicationError) as exc_info:
            car_service.replace_rows([_valid_row()] * (MAX_ROWS + 1))
        assert exc_info.value.code == 'PRIVATE_CAR_TOO_MANY_ROWS'

    def test_replace_rows_accepts_at_cap(self, car_service):
        from invoice_processor.application.private_car_service import MAX_ROWS

        rows = car_service.replace_rows([_valid_row()] * MAX_ROWS)
        assert len(rows) == MAX_ROWS


class TestDailyTotals:
    def test_aggregates_by_date(self, car_service):
        car_service.replace_rows([
            _valid_row(toll_fee='88'),
            _valid_row(date='2026-10-24', start_mileage='44165',
                       end_mileage='44265', toll_fee='12.5'),
            _valid_row(date='2026-10-24', start_mileage='44165',
                       end_mileage='44175', toll_fee='', parking_fee=''),
        ])
        totals = car_service.collect_daily_totals()
        # 100km×1.5=150 + 10km×1.5=15 = 165；过路费 12.5
        assert totals['2026-10-23'] == (70.5, 88.0)
        assert totals['2026-10-24'] == (165.0, 12.5)

    def test_invalid_date_rows_skipped(self, car_service):
        car_service.replace_rows([
            _valid_row(date='2026/10/23'),
            _valid_row(date=''),
        ])
        assert car_service.collect_daily_totals() == {}

    def test_corrupt_amounts_skipped(self, car_service, tmp_path):
        car_service.replace_rows([_valid_row()])
        # 手编 config 把补贴改坏 → 整行金额跳过，不抛异常
        import json

        import invoice_processor.config_manager as cm

        cfg = cm.load_config()
        rows = json.loads(cfg.get('private_car', 'rows_json'))
        rows[0]['subsidy_text'] = 'not-a-number'
        cm.set_private_car_config(rows_json=rows)
        # 补贴损坏按 0 计（Decimal 解析失败跳过该金额，toll 保留）
        assert car_service.collect_daily_totals() == {'2026-10-23': (0.0, 88.0)}


class TestExport:
    def test_export_uses_saved_rows(self, car_service, tmp_path):
        car_service.replace_rows([_valid_row()])
        out = tmp_path / 'out'
        out.mkdir()
        path = car_service.export(output_directory=str(out))
        assert Path(path).is_file()
        assert '新代私车公用费用统计表_2026-10-23_客户甲' in path

    def test_export_empty_raises_no_rows(self, car_service, tmp_path):
        out = tmp_path / 'out'
        out.mkdir()
        with pytest.raises(ApplicationError) as exc_info:
            car_service.export(output_directory=str(out))
        assert exc_info.value.code == 'PRIVATE_CAR_NO_ROWS'

    def test_export_strict_row_error(self, car_service, tmp_path):
        out = tmp_path / 'out'
        out.mkdir()
        with pytest.raises(ApplicationError) as exc_info:
            car_service.export(
                output_directory=str(out),
                rows=[_valid_row(end_mileage='44100')],  # < start
            )
        assert exc_info.value.code == 'PRIVATE_CAR_ROW_INVALID'
        assert '私车公用表第1行' in exc_info.value.message

    def test_export_explicit_rows_and_plate(self, car_service, tmp_path):
        out = tmp_path / 'out'
        out.mkdir()
        path = car_service.export(
            output_directory=str(out),
            rows=[_valid_row()],
            license_plate='苏A88888',
        )
        assert Path(path).is_file()
        assert '苏A88888' not in path  # 车牌只进表格内容
