import { Inbox, ScanSearch, Settings2 } from 'lucide-react'

const copy = {
  inbox: { icon: Inbox, eyebrow: 'INBOX / AUTOMATION', title: '发票收件箱', text: '邮箱拉取和目录监听将在这里汇聚。' },
  audit: { icon: ScanSearch, eyebrow: 'AUDIT / REVIEW', title: '审核中心', text: '本地规则与 AI 审核报告会在任务完成后集中呈现。' },
  settings: { icon: Settings2, eyebrow: 'WORKBENCH / SETTINGS', title: '工作台设置', text: '业务、邮箱与 AI 审核配置即将接入。' },
} as const

export function PlaceholderView({ view }: { view: 'inbox' | 'audit' | 'settings' }) {
  const item = copy[view]
  const Icon = item.icon
  return <div className="editor-view placeholder-view"><div className="editor-tabs"><div className="editor-tab active"><Icon size={14} /> {item.title}</div></div><div className="placeholder-content"><div className="placeholder-icon"><Icon size={26} /></div><div className="eyebrow">{item.eyebrow}</div><h1>{item.title}</h1><p>{item.text}</p><span className="placeholder-status">本阶段 API 接口已预留</span></div></div>
}