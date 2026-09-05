import { FileCheck2, Inbox, PanelLeft, ScanSearch, Settings } from 'lucide-react'
import type { PointerEventHandler, ReactNode } from 'react'
import type { ToolDescriptor } from '../api/types'
import type { WorkbenchView } from '../stores/workbench'
import { useWorkbench } from '../stores/workbench'

interface SidebarProps {
  activeView: WorkbenchView
  version: string | null
  sidebarCollapsed: boolean
  onToggleCollapsed: () => void
  tools: ToolDescriptor[]
  sidebarWidth: number
  onDragStart: PointerEventHandler<HTMLDivElement>
}

type PrimaryView = Exclude<WorkbenchView, 'settings'>

const mainItems: { id: PrimaryView; label: string; icon: ReactNode }[] = [
  { id: 'processing', label: '处理工作台', icon: <FileCheck2 size={16} /> },
  { id: 'inbox', label: '发票收件箱', icon: <Inbox size={16} /> },
  { id: 'audit', label: '审核中心', icon: <ScanSearch size={16} /> },
]

export function Sidebar({ activeView, version, sidebarCollapsed, onToggleCollapsed, tools, sidebarWidth, onDragStart }: SidebarProps) {
  const setView = useWorkbench((state) => state.setView)
  const invoiceTool = tools.find((tool) => tool.kind === 'invoice_processing')
  const items = mainItems.map((item) => (
    item.id === 'processing' && invoiceTool
      ? { ...item, label: invoiceTool.title }
      : item
  ))

  return (
    <>
    <aside className="side-bar">
      <div className="sidebar-brand-row">
        <div className="brand-mark" aria-label="SYNTEC">S</div>
        {!sidebarCollapsed && <span className="sidebar-brand-name">SYNTEC</span>}
        <button
          className="icon-button sidebar-toolbar-button"
          title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
          aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
          onClick={onToggleCollapsed}
        >
          <PanelLeft size={15} />
        </button>
      </div>
      <nav className="sidebar-primary-nav" aria-label="主导航">
        {items.map((item) => (
          <button
            key={item.id}
            className={`sidebar-primary-item ${activeView === item.id ? 'is-active' : ''}`}
            title={item.label}
            aria-label={item.label}
            onClick={() => setView(item.id)}
            aria-current={activeView === item.id ? 'page' : undefined}
          >
            <span className="sidebar-primary-icon">{item.icon}</span>
            {!sidebarCollapsed && <span>{item.label}</span>}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-footer-avatar">S</div>
        {!sidebarCollapsed && <div className="sidebar-footer-copy">
          <strong>SYNTEC</strong>
          <span>本地模式 · v{version ?? '--'}</span>
        </div>}
        <button
          className={`icon-button sidebar-toolbar-button ${activeView === 'settings' ? 'is-active' : ''}`}
          title={activeView === 'settings' ? '当前设置' : '打开设置'}
          aria-label={activeView === 'settings' ? '当前设置' : '打开设置'}
          aria-current={activeView === 'settings' ? 'page' : undefined}
          onClick={() => setView('settings')}
        >
          <Settings size={15} />
        </button>
      </div>
    </aside>
    {!sidebarCollapsed && (
      <div
        className="sidebar-drag-handle"
        style={{ left: sidebarWidth - 4 }}
        onPointerDown={onDragStart}
        aria-hidden="true"
      />
    )}
    </>
  )
}