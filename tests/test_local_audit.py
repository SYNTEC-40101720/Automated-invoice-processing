"""单元测试：本地规则预检（纯函数，不依赖 PDF/网络）

运行方式: pytest tests/test_local_audit.py -v
"""
import base64

import pytest

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


# ---- 内嵌合成发票 PDF（一次性生成后 base64 固化，
# 假发票号 SYNTH000x，无真实发票数据）----
# 运行时仅 base64 解码写入 tmp_path，不依赖 reportlab 等生成库，也不入库。
_SYNTH_TRIP_PDF_B64 = (
    "JVBERi0xLjMKJZOMi54gUmVwb3J0TGFiIEdlbmVyYXRlZCBQREYgZG9jdW1lbnQgKG9wZW5zb3VyY2Up"
    "CjEgMCBvYmoKPDwKL0YxIDIgMCBSIC9GMiAzIDAgUgo+PgplbmRvYmoKMiAwIG9iago8PAovQmFzZUZv"
    "bnQgL0hlbHZldGljYSAvRW5jb2RpbmcgL1dpbkFuc2lFbmNvZGluZyAvTmFtZSAvRjEgL1N1YnR5cGUg"
    "L1R5cGUxIC9UeXBlIC9Gb250Cj4+CmVuZG9iagozIDAgb2JqCjw8Ci9CYXNlRm9udCAvU1RTb25nLUxp"
    "Z2h0IC9EZXNjZW5kYW50Rm9udHMgWyA8PAovQmFzZUZvbnQgL1NUU29uZy1MaWdodCAvQ0lEU3lzdGVt"
    "SW5mbyA8PAovT3JkZXJpbmcgKEdCMSkgL1JlZ2lzdHJ5IChBZG9iZSkgL1N1cHBsZW1lbnQgMAo+PiAv"
    "RFcgMTAwMCAvRm9udERlc2NyaXB0b3IgPDwKL0FzY2VudCA3NTIgL0NhcEhlaWdodCA3MzcgL0Rlc2Nl"
    "bnQgLTI3MSAvRmxhZ3MgNiAvRm9udEJCb3ggWyAtMjUgLTI1NCAxMDAwIDg4MCBdIC9Gb250TmFtZSAv"
    "U1RTb25nU3RkLUxpZ2h0IAogIC9JdGFsaWNBbmdsZSAwIC9MZWFkaW5nIDE0OCAvTWF4V2lkdGggMTAw"
    "MCAvTWlzc2luZ1dpZHRoIDUwMCAvU3RlbUggOTEgL1N0ZW1WIDU4IAogIC9UeXBlIC9Gb250RGVzY3Jp"
    "cHRvciAvWEhlaWdodCA1NTMKPj4gL1N1YnR5cGUgL0NJREZvbnRUeXBlMCAvVHlwZSAvRm9udCAKICAv"
    "VyBbIDEgWyAyMDcgMjcwIDM0MiA0NjcgNDYyIDc5NyA3MTAgMjM5IDM3NCBdIDEwIFsgMzc0IDQyMyA2"
    "MDUgMjM4IDM3NSAyMzggMzM0IDQ2MiBdIDE4IDI2IDQ2MiAyNyAyOCAyMzggCiAgMjkgMzEgNjA1IDMy"
    "IFsgMzQ0IDc0OCA2ODQgNTYwIDY5NSA3MzkgNTYzIDUxMSA3MjkgNzkzIAogIDMxOCAzMTIgNjY2IDUy"
    "NiA4OTYgNzU4IDc3MiA1NDQgNzcyIDYyOCAKICA0NjUgNjA3IDc1MyA3MTEgOTcyIDY0NyA2MjAgNjA3"
    "IDM3NCAzMzMgCiAgMzc0IDYwNiA1MDAgMjM5IDQxNyA1MDMgNDI3IDUyOSA0MTUgMjY0IAogIDQ0NCA1"
    "MTggMjQxIDIzMCA0OTUgMjI4IDc5MyA1MjcgNTI0IF0gODEgWyA1MjQgNTA0IDMzOCAzMzYgMjc3IDUx"
    "NyA0NTAgNjUyIDQ2NiA0NTIgCiAgNDA3IDM3MCAyNTggMzcwIDYwNSBdIF0KPj4gXSAvRW5jb2Rpbmcg"
    "L1VuaUdCLVVDUzItSCAvTmFtZSAvRjIgL1N1YnR5cGUgL1R5cGUwIC9UeXBlIC9Gb250Cj4+CmVuZG9i"
    "ago0IDAgb2JqCjw8Ci9Db250ZW50cyA4IDAgUiAvTWVkaWFCb3ggWyAwIDAgNTk1LjI3NTYgODQxLjg4"
    "OTggXSAvUGFyZW50IDcgMCBSIC9SZXNvdXJjZXMgPDwKL0ZvbnQgMSAwIFIgL1Byb2NTZXQgWyAvUERG"
    "IC9UZXh0IC9JbWFnZUIgL0ltYWdlQyAvSW1hZ2VJIF0KPj4gL1JvdGF0ZSAwIC9UcmFucyA8PAoKPj4g"
    "CiAgL1R5cGUgL1BhZ2UKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL1BhZ2VNb2RlIC9Vc2VOb25lIC9QYWdl"
    "cyA3IDAgUiAvVHlwZSAvQ2F0YWxvZwo+PgplbmRvYmoKNiAwIG9iago8PAovQXV0aG9yIChhbm9ueW1v"
    "dXMpIC9DcmVhdGlvbkRhdGUgKEQ6MjAyNjA4MDUxMDE3MjMrMDgnMDAnKSAvQ3JlYXRvciAoYW5vbnlt"
    "b3VzKSAvS2V5d29yZHMgKCkgL01vZERhdGUgKEQ6MjAyNjA4MDUxMDE3MjMrMDgnMDAnKSAvUHJvZHVj"
    "ZXIgKFJlcG9ydExhYiBQREYgTGlicmFyeSAtIFwob3BlbnNvdXJjZVwpKSAKICAvU3ViamVjdCAodW5z"
    "cGVjaWZpZWQpIC9UaXRsZSAodW50aXRsZWQpIC9UcmFwcGVkIC9GYWxzZQo+PgplbmRvYmoKNyAwIG9i"
    "ago8PAovQ291bnQgMSAvS2lkcyBbIDQgMCBSIF0gL1R5cGUgL1BhZ2VzCj4+CmVuZG9iago4IDAgb2Jq"
    "Cjw8Ci9GaWx0ZXIgWyAvQVNDSUk4NURlY29kZSAvRmxhdGVEZWNvZGUgXSAvTGVuZ3RoIDMzOQo+Pgpz"
    "dHJlYW0KR2F0PWU1dGYqXCY7QlRPJ20hP0pFRnNBUVJzT1FIa2MiXE89JjIyO01KWjVVYEltKlAyYG8j"
    "XldoczUzNEViQSMydE9db0AvbD5SX1tiVFNfPitOQDByLVtnWTw4VUA+YzNHMCkyUFpmLlA+aV4vLTgu"
    "aiNcaiVWUmpUbEtDOVEnQk1fJU9dPSpZVC1baEFDI1IiSE9AaXE9KTcnO1Z0LHJpbUA0MDQrVCtdS05H"
    "PmBWSF9NRj44LC8oPSVNVFdqPkMkKEBCN2YiXyIzVUJtNkFuMyhRMT5kWE9iSm1Ucy8+MWlbQl0la1JT"
    "LVNSbz5jKEpQVWxbWyFOcyRVS2ZURTo/TDwvPi9QV1lGRWdiMENTYWUnUVQ6cFJCJzJtKyRpSk9YZk0m"
    "NSo4RFY7a01zQENablpOLChBblBmKzdwNVxLXmZNQXJXYHBzJiRuQDZuY34+ZW5kc3RyZWFtCmVuZG9i"
    "agp4cmVmCjAgOQowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwNjEgMDAwMDAgbiAKMDAwMDAwMDEw"
    "MiAwMDAwMCBuIAowMDAwMDAwMjA5IDAwMDAwIG4gCjAwMDAwMDExNDIgMDAwMDAgbiAKMDAwMDAwMTM0"
    "NSAwMDAwMCBuIAowMDAwMDAxNDEzIDAwMDAwIG4gCjAwMDAwMDE2NzQgMDAwMDAgbiAKMDAwMDAwMTcz"
    "MyAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9JRCAKWzw1YzkyZjNhYjIwMGY5OTcyNGUwNGJlYzRhYTk5NGFm"
    "Zj48NWM5MmYzYWIyMDBmOTk3MjRlMDRiZWM0YWE5OTRhZmY+XQolIFJlcG9ydExhYiBnZW5lcmF0ZWQg"
    "UERGIGRvY3VtZW50IC0tIGRpZ2VzdCAob3BlbnNvdXJjZSkKCi9JbmZvIDYgMCBSCi9Sb290IDUgMCBS"
    "Ci9TaXplIDkKPj4Kc3RhcnR4cmVmCjIxNjIKJSVFT0YK"
)

