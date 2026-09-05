"""目录处理任务应用服务。"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed

from ..config_manager import get_inbox_dir, get_max_workers
from ..core.processor import InvoiceProcessor
from ..domain.errors import (
    ApplicationError,
    InvalidSourceDirectory,
    JobAlreadyRunning,
    JobNotFound,
    NoPdfFiles,
)
from ..domain.job import Job, JobPhase, JobStatus, JobTrigger
from .audit_service import AuditService
from .email_poller import EmailPoller
from .event_bus import EventBus
from .invoice_file_service import FileProcessResult, InvoiceFileService

logger = logging.getLogger(__name__)


class JobService:
    """持有任务状态并编排处理、审核和自动归档。"""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        processor_factory: Callable[[], object] = InvoiceProcessor,
        max_workers_provider: Callable[[], int] = get_max_workers,
        audit_service_factory: Callable[..., AuditService] = AuditService,
        file_service_factory: Callable[..., InvoiceFileService] = InvoiceFileService,
        job_history_limit: int = 100,
    ):
        self.events = event_bus or EventBus()
        self._processor_factory = processor_factory
        self._job_history_limit = max(1, job_history_limit)
        self._max_workers = max_workers_provider
        self._audit_service_factory = audit_service_factory
        self._file_service_factory = file_service_factory
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._current_job_id: str | None = None
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._progress_callbacks: dict[str, Callable[[float, str], None]] = {}
        self._email_poller = EmailPoller(self.start_job)

    def start_background_tasks(self) -> None:
        """启动桌面模式所需的后台任务。"""
        self._email_poller.start()

    def wake_background_tasks(self) -> None:
        """通知后台任务立即重读外部配置。"""
        self._email_poller.wake()

    def start_job(
        self,
        source_dir: str,
        trigger: JobTrigger | str = JobTrigger.MANUAL,
    ) -> dict:
        job, pdf_files, snapshot = self._prepare_job(source_dir, trigger)

        self._publish_snapshot(job)
        thread = threading.Thread(
            target=self._run_job,
            args=(job.id, tuple(pdf_files)),
            name=f'invoice-job-{job.id[:8]}',
            daemon=True,
        )
        with self._lock:
            self._threads[job.id] = thread
        thread.start()
        return snapshot

    def run_job_sync(
        self,
        source_dir: str,
        trigger: JobTrigger | str = JobTrigger.MANUAL,
        *,
        job_id: str | None = None,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Run one invoice pipeline synchronously for a host runtime task.

        DevBase owns the worker thread. This method only prepares the business
        job and executes the existing pipeline in the caller's thread, so the
        invoice service does not create a second task thread.
        """
        job, pdf_files, _snapshot = self._prepare_job(
            source_dir,
            trigger,
            job_id=job_id,
            cancellation_event=cancellation_event,
        )
        if progress_callback is not None:
            with self._lock:
                self._progress_callbacks[job.id] = progress_callback
        self._publish_snapshot(job)
        try:
            self._run_job(job.id, pdf_files)
        finally:
            with self._lock:
                self._progress_callbacks.pop(job.id, None)
        return self.get_job(job.id)

    def scan_directory(self, source_dir: str) -> dict[str, str | int]:
        normalized = os.path.abspath(os.path.expanduser(source_dir))
        if not os.path.isdir(normalized) or not os.access(normalized, os.R_OK):
            raise InvalidSourceDirectory(source_dir)
        return {
            'source_dir': normalized,
            'pdf_count': len(self._list_pdf_files(normalized)),
        }

    def _prepare_job(
        self,
        source_dir: str,
        trigger: JobTrigger | str,
        *,
        job_id: str | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> tuple[Job, tuple[str, ...], dict]:
        scanned = self.scan_directory(source_dir)
        normalized = scanned['source_dir']
        pdf_files = self._list_pdf_files(normalized)
        if not pdf_files:
            raise NoPdfFiles(normalized)

        job_kwargs = {
            'source_dir': normalized,
            'trigger': JobTrigger(trigger),
        }
        if job_id is not None:
            job_kwargs['id'] = job_id
        job = Job(**job_kwargs)
        job.stats.total = len(pdf_files)
        with self._lock:
            if self._current_job_id:
                current = self._jobs.get(self._current_job_id)
                if current and not current.status.is_terminal:
                    raise JobAlreadyRunning(current.id)
            self._jobs[job.id] = job
            self._current_job_id = job.id
            self._cancel_events[job.id] = (
                cancellation_event
                if cancellation_event is not None
                else threading.Event()
            )
            snapshot = job.to_dict()
        return job, tuple(pdf_files), snapshot

    def cancel_job(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.status.is_terminal:
                return job.to_dict()
            job.request_cancel()
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event:
                cancel_event.set()
            job.message = '正在停止…'
            snapshot = job.to_dict()
        self._publish_status(job)
        self._publish_snapshot(job)
        return snapshot

    def current_job(self) -> dict | None:
        with self._lock:
            if not self._current_job_id:
                return None
            job = self._jobs.get(self._current_job_id)
            return job.to_dict() if job else None

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            return job.to_dict()

    def is_known_output_directory(self, path: str) -> bool:
        normalized = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        with self._lock:
            return any(
                job.output_dir
                and os.path.realpath(job.output_dir) == normalized
                for job in self._jobs.values()
            )

    def is_known_directory(self, path: str) -> bool:
        """判断目录是否为配置的收件目录或任务输出目录。"""
        normalized = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        inbox_dir = os.path.realpath(
            os.path.abspath(os.path.expanduser(get_inbox_dir()))
        )
        if normalized == inbox_dir:
            return True
        return self.is_known_output_directory(normalized)

    def wait_for_job(self, job_id: str, timeout: float | None = None) -> dict:
        with self._lock:
            thread = self._threads.get(job_id)
        if thread:
            thread.join(timeout)
        return self.get_job(job_id)

    def shutdown(self, timeout: float = 5.0) -> None:
        """请求当前任务停止并等待 worker 收敛，供桌面壳退出时调用。"""
        self._email_poller.stop(timeout)
        with self._lock:
            job_id = self._current_job_id
            thread = self._threads.get(job_id) if job_id else None
        if job_id:
            try:
                self.cancel_job(job_id)
            except ApplicationError:
                pass
        if thread:
            thread.join(timeout)

    def _run_job(self, job_id: str, pdf_files: tuple[str, ...]) -> None:
        job = self._get_job_object(job_id)
        with self._lock:
            cancel_event = self._cancel_events.get(job_id)
        if cancel_event is None:
            return
        processor = None
        try:
            if cancel_event.is_set() or self._is_cancel_requested(job):
                self._finish_cancelled(job)
                return
            processor = self._processor_factory()
            with self._lock:
                if job.status == JobStatus.CANCELLED:
                    return
                job.transition(JobStatus.RUNNING)
                job.phase = JobPhase.PROCESS
                job.message = '正在处理 PDF 文件'
            self._publish_status(job)
            self._publish_snapshot(job)

            output_dir = processor.create_output_directory(job.source_dir)
            with self._lock:
                job.output_dir = output_dir
            processor.reset_dedup()
            self._log(job, f'发现 {job.stats.total} 个待处理文件', 'info')
            self._log(job, f'使用 {self._max_workers()} 线程并发处理', 'info')

            file_service = self._file_service_factory(processor)
            success_count, failure_count = self._process_files(
                job, processor, file_service, pdf_files, cancel_event
            )
            if cancel_event.is_set() or self._is_cancel_requested(job):
                self._finish_cancelled(job)
                return

            self._log(
                job,
                f'统计: 总 {job.stats.total} | 成功 {success_count} '
                f'| 失败 {failure_count}',
                'info',
            )
            self._set_phase(job, JobPhase.POST_PROCESS, '执行后处理…')

            def on_post_progress(ratio: float) -> None:
                self._set_progress(job, 0.70 + 0.30 * ratio)

            result = processor.post_process(
                output_dir, progress_callback=on_post_progress
            )
            for issue in result.get('tax_issues') or []:
                self._log(job, issue, 'warning')
            tax_issues = result.get('tax_issues') or []
            with self._lock:
                job.stats.tax_issues = len(tax_issues)
            self._publish_stats(job)
            if cancel_event.is_set() or self._is_cancel_requested(job):
                self._finish_cancelled(job)
                return
            self._log(
                job, f"金额映射: {len(result.get('amount_map') or {})} 条", 'info'
            )
            self._log(job, '待搜索文件替换完成', 'success')
            self._log(
                job,
                'PDF 合并完成' if result.get('merged') else 'PDF 合并失败',
                'success' if result.get('merged') else 'error',
            )
            if result.get('excel'):
                self._log(job, f"费用汇总已生成: {result['excel']}", 'success')
            else:
                self._log(
                    job, '费用汇总生成失败（输出目录中可能无可识别发票）', 'warning'
                )

            self._set_phase(job, JobPhase.LOCAL_AUDIT, '执行审核…')
            if cancel_event.is_set() or self._is_cancel_requested(job):
                self._finish_cancelled(job)
                return
            audit_service = self._audit_service_factory(
                processor,
                log_callback=lambda message, level: self._log(job, message, level),
            )
            audit_result = audit_service.run(output_dir)
            result['audit'] = audit_result
            if cancel_event.is_set() or self._is_cancel_requested(job):
                self._finish_cancelled(job)
                return

            if job.trigger in {JobTrigger.INBOX, JobTrigger.EMAIL}:
                self._set_phase(job, JobPhase.ARCHIVE, '归档已处理文件…')
                if cancel_event.is_set() or self._is_cancel_requested(job):
                    self._finish_cancelled(job)
                    return
                archived = self._archive_files(job.source_dir, pdf_files)
                result['archived'] = archived
                if archived:
                    self._log(job, f'已归档 {archived} 个已处理发票', 'info')
                if cancel_event.is_set() or self._is_cancel_requested(job):
                    self._finish_cancelled(job)
                    return

            self._set_progress(job, 1.0)
            with self._lock:
                job.result = result
                job.phase = JobPhase.DONE
                job.message = f'处理完成 — 成功 {success_count}/{job.stats.total}'
                final_status = (
                    JobStatus.SUCCEEDED
                    if failure_count == 0 and not tax_issues
                    else JobStatus.COMPLETED_WITH_WARNINGS
                )
                job.transition(final_status)
            self._publish_status(job)
            self._publish_snapshot(job)
            self.events.publish('job.completed', result, job.id)
            self._log(job, '所有处理已完成！', 'success')
        except Exception as exc:
            logger.exception('任务处理失败: %s', job.id)
            with self._lock:
                if not job.status.is_terminal:
                    if job.cancel_requested:
                        job.message = '处理已中止，部分文件可能未完成'
                        job.phase = JobPhase.DONE
                        job.transition(JobStatus.CANCELLED)
                    else:
                        job.error_code = 'INTERNAL_ERROR'
                        job.error_message = str(exc)
                        job.message = f'处理出错: {exc}'
                        job.transition(JobStatus.FAILED)
            self._log(job, f'处理出错: {exc}', 'error')
            self._publish_status(job)
            self._publish_snapshot(job)
        finally:
            if processor is not None:
                try:
                    processor.clear_cache()
                except Exception:
                    logger.exception('清理处理器缓存失败')
            with self._lock:
                self._threads.pop(job_id, None)
                self._cancel_events.pop(job_id, None)
                self._trim_job_history_locked()

    def _process_files(
        self,
        job: Job,
        processor,
        file_service: InvoiceFileService,
        pdf_files: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> tuple[int, int]:
        success_count = 0
        failure_count = 0
        completed_count = 0
        executor = ThreadPoolExecutor(max_workers=self._max_workers())
        futures = {
            executor.submit(
                file_service.process_file,
                filename,
                job.source_dir,
                job.output_dir,
                cancel_event.is_set,
            ): filename
            for filename in pdf_files
        }
        try:
            for future in as_completed(futures):
                if cancel_event.is_set():
                    for pending in futures:
                        pending.cancel()
                    break
                if future.cancelled():
                    continue
                try:
                    file_result: FileProcessResult = future.result()
                except CancelledError:
                    continue
                except Exception as exc:
                    filename = futures[future]
                    file_result = FileProcessResult(
                        filename,
                        None,
                        'error',
                        f'处理失败: {filename}，{exc}',
                        'failure',
                    )
                completed_count += 1
                if file_result.outcome == 'success':
                    success_count += 1
                elif file_result.outcome == 'failure':
                    failure_count += 1
                self._log(job, file_result.message, file_result.level)
                with self._lock:
                    job.stats.success = success_count
                    job.stats.failure = failure_count
                self._publish_stats(job)
                self._set_progress(job, 0.70 * completed_count / len(pdf_files))
        finally:
            executor.shutdown(wait=True, cancel_futures=cancel_event.is_set())
        return success_count, failure_count

    def _archive_files(self, source_dir: str, filenames: tuple[str, ...]) -> int:
        archived_dir = os.path.join(source_dir, '已处理')
        os.makedirs(archived_dir, exist_ok=True)
        moved = 0
        for filename in filenames:
            source = os.path.join(source_dir, filename)
            if not os.path.isfile(source):
                continue
            target = os.path.join(archived_dir, filename)
            counter = 1
            while os.path.exists(target):
                name, ext = os.path.splitext(filename)
                target = os.path.join(archived_dir, f'{name}_{counter}{ext}')
                counter += 1
            shutil.move(source, target)
            moved += 1
        return moved

    def _get_job_object(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            return job

    @staticmethod
    def _list_pdf_files(source_dir: str) -> list[str]:
        return sorted(
            filename for filename in os.listdir(source_dir)
            if filename.lower().endswith('.pdf')
            and os.path.isfile(os.path.join(source_dir, filename))
        )

    def _is_cancel_requested(self, job: Job) -> bool:
        with self._lock:
            return job.cancel_requested

    def _finish_cancelled(self, job: Job) -> None:
        with self._lock:
            if not job.status.is_terminal:
                job.message = '处理已中止，部分文件可能未完成'
                job.phase = JobPhase.DONE
                job.transition(JobStatus.CANCELLED)
        self._log(job, '处理已中止，部分文件可能未完成', 'warning')
        self._publish_status(job)
        self._publish_snapshot(job)

    def _set_phase(self, job: Job, phase: JobPhase, message: str) -> None:
        with self._lock:
            if job.status.is_terminal:
                return
            job.phase = phase
            job.message = message
        self._publish_status(job)
        self._publish_snapshot(job)

    def _set_progress(self, job: Job, ratio: float) -> None:
        with self._lock:
            job.set_progress(ratio)
            progress = job.progress
            phase = job.phase.value
            message = job.message
            callback = self._progress_callbacks.get(job.id)
        self.events.publish(
            'job.progress', {'progress': progress, 'phase': phase}, job.id
        )
        if callback is not None:
            try:
                callback(progress, message)
            except Exception:
                logger.exception('外部进度回调失败: %s', job.id)

    def _publish_stats(self, job: Job) -> None:
        with self._lock:
            payload = job.stats.to_dict()
        self.events.publish('job.stats_changed', payload, job.id)

    def _publish_status(self, job: Job) -> None:
        with self._lock:
            payload = {
                'status': job.status.value,
                'phase': job.phase.value,
                'message': job.message,
            }
        self.events.publish('job.status_changed', payload, job.id)

    def _publish_snapshot(self, job: Job) -> None:
        with self._lock:
            payload = job.to_dict()
        self.events.publish('job.snapshot', payload, job.id)

    def _log(self, job: Job, message: str, level: str) -> None:
        log_level = {
            'info': logging.INFO,
            'success': logging.INFO,
            'warning': logging.WARNING,
            'error': logging.ERROR,
        }.get(level, logging.INFO)
        logger.log(log_level, '[%s] %s', job.id, message)
        self.events.publish(
            'job.log_appended', {'message': message, 'level': level}, job.id
        )

    def _trim_job_history_locked(self) -> None:
        terminal_jobs = [
            job for job in self._jobs.values()
            if job.status.is_terminal and job.id != self._current_job_id
        ]
        excess = len(terminal_jobs) - self._job_history_limit
        if excess <= 0:
            return
        terminal_jobs.sort(
            key=lambda job: job.finished_at or job.started_at,
        )
        for job in terminal_jobs[:excess]:
            self._jobs.pop(job.id, None)
