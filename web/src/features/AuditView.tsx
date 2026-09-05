import { AlertTriangle, CheckCircle2, ScanSearch } from 'lucide-react'
import type { AuditFinding, Job } from '../api/types'

export function AuditView({ job }: { job: Job | null }) {
  const audit = job?.result?.audit
  const localFindings = audit?.local_findings ?? []
  const aiFindings = audit?.ai_findings ?? []
  const findings = [...localFindings, ...aiFindings]
  const statusLabel = !job ? '等待处理' : !audit ? '等待审核结果' : findings.length > 0 ? `${findings.length} 项待处理` : '审核通过'
  const statusTone = audit && findings.length === 0 ? 'success' : findings.length > 0 ? 'working' : ''
  return (
    <div className="editor-view feature-view">
      <div className="view-scroll feature-scroll">
        <header className="view-header feature-header audit-header">
          <div><div className="eyebrow">AUDIT / REVIEW</div><h1>审核中心</h1><p>{job ? `任务 ${job.id.slice(0, 8)} · ${job.message}` : '处理完成后，审核结果会在这里显示。'}</p></div>
          <div className={`state-badge ${statusTone}`}>
            {audit && findings.length === 0 ? <CheckCircle2 size={14} /> : findings.length > 0 ? <AlertTriangle size={14} /> : <ScanSearch size={14} />}
            <span>{statusLabel}</span>
          </div>
        </header>
        <section className="feature-section audit-summary" aria-label="审核摘要">
          <div className="audit-summary-heading">
            <div><span className="field-label">审核摘要</span><strong>{audit ? '本次任务' : '等待结果'}</strong></div>
            <span className="feature-section-meta">{job ? `任务 ${job.id.slice(0, 8)}` : '尚未生成任务'}</span>
          </div>
          <div className="audit-summary-grid">
            <div className={`audit-stat ${findings.length > 0 ? 'has-findings' : 'is-clear'}`}><span>问题总数</span><strong>{findings.length}</strong></div>
            <div className="audit-stat"><span>本地规则</span><strong>{localFindings.length}</strong></div>
            <div className="audit-stat"><span>AI 审核</span><strong>{aiFindings.length}</strong></div>
          </div>
        </section>
        {!audit ? <div className="feature-section empty-feature"><ScanSearch size={20} /><span>暂无可查看的审核结果</span></div> : findings.length === 0 ? <div className="feature-section empty-feature success-text"><CheckCircle2 size={20} /><span>本次审核未发现问题</span></div> : <div className="finding-list">{findings.map((finding, index) => <Finding key={`${finding.file}-${index}`} finding={finding} />)}</div>}
      </div>
    </div>
  )
}

function Finding({ finding }: { finding: AuditFinding }) {
  return <article className="finding-row"><AlertTriangle size={16} /><div><strong>{finding.file}</strong><p>{finding.issue}</p>{finding.suggestion && <span>{finding.suggestion}</span>}</div><em>{finding.source ?? finding.type}</em></article>
}