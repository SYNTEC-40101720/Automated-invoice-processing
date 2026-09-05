"""单元测试：AI 审核模块（提示词构造 + 响应解析，不联网）

运行方式: pytest tests/test_ai_audit.py -v
"""
import json
import urllib.request

from invoice_processor.core.ai_audit import build_prompt, parse_findings
from invoice_processor.core.ai_audit import test_connection as check_ai_connection


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class TestBuildPrompt:
    def test_contains_data(self):
        records = [{
            'file': 'a.pdf',
            'rows': [{'date': '2026-07-27', 'category': 'transport',
                      'transport_amount': 17.9}],
        }]
        prompt = build_prompt(records)
        assert 'a.pdf' in prompt
        assert '2026-07-27' in prompt

    def test_chinese_audit_rules(self):
        prompt = build_prompt([{'file': 'x'}])
        assert '金额' in prompt
        assert '重复' in prompt
        # 审核重点是金额错误，行程只做简易核对
        assert '重点是金额错误' in prompt


class TestParseFindings:
    def test_empty_array(self):
        assert parse_findings('[]') == []

    def test_plain_json_array(self):
        content = (
            '[{"file": "a.pdf", "type": "conflict", '
            '"issue": "时间冲突", "suggestion": "核对"}]'
        )
        out = parse_findings(content)
        assert len(out) == 1
        assert out[0]['file'] == 'a.pdf'
        assert out[0]['type'] == 'conflict'

    def test_markdown_fenced(self):
        content = (
            '```json\n[{"file": "b.pdf", "type": "extract", '
            '"issue": "x", "suggestion": "y"}]\n```'
        )
        out = parse_findings(content)
        assert len(out) == 1
        assert out[0]['type'] == 'extract'

    def test_noise_around(self):
        content = (
            '好的，以下是审核结果：\n'
            '[{"file": "c.pdf", "type": "duplicate", "issue": "重复", '
            '"suggestion": "z"}]\n完毕'
        )
        out = parse_findings(content)
        assert len(out) == 1
        assert out[0]['type'] == 'duplicate'

    def test_invalid_inputs(self):
        assert parse_findings('无法解析') == []
        assert parse_findings(None) == []
        assert parse_findings('') == []
        assert parse_findings('{}') == []


def test_connection_posts_minimal_chat_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured['request'] = request
        captured['timeout'] = timeout
        return FakeResponse(b'{"choices":[{"message":{"content":"OK"}}]}')

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)

    check_ai_connection(
        'pending-key',
        api_base='https://ai.example.com/',
        model='test-model',
        timeout=15,
    )

    request = captured['request']
    assert request.full_url == 'https://ai.example.com/chat/completions'
    assert request.get_header('Authorization') == 'Bearer pending-key'
    assert captured['timeout'] == 15
    assert json.loads(request.data) == {
        'model': 'test-model',
        'messages': [{'role': 'user', 'content': '请仅回复 OK'}],
        'temperature': 0,
        'max_tokens': 1,
        'stream': False,
    }
