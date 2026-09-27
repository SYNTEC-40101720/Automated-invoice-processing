import { beforeEach, describe, expect, it } from 'vitest'
import type { DomainEvent, Job, LogEntry } from '../src/api/types'
import { useWorkbench } from '../src/stores/workbench'

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    source_dir: 'C:/inbox',
    output_dir: null,
    trigger: 'manual',
    status: 'queued',
    phase: 'scan',
    progress: 0,
    message: '任务已排队',
    stats: { total: 0, success: 0, failure: 0, tax_issues: 0 },
    started_at: null,
    finished_at: null,
    cancel_requested: false,
    error_code: null,
    error_message: null,
    result: null,
    ...overrides,
  }
}

function makeEvent(
  type: string,
  payload: Record<string, unknown>,
  overrides: Partial<DomainEvent> = {},
): DomainEvent {
  return {
    event_id: 1,
    type,
    occurred_at: '2026-09-27T00:00:00Z',
    job_id: 'job-1',
    payload,
    ...overrides,
  }
}

const initialState = useWorkbench.getState()

describe('workbench store', () => {
  beforeEach(() => {
    useWorkbench.setState(initialState, true)
  })

  it('默认视图为收件箱，未连接、无任务', () => {
    const state = useWorkbench.getState()
    expect(state.activeView).toBe('inbox')
    expect(state.connected).toBe(false)
    expect(state.currentJob).toBeNull()
    expect(state.logs).toEqual([])
  })

  it('job.snapshot 事件设置当前任务', () => {
    const job = makeJob()
    useWorkbench.getState().appendEvent(
      makeEvent('job.snapshot', job as unknown as Record<string, unknown>),
    )
    expect(useWorkbench.getState().currentJob).toEqual(job)
  })

  it('job.log_appended 追加日志并去重同一事件', () => {
    const store = useWorkbench.getState()
    store.appendEvent(
      makeEvent('job.log_appended', { level: 'info', message: 'hello' }, { event_id: 5 }),
    )
    store.appendEvent(
      makeEvent('job.log_appended', { level: 'info', message: 'hello' }, { event_id: 5 }),
    )
    const logs = useWorkbench.getState().logs
    expect(logs).toHaveLength(1)
    expect(logs[0].message).toBe('hello')
    expect(logs[0].event_id).toBe(5)
  })

  it('日志超出 500 条时裁剪最早条目', () => {
    for (let i = 1; i <= 502; i += 1) {
      useWorkbench.getState().appendEvent(
        makeEvent('job.log_appended', { level: 'info', message: `m${i}` }, { event_id: i }),
      )
    }
    const logs = useWorkbench.getState().logs
    expect(logs).toHaveLength(500)
    expect(logs[0].event_id).toBe(3)
    expect(logs.at(-1)?.event_id).toBe(502)
  })

  it('进度/状态/统计事件更新当前任务，且忽略其他任务的事件', () => {
    useWorkbench.getState().appendEvent(
      makeEvent('job.snapshot', makeJob() as unknown as Record<string, unknown>),
    )
    useWorkbench.getState().appendEvent(
      makeEvent('job.progress', { progress: 0.5, phase: 'process' }),
    )
    useWorkbench.getState().appendEvent(
      makeEvent('job.status_changed', { status: 'running', phase: 'process', message: '处理中' }),
    )
    useWorkbench.getState().appendEvent(
      makeEvent('job.stats_changed', { total: 4, success: 2, failure: 1, tax_issues: 0 }),
    )
    let job = useWorkbench.getState().currentJob!
    expect(job.progress).toBe(0.5)
    expect(job.status).toBe('running')
    expect(job.message).toBe('处理中')
    expect(job.stats).toEqual({ total: 4, success: 2, failure: 1, tax_issues: 0 })

    // 其他任务的事件不落地
    useWorkbench.getState().appendEvent(
      makeEvent('job.progress', { progress: 0.9 }, { job_id: 'other-job' }),
    )
    job = useWorkbench.getState().currentJob!
    expect(job.progress).toBe(0.5)
  })

  it('job.completed 挂载任务结果', () => {
    useWorkbench.getState().appendEvent(
      makeEvent('job.snapshot', makeJob() as unknown as Record<string, unknown>),
    )
    const result = { merged: 'merged.pdf', tax_issues: [] }
    useWorkbench.getState().appendEvent(makeEvent('job.completed', result))
    expect(useWorkbench.getState().currentJob?.result).toEqual(result)
  })

  it('mergeLogs 按事件 ID 排序合并并去重', () => {
    const entry = (id: number, message: string): LogEntry => ({
      event_id: id,
      occurred_at: '',
      level: 'info',
      message,
    })
    const store = useWorkbench.getState()
    store.setLogs([entry(2, 'two'), entry(1, 'one')])
    store.mergeLogs([entry(1, 'one-updated'), entry(3, 'three')])
    const logs = useWorkbench.getState().logs
    expect(logs.map((item) => item.message)).toEqual(['one-updated', 'two', 'three'])
  })

  it('toggleBottomPanel 切换底部面板', () => {
    const store = useWorkbench.getState()
    expect(store.bottomPanelOpen).toBe(false)
    store.toggleBottomPanel()
    expect(useWorkbench.getState().bottomPanelOpen).toBe(true)
    store.toggleBottomPanel()
    expect(useWorkbench.getState().bottomPanelOpen).toBe(false)
  })
})