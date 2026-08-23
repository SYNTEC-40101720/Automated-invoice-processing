import { AlertTriangle, ChevronUp, ClipboardList, Download, Terminal, X } from 'lucide-react'
import { useWorkbench } from '../stores/workbench'

export function BottomPanel() {
  const panel = useWorkbench((state) => state.bottomPanel)
  const setPanel = useWorkbench((state) => state.setBottomPanel)
  const logs = useWorkbench((state) => state.logs)
  const clearLogs = useWorkbench((state) => state.clearLogs)
  const exportLogs = async () => {
    if (logs.length === 0) return
    const content = logs.map((log) => (
      `${log.occurred_at} [${log.level.toUpperCase()}] ${log.message}`
    )).join('\n') + '\n'
    try {
      if (window.pywebview?.api) {
        const path = await window.pywebview.api.save_log_dialog('invoice.log.txt')
        if (!path) return
        if (!await window.pywebview.api.write_log(content)) {
          window.alert('日志导出失败')
        }
        return
      }
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'invoice.log.txt'
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      window.alert((error as Error).message)
    }
  }
  return (
    <section className="bottom-panel">
      <div className="panel-tabs">
        <button className={panel === 'output' ? 'panel-tab active' : 'panel-tab'} onClick={() => setPanel('output')}>
          <Terminal size={14} /> 输出
        </button>
        <button className={panel === 'problems' ? 'panel-tab active' : 'panel-tab'} onClick={() => setPanel('problems')}>
          <AlertTriangle size={14} /> 问题
        </button>
        <button className={panel === 'details' ? 'panel-tab active' : 'panel-tab'} onClick={() => setPanel('details')}>
          <ClipboardList size={14} /> 任务详情
        </button>
        <span className="panel-grow" />
        <button className="icon-button subtle" title="导出日志" aria-label="导出日志" onClick={() => void exportLogs()} disabled={logs.length === 0}><Download size={14} /></button>
        <button className="icon-button subtle" title="清空当前日志" onClick={clearLogs}><X size={14} /></button>
        <ChevronUp size={15} className="panel-chevron" />
      </div>
      <div className="panel-content">
        {panel === 'output' && (logs.length === 0
          ? <span className="panel-empty">等待处理输出…</span>
          : logs.map((log) => (
            <div className={`log-line log-${log.level}`} key={log.event_id}>
              <span className="log-time">{new Date(log.occurred_at).toLocaleTimeString('zh-CN', { hour12: false })}</span>
              <span>{log.message}</span>
            </div>
          )))}
        {panel === 'problems' && <span className="panel-empty">当前任务没有已加载的问题。</span>}
        {panel === 'details' && <span className="panel-empty">选择一个任务查看处理明细。</span>}
      </div>
    </section>
  )
}