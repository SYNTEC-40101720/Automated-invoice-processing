import { ArrowRight, FileCheck2, Inbox, PanelLeft, ScanSearch, Settings } from 'lucide-react'
import type { PointerEventHandler, ReactNode } from 'react'
import type { ToolDescriptor } from '../api/types'
import type { WorkbenchView } from '../stores/workbench'
import { useWorkbench } from '../stores/workbench'
import appLogo from '../assets/app-logo.svg'

interface SidebarProps {
  activeView: WorkbenchView
  sidebarCollapsed: boolean
  onToggleCollapsed: () => void
  tools: ToolDescriptor[]
  sidebarWidth: number
  onDragStart: PointerEventHandler<HTMLDivElement>
}

interface NavigationItem {
  id: WorkbenchView
  label: string
  subtitle: string
  icon: ReactNode
}

const businessItems: NavigationItem[] = [
  {
    id: 'inbox',
    label: '发票收件箱',
    subtitle: '邮箱与附件',
    icon: <Inbox size={18} strokeWidth={1.6} />,
  },
  {
    id: 'audit',
    label: '审核中心',
    subtitle: '异常与核验',
    icon: <ScanSearch size={18} strokeWidth={1.6} />,
  },
]

export function Sidebar({
  activeView,
  sidebarCollapsed,
  onToggleCollapsed,
  tools,
  sidebarWidth,
  onDragStart,
}: SidebarProps) {
  const setView = useWorkbench((state) => state.setView)
  const setSelectedTool = useWorkbench((state) => state.setSelectedTool)
  const invoiceTool = tools.find((tool) => tool.kind === 'invoice_processing')

  const openInvoiceTool = () => {
    setSelectedTool('invoice_processing')
    setView('processing')
  }

  const openBusinessView = (view: WorkbenchView) => {
    setSelectedTool(null)
    setView(view)
  }

  return (
    <>
      <aside className={`side-bar sidebar${sidebarCollapsed ? ' is-collapsed' : ''}`}>
        <div className="sidebar-brand-row">
          {!sidebarCollapsed && (
            <button type="button" className="sidebar-brand" title="SYNTEC" onClick={openInvoiceTool}>
              <img className="sidebar-brand-mark" src={appLogo} alt="SYNTEC" />
              <span className="sidebar-brand-name">SYNTEC</span>
            </button>
          )}
          {sidebarCollapsed && (
            <>
              <img className="sidebar-brand-mark" src={appLogo} alt="SYNTEC" title="SYNTEC" />
              <button
                type="button"
                className="sidebar-toggle sidebar-toggle-rail"
                aria-label="展开侧栏"
                title="展开侧栏"
                onClick={onToggleCollapsed}
              >
                <ArrowRight size={18} strokeWidth={1.6} />
              </button>
            </>
          )}
          {!sidebarCollapsed && (
            <button
              type="button"
              className="sidebar-toggle"
              aria-label="收起侧栏"
              title="收起侧栏"
              onClick={onToggleCollapsed}
            >
              <PanelLeft size={16} strokeWidth={1.6} />
            </button>
          )}
        </div>

        <div className="sidebar-region" role="navigation">
          <ul className="sidebar-nav-list">
            <li>
              <button
                type="button"
                className={`sidebar-nav-item${activeView === 'processing' ? ' is-selected' : ''}`}
                title={invoiceTool?.title ?? '发票处理'}
                aria-label={invoiceTool?.title ?? '发票处理'}
                aria-current={activeView === 'processing' ? 'page' : undefined}
                onClick={openInvoiceTool}
              >
                <span className="sidebar-nav-icon"><FileCheck2 size={18} strokeWidth={1.6} /></span>
                {!sidebarCollapsed && (
                  <span className="sidebar-nav-text">
                    <span className="sidebar-nav-title">{invoiceTool?.title ?? '发票处理'}</span>
                    <span className="sidebar-nav-sub">{invoiceTool?.subtitle ?? '扫描与归档'}</span>
                  </span>
                )}
              </button>
            </li>
            {businessItems.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={`sidebar-nav-item${activeView === item.id ? ' is-selected' : ''}`}
                  title={item.label}
                  aria-label={item.label}
                  aria-current={activeView === item.id ? 'page' : undefined}
                  onClick={() => openBusinessView(item.id)}
                >
                  <span className="sidebar-nav-icon">{item.icon}</span>
                  {!sidebarCollapsed && (
                    <span className="sidebar-nav-text">
                      <span className="sidebar-nav-title">{item.label}</span>
                      <span className="sidebar-nav-sub">{item.subtitle}</span>
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="sidebar-foot">
          <button
            type="button"
            className={`sidebar-settings-btn${activeView === 'settings' ? ' is-active' : ''}`}
            title="设置"
            aria-label="设置"
            aria-current={activeView === 'settings' ? 'page' : undefined}
            onClick={() => {
              setSelectedTool(null)
              setView('settings')
            }}
          >
            <Settings size={sidebarCollapsed ? 18 : 16} strokeWidth={1.6} />
            {!sidebarCollapsed && <span className="sidebar-settings-label">设置</span>}
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
