import { ChevronDown, FileText, FolderOpen, History, Plus } from 'lucide-react'
import type { Job } from '../api/types'

interface SidebarProps {
  activeView: string
  job: Job | null
  onChooseDirectory: () => void
}

export function Sidebar({ activeView, job, onChooseDirectory }: SidebarProps) {
  const title = activeView === 'processing'
    ? '处理工作区'
    : activeView === 'inbox'
      ? '发票收件箱'
      : activeView === 'audit'
        ? '审核中心'
        : '工作台设置'

  return (
    <aside className="side-bar">
      <div className="sidebar-heading">
        <span>{title}</span>
        <ChevronDown size={14} />
      </div>
      {activeView === 'processing' && (
        <>
          <div className="sidebar-section-label">当前目录</div>
          <button className="directory-row" onClick={onChooseDirectory} title="选择 PDF 文件目录">
            <FolderOpen size={15} />
            <span>{job?.source_dir ?? '尚未选择目录'}</span>
          </button>
          <div className="sidebar-section-label">任务概览</div>
          <div className="sidebar-card">
            <div className="sidebar-card-icon"><FileText size={16} /></div>
            <div>
              <strong>{job ? `${job.stats.total} 个 PDF` : '准备导入发票'}</strong>
              <span>{job ? job.status : '等待选择工作目录'}</span>
            </div>
          </div>
          <div className="sidebar-section-label history-label">最近任务</div>
          <div className="empty-sidebar-row"><History size={14} /> 暂无历史快照</div>
        </>
      )}
      {activeView === 'inbox' && (
        <>
          <div className="sidebar-section-label">自动收件箱</div>
          <div className="inbox-summary"><span className="status-dot" /> 监听未连接</div>
          <button className="sidebar-action" onClick={onChooseDirectory}><Plus size={14} /> 指定收件箱目录</button>
        </>
      )}
      {activeView === 'audit' && (
        <div className="sidebar-note">处理完成后，审核报告会出现在这里。</div>
      )}
      {activeView === 'settings' && (
        <div className="sidebar-note">业务、邮箱和 AI 审核配置统一由本地服务保存。</div>
      )}
    </aside>
  )
}