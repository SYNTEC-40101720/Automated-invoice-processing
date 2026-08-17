"""本地规则和 AI 审核的应用编排。"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from ..config_manager import (
    get_ai_api_base,
    get_ai_api_key,
    get_ai_enabled,
    get_ai_model,
    get_ai_timeout,
)
from ..core.ai_audit import audit_records, write_audit_report
from ..core.excel_summary import _parse_invoice
from ..core.local_audit import run_local_audit

logger = logging.getLogger(__name__)


class AuditService:
    """运行审核但不阻断主处理流程。"""

    def __init__(
        self,
        processor,
        log_callback: Callable[[str, str], None] | None = None,
        ai_enabled_provider: Callable[[], bool] = get_ai_enabled,
        ai_api_key_provider: Callable[[], str] = get_ai_api_key,
        ai_api_base_provider: Callable[[], str] = get_ai_api_base,
        ai_model_provider: Callable[[], str] = get_ai_model,
        ai_timeout_provider: Callable[[], int] = get_ai_timeout,
    ):
        self.processor = processor
        self._log_callback = log_callback
        self._ai_enabled = ai_enabled_provider
        self._ai_api_key = ai_api_key_provider
        self._ai_api_base = ai_api_base_provider
        self._ai_model = ai_model_provider
        self._ai_timeout = ai_timeout_provider

    def run(self, output_dir: str) -> dict:
        local_findings = run_local_audit(output_dir, self.processor)
        self._report_findings('本地规则预检', local_findings)

        ai_findings: list[dict] = []
        if self._ai_enabled():
            try:
                ai_findings = self._run_ai_audit(output_dir)
            except Exception as exc:
                self._log(f'AI 审核调用失败: {exc}', 'warning')
                ai_findings = []

        combined = (
            [{'source': '本地规则', **finding} for finding in local_findings]
            + [{'source': 'AI 审核', **finding} for finding in ai_findings]
        )
        try:
            report_path = write_audit_report(output_dir, combined)
            if report_path:
                self._log(f'审核报告已写入: {report_path}', 'success')
        except Exception as exc:
            logger.warning('审核报告写入失败: %s', exc)
            self._log(f'审核报告写入失败: {exc}', 'warning')
            report_path = None

        return {
            'local_findings': local_findings,
            'ai_findings': ai_findings,
            'report': report_path,
        }

    def _run_ai_audit(self, output_dir: str) -> list[dict]:
        records = []
        try:
            filenames = sorted(os.listdir(output_dir))
        except OSError as exc:
            raise RuntimeError(f'AI 审核数据收集失败: {exc}') from exc

        for filename in filenames:
            if filename == '合并结果.pdf' or not filename.lower().endswith('.pdf'):
                continue
            path = os.path.join(output_dir, filename)
            if not os.path.isfile(path):
                continue
            rows = _parse_invoice(output_dir, filename, self.processor)
            if rows:
                records.append({'file': filename, 'rows': rows})

        if not records:
            self._log('AI 审核：无可用发票数据', 'info')
            return []

        self._log(f'AI 审核中…（{len(records)} 个文件）', 'info')
        findings = audit_records(
            records,
            api_key=self._ai_api_key(),
            api_base=self._ai_api_base(),
            model=self._ai_model(),
            timeout=self._ai_timeout(),
        )
        self._report_findings('AI 审核', findings)
        return findings

    def _report_findings(self, name: str, findings: list[dict]) -> None:
        if not findings:
            self._log(f'{name}：未发现问题', 'success')
            return
        self._log(f'{name}发现 {len(findings)} 个问题：', 'warning')
        for item in findings[:20]:
            suggestion = item.get('suggestion', '')
            suffix = f'（建议：{suggestion}）' if suggestion else ''
            self._log(
                f"  [{item.get('type', 'other')}] {item.get('file', '')}："
                f"{item.get('issue', '')}{suffix}",
                'warning',
            )
        if len(findings) > 20:
            self._log(f'  …其余 {len(findings) - 20} 条省略', 'info')

    def _log(self, message: str, level: str) -> None:
        if self._log_callback:
            self._log_callback(message, level)
