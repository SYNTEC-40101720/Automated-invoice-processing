"""FastAPI HTTP/WebSocket 契约测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import get_job_service
from src.api.routes import email as email_route
from src.api.routes import settings as settings_route
from src.api.schemas import SettingsResponse
from src.application.event_bus import EventBus
from src.application.job_service import JobService
from src.domain.job import JobTrigger
from src.version import __version__


def make_app(tmp_path):
    service = JobService(
        event_bus=EventBus(),
        max_workers_provider=lambda: 2,
    )
    return create_app(service, local_token='test-token')


def test_health_requires_local_token_and_returns_version(tmp_path):
    client = TestClient(make_app(tmp_path))
    assert client.get('/api/v1/system/health').status_code == 401
    response = client.get(
        '/api/v1/system/health',
        headers={'X-Local-Token': 'test-token'},
    )
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
    assert response.json()['mode'] == 'local'


def test_api_rejects_untrusted_origin_and_sets_security_headers(tmp_path):
    app = create_app(
        local_token='test-token',
        allowed_origins={'http://testserver'},
    )
    client = TestClient(app)

    trusted = client.get(
        '/api/v1/system/health',
        headers={
            'X-Local-Token': 'test-token',
            'Origin': 'http://testserver',
        },
    )
    assert trusted.status_code == 200
    assert "default-src 'self'" in trusted.headers['content-security-policy']
    assert trusted.headers['x-content-type-options'] == 'nosniff'

    untrusted = client.get(
        '/api/v1/system/health',
        headers={
            'X-Local-Token': 'test-token',
            'Origin': 'http://evil.example',
        },
    )
    assert untrusted.status_code == 403


def test_empty_source_returns_stable_error(tmp_path):
    source = tmp_path / 'empty'
    source.mkdir()
    client = TestClient(make_app(tmp_path))
    response = client.post(
        '/api/v1/jobs',
        headers={'X-Local-Token': 'test-token'},
        json={'source_dir': str(source)},
    )
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'NO_PDF_FILES'


def test_scan_directory_returns_top_level_pdf_count(tmp_path):
    (tmp_path / 'invoice-a.pdf').write_bytes(b'%PDF')
    (tmp_path / 'invoice-b.PDF').write_bytes(b'%PDF')
    (tmp_path / 'notes.txt').write_text('not an invoice', encoding='utf-8')
    nested = tmp_path / 'nested'
    nested.mkdir()
    (nested / 'invoice-c.pdf').write_bytes(b'%PDF')
    client = TestClient(make_app(tmp_path))

    response = client.post(
        '/api/v1/jobs/scan',
        headers={'X-Local-Token': 'test-token'},
        json={'source_dir': str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json()['source_dir'] == str(tmp_path)
    assert response.json()['pdf_count'] == 2


def test_websocket_sends_ready_and_current_snapshot(tmp_path):
    client = TestClient(make_app(tmp_path))
    with client.websocket_connect('/api/v1/events?token=test-token') as websocket:
        ready = websocket.receive_json()
        assert ready['type'] == 'system.ready'
        assert ready['payload']['version'] == __version__


def test_job_logs_endpoint_returns_only_job_logs(tmp_path):
    service = JobService(event_bus=EventBus())
    app = create_app(service, local_token='test-token')
    client = TestClient(app)
    service.events.publish(
        'job.log_appended', {'level': 'info', 'message': 'hello'}, 'job-1'
    )
    service.events.publish('job.progress', {'progress': 0.5}, 'job-1')
    service.events.publish(
        'job.log_appended', {'level': 'warning', 'message': 'warn'}, 'job-2'
    )

    # 注入一个已知任务，绕过启动线程，只测试日志过滤协议。
    from src.domain.job import Job
    service._jobs['job-1'] = Job(source_dir=str(tmp_path), id='job-1')

    response = client.get(
        '/api/v1/jobs/job-1/logs',
        headers={'X-Local-Token': 'test-token'},
    )
    assert response.status_code == 200
    assert [item['message'] for item in response.json()['items']] == ['hello']


def test_job_logs_endpoint_supports_event_cursor(tmp_path):
    service = JobService(event_bus=EventBus())
    app = create_app(service, local_token='test-token')
    client = TestClient(app)
    first = service.events.publish(
        'job.log_appended', {'level': 'info', 'message': 'first'}, 'job-1'
    )
    second = service.events.publish(
        'job.log_appended', {'level': 'info', 'message': 'second'}, 'job-1'
    )

    from src.domain.job import Job
    service._jobs['job-1'] = Job(source_dir=str(tmp_path), id='job-1')

    response = client.get(
        f'/api/v1/jobs/job-1/logs?after_event_id={first.event_id}',
        headers={'X-Local-Token': 'test-token'},
    )

    assert response.status_code == 200
    assert [item['message'] for item in response.json()['items']] == ['second']
    assert response.json()['next_event_id'] == second.event_id


def test_settings_response_redacts_secret_values(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_route, 'get_target_tax_id', lambda: 'TAX-ID')
    monkeypatch.setattr(settings_route, 'get_max_workers', lambda: 8)
    monkeypatch.setattr(settings_route, 'get_email_config', lambda: {
        'enabled': 'true', 'imap_host': 'imap.example.com', 'imap_port': '993',
        'username': 'user@example.com', 'auth_code': 'secret-auth',
        'inbox_dir': 'inbox', 'days_back': '30', 'poll_minutes': '0',
    })
    monkeypatch.setattr(settings_route, 'get_email_enabled', lambda: True)
    monkeypatch.setattr(settings_route, 'get_email_auto_process', lambda: False)
    monkeypatch.setattr(settings_route, 'get_inbox_dir', lambda: 'C:/invoice-inbox')
    monkeypatch.setattr(
        settings_route, 'get_email_username', lambda: 'user@example.com'
    )
    monkeypatch.setattr(settings_route, 'get_email_auth_code', lambda: 'secret-auth')
    monkeypatch.setattr(settings_route, 'get_email_days_back', lambda: 30)
    monkeypatch.setattr(settings_route, 'get_email_poll_minutes', lambda: 0)
    monkeypatch.setattr(settings_route, 'get_ai_enabled', lambda: True)
    monkeypatch.setattr(settings_route, 'get_ai_api_base', lambda: 'https://ai.example.com')
    monkeypatch.setattr(settings_route, 'get_ai_model', lambda: 'model')
    monkeypatch.setattr(settings_route, 'get_ai_timeout', lambda: 60)
    monkeypatch.setattr(settings_route, 'get_ai_api_key', lambda: 'secret-key')

    client = TestClient(make_app(tmp_path))
    response = client.get('/api/v1/settings', headers={'X-Local-Token': 'test-token'})

    assert response.status_code == 200
    body = response.json()
    assert body['email']['auth_code_configured'] is True
    assert body['email']['auto_process'] is False
    assert body['email']['inbox_dir'] == 'C:/invoice-inbox'
    assert body['ai']['api_key_configured'] is True
    assert 'secret-auth' not in response.text
    assert 'secret-key' not in response.text


def test_ai_test_uses_pending_key_and_settings(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(settings_route, 'get_ai_api_key', lambda: 'stored-key')
    monkeypatch.setattr(settings_route, 'get_ai_api_base', lambda: 'https://stored.example.com')
    monkeypatch.setattr(settings_route, 'get_ai_model', lambda: 'stored-model')
    monkeypatch.setattr(settings_route, 'get_ai_timeout', lambda: 60)

    def fake_test_connection(api_key, *, api_base, model, timeout):
        captured.update(
            api_key=api_key, api_base=api_base, model=model, timeout=timeout
        )

    monkeypatch.setattr(settings_route, 'test_ai_connection', fake_test_connection)
    client = TestClient(make_app(tmp_path))

    response = client.post(
        '/api/v1/settings/ai/test',
        headers={'X-Local-Token': 'test-token'},
        json={
            'api_base': 'https://pending.example.com',
            'model': 'pending-model',
            'timeout': 30,
            'api_key': 'pending-key',
        },
    )

    assert response.status_code == 200
    assert response.json() == {'ok': True, 'message': 'AI 接口连接成功，配置可用'}
    assert captured == {
        'api_key': 'pending-key',
        'api_base': 'https://pending.example.com',
        'model': 'pending-model',
        'timeout': 30,
    }


def test_ai_test_rejects_missing_key(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_route, 'get_ai_api_key', lambda: '')
    monkeypatch.setattr(settings_route, 'get_ai_api_base', lambda: 'https://ai.example.com')
    monkeypatch.setattr(settings_route, 'get_ai_model', lambda: 'model')
    client = TestClient(make_app(tmp_path))

    response = client.post(
        '/api/v1/settings/ai/test',
        headers={'X-Local-Token': 'test-token'},
        json={},
    )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'AI_CONFIGURATION_INCOMPLETE'


def test_email_pull_starts_email_job_for_downloaded_files(monkeypatch, tmp_path):
    class FakeJobService:
        def __init__(self):
            self.arguments = None

        def start_job(self, source_dir, trigger):
            self.arguments = (source_dir, trigger)
            return {'id': 'job-email', 'status': 'queued'}

    fake_service = FakeJobService()
    monkeypatch.setattr(email_route, 'get_email_config', lambda: {
        'imap_host': 'imap.example.com', 'imap_port': '993',
    })
    monkeypatch.setattr(email_route, 'get_email_username', lambda: 'user@example.com')
    monkeypatch.setattr(email_route, 'get_email_auth_code', lambda: 'auth')
    monkeypatch.setattr(email_route, 'get_inbox_dir', lambda: str(tmp_path))
    monkeypatch.setattr(email_route, 'get_email_days_back', lambda: 30)
    monkeypatch.setattr(email_route, 'get_email_auto_process', lambda: True)
    monkeypatch.setattr(email_route, 'pull_invoices', lambda **kwargs: {
        'downloaded': 1, 'new_files': [str(tmp_path / 'invoice.pdf')],
        'errors': [], 'total_scanned': 1,
    })

    app = make_app(tmp_path)
    app.dependency_overrides[get_job_service] = lambda: fake_service
    client = TestClient(app)
    response = client.post(
        '/api/v1/email/pull', headers={'X-Local-Token': 'test-token'}
    )

    assert response.status_code == 200
    assert response.json()['job']['id'] == 'job-email'
    assert fake_service.arguments == (str(tmp_path), JobTrigger.EMAIL)


def test_email_pull_only_downloads_when_auto_process_disabled(monkeypatch, tmp_path):
    class FakeJobService:
        def __init__(self):
            self.called = False

        def start_job(self, source_dir, trigger):
            self.called = True
            return {'id': 'unexpected-job', 'status': 'queued'}

    fake_service = FakeJobService()
    monkeypatch.setattr(email_route, 'get_email_config', lambda: {
        'imap_host': 'imap.example.com', 'imap_port': '993',
    })
    monkeypatch.setattr(email_route, 'get_email_username', lambda: 'user@example.com')
    monkeypatch.setattr(email_route, 'get_email_auth_code', lambda: 'auth')
    monkeypatch.setattr(email_route, 'get_inbox_dir', lambda: str(tmp_path))
    monkeypatch.setattr(email_route, 'get_email_days_back', lambda: 30)
    monkeypatch.setattr(email_route, 'get_email_auto_process', lambda: False)
    monkeypatch.setattr(email_route, 'pull_invoices', lambda **kwargs: {
        'downloaded': 1, 'new_files': [str(tmp_path / 'invoice.pdf')],
        'errors': [], 'total_scanned': 1,
    })

    app = make_app(tmp_path)
    app.dependency_overrides[get_job_service] = lambda: fake_service
    client = TestClient(app)
    response = client.post(
        '/api/v1/email/pull', headers={'X-Local-Token': 'test-token'}
    )

    assert response.status_code == 200
    assert response.json()['job'] is None
    assert fake_service.called is False


def test_static_frontend_is_served_after_api_routes(tmp_path):
    static_dir = tmp_path / 'dist'
    static_dir.mkdir()
    (static_dir / 'index.html').write_text(
        '<html><body>workbench</body></html>', encoding='utf-8'
    )
    client = TestClient(create_app(local_token='test-token', static_dir=static_dir))

    response = client.get('/')

    assert response.status_code == 200
    assert 'workbench' in response.text


def test_email_patch_does_not_persist_none_values(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        settings_route,
        'set_email_config',
        lambda **values: captured.update(values),
    )
    monkeypatch.setattr(settings_route, 'get_email_config', lambda: {
        'enabled': 'false', 'imap_host': 'imap.example.com', 'imap_port': '993',
        'username': '', 'auth_code': '', 'inbox_dir': 'inbox', 'days_back': '30',
        'poll_minutes': '0',
    })
    monkeypatch.setattr(settings_route, 'get_email_enabled', lambda: False)
    monkeypatch.setattr(settings_route, 'get_email_username', lambda: '')
    monkeypatch.setattr(settings_route, 'get_email_auth_code', lambda: '')
    monkeypatch.setattr(settings_route, 'get_email_days_back', lambda: 30)
    monkeypatch.setattr(settings_route, 'get_email_poll_minutes', lambda: 0)
    monkeypatch.setattr(settings_route, 'get_email_auto_process', lambda: False)

    client = TestClient(make_app(tmp_path))
    response = client.patch(
        '/api/v1/settings/email',
        headers={'X-Local-Token': 'test-token'},
        json={'imap_host': 'imap.updated.example.com'},
    )

    assert response.status_code == 200
    assert captured == {'imap_host': 'imap.updated.example.com'}
    assert None not in captured.values()


def test_settings_patch_writes_all_sections_once(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        settings_route,
        'set_all_config',
        lambda **values: captured.update(values),
    )
    monkeypatch.setattr(settings_route, 'reload_business_config', lambda: None)
    monkeypatch.setattr(settings_route, '_settings', lambda: SettingsResponse(
        business={'target_tax_id': 'TAX-ID', 'max_workers': 4},
        email={
            'enabled': True,
            'imap_host': 'imap.example.com',
            'imap_port': 993,
            'username': 'user@example.com',
            'inbox_dir': 'inbox',
            'days_back': 30,
            'poll_minutes': 0,
            'auto_process': False,
            'auth_code_configured': False,
        },
        ai={
            'enabled': False,
            'api_base': 'https://ai.example.com',
            'model': 'model',
            'timeout': 60,
            'api_key_configured': False,
        },
    ))

    client = TestClient(make_app(tmp_path))
    response = client.patch(
        '/api/v1/settings',
        headers={'X-Local-Token': 'test-token'},
        json={
            'business': {'target_tax_id': 'TAX-ID', 'max_workers': 4},
            'email': {'enabled': True},
            'ai': {'enabled': False},
        },
    )

    assert response.status_code == 200
    assert captured == {
        'business': {'target_tax_id': 'TAX-ID', 'max_workers': 4},
        'email': {'enabled': True},
        'ai': {'enabled': False},
    }
