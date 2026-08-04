"""单元测试：本地规则预检（纯函数，不依赖 PDF/网络）

运行方式: pytest tests/test_local_audit.py -v
"""
import glob

from src.core.local_audit import check_filenames, check_rows


class TestCheckFilenames:
    def test_same_invoice_diff_amounts(self):
        out = check_filenames(['A-100.00.pdf', 'A-120.00.pdf'])
        assert any(f['type'] == 'extract' and '不一致金额' in f['issue'] for f in out)

    def test_duplicate_detected(self):
        out = check_filenames(['A-100.00.pdf', 'A-100.00.pdf'])
        assert any(f['type'] == 'duplicate' for f in out)

    def test_invoice_and_trip_paired_not_duplicate(self):
        """发票 + 行程单同号同额是配套，不算重复"""
        out = check_filenames(['A-67.30.pdf', 'A-67.30行程单.pdf'])
        assert not any(f['type'] in ('duplicate', 'extract') for f in out)

    def test_clean_files_no_findings(self):
        assert check_filenames(['B-50.00.pdf', 'C-30.00高铁票.pdf']) == []


class TestCheckRows:
    def test_trip_sum_mismatch(self):
        rows = {
            'A-100.00行程单.pdf': [
                {'date': '2026-07-27', 'transport_amount': 40.0},
                {'date': '2026-07-28', 'transport_amount': 40.0},
            ],
        }
        out = check_rows(rows)
        assert any('行程单合计 80.0 ≠ 发票价税合计 100.0' in f['issue'] for f in out)

    def test_hotel_rate_abnormal(self):
        rows = {
            'H-150.00.pdf': [
                {'date': '2026-07-27', 'hotel_amount': 100.0, 'hotel_tax': 50.0},
            ],
        }
        out = check_rows(rows)
        assert any('住宿税率异常' in f['issue'] for f in out)

    def test_hotel_rate_normal(self):
        rows = {
            'H-106.00.pdf': [
                {'date': '2026-07-27', 'hotel_amount': 100.0, 'hotel_tax': 6.0},
            ],
        }
        out = check_rows(rows)
        assert not any('住宿税率异常' in f['issue'] for f in out)

    def test_traffic_threshold(self):
        rows = {
            'A-600.00.pdf': [
                {'date': '2026-07-27', 'transport_amount': 600.0},
            ],
        }
        out = check_rows(rows)
        assert any('超过 500 元差标' in f['issue'] for f in out)

    def test_below_threshold_ok(self):
        rows = {
            'A-300.00.pdf': [
                {'date': '2026-07-27', 'transport_amount': 300.0},
            ],
        }
        assert check_rows(rows) == []


class TestRunLocalAuditIntegration:
    """在测试输出目录上实跑（真实 PDF 解析）"""

    def test_runs_on_fixture_dir(self):
        from src.core.local_audit import run_local_audit
        from src.core.processor import InvoiceProcessor

        dirs = glob.glob('tests/data/output_test/*')
        assert dirs, '缺少 tests/data/output_test 目录'
        proc = InvoiceProcessor()
        findings = run_local_audit(dirs[0], proc)
        assert isinstance(findings, list)
        # 已知良好数据：滴滴行程合计与发票一致，不应报行程合计不匹配
        assert not any('行程单合计' in f['issue'] for f in findings)
