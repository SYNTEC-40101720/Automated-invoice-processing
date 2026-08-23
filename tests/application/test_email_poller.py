"""邮箱自动轮询测试。"""

from __future__ import annotations

from src.application.email_poller import EmailPoller
from src.domain.job import JobTrigger


def test_disabled_email_poller_does_not_connect(monkeypatch):
    calls = []
    monkeypatch.setattr('src.application.email_poller.get_email_enabled', lambda: False)
    monkeypatch.setattr(
        'src.application.email_poller.get_email_poll_minutes', lambda: 5
    )

    poller = EmailPoller(
        lambda *_: calls.append('job'), lambda **_: calls.append('pull')
    )
    result = poller.poll_once()

    assert result['new_files'] == []
    assert calls == []


def test_email_poller_starts_email_job_for_new_files(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr('src.application.email_poller.get_email_enabled', lambda: True)
    monkeypatch.setattr(
        'src.application.email_poller.get_email_poll_minutes', lambda: 5
    )
    monkeypatch.setattr(
        'src.application.email_poller.get_inbox_dir', lambda: str(tmp_path)
    )
    monkeypatch.setattr('src.application.email_poller.get_email_config', lambda: {
        'imap_host': 'imap.example.com',
        'imap_port': '993',
    })
    monkeypatch.setattr(
        'src.application.email_poller.get_email_username',
        lambda: 'user@example.com',
    )
    monkeypatch.setattr(
        'src.application.email_poller.get_email_auth_code', lambda: 'auth'
    )
    monkeypatch.setattr('src.application.email_poller.get_email_days_back', lambda: 30)

    def fake_pull(**kwargs):
        calls.append(('pull', kwargs))
        return {
            'downloaded': 1,
            'new_files': [str(tmp_path / 'invoice.pdf')],
            'errors': [],
            'total_scanned': 1,
        }

    def fake_start_job(source_dir, trigger):
        calls.append(('job', source_dir, trigger))
        return {'id': 'job-email'}

    poller = EmailPoller(fake_start_job, fake_pull)
    result = poller.poll_once()

    assert result['downloaded'] == 1
    assert calls[0][0] == 'pull'
    assert calls[1] == ('job', str(tmp_path), JobTrigger.EMAIL)


def test_email_poller_stop_wakes_disabled_wait(monkeypatch):
    monkeypatch.setattr('src.application.email_poller.get_email_enabled', lambda: False)
    monkeypatch.setattr(
        'src.application.email_poller.get_email_poll_minutes', lambda: 5
    )

    poller = EmailPoller(lambda *_: None)
    poller.start()
    poller.stop(timeout=1.0)

    assert poller._thread is not None
    assert not poller._thread.is_alive()


def test_email_poller_does_not_start_job_after_stop(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr('src.application.email_poller.get_email_enabled', lambda: True)
    monkeypatch.setattr(
        'src.application.email_poller.get_email_poll_minutes', lambda: 5
    )
    monkeypatch.setattr(
        'src.application.email_poller.get_inbox_dir', lambda: str(tmp_path)
    )
    monkeypatch.setattr('src.application.email_poller.get_email_config', lambda: {
        'imap_host': 'imap.example.com', 'imap_port': '993',
    })
    monkeypatch.setattr(
        'src.application.email_poller.get_email_username', lambda: 'user'
    )
    monkeypatch.setattr(
        'src.application.email_poller.get_email_auth_code', lambda: 'auth'
    )
    monkeypatch.setattr('src.application.email_poller.get_email_days_back', lambda: 30)

    poller = EmailPoller(
        lambda *_: calls.append('job'),
        lambda **_: {
            'downloaded': 1,
            'new_files': ['invoice.pdf'],
            'errors': [],
            'total_scanned': 1,
        },
    )
    poller._stop_event.set()

    result = poller.poll_once()

    assert result['new_files'] == []
    assert calls == []
