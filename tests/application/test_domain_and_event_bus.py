"""领域模型和事件总线的第一批回归测试。"""

import threading

import pytest

from src.application.event_bus import EventBus
from src.domain.errors import EventStreamClosed, InvalidJobTransition
from src.domain.job import Job, JobStatus, JobTrigger


def test_job_cancel_is_cooperative_and_terminal_transition_is_rejected():
    job = Job(source_dir='D:/invoices', trigger=JobTrigger.MANUAL)
    job.transition(JobStatus.RUNNING)
    assert job.request_cancel() is True
    assert job.status is JobStatus.CANCELLING
    assert job.request_cancel() is False

    job.transition(JobStatus.CANCELLED)
    assert job.finished_at is not None
    with pytest.raises(InvalidJobTransition):
        job.transition(JobStatus.RUNNING)


def test_job_progress_is_bounded_and_monotonic():
    job = Job(source_dir='D:/invoices')
    job.set_progress(0.7)
    job.set_progress(0.2)
    assert job.progress == 0.7
    job.set_progress(2)
    assert job.progress == 1.0


def test_event_bus_delivers_events_and_assigns_sequence_ids():
    bus = EventBus()
    subscription = bus.subscribe(maxsize=4)
    first = bus.publish('job.status_changed', {'status': 'running'}, 'job-1')
    second = bus.publish('job.progress', {'progress': 0.5}, 'job-1')

    assert subscription.get(timeout=0.1) == first
    assert subscription.get(timeout=0.1) == second
    assert [event.event_id for event in bus.history()] == [1, 2]
    subscription.close()
    with pytest.raises(EventStreamClosed):
        subscription.get(timeout=0.1)


def test_event_bus_drops_progress_before_critical_events():
    bus = EventBus()
    subscription = bus.subscribe(maxsize=2)
    bus.publish('job.progress', {'progress': 0.1}, 'job-1')
    bus.publish('job.progress', {'progress': 0.2}, 'job-1')
    bus.publish('job.completed', {'status': 'succeeded'}, 'job-1')

    events = [subscription.get(timeout=0.1), subscription.get(timeout=0.1)]
    assert any(event.type == 'job.completed' for event in events)


def test_event_bus_does_not_block_when_critical_queue_is_full():
    bus = EventBus()
    subscription = bus.subscribe(maxsize=1)
    bus.publish('job.status_changed', {'status': 'running'}, 'job-1')
    finished = threading.Event()

    def publish_second_event():
        bus.publish('job.completed', {'status': 'succeeded'}, 'job-1')
        finished.set()

    thread = threading.Thread(target=publish_second_event)
    thread.start()
    assert finished.wait(timeout=0.2)
    thread.join(timeout=1)
    assert subscription.get(timeout=0.1).type == 'job.status_changed'
    with pytest.raises(EventStreamClosed):
        subscription.get(timeout=0.1)
