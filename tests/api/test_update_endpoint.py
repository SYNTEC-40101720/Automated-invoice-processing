"""更新检查 API 测试。"""

from fastapi.testclient import TestClient
from invoice_processor.api.app import create_app
from invoice_processor.api.routes import system as system_route
from invoice_processor.application.update_checker import UpdateResult


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
    }


def test_update_endpoint_requires_local_token():
    client = TestClient(create_app(local_token='test-token'))

    response = client.get('/api/v1/system/update')

    assert response.status_code == 401
