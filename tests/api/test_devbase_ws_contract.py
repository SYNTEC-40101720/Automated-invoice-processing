"""DevBase 模板宿主层契约：共享总线属性与模板 WS 事件流。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from devbase.api.app import create_app
from devbase.application.job_runtime import JobRuntime


def make_devbase_app() -> tuple[TestClient, JobRuntime]:
    runtime = JobRuntime(total_steps=1, step_delay=0.01)
    app = create_app(runtime=runtime, local_token='test-token')
    return TestClient(app), runtime


def test_runtime_exposes_shared_event_bus():
    # 模板 WS 路由通过 runtime.event_bus 订阅共享总线（模板宿主与
    # 业务服务共号）。属性缺失会让 WS 连接直接 AttributeError。
    runtime = JobRuntime()
    assert runtime.event_bus is not None
    event = runtime.event_bus.publish('job.progress', {'progress': 0.5}, 'job-1')
    assert runtime.event_bus.history()[0].event_id == event.event_id


def test_devbase_ws_sends_health_snapshot_and_progress_events():
    client, runtime = make_devbase_app()

    with client.websocket_connect('/api/v1/events?token=test-token') as websocket:
        health = websocket.receive_json()
        assert health['type'] == 'health'
        assert health['data']['active_job_id'] is None

        snapshot = websocket.receive_json()
        assert snapshot['type'] == 'snapshot'
        assert snapshot['data']['job'] is None

        published = runtime.event_bus.publish(
            'job.progress', {'progress': 0.25}, 'job-1'
        )
        event = websocket.receive_json()
        assert event['type'] == 'event'
        assert event['data']['event_id'] == published.event_id
        assert event['data']['type'] == 'job.progress'
        assert event['data']['payload']['progress'] == 0.25


def test_devbase_ws_replays_history_after_cursor():
    client, runtime = make_devbase_app()

    first = runtime.event_bus.publish('job.status_changed', {}, 'job-1')
    second = runtime.event_bus.publish('job.progress', {'progress': 0.5}, 'job-1')

    with client.websocket_connect(
        f'/api/v1/events?token=test-token&after={first.event_id}'
    ) as websocket:
        assert websocket.receive_json()['type'] == 'health'
        assert websocket.receive_json()['type'] == 'snapshot'
        replayed = websocket.receive_json()
        assert replayed['type'] == 'event'
        assert replayed['data']['event_id'] == second.event_id
        assert replayed['data']['event_id'] == 2
        # first（event_id=1）在游标之前，不重放。
        assert first.event_id == 1
