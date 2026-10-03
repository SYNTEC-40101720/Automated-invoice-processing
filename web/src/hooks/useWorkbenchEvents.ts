import { useEffect, useRef } from 'react'
import { api, connectEvents } from '../api/client'
import { applyEventCursor } from '../api/eventCursor'
import { useWorkbench } from '../stores/workbench'

interface WorkbenchEventsOptions {
  /** 任务快照到达时同步源目录输入框（App 本地状态） */
  onSnapshotDirectory: (sourceDir: string) => void
}

/**
 * 工作台 WebSocket 连接与事件恢复。
 *
 * 事件流语义（与后端 events.py 对齐）：
 * - event_id 全局单调递增；event_id 为 0 的帧是控制帧
 *   （system.ready / system.heartbeat / 服务端下发的 job.snapshot），
 *   不参与游标推进。
 * - 断线后按指数退避重连，重连时把 lastEventId 作为 after 游标交给
 *   服务端重放漏掉的事件。
 * - 收到带洞事件（event_id 跳号）时拉取当前任务快照 + 日志补洞。
 *
 * 游标推进规则抽成纯函数 applyEventCursor（见 eventCursor.ts），
 * 含跨重启的游标回退保护；单测覆盖在 tests/eventCursor.test.ts。
 */
export function useWorkbenchEvents(options: WorkbenchEventsOptions) {
  const setConnected = useWorkbench((state) => state.setConnected)
  const setJob = useWorkbench((state) => state.setJob)
  const appendEvent = useWorkbench((state) => state.appendEvent)
  const setLogs = useWorkbench((state) => state.setLogs)
  const mergeLogs = useWorkbench((state) => state.mergeLogs)
  const { onSnapshotDirectory } = options
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const lastEventId = useRef(0)

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
        onSnapshotDirectory(snapshot.source_dir)
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
          const { accepted, nextCursor, needRestore } = applyEventCursor(
            lastEventId.current, event,
          )
          lastEventId.current = nextCursor
          if (needRestore) void restoreState()
          if (!accepted) return
        }
        appendEvent(event)
        if (event.type === 'job.snapshot') {
          const nextJob = event.payload as never
          setJob(nextJob)
          onSnapshotDirectory((nextJob as { source_dir: string }).source_dir)
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
      }, lastEventId.current)
    }
    connect()
    return () => {
      disposed = true
      cleanup?.()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [appendEvent, mergeLogs, onSnapshotDirectory, setConnected, setJob, setLogs])
}
