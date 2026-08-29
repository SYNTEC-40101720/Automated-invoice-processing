import { Bot, ChevronDown, FileText, FolderOpen, History, Mail, Plus, RefreshCw, ShieldCheck } from 'lucide-react'
import type { EmailSettings, Job } from '../api/types'
import type { SettingsSection } from '../stores/workbench'
import { useWorkbench } from '../stores/workbench'

interface SidebarProps {
  activeView: string
  job: Job | null
  emailSettings: EmailSettings | null
  onChooseDirectory: () => void
  onOpenInbox: () => void
}

const settingsItems: { id: SettingsSection; label: string; description: string; icon: React.ReactNode }[] = [
  { id: 'business', label: '业务规则', description: '税号与处理并发', icon: <ShieldCheck size={16} /> },
  { id: 'email', label: '邮箱连接', description: 'IMAP 与发件人白名单', icon: <Mail size={16} /> },
  { id: 'ai', label: 'AI 审核', description: '模型接口与审核开关', icon: <Bot size={16} /> },
  { id: 'updates', label: '软件更新', description: '版本检查与安装', icon: <RefreshCw size={16} /> },
]

export function Sidebar({ activeView, job, emailSettings, onChooseDirectory, onOpenInbox }: SidebarProps) {
  const settingsSection = useWorkbench((state) => state.settingsSection)
  const setSettingsSection = useWorkbench((state) => state.setSettingsSection)
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
          <div className="sidebar-section-label">收件目录</div>
          <button className="directory-row" onClick={onOpenInbox} title="打开收件箱设置">
            <FolderOpen size={15} />
            <span>{emailSettings?.inbox_dir ?? '正在读取收件目录'}</span>
          </button>
          <div className="sidebar-section-label">自动收件</div>
          <div className={`inbox-summary ${emailSettings?.enabled && emailSettings.poll_minutes > 0 ? 'is-active' : ''}`}>
            <span className="status-dot" />
            {emailSettings
              ? emailSettings.enabled && emailSettings.poll_minutes > 0
                ? `已开启 · 每 ${emailSettings.poll_minutes} 分钟`
                : '已关闭'
              : '正在读取状态'}
          </div>
          <button className="sidebar-action" onClick={onOpenInbox}><Plus size={14} /> 管理收件设置</button>
        </>
      )}
      {activeView === 'audit' && (
        <div className="sidebar-note">处理完成后，审核报告会出现在这里。</div>
      )}
      {activeView === 'settings' && (
        <>
          <div className="sidebar-section-label settings-section-label">设置分类</div>
          <nav className="settings-nav" aria-label="设置分类">
            {settingsItems.map((item) => (
              <button
                key={item.id}
                className={`settings-nav-item ${settingsSection === item.id ? 'is-active' : ''}`}
                onClick={() => setSettingsSection(item.id)}
                aria-current={settingsSection === item.id ? 'page' : undefined}
              >
                <span className="settings-nav-icon">{item.icon}</span>
                <span className="settings-nav-copy">
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </button>
            ))}
          </nav>
          <div className="sidebar-note settings-sidebar-note">配置由本地服务保存，切换分类不会丢失未保存的修改。</div>
        </>
      )}
    </aside>
  )
}