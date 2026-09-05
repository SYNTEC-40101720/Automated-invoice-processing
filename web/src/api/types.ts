export type JobStatus =
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'succeeded'
  | 'completed_with_warnings'
  | 'cancelled'
  | 'failed'

export type JobPhase =
  | 'scan'
  | 'process'
  | 'post_process'
  | 'local_audit'
  | 'ai_audit'
  | 'archive'
  | 'done'

export type JobTrigger = 'manual' | 'inbox' | 'email'

export interface JobStats {
  total: number
  success: number
  failure: number
  tax_issues: number
}

export interface JobResult {
  amount_map?: Record<string, string>
  tax_issues?: string[]
  merged?: string | null
  excel?: string | null
  audit?: {
    local_findings: AuditFinding[]
    ai_findings: AuditFinding[]
    report: string | null
  }
  archived?: number
}

export interface Job {
  id: string
  source_dir: string
  output_dir: string | null
  trigger: JobTrigger
  status: JobStatus
  phase: JobPhase
  progress: number
  message: string
  stats: JobStats
  started_at: string | null
  finished_at: string | null
  cancel_requested: boolean
  error_code: string | null
  error_message: string | null
  result: JobResult | null
}

export interface AuditFinding {
  source?: string
  file: string
  type: string
  issue: string
  suggestion?: string
}

export interface LogEntry {
  event_id: number
  occurred_at: string
  level: string
  message: string
}

export interface DomainEvent {
  event_id: number
  type: string
  occurred_at: string
  job_id: string | null
  payload: Record<string, unknown>
}

export interface HealthResponse {
  status: string
  version: string
  build: string
  mode: string
}

export interface UpdateResponse {
  current_version: string
  checked: boolean
  available: boolean
  latest_version: string | null
  release_url: string | null
  installable: boolean
  asset_name: string | null
  asset_size: number | null
}

export interface UpdateApplyResponse {
  status: string
  message: string
  latest_version: string | null
}

export interface UpdateProgress {
  status: 'idle' | 'downloading' | 'preparing' | 'starting' | 'failed' | 'busy' | 'unsupported' | 'unavailable'
  downloaded_bytes: number
  total_bytes: number | null
  progress_percent: number | null
  latest_version: string | null
  message: string
}

export interface BusinessSettings {
  target_tax_id: string
  max_workers: number
}

export interface EmailSettings {
  enabled: boolean
  imap_host: string
  imap_port: number
  username: string
  inbox_dir: string
  days_back: number
  poll_minutes: number
  auto_process: boolean
  senders: string[]
  keywords: string[]
  auth_code_configured: boolean
}

export interface AiSettings {
  enabled: boolean
  api_base: string
  model: string
  timeout: number
  api_key_configured: boolean
}

export interface SettingsResponse {
  business: BusinessSettings
  email: EmailSettings
  ai: AiSettings
}

export interface EmailPullResponse {
  pull: {
    downloaded: number
    new_files: string[]
    errors: string[]
    total_scanned: number
    job_error?: { code: string; message: string }
  }
  job: Job | null
}

export interface ToolDescriptor {
  kind: string
  title: string
  subtitle: string | null
  group: string
  glyph: string
  access_key: string | null
  supports_input: boolean
  mode: string
}

export interface ToolListResponse {
  tools: ToolDescriptor[]
}