"""目录处理任务应用服务。"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import (
    CancelledError,
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from devbase.application.event_bus import EventBus

from ..config_manager import get_inbox_dir, get_max_workers
from ..core.duplicate_check import DuplicateIndex, compute_sha256
from ..core.exclusions import is_excluded_filename
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
from .invoice_file_service import FileProcessResult, InvoiceFileService
from .job_history import JobHistoryStore
from .private_car_service import PrivateCarService

logger = logging.getLogger(__name__)


def is_timestamp_output_dir(name: str) -> bool:
    """识别历史输出目录（YYYYMMDD_HHMMSS_%f，处理器输出目录命名）。"""
    if len(name) < 16:
        return False
    head = name[:16]
    return (
        head[:8].isdigit()
        and head[8] == '_'
        and head[9:15].isdigit()
        and head[15] == '_'
        and name[16:].isdigit()
    )


def is_inbox_root(normalized: str) -> bool:
    """判断目录是否为配置的收件根目录（realpath 归一后比较）。"""
    inbox_dir = os.path.realpath(
        os.path.abspath(os.path.expanduser(get_inbox_dir()))
    )
    return os.path.realpath(normalized) == inbox_dir


def list_inbox_tree(inbox_dir: str) -> list[str]:
    """收件根目录全部待处理 PDF，以 source_dir 相对路径表示。

    根目录散放文件直接用文件名，批次子目录文件带一层目录前缀；
    「已处理」与历史输出目录（时间戳目录）不参与收集。
    """
    collected = list(JobService._list_pdf_files(inbox_dir))
    try:
        entries = sorted(os.listdir(inbox_dir))
    except OSError:
        entries = []
    for entry in entries:
        batch_dir = os.path.join(inbox_dir, entry)
        if not os.path.isdir(batch_dir):
            continue
        if entry == '已处理' or is_timestamp_output_dir(entry):
            continue
        collected.extend(
            os.path.join(entry, filename)
            for filename in JobService._list_pdf_files(batch_dir)
        )
    return collected


@dataclass
class _JobHandle:
    """单个任务的运行时资源，与 Job 一一对应，生命周期一致。

    融合二期后不再持有 worker 线程引用：任务由宿主（DevBase runtime）
    在自己的线程里经 ``run_job_sync`` 驱动，本服务只管状态与事件。
    """

    job: Job
    cancel_event: threading.Event
    progress_callback: Callable[[float, str], None] | None = None


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
        job_history_store: JobHistoryStore | None = None,
        duplicate_index: DuplicateIndex | None = None,
        private_car_service: PrivateCarService | None = None,
    ):
        self.events = event_bus or EventBus()
        self._processor_factory = processor_factory
        self._job_history_limit = max(1, job_history_limit)
        self._max_workers = max_workers_provider
        self._audit_service_factory = audit_service_factory
        self._file_service_factory = file_service_factory
        # 跨启动处理历史（终态旁路落盘）；None 时历史功能停用
        self._job_history_store = job_history_store
        # 全局内容去重索引（跨任务 sha256）；None 时去重功能停用
        self._duplicate_index = duplicate_index
        # 私车公用服务（三条联动数据源）；None 时费用汇总不带私车数据
        self._private_car_service = private_car_service
        self._lock = threading.RLock()
        self._handles: dict[str, _JobHandle] = {}
        self._current_job_id: str | None = None

    def _private_car_daily_totals(self) -> dict[str, tuple[float, float]]:
        """私车公用按日合计 {日期: (补贴, 过路费)}；无数据/服务缺失返回 {}。"""
        if self._private_car_service is None:
            return {}
        try:
            return self._private_car_service.collect_daily_totals()
        except Exception as exc:  # 私车数据读失败不阻断发票任务
            logger.warning('私车公用数据读取失败（汇总不含私车联动）: %s', exc)
            return {}

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
        invoice service does not create a second task thread. It is the only
        production entry point since the legacy self-thread ``start_job``
        path was removed in the phase-2 bus fusion.
        """
        job, pdf_files, _snapshot = self._prepare_job(
            source_dir,
            trigger,
            job_id=job_id,
            cancellation_event=cancellation_event,
        )
        if progress_callback is not None:
            with self._lock:
                self._handles[job.id].progress_callback = progress_callback
        self._publish_snapshot(job)
        try:
            self._run_job(job.id, pdf_files)
        finally:
            with self._lock:
                self._handles[job.id].progress_callback = None
        return self.get_job(job.id)

    def scan_directory(self, source_dir: str) -> dict[str, str | int]:
        normalized = os.path.abspath(os.path.expanduser(source_dir))
        if not os.path.isdir(normalized) or not os.access(normalized, os.R_OK):
            raise InvalidSourceDirectory(source_dir)
        return {
            'source_dir': normalized,
            'pdf_count': len(self._list_pdf_files(normalized)),
        }

    def scan_inbox(self) -> dict[str, Any]:
        """扫描统一收件目录：待处理清单（根+批次）+ 各批次子目录概览。

        收件目录不存在时不报错（视为空收件箱），由前端引导先设定目录；
        批次子目录统计与根目录共用同一收集语义，计数跨根与批次求和。
        """
        inbox_raw = get_inbox_dir()
        inbox = os.path.realpath(os.path.abspath(os.path.expanduser(inbox_raw)))
        if not os.path.isdir(inbox) or not os.access(inbox, os.R_OK):
            return {
                'inbox_dir': inbox,
                'pending_count': 0,
                'pending_files': [],
                'batches': [],
            }
        pending_files = list_inbox_tree(inbox)
        batches: list[dict[str, Any]] = []
        try:
            entries = sorted(os.listdir(inbox))
        except OSError:
            entries = []
        for entry in entries:
            batch_dir = os.path.join(inbox, entry)
            if not os.path.isdir(batch_dir):
                continue
            if entry == '已处理' or is_timestamp_output_dir(entry):
                continue
            batches.append(
                {
                    'name': entry,
                    'path': batch_dir,
                    'pdf_count': len(self._list_pdf_files(batch_dir)),
                }
            )
        return {
            'inbox_dir': inbox,
            'pending_count': len(pending_files),
            'pending_files': pending_files,
            'batches': batches,
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
        pdf_files = self._collect_job_entries(trigger, normalized)
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
                current = self._handles[self._current_job_id].job
                if current and not current.status.is_terminal:
                    raise JobAlreadyRunning(current.id)
            handle = _JobHandle(
                job=job,
                cancel_event=(
                    cancellation_event
                    if cancellation_event is not None
                    else threading.Event()
                ),
            )
            self._handles[job.id] = handle
            self._current_job_id = job.id
            snapshot = job.to_dict()
        return job, pdf_files, snapshot

    def _collect_job_entries(
        self, trigger: JobTrigger | str, normalized: str
    ) -> tuple[str, ...]:
        """确定任务处理清单：根目录整体收件语义 or 单目录。

        - trigger=inbox 且源目录就是收件根目录 → 收集全部（根+批次子目录）
        - 其余（手动/批次单目录启动）→ 只取该目录一层的 PDF
        返回值以 source_dir 相对路径表示：根目录文件直接用文件名，
        批次文件带一层子目录前缀（处理/归档按 join 还原完整路径）。
        """
        if JobTrigger(trigger) is JobTrigger.INBOX and is_inbox_root(
            normalized
        ):
            return tuple(list_inbox_tree(normalized))
        return tuple(self._list_pdf_files(normalized))

    def cancel_job(self, job_id: str) -> dict:
        with self._lock:
            handle = self._handles.get(job_id)
            if handle is None:
                raise JobNotFound(job_id)
            job = handle.job
            if job.status.is_terminal:
                return job.to_dict()
            job.request_cancel()
            handle.cancel_event.set()
            job.message = '正在停止…'
            snapshot = job.to_dict()
        self._publish_status(job)
        self._publish_snapshot(job)
        return snapshot

    def current_job(self) -> dict | None:
        with self._lock:
            if not self._current_job_id:
                return None
            handle = self._handles.get(self._current_job_id)
            return handle.job.to_dict() if handle else None

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            handle = self._handles.get(job_id)
            if handle is None:
                raise JobNotFound(job_id)
            return handle.job.to_dict()

    def job_history_entries(self) -> list[dict]:
        """跨启动终态历史（旧→新）；历史功能停用（store 为 None）时为空。"""
        if self._job_history_store is None:
            return []
        return self._job_history_store.list()

    def is_known_output_directory(self, path: str) -> bool:
        normalized = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        with self._lock:
            return any(
                handle.job.output_dir
                and os.path.realpath(handle.job.output_dir) == normalized
                for handle in self._handles.values()
            )

    def is_known_directory(self, path: str) -> bool:
        """判断目录是否为配置的收件目录（含拉取批次子目录）、任务输出目录或历史输出目录。"""
        normalized = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        inbox_dir = os.path.realpath(
            os.path.abspath(os.path.expanduser(get_inbox_dir()))
        )
        if normalized == inbox_dir or os.path.dirname(normalized) == inbox_dir:
            # 收件根目录本身，或其下的拉取批次子目录（拉取_时间戳）。
            # 后者不逐一校验目录名：根目录已知可信，一层子目录均为
            # 用户可见的拉取批次或手动整理结果，放开即可。
            return True
        if self.is_known_output_directory(normalized):
            return True
        # 重启后内存 handles 已空：跨启动历史中的输出目录同样放行，
        # 供「打开输出目录」按历史回溯（目录是否仍存在由调用方判定）。
        if self._job_history_store is None:
            return False
        return any(
            entry.get('output_dir')
            and os.path.realpath(str(entry['output_dir'])) == normalized
            for entry in self._job_history_store.list()
        )

    def shutdown(self, timeout: float = 5.0) -> None:
        """请求当前任务停止，供桌面壳退出时调用。

        融合二期后本服务不再持有 worker 线程：任务由宿主 runtime 的
        daemon 线程驱动，此处只协作式请求取消，进程退出即收敛。
        """
        with self._lock:
            job_id = self._current_job_id
        if job_id:
            try:
                self.cancel_job(job_id)
            except ApplicationError:
                pass

    def _run_job(self, job_id: str, pdf_files: tuple[str, ...]) -> None:
        job = self._get_job_object(job_id)
        with self._lock:
            cancel_event = self._handles[job_id].cancel_event
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
            success_count, failure_count, duplicate_rel_paths = (
                self._process_files(
                    job, processor, file_service, pdf_files, cancel_event
                )
            )
            if cancel_event.is_set() or self._is_cancel_requested(job):
                self._finish_cancelled(job)
                return

            self._log(
                job,
                f'统计: 总 {job.stats.total} | 成功 {success_count} '
                f'| 失败 {failure_count}'
                + (
                    f' | 跳过重复 {job.stats.duplicates}'
                    if job.stats.duplicates
                    else ''
                ),
                'info',
            )
            self._set_phase(job, JobPhase.POST_PROCESS, '执行后处理…')

            def on_post_progress(ratio: float) -> None:
                self._set_progress(job, 0.70 + 0.30 * ratio)

            result = processor.post_process(
                output_dir,
                progress_callback=on_post_progress,
                daily_manual_totals=self._private_car_daily_totals(),
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
                # 重复文件留在原地：不进处理流程，也不参与归档
                archive_targets = tuple(
                    rel for rel in pdf_files
                    if rel not in duplicate_rel_paths
                )
                archived = self._archive_files(job, archive_targets)
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
                duplicates_suffix = (
                    f'，跳过重复 {job.stats.duplicates}'
                    if job.stats.duplicates
                    else ''
                )
                job.message = (
                    f'处理完成 — 成功 {success_count}/{job.stats.total}'
                    f'{duplicates_suffix}'
                )
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
            # 成功终态统一追加归档台账（任何触发方式）；取消/失败不记
            self._append_ledger_entry(job, result)
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
            # 终态旁路落盘处理历史与去重索引（锁序约束：不得在持
            # service 锁时做磁盘 IO；两者 IO 失败均内部降级不 fail 任务）。
            if self._job_history_store is not None and job.status.is_terminal:
                self._job_history_store.append(job.to_dict())
            if self._duplicate_index is not None and job.status.is_terminal:
                self._duplicate_index.save()
            with self._lock:
                # 保留 handle 供任务历史查询，仅释放运行时资源引用；
                # 历史上限由 _trim_job_history_locked 统一裁剪。
                handle = self._handles.get(job_id)
                if handle is not None:
                    handle.progress_callback = None
                self._trim_job_history_locked()

    def _process_files(
        self,
        job: Job,
        processor,
        file_service: InvoiceFileService,
        pdf_files: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> tuple[int, int, list[str]]:
        """处理 PDF 批次；返回 (成功数, 失败数, 归集到需人工处理的相对路径)。

        去重判定在提交前由主线程串行完成（锁序：sha256/contains/add 均
        在 service 锁外做磁盘 IO），命中全局索引的文件跳过处理并留在
        原地（不进处理流程、不参与归档）。
        """
        success_count = 0
        failure_count = 0
        completed_count = 0
        duplicates_count = 0
        duplicate_rel_paths: list[str] = []
        manual_review_rel_paths: list[str] = []
        index = self._duplicate_index
        pending: dict[Future, str] = {}
        executor = ThreadPoolExecutor(max_workers=self._max_workers())
        for filename in pdf_files:
            content_hash: str | None = None
            if index is not None:
                file_path = os.path.join(job.source_dir, filename)
                try:
                    # 锁外磁盘 IO：不在持 service 锁时计算/查询索引
                    content_hash = compute_sha256(file_path)
                except OSError as exc:
                    self._log(
                        job, f'重复检测跳过（读取失败）: {filename}，{exc}',
                        'warning',
                    )
                else:
                    if index.contains(content_hash):
                        duplicates_count += 1
                        duplicate_rel_paths.append(filename)
                        self._log(job, f'重复文件，已跳过: {filename}', 'warning')
                        continue
                    # 处理前先入索引（含处理失败场景：失败文件同样不该在
                    # 后续任务里被当作新内容重放处理）
                    index.add(content_hash, {'first_seen': filename})
            pending[executor.submit(
                file_service.process_file,
                filename,
                job.source_dir,
                job.output_dir,
                cancel_event.is_set,
            )] = filename
        try:
            for future in as_completed(pending):
                if cancel_event.is_set():
                    for pending_future in pending:
                        pending_future.cancel()
                    break
                if future.cancelled():
                    continue
                try:
                    file_result: FileProcessResult = future.result()
                except CancelledError:
                    continue
                except Exception as exc:
                    filename = pending[future]
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
                    if '已归集到需人工处理' in file_result.message:
                        manual_review_rel_paths.append(
                            {'rel': file_result.filename,
                             'msg': file_result.message}
                        )
                self._log(job, file_result.message, file_result.level)
                with self._lock:
                    job.stats.success = success_count
                    job.stats.failure = failure_count
                self._publish_stats(job)
                self._set_progress(job, 0.70 * completed_count / len(pdf_files))
        finally:
            executor.shutdown(wait=True, cancel_futures=cancel_event.is_set())
        with self._lock:
            job.stats.duplicates = duplicates_count
        self._publish_stats(job)
        self._publish_snapshot(job)
        # 归集清单落 job（终态快照可见）；返回待收集中间态
        review_items = self._build_review_items(
            manual_review_rel_paths, job.output_dir
        )
        with self._lock:
            job.manual_review_files = review_items
        self._publish_snapshot(job)
        return success_count, failure_count, duplicate_rel_paths

    @staticmethod
    def _build_review_items(
        collected: list[dict[str, str]], output_dir: str | None
    ) -> list[dict[str, str]]:
        """把处理结果归集清单映射为需人工处理列表（path = 实际落点）。

        归集时文件被复制到 output_dir/需人工处理/ 下（计数器改名后可能
        与原名不同），所以 path 取目录里实际存在的文件名；reason 取
        处理日志的失败原因前缀（如「PDF 已加密」「字段提取失败」）。
        """
        if not collected or not output_dir:
            return []
        manual_dir = os.path.join(output_dir, '需人工处理')
        try:
            present = set(os.listdir(manual_dir))
        except OSError:
            return []
        items: list[dict[str, str]] = []
        for entry in collected:
            rel = entry['rel']
            message = entry['msg']
            base = os.path.basename(rel)
            stem, ext = os.path.splitext(base)
            matched = ''
            if base in present:
                matched = base
            else:
                counter = 1
                while True:
                    candidate = f'{stem}_{counter}{ext}'
                    if candidate in present:
                        matched = candidate
                        break
                    counter += 1
                    if counter > 99:
                        break
            if not matched:
                continue
            reason = message.split('，', 1)[0] if '，' in message else message
            items.append({'path': matched, 'reason': reason})
        return items

    def _append_ledger_entry(self, job: Job, result: dict) -> None:
        """归档台账：任务成功终态时向输出目录上级追加一行汇总档案。

        台账文件「发票打印汇总档案.xlsx」位于输出目录同级（每个输出
        容器一份）。写入失败仅记 warning，不影响任务终态。
        """
        try:
            from openpyxl import Workbook, load_workbook

            totals = result.get('totals') or {}
            ledger_path = os.path.join(
                os.path.dirname(job.output_dir or '') or '.',
                '发票打印汇总档案.xlsx',
            )
            headers = [
                '任务编号', '完成时间', '输出目录', '发票总数', '成功',
                '失败', '跳过重复', '交通费', '私车补贴', '住宿费',
                '住宿费税金', '税号异常', '人工审核报告',
            ]
            if os.path.isfile(ledger_path):
                wb = load_workbook(ledger_path)
                ws = wb.active
            else:
                wb = Workbook()
                ws = wb.active
                ws.title = '归档台账'
                ws.append(headers)
            row = [
                job.id,
                # 本地时间（财务对账口径；UTC 会比本地早 8 小时）
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                job.output_dir or '',
                job.stats.total,
                job.stats.success,
                job.stats.failure,
                job.stats.duplicates,
                float(totals.get('transport') or 0),
                float(totals.get('subsidy') or 0),
                float(totals.get('hotel') or 0),
                float(totals.get('hotel_tax') or 0),
                job.stats.tax_issues,
                (result.get('audit') or {}).get('report') or '',
            ]
            ws.append(row)
            wb.save(ledger_path)
            self._log(
                job, f'归档台账已更新: {ledger_path}', 'info'
            )
        except Exception as exc:
            logger.warning('归档台账写入失败: %s', exc)
            self._log(job, f'归档台账写入失败: {exc}', 'warning')

    def _archive_files(self, job: Job, filenames: tuple[str, ...]) -> int:
        """归档已处理文件到各自所在目录的「已处理」子目录。

        收件根目录整体任务（trigger=inbox）时批次文件按各自批次目录归档；
        其余任务（单目录）保持原有行为：文件全部位于 source_dir 一层。
        filenames 为 source_dir 相对路径（可含一层子目录前缀）。
        """
        source_dir = job.source_dir
        archived = 0
        # 按目录分组，同一目录只建一次「已处理」
        by_dir: dict[str, list[str]] = {}
        for rel_path in filenames:
            directory, filename = os.path.split(rel_path)
            container = os.path.join(source_dir, directory) if directory \
                else source_dir
            by_dir.setdefault(container, []).append(filename)
        for container, names in by_dir.items():
            archived_dir = os.path.join(container, '已处理')
            os.makedirs(archived_dir, exist_ok=True)
            for filename in names:
                source = os.path.join(container, filename)
                if not os.path.isfile(source):
                    continue
                target = os.path.join(archived_dir, filename)
                counter = 1
                while os.path.exists(target):
                    name, ext = os.path.splitext(filename)
                    target = os.path.join(archived_dir, f'{name}_{counter}{ext}')
                    counter += 1
                shutil.move(source, target)
                archived += 1
        return archived

    def _get_job_object(self, job_id: str) -> Job:
        with self._lock:
            handle = self._handles.get(job_id)
            if handle is None:
                raise JobNotFound(job_id)
            return handle.job

    @staticmethod
    def _list_pdf_files(source_dir: str) -> list[str]:
        # 结账单等排除关键词命中的 PDF 不进入处理/统计/归档
        return sorted(
            filename for filename in os.listdir(source_dir)
            if filename.lower().endswith('.pdf')
            and not is_excluded_filename(filename)
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
        # progress 单一发布者（融合二期）：注册了宿主回调（DevBase runtime
        # 生产路径）时仅调回调，由 runtime 统一发布 job.progress；无回调
        # （直调本服务的调用方）时才在总线上自发布。两者互斥，任一时刻
        # 只有一个发布者，避免每个 tick 双写两套编号。
        # 锁序：必须在释放本服务锁之后再调回调——回调链会拿 runtime
        # _lock 再拿总线 _lock，不得在持 service 锁时回调 runtime。
        with self._lock:
            job.set_progress(ratio)
            progress = job.progress
            phase = job.phase.value
            message = job.message
            handle = self._handles.get(job.id)
            callback = handle.progress_callback if handle else None
        if callback is not None:
            try:
                callback(progress, message)
            except Exception:
                logger.exception('外部进度回调失败: %s', job.id)
            return
        self.events.publish(
            'job.progress', {'progress': progress, 'phase': phase}, job.id
        )

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
        terminal_handles = [
            handle
            for handle in self._handles.values()
            if handle.job.status.is_terminal and handle.job.id != self._current_job_id
        ]
        excess = len(terminal_handles) - self._job_history_limit
        if excess <= 0:
            return
        terminal_handles.sort(
            key=lambda handle: handle.job.finished_at or handle.job.started_at,
        )
        for handle in terminal_handles[:excess]:
            self._handles.pop(handle.job.id, None)
