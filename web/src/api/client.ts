import type {
  AiSettings,
  BusinessSettings,
  DomainEvent,
  EmailPullResponse,
  EmailSettings,
  HealthResponse,
  Job,
  LogEntry,
  SettingsResponse,
  UpdateApplyResponse,
  UpdateProgress,
  UpdateResponse,
  ToolListResponse,
  RuntimeJobResponse,
} from './types'

const apiBase = import.meta.env.VITE_API_BASE_URL ?? ''
const localToken = import.meta.env.VITE_LOCAL_TOKEN
  ?? new URLSearchParams(window.location.search).get('token')
  ?? ''

function requestHeaders(): HeadersInit {
  return localToken ? { 'X-Local-Token': localToken } : {}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, {
    ...init,
    headers: {
      ...requestHeaders(),
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message ?? `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<HealthResponse>('/system/health'),
  tools: () => request<ToolListResponse>('/tools'),
  updateCheck: () => request<UpdateResponse>('/system/update'),
  applyUpdate: () => request<UpdateApplyResponse>('/system/update/apply', { method: 'POST' }),
  updateProgress: () => request<UpdateProgress>('/system/update/progress'),
  currentJob: () => request<Job | null>('/jobs/current'),
  scanDirectory: (sourceDir: string) => request<{ source_dir: string; pdf_count: number }>('/jobs/scan', {
    method: 'POST', body: JSON.stringify({ source_dir: sourceDir }),
  }),
  startJob: async (sourceDir: string) => {
    const runtimeJob = await request<RuntimeJobResponse>('/jobs/start', {
      method: 'POST',
      body: JSON.stringify({
        kind: 'invoice_processing',
        input: { source_dir: sourceDir, trigger: 'manual' },
      }),
    })
    return {
      id: runtimeJob.id,
      source_dir: sourceDir,
      output_dir: null,
      trigger: 'manual' as const,
      status: runtimeJob.status,
      phase: 'scan' as const,
      progress: runtimeJob.progress / 100,
      message: runtimeJob.message,
      stats: { total: 0, success: 0, failure: 0, tax_issues: 0 },
      started_at: runtimeJob.created_at,
      finished_at: null,
      cancel_requested: false,
      error_code: null,
      error_message: null,
      result: null,
    }
  },
  cancelRuntimeJob: () => request<RuntimeJobResponse>('/jobs/cancel', {
    method: 'POST',
  }),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, {
    method: 'POST',
  }),
  logs: (jobId: string, afterEventId = 0) => request<{
    items: LogEntry[]
    next_event_id: number | null
  }>(
    `/jobs/${jobId}/logs?after_event_id=${afterEventId}`,
  ),
  settings: () => request<SettingsResponse>('/settings'),
  updateSettings: (body: {
    business: BusinessSettings
    email: Record<string, unknown>
    ai: Record<string, unknown>
  }) => request<SettingsResponse>('/settings', {
    method: 'PATCH', body: JSON.stringify(body),
  }),
  updateBusiness: (body: Partial<BusinessSettings>) => request<BusinessSettings>('/settings/business', {
    method: 'PATCH', body: JSON.stringify(body),
  }),
  updateEmail: (body: Record<string, unknown>) => request<EmailSettings>('/settings/email', {
    method: 'PATCH', body: JSON.stringify(body),
  }),
  updateAi: (body: Record<string, unknown>) => request<AiSettings>('/settings/ai', {
    method: 'PATCH', body: JSON.stringify(body),
  }),
  testEmail: (body: Record<string, unknown>) => request<{ ok: boolean; message: string }>('/settings/email/test', {
    method: 'POST', body: JSON.stringify(body),
  }),
  testAi: (body: Record<string, unknown>) => request<{ ok: boolean; message: string }>('/settings/ai/test', {
    method: 'POST', body: JSON.stringify(body),
  }),
  pullEmail: () => request<EmailPullResponse>('/email/pull', { method: 'POST' }),
}

export function connectEvents(
  onEvent: (event: DomainEvent) => void,
  onStatus: (connected: boolean) => void,
): () => void {
  const base = apiBase || window.location.origin
  const url = new URL('/api/v1/events', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  if (localToken) url.searchParams.set('token', localToken)
  const socket = new WebSocket(url.toString())
  socket.addEventListener('open', () => onStatus(true))
  socket.addEventListener('close', () => onStatus(false))
  socket.addEventListener('error', () => onStatus(false))
  socket.addEventListener('message', (message) => {
    try {
      onEvent(JSON.parse(message.data) as DomainEvent)
    } catch {
      // 丢弃非 JSON 心跳，保持连接状态即可。
    }
  })
  return () => socket.close()
}