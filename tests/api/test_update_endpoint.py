"""更新检查 API 测试。"""

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.routes import system as system_route
from src.application.update_checker import UpdateApplyResult, UpdateResult


def test_update_endpoint_returns_release_information(monkeypatch):
    monkeypatch.setattr(
        system_route,
        'check_for_update',
        lambda _current_version: UpdateResult(
            current_version='7.0.4',
            checked=True,
            available=True,
            latest_version='7.0.5',
            release_url='https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.0.5',
            asset_name='SYNTEC-电子票据处理系统-v7.0.5.zip',
        ),
    )
    client = TestClient(create_app(local_token='test-token'))

    response = client.get(
        '/api/v1/system/update',
        headers={'X-Local-Token': 'test-token'},
    )

    assert response.status_code == 200
    assert response.json() == {
        'current_version': '7.0.4',
        'checked': True,
        'available': True,
        'latest_version': '7.0.5',
        'release_url': 'https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.0.5',
        'installable': False,
        'asset_name': 'SYNTEC-电子票据处理系统-v7.0.5.zip',
    }


def test_update_endpoint_requires_local_token():
    client = TestClient(create_app(local_token='test-token'))

    response = client.get('/api/v1/system/update')

    assert response.status_code == 401


def test_update_apply_endpoint_uses_desktop_handler():
    client = TestClient(create_app(
        local_token='test-token',
        update_apply=lambda _version: UpdateApplyResult(
            status='started',
            message='更新已准备，程序即将重启',
            latest_version='7.0.5',
        ),
    ))

    response = client.post(
        '/api/v1/system/update/apply',
        headers={'X-Local-Token': 'test-token'},
    )

    assert response.status_code == 200
    assert response.json() == {
        'status': 'started',
        'message': '更新已准备，程序即将重启',
        'latest_version': '7.0.5',
    }
