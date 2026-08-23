import { FileCheck2, Inbox, ScanSearch, Settings2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { useWorkbench } from '../stores/workbench'

const items: { id: 'processing' | 'inbox' | 'audit' | 'settings'; label: string; icon: ReactNode }[] = [
  { id: 'processing', label: '处理', icon: <FileCheck2 size={19} /> },
  { id: 'inbox', label: '收件箱', icon: <Inbox size={19} /> },
  { id: 'audit', label: '审核', icon: <ScanSearch size={19} /> },
  { id: 'settings', label: '设置', icon: <Settings2 size={19} /> },
]

export function ActivityBar({ version }: { version: string | null }) {
  const activeView = useWorkbench((state) => state.activeView)
  const setView = useWorkbench((state) => state.setView)
  return (
    <nav className="activity-bar" aria-label="主导航">
      <div className="brand-mark" aria-label="SYNTEC">S</div>
      <div className="activity-items">
        {items.map((item) => (
          <button
            key={item.id}
            className={`activity-button ${activeView === item.id ? 'is-active' : ''}`}
            onClick={() => setView(item.id)}
            title={item.label}
            aria-label={item.label}
          >
            {item.icon}
          </button>
        ))}
      </div>
      <div className="activity-foot">v{version ?? '--'}</div>
    </nav>
  )
}