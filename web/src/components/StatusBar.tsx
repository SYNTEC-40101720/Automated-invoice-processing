import { CircleCheck, CircleX, LoaderCircle } from 'lucide-react'
import type { Job } from '../api/types'

interface StatusBarProps {
  connected: boolean
  job: Job | null
  version: string | null
}

const phaseLabels: Record<string, string> = {
  scan: '扫描目录',
  process: '处理 PDF',
  post_process: '后处理',
  local_audit: '本地审核',
  ai_audit: 'AI 审核',
  archive: '归档',
  done: '已完成',
}

export function StatusBar({ connected, job, version }: StatusBarProps) {
  const running = job?.status === 'running' || job?.status === 'cancelling'
  return (
    <footer className="status-bar">
      <span className={connected ? 'connection connected' : 'connection'}>
        {connected ? <CircleCheck size={13} /> : <CircleX size={13} />}
        {connected ? '本地服务已连接' : '正在连接本地服务'}
      </span>
      <span className="status-divider" />
      <span className="status-phase">
        {running && <LoaderCircle className="spin" size={13} />}
        {job ? phaseLabels[job.phase] ?? job.phase : '就绪'}
      </span>
      <span className="status-spacer" />
      <span>{job ? `${Math.round(job.progress * 100)}%` : '0%'}</span>
      <span className="status-divider" />
      <span>本地模式</span>
      <span className="status-divider" />
      <span className="status-version">SYNTEC {version ?? '--'}</span>
    </footer>
  )
}