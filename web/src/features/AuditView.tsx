import { AlertTriangle, CheckCircle2, ScanSearch } from 'lucide-react'
import type { AuditFinding, Job } from '../api/types'

export function AuditView({ job }: { job: Job | null }) {
  const findings = [
    ...(job?.result?.audit?.local_findings ?? []),
    ...(job?.result?.audit?.ai_findings ?? []),
  ]
  return (
    <div className="editor-view feature-view">
      <div className="view-scroll feature-scroll">
        <header className="view-header feature-header"><div><div className="eyebrow">AUDIT / REVIEW</div><h1>审核中心</h1><p>{job ? `任务 ${job.id.slice(0, 8)} · ${job.message}` : '处理完成后，审核结果会在这里显示。'}</p></div></header>
        {!job?.result?.audit ? <div className="feature-section empty-feature"><ScanSearch size={20} /><span>暂无可查看的审核结果</span></div> : findings.length === 0 ? <div className="feature-section empty-feature success-text"><CheckCircle2 size={20} /><span>本次审核未发现问题</span></div> : <div className="finding-list">{findings.map((finding, index) => <Finding key={`${finding.file}-${index}`} finding={finding} />)}</div>}
      </div>
    </div>
  )
}

function Finding({ finding }: { finding: AuditFinding }) {
  return <article className="finding-row"><AlertTriangle size={16} /><div><strong>{finding.file}</strong><p>{finding.issue}</p>{finding.suggestion && <span>{finding.suggestion}</span>}</div><em>{finding.source ?? finding.type}</em></article>
}