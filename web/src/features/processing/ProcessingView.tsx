import { CheckCircle2, FolderOpen, Play, Square, TriangleAlert } from 'lucide-react'
import type { Job } from '../../api/types'

interface ProcessingViewProps {
  job: Job | null
  onChooseDirectory: () => void
  onStart: () => void
  onCancel: () => void
  onOpenOutput: (path: string) => void
}

const phaseLabels: Record<string, string> = {
  scan: '扫描目录', process: '处理 PDF', post_process: '后处理',
  local_audit: '本地审核', ai_audit: 'AI 审核', archive: '归档', done: '已完成',
}

export function ProcessingView({ job, onChooseDirectory, onStart, onCancel, onOpenOutput }: ProcessingViewProps) {
  const active = Boolean(job?.id) && (
    job?.status === 'running' || job?.status === 'cancelling' || job?.status === 'queued'
  )
  const finished = job?.status === 'succeeded' || job?.status === 'completed_with_warnings'
  const percent = Math.round((job?.progress ?? 0) * 100)
  return (
    <div className="editor-view processing-view">
      <div className="view-scroll">
        <header className="view-header">
          <div>
            <div className="eyebrow">INVOICE PROCESSING / WORKSPACE</div>
            <h1>电子票据处理</h1>
            <p>把目录里的 PDF 变成可核验、可归档的报销资料。</p>
          </div>
          <div className={`state-badge ${finished ? 'success' : active ? 'working' : ''}`}>
            {finished ? <CheckCircle2 size={15} /> : active ? <span className="pulse-dot" /> : <span className="idle-dot" />}
            {finished ? '本次任务已完成' : active ? (job?.message ?? '正在处理') : '工作台就绪'}
          </div>
        </header>

        <section className="source-strip">
          <div className="source-icon"><FolderOpen size={20} /></div>
          <div className="source-copy">
            <span className="field-label">源文件目录</span>
            <strong title={job?.source_dir}>{job?.source_dir ?? '请选择包含 PDF 发票的文件夹'}</strong>
          </div>
          <button className="secondary-button" onClick={onChooseDirectory} disabled={active}>
            <FolderOpen size={15} /> 选择目录
          </button>
        </section>

        <div className="metric-grid">
          <Metric label="文件总数" value={job?.stats.total ?? 0} tone="neutral" />
          <Metric label="处理成功" value={job?.stats.success ?? 0} tone="green" />
          <Metric label="处理失败" value={job?.stats.failure ?? 0} tone="red" />
          <Metric label="税号异常" value={job?.stats.tax_issues ?? 0} tone="amber" />
        </div>

        <section className="progress-section">
          <div className="section-heading">
            <div>
              <span className="field-label">任务进度</span>
              <strong>{job ? phaseLabels[job.phase] ?? job.phase : '等待开始'}</strong>
            </div>
            <span className="progress-value">{percent}%</span>
          </div>
          <div className="progress-track"><div className="progress-fill" style={{ width: `${percent}%` }} /></div>
          <div className="progress-meta">
            <span>{job?.message ?? '选择目录后开始处理'}</span>
            {job?.output_dir && <span className="mono-text" title={job.output_dir}>输出 · {job.output_dir}</span>}
          </div>
        </section>

        <div className="action-row">
          <button className={active ? 'danger-button' : 'primary-button'} onClick={active ? onCancel : onStart} disabled={!job?.source_dir && !active}>
            {active ? <><Square size={15} /> 停止处理</> : <><Play size={15} /> 开始处理</>}
          </button>
          {!job && <button className="text-button" onClick={onChooseDirectory}>先选择一个目录</button>}
          {job?.status === 'failed' && <span className="inline-warning"><TriangleAlert size={14} /> {job.error_message}</span>}
        </div>

        {finished && (
          <section className="result-strip">
            <div><CheckCircle2 size={18} /><span>处理结果已生成</span></div>
            <div className="result-path">{job.output_dir}</div>
            <button className="secondary-button" onClick={() => job.output_dir && onOpenOutput(job.output_dir)} disabled={!job.output_dir}>打开输出目录</button>
          </section>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className={`metric-card tone-${tone}`}><span>{label}</span><strong>{value}</strong></div>
}