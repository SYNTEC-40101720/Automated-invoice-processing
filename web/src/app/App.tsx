import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BottomPanel } from '../components/BottomPanel'
import { Sidebar } from '../components/Sidebar'
import { StatusBar } from '../components/StatusBar'
import { UpdateBanner } from '../components/UpdateBanner'
import { api, connectEvents } from '../api/client'
import { ProcessingView } from '../features/processing/ProcessingView'
import { AuditView } from '../features/AuditView'
import { InboxView } from '../features/InboxView'
import { SettingsView } from '../features/SettingsView'
import { useWorkbench } from '../stores/workbench'

export function App() {
  const activeView = useWorkbench((state) => state.activeView)
  const connected = useWorkbench((state) => state.connected)
  const job = useWorkbench((state) => state.currentJob)
  const setView = useWorkbench((state) => state.setView)
  const setConnected = useWorkbench((state) => state.setConnected)
  const setJob = useWorkbench((state) => state.setJob)
  const appendEvent = useWorkbench((state) => state.appendEvent)
  const setLogs = useWorkbench((state) => state.setLogs)
  const mergeLogs = useWorkbench((state) => state.mergeLogs)
  const [directory, setDirectory] = useState('')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const lastEventId = useRef(0)
  const healthQuery = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false })
  const updateQuery = useQuery({
    queryKey: ['update'],
    queryFn: api.updateCheck,
    retry: false,
    staleTime: 5 * 60_000,
  })
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: api.settings, retry: false })
  const currentJobQuery = useQuery({ queryKey: ['current-job'], queryFn: api.currentJob, retry: false })
  const toolsQuery = useQuery({ queryKey: ['tools'], queryFn: api.tools, retry: false })

  useEffect(() => {
    if (currentJobQuery.data) {
      setJob(currentJobQuery.data)
      setDirectory(currentJobQuery.data.source_dir)
    }
  }, [currentJobQuery.data, setJob])

  useEffect(() => {
    let disposed = false
    let cleanup: (() => void) | undefined
    let reconnectScheduled = false
    let reconnectDelay = 1500
    let restoreInFlight: Promise<void> | undefined
    const restoreState = () => {
      if (restoreInFlight) return restoreInFlight
      const afterEventId = lastEventId.current
      restoreInFlight = api.currentJob().then((snapshot) => {
        setJob(snapshot)
        if (!snapshot?.id) {
          setLogs([])
          return
        }
        setDirectory(snapshot.source_dir)
        return api.logs(snapshot.id, afterEventId).then((response) => {
          mergeLogs(response.items)
          const latestLogEventId = response.items.at(-1)?.event_id ?? 0
          lastEventId.current = Math.max(lastEventId.current, latestLogEventId)
        })
      }).catch(() => undefined).finally(() => {
        restoreInFlight = undefined
      })
      return restoreInFlight
    }
    const connect = () => {
      if (disposed) return
      reconnectScheduled = false
      cleanup = connectEvents((event) => {
        if (event.event_id > 0) {
          if (lastEventId.current > 0 && event.event_id > lastEventId.current + 1) {
            void restoreState()
          }
          if (event.event_id <= lastEventId.current) return
          lastEventId.current = event.event_id
        }
        appendEvent(event)
        if (event.type === 'job.snapshot') {
          const nextJob = event.payload as never
          setJob(nextJob)
          setDirectory((nextJob as { source_dir: string }).source_dir)
        }
      }, (isConnected) => {
        setConnected(isConnected)
        if (isConnected) {
          reconnectDelay = 1500
          void restoreState()
        } else if (!disposed && !reconnectScheduled) {
          reconnectScheduled = true
          const delay = reconnectDelay
          reconnectDelay = Math.min(reconnectDelay * 2, 10000)
          reconnectTimer.current = setTimeout(() => {
            reconnectTimer.current = undefined
            connect()
          }, delay)
        }
      })
    }
    connect()
    return () => {
      disposed = true
      cleanup?.()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [appendEvent, mergeLogs, setConnected, setJob, setLogs])

  useEffect(() => {
    if (!job?.id) {
      setLogs([])
      return
    }
    setLogs([])
    api.logs(job.id).then((response) => {
      mergeLogs(response.items)
      lastEventId.current = Math.max(lastEventId.current, response.next_event_id ?? 0)
    }).catch(() => undefined)
  }, [job?.id, mergeLogs, setLogs])

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        setSidebarCollapsed((value) => !value)
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  const chooseDirectory = async () => {
    const value = window.pywebview?.api
      ? await window.pywebview.api.select_directory()
      : window.prompt('请输入包含 PDF 发票的文件夹路径', directory) ?? ''
    if (!value?.trim()) return
    try {
      const scanned = await api.scanDirectory(value.trim())
      setDirectory(scanned.source_dir)
      setJob({
        id: '', source_dir: scanned.source_dir, output_dir: null, trigger: 'manual', status: 'queued', phase: 'scan',
        progress: 0, message: `已就绪 — ${scanned.pdf_count} 个 PDF 文件待处理`,
        stats: { total: scanned.pdf_count, success: 0, failure: 0, tax_issues: 0 },
        started_at: null, finished_at: null, cancel_requested: false, error_code: null, error_message: null, result: null,
      })
    } catch (error) {
      window.alert((error as Error).message)
    }
  }

  const openOutput = async (path: string) => {
    if (window.pywebview?.api) {
      await window.pywebview.api.open_directory(path)
      return
    }
    window.alert(`输出目录：${path}`)
  }

  const start = () => {
    const sourceDir = directory || job?.source_dir
    if (!sourceDir) {
      window.alert('请先选择包含 PDF 发票的文件夹')
      return
    }
    api.startJob(sourceDir).then((nextJob) => setJob(nextJob)).catch((error: Error) => window.alert(error.message))
  }

  const cancel = () => {
    if (!job?.id) return
    api.cancelJob(job.id).then((nextJob) => setJob(nextJob)).catch((error: Error) => window.alert(error.message))
  }

  const checkForUpdate = async () => {
    const result = await updateQuery.refetch()
    if (result.error) throw result.error
    return result.data ?? null
  }

  const applyUpdate = () => api.applyUpdate()

  const emailSettings = settingsQuery.data?.email ?? null

  return <div className={`workbench-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
    <Sidebar
      activeView={activeView}
      version={healthQuery.data?.version ?? null}
      sidebarCollapsed={sidebarCollapsed}
      onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
      tools={toolsQuery.data?.tools ?? []}
    />
    <main className={`main-column ${updateQuery.data?.available ? 'has-update' : ''}`}>
      {updateQuery.data?.available && <UpdateBanner update={updateQuery.data} onOpenSettings={() => setView('settings')} />}
      <div className="main-content">
        {activeView === 'processing'
          ? <ProcessingView job={job} onChooseDirectory={chooseDirectory} onStart={start} onCancel={cancel} onOpenOutput={openOutput} />
          : activeView === 'inbox'
            ? <InboxView emailSettings={emailSettings} />
            : activeView === 'audit'
              ? <AuditView job={job} />
              : <SettingsView
                version={healthQuery.data?.version ?? null}
                update={updateQuery.data ?? null}
                onCheckUpdate={checkForUpdate}
                onApplyUpdate={applyUpdate}
              />}
      </div>
      <BottomPanel />
    </main>
    <StatusBar connected={connected} job={job} version={healthQuery.data?.version ?? null} />
  </div>
}