_SYNTH_INV_PDF_B64 = (
    "JVBERi0xLjMKJZOMi54gUmVwb3J0TGFiIEdlbmVyYXRlZCBQREYgZG9jdW1lbnQgKG9wZW5zb3VyY2Up"
    "CjEgMCBvYmoKPDwKL0YxIDIgMCBSIC9GMiAzIDAgUgo+PgplbmRvYmoKMiAwIG9iago8PAovQmFzZUZv"
    "bnQgL0hlbHZldGljYSAvRW5jb2RpbmcgL1dpbkFuc2lFbmNvZGluZyAvTmFtZSAvRjEgL1N1YnR5cGUg"
    "L1R5cGUxIC9UeXBlIC9Gb250Cj4+CmVuZG9iagozIDAgb2JqCjw8Ci9CYXNlRm9udCAvU1RTb25nLUxp"
    "Z2h0IC9EZXNjZW5kYW50Rm9udHMgWyA8PAovQmFzZUZvbnQgL1NUU29uZy1MaWdodCAvQ0lEU3lzdGVt"
    "SW5mbyA8PAovT3JkZXJpbmcgKEdCMSkgL1JlZ2lzdHJ5IChBZG9iZSkgL1N1cHBsZW1lbnQgMAo+PiAv"
    "RFcgMTAwMCAvRm9udERlc2NyaXB0b3IgPDwKL0FzY2VudCA3NTIgL0NhcEhlaWdodCA3MzcgL0Rlc2Nl"
    "bnQgLTI3MSAvRmxhZ3MgNiAvRm9udEJCb3ggWyAtMjUgLTI1NCAxMDAwIDg4MCBdIC9Gb250TmFtZSAv"
    "U1RTb25nU3RkLUxpZ2h0IAogIC9JdGFsaWNBbmdsZSAwIC9MZWFkaW5nIDE0OCAvTWF4V2lkdGggMTAw"
    "MCAvTWlzc2luZ1dpZHRoIDUwMCAvU3RlbUggOTEgL1N0ZW1WIDU4IAogIC9UeXBlIC9Gb250RGVzY3Jp"
    "cHRvciAvWEhlaWdodCA1NTMKPj4gL1N1YnR5cGUgL0NJREZvbnRUeXBlMCAvVHlwZSAvRm9udCAKICAv"
    "VyBbIDEgWyAyMDcgMjcwIDM0MiA0NjcgNDYyIDc5NyA3MTAgMjM5IDM3NCBdIDEwIFsgMzc0IDQyMyA2"
    "MDUgMjM4IDM3NSAyMzggMzM0IDQ2MiBdIDE4IDI2IDQ2MiAyNyAyOCAyMzggCiAgMjkgMzEgNjA1IDMy"
    "IFsgMzQ0IDc0OCA2ODQgNTYwIDY5NSA3MzkgNTYzIDUxMSA3MjkgNzkzIAogIDMxOCAzMTIgNjY2IDUy"
    "NiA4OTYgNzU4IDc3MiA1NDQgNzcyIDYyOCAKICA0NjUgNjA3IDc1MyA3MTEgOTcyIDY0NyA2MjAgNjA3"
    "IDM3NCAzMzMgCiAgMzc0IDYwNiA1MDAgMjM5IDQxNyA1MDMgNDI3IDUyOSA0MTUgMjY0IAogIDQ0NCA1"
    "MTggMjQxIDIzMCA0OTUgMjI4IDc5MyA1MjcgNTI0IF0gODEgWyA1MjQgNTA0IDMzOCAzMzYgMjc3IDUx"
    "NyA0NTAgNjUyIDQ2NiA0NTIgCiAgNDA3IDM3MCAyNTggMzcwIDYwNSBdIF0KPj4gXSAvRW5jb2Rpbmcg"
    "L1VuaUdCLVVDUzItSCAvTmFtZSAvRjIgL1N1YnR5cGUgL1R5cGUwIC9UeXBlIC9Gb250Cj4+CmVuZG9i"
    "ago0IDAgb2JqCjw8Ci9Db250ZW50cyA4IDAgUiAvTWVkaWFCb3ggWyAwIDAgNTk1LjI3NTYgODQxLjg4"
    "OTggXSAvUGFyZW50IDcgMCBSIC9SZXNvdXJjZXMgPDwKL0ZvbnQgMSAwIFIgL1Byb2NTZXQgWyAvUERG"
    "IC9UZXh0IC9JbWFnZUIgL0ltYWdlQyAvSW1hZ2VJIF0KPj4gL1JvdGF0ZSAwIC9UcmFucyA8PAoKPj4g"
    "CiAgL1R5cGUgL1BhZ2UKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL1BhZ2VNb2RlIC9Vc2VOb25lIC9QYWdl"
    "cyA3IDAgUiAvVHlwZSAvQ2F0YWxvZwo+PgplbmRvYmoKNiAwIG9iago8PAovQXV0aG9yIChhbm9ueW1v"
    "dXMpIC9DcmVhdGlvbkRhdGUgKEQ6MjAyNjA4MDUxMDE3MjMrMDgnMDAnKSAvQ3JlYXRvciAoYW5vbnlt"
    "b3VzKSAvS2V5d29yZHMgKCkgL01vZERhdGUgKEQ6MjAyNjA4MDUxMDE3MjMrMDgnMDAnKSAvUHJvZHVj"
    "ZXIgKFJlcG9ydExhYiBQREYgTGlicmFyeSAtIFwob3BlbnNvdXJjZVwpKSAKICAvU3ViamVjdCAodW5z"
    "cGVjaWZpZWQpIC9UaXRsZSAodW50aXRsZWQpIC9UcmFwcGVkIC9GYWxzZQo+PgplbmRvYmoKNyAwIG9i"
    "ago8PAovQ291bnQgMSAvS2lkcyBbIDQgMCBSIF0gL1R5cGUgL1BhZ2VzCj4+CmVuZG9iago4IDAgb2Jq"
    "Cjw8Ci9GaWx0ZXIgWyAvQVNDSUk4NURlY29kZSAvRmxhdGVEZWNvZGUgXSAvTGVuZ3RoIDE4Mgo+Pgpz"
    "dHJlYW0KR2FybzldYURWUSRxQnRUYEFhZik5bGc5KCJlQFwmQWkmP2ZnKjUla1RsNy4vLDFXQSIzJF1t"
    "MSRcUjxUS3BOazUtcnJENiRoT1lzWz4tWm1DL3Fvc1xUaDMhZkNMQDYmQ1IjP3JQW2dhQDRxRC5LPU42"
    "UzlbLEFgcC4nMkA2VDllV1RvNGNHcGIyL1I2bzkhZUYkP3MjMCcqcmdQIU5SbzFSPWUvaiZpYlNrO0I3"
    "VUdsQmZbfj5lbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA5CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAw"
    "MDA2MSAwMDAwMCBuIAowMDAwMDAwMTAyIDAwMDAwIG4gCjAwMDAwMDAyMDkgMDAwMDAgbiAKMDAwMDAw"
    "MTE0MiAwMDAwMCBuIAowMDAwMDAxMzQ1IDAwMDAwIG4gCjAwMDAwMDE0MTMgMDAwMDAgbiAKMDAwMDAw"
    "MTY3NCAwMDAwMCBuIAowMDAwMDAxNzMzIDAwMDAwIG4gCnRyYWlsZXIKPDwKL0lEIApbPDgxNGMxMDk3"
    "ZjZmOWQ3ODdkZTdlN2Y5ZGI1MjExYTJlPjw4MTRjMTA5N2Y2ZjlkNzg3ZGU3ZTdmOWRiNTIxMWEyZT5d"
    "CiUgUmVwb3J0TGFiIGdlbmVyYXRlZCBQREYgZG9jdW1lbnQgLS0gZGlnZXN0IChvcGVuc291cmNlKQoK"
    "L0luZm8gNiAwIFIKL1Jvb3QgNSAwIFIKL1NpemUgOQo+PgpzdGFydHhyZWYKMjAwNQolJUVPRgo="
)


@pytest.fixture
def synthetic_output_dir(tmp_path):
    """解码内嵌的合成发票 PDF 到 tmp_path（假发票号，无敏感数据）。

    合成数据在测试文件内以 base64 固化，运行时仅解码，无需 reportlab 生成。
    """
    d = tmp_path / 'synthetic_output'
    d.mkdir()
    (d / 'SYNTH0001-45.80行程单.pdf').write_bytes(base64.b64decode(_SYNTH_TRIP_PDF_B64))
    (d / 'SYNTH0001-45.80.pdf').write_bytes(base64.b64decode(_SYNTH_INV_PDF_B64))
    return d


class TestRunLocalAuditIntegration:
    """在合成 PDF 目录上实跑（真实 InvoiceProcessor 解析，无真实发票数据）"""

    def test_runs_on_synthetic_dir(self, synthetic_output_dir):
        from src.core.local_audit import run_local_audit
        from src.core.processor import InvoiceProcessor

        proc = InvoiceProcessor()
        findings = run_local_audit(str(synthetic_output_dir), proc)
        assert isinstance(findings, list)
        # 已知良好数据：滴滴行程合计与发票一致，不应报行程单合计不匹配
        assert not any('行程单合计' in f['issue'] for f in findings)
