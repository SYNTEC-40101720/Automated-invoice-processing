"""邮箱自动轮询测试。"""

from __future__ import annotations

from invoice_processor.application.email_poller import EmailPoller

POLLER_MODULE = 'invoice_processor.application.email_poller'


def _patch_email_config(
    monkeypatch,
    *,
    enabled: bool = True,
    inbox_dir: str | None = None,
    senders: list | None = None,
    keywords: list | None = None,
) -> None:
    """集中打桩邮箱轮询配置，避免每个用例重复长 monkeypatch 行。"""
    monkeypatch.setattr(f'{POLLER_MODULE}.get_email_enabled', lambda: enabled)
    monkeypatch.setattr(f'{POLLER_MODULE}.get_email_poll_minutes', lambda: 5)
    if inbox_dir is not None:
        monkeypatch.setattr(f'{POLLER_MODULE}.get_inbox_dir', lambda: inbox_dir)
    monkeypatch.setattr(
        f'{POLLER_MODULE}.get_email_config',
        lambda: {'imap_host': 'imap.example.com', 'imap_port': '993'},
    )
    monkeypatch.setattr(f'{POLLER_MODULE}.get_email_username', lambda: 'user')
    monkeypatch.setattr(f'{POLLER_MODULE}.get_email_auth_code', lambda: 'auth')
    monkeypatch.setattr(f'{POLLER_MODULE}.get_email_days_back', lambda: 30)
    monkeypatch.setattr(f'{POLLER_MODULE}.get_email_senders', lambda: senders or [])
    monkeypatch.setattr(
        f'{POLLER_MODULE}.get_email_keywords', lambda: keywords or []
    )


def test_disabled_email_poller_does_not_connect(monkeypatch):
    calls = []
    _patch_email_config(monkeypatch, enabled=False)

    poller = EmailPoller(
        lambda *_: calls.append('job'), lambda **_: calls.append('pull')
    )
    result = poller.poll_once()

    assert result['new_files'] == []
    assert calls == []


def test_email_poller_only_pulls_new_files(monkeypatch, tmp_path):
    calls = []
    _patch_email_config(
        monkeypatch,
        inbox_dir=str(tmp_path),
        senders=['[EMAIL]'],
        keywords=['差旅'],
    )

    def fake_pull(**kwargs):
        calls.append(('pull', kwargs))
        return {
            'downloaded': 1,
            'new_files': [str(tmp_path / 'invoice.pdf')],
            'errors': [],
            'total_scanned': 1,
        }

    poller = EmailPoller(lambda *_: calls.append('job'), fake_pull)
    result = poller.poll_once()

    assert result['downloaded'] == 1
    assert calls[0][0] == 'pull'
    assert calls[0][1]['senders'] == ['[EMAIL]']
    assert calls[0][1]['keywords'] == ['差旅']
    assert calls == [('pull', calls[0][1])]


def test_email_poller_pulls_new_files_without_processing(monkeypatch, tmp_path):
    calls = []
    _patch_email_config(monkeypatch, inbox_dir=str(tmp_path))

    def fake_pull(**_):
        calls.append('pull')
        return {
            'downloaded': 1,
            'new_files': [str(tmp_path / 'invoice.pdf')],
            'errors': [],
            'total_scanned': 1,
        }

    poller = EmailPoller(lambda *_: calls.append('job'), fake_pull)
    result = poller.poll_once()

    assert result['new_files']
    assert calls == ['pull']


def test_email_poller_stop_wakes_disabled_wait(monkeypatch):
    _patch_email_config(monkeypatch, enabled=False)

    poller = EmailPoller(lambda *_: None)
    poller.start()
    poller.stop(timeout=1.0)

    assert poller._thread is not None
    assert not poller._thread.is_alive()


def test_email_poller_does_not_start_job_after_stop(monkeypatch, tmp_path):
    calls = []
    _patch_email_config(monkeypatch, inbox_dir=str(tmp_path))

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
