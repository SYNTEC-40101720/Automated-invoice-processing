import { ChevronUp, Download, Terminal, X } from 'lucide-react'
import { useWorkbench } from '../stores/workbench'

export function BottomPanel() {
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
        <span className="panel-tab active">
          <Terminal size={14} /> 处理日志
        </span>
        <span className="panel-grow" />
        <button className="icon-button subtle" title="导出日志" aria-label="导出日志" onClick={() => void exportLogs()} disabled={logs.length === 0}><Download size={14} /></button>
        <button className="icon-button subtle" title="清空当前日志" onClick={clearLogs}><X size={14} /></button>
        <ChevronUp size={15} className="panel-chevron" />
      </div>
      <div className="panel-content">
        {logs.length === 0
          ? <span className="panel-empty">等待处理输出…</span>
          : logs.map((log) => (
            <div className={`log-line log-${log.level}`} key={log.event_id}>
              <span className="log-time">{new Date(log.occurred_at).toLocaleTimeString('zh-CN', { hour12: false })}</span>
              <span>{log.message}</span>
            </div>
          ))}
      </div>
    </section>
  )
}