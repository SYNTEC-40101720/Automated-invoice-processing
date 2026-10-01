import { useEffect, useRef } from 'react'
import { CheckCircle2, FolderOpen, History, LoaderCircle, Play, Square, TriangleAlert } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Job, JobHistoryEntry, JobStatus } from '../../api/types'

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

const historyStatusLabels: Record<JobStatus, string> = {
  queued: '排队中',
  running: '处理中',
  cancelling: '停止中',
  succeeded: '成功',
  completed_with_warnings: '有警告',
  cancelled: '已取消',
  failed: '失败',
}

export function ProcessingView({ job, onChooseDirectory, onStart, onCancel, onOpenOutput }: ProcessingViewProps) {
  const active = Boolean(job?.id) && (
    job?.status === 'running' || job?.status === 'cancelling' || job?.status === 'queued'
  )
  const finished = job?.status === 'succeeded' || job?.status === 'completed_with_warnings'
  const percent = Math.round((job?.progress ?? 0) * 100)
  const statusLabel = !job
    ? '等待开始'
    : active
      ? job.status === 'queued' ? '等待处理' : '正在处理'
      : finished
        ? '处理完成'
        : job.status === 'failed'
          ? '处理失败'
          : job.status === 'cancelled'
            ? '已取消'
            : '已就绪'
  const statusTone = active ? 'working' : finished ? 'success' : job?.status === 'failed' ? 'error' : ''
  useInvalidateHistoryOnTerminal(job)
  return (
    <div className="editor-view processing-view">
      <div className="view-scroll">
        <header className="view-header processing-header">
          <div>
            <div className="eyebrow">INVOICE PROCESSING / WORKSPACE</div>
            <h1>电子票据处理</h1>
            <p>把目录里的 PDF 变成可核验、可归档的报销资料。</p>
          </div>
          <div className={`state-badge ${statusTone}`}>
            {active ? <LoaderCircle className="spin" size={14} /> : finished ? <CheckCircle2 size={14} /> : job?.status === 'failed' ? <TriangleAlert size={14} /> : <FolderOpen size={14} />}
            <span>{statusLabel}</span>
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

        <RecentHistory currentJobId={job?.id ?? null} onOpenOutput={onOpenOutput} />
      </div>
    </div>
  )
}

function useInvalidateHistoryOnTerminal(job: Job | null) {
  const queryClient = useQueryClient()
  const status = job?.status ?? null
  const prevStatus = useRef<JobStatus | null>(null)
  useEffect(() => {
    const wasActive = prevStatus.current === 'running'
      || prevStatus.current === 'queued'
      || prevStatus.current === 'cancelling'
    prevStatus.current = status
    const terminal = status === 'succeeded' || status === 'completed_with_warnings'
      || status === 'failed' || status === 'cancelled'
    if (terminal && wasActive) {
      void queryClient.invalidateQueries({ queryKey: ['job-history'] })
    }
  }, [queryClient, status])
}

function RecentHistory({ currentJobId, onOpenOutput }: {
  currentJobId: string | null
  onOpenOutput: (path: string) => void
}) {
  const historyQuery = useQuery({
    queryKey: ['job-history'],
    queryFn: () => api.jobHistory(10),
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  })
  const items = (historyQuery.data?.items ?? []).filter(
    (entry) => entry.job_id !== currentJobId,
  )
  return (
    <section className="feature-section history-section" aria-label="最近处理历史">
      <div className="audit-summary-heading">
        <div><span className="field-label">最近处理历史</span><strong>跨启动记录</strong></div>
        <span className="feature-section-meta">最近 {items.length} 条</span>
      </div>
      {items.length === 0 ? (
        <div className="history-empty"><History size={18} /><span>暂无处理历史，完成任务后会在这里显示</span></div>
      ) : (
        <div className="history-list">
          {items.map((entry) => <HistoryRow key={entry.job_id} entry={entry} onOpenOutput={onOpenOutput} />)}
        </div>
      )}
    </section>
  )
}

function HistoryRow({ entry, onOpenOutput }: {
  entry: JobHistoryEntry
  onOpenOutput: (path: string) => void
}) {
  const tone = entry.status === 'succeeded' ? 'ok'
    : entry.status === 'failed' ? 'bad'
    : entry.status === 'cancelled' ? 'muted'
    : 'warn'
  const stats = entry.stats
  return (
    <article className="history-row">
      <div className="history-row-main">
        <span className={`history-status-dot tone-${tone}`} title={entry.error_message ?? undefined} />
        <div className="history-row-copy">
          <strong title={entry.source_dir}>{entry.source_dir}</strong>
          <span className="history-row-meta">
            {historyStatusLabels[entry.status]} · 成功 {stats.success ?? 0}/{stats.total ?? 0}
            {stats.failure ? ` · 失败 ${stats.failure}` : ''}
            {entry.finished_at ? ` · ${formatTime(entry.finished_at)}` : ''}
          </span>
          {entry.status === 'failed' && entry.error_message && (
            <span className="history-row-error" title={entry.error_message}>{entry.error_message}</span>
          )}
        </div>
      </div>
      <div className="history-row-actions">
        {entry.output_dir && (
          <button className="secondary-button" onClick={() => onOpenOutput(entry.output_dir as string)} title={entry.output_dir}>
            <FolderOpen size={15} /> 打开输出
          </button>
        )}
      </div>
    </article>
  )
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className={`metric-card tone-${tone}`}><span>{label}</span><strong>{value}</strong></div>
}