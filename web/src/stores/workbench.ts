import { create } from 'zustand'
import type { DomainEvent, Job, LogEntry } from '../api/types'

interface WorkbenchState {
  connected: boolean
  currentJob: Job | null
  logs: LogEntry[]
  activeView: 'processing' | 'inbox' | 'audit' | 'settings'
  bottomPanel: 'output' | 'problems' | 'details'
  setConnected: (connected: boolean) => void
  setJob: (job: Job | null) => void
  setView: (view: WorkbenchState['activeView']) => void
  setBottomPanel: (panel: WorkbenchState['bottomPanel']) => void
  appendEvent: (event: DomainEvent) => void
  setLogs: (logs: LogEntry[]) => void
  clearLogs: () => void
}

export const useWorkbench = create<WorkbenchState>((set) => ({
  connected: false,
  currentJob: null,
  logs: [],
  activeView: 'processing',
  bottomPanel: 'output',
  setConnected: (connected) => set({ connected }),
  setJob: (currentJob) => set({ currentJob }),
  setView: (activeView) => set({ activeView }),
  setBottomPanel: (bottomPanel) => set({ bottomPanel }),
  appendEvent: (event) => set((state) => {
    if (event.type === 'job.snapshot') {
      return { currentJob: event.payload as unknown as Job }
    }
    if (event.type === 'job.log_appended') {
      const entry: LogEntry = {
        event_id: event.event_id,
        occurred_at: event.occurred_at,
        level: String(event.payload.level ?? 'info'),
        message: String(event.payload.message ?? ''),
      }
      return { logs: [...state.logs, entry].slice(-500) }
    }
    if (!state.currentJob || state.currentJob.id !== event.job_id) return state
    if (event.type === 'job.progress') {
      return {
        currentJob: {
          ...state.currentJob,
          progress: Number(event.payload.progress ?? state.currentJob.progress),
          phase: String(event.payload.phase ?? state.currentJob.phase) as Job['phase'],
        },
      }
    }
    if (event.type === 'job.status_changed') {
      return {
        currentJob: {
          ...state.currentJob,
          status: String(event.payload.status ?? state.currentJob.status) as Job['status'],
          phase: String(event.payload.phase ?? state.currentJob.phase) as Job['phase'],
          message: String(event.payload.message ?? state.currentJob.message),
        },
      }
    }
    if (event.type === 'job.stats_changed') {
      return {
        currentJob: {
          ...state.currentJob,
          stats: {
            total: Number(event.payload.total ?? state.currentJob.stats.total),
            success: Number(event.payload.success ?? state.currentJob.stats.success),
            failure: Number(event.payload.failure ?? state.currentJob.stats.failure),
            tax_issues: Number(event.payload.tax_issues ?? state.currentJob.stats.tax_issues),
          },
        },
      }
    }
    if (event.type === 'job.completed') {
      return { currentJob: { ...state.currentJob, result: event.payload as Job['result'] } }
    }
    return state
  }),
  setLogs: (logs) => set({ logs }),
  clearLogs: () => set({ logs: [] }),
}))