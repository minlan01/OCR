/**
 * ScanStruct API Client
 * 基于 fetch 封装，自动注入 X-API-Key，统一错误处理
 */

const BASE = '/api/v1'

function headers(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const key = import.meta.env.VITE_API_KEY
  if (key) {
    h['X-API-Key'] = key
  }
  return h
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: { ...headers(), ...(options.headers as Record<string, string> || {}) },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = body?.detail || `HTTP ${res.status}`
    throw new Error(detail)
  }

  // 204 / 空响应
  const text = await res.text()
  if (!text) return undefined as unknown as T

  return JSON.parse(text) as T
}

export async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return request<T>(`${BASE}${path}${qs}`)
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(`${BASE}${path}`, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
}

export async function del<T = void>(path: string): Promise<T> {
  return request<T>(`${BASE}${path}`, { method: 'DELETE' })
}

export async function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(`${BASE}${path}`, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  })
}

/**
 * 下载文件（blob 响应，非 JSON）
 * 用于下载 Word 文档等二进制文件
 */
export async function downloadBlob(path: string, filename: string): Promise<void> {
  const h: Record<string, string> = {}
  const key = import.meta.env.VITE_API_KEY
  if (key) h['X-API-Key'] = key

  const res = await fetch(`${BASE}${path}`, { headers: h })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `Download failed: HTTP ${res.status}`)
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export async function uploadPDF(
  file: File,
  metadata?: { scanner_id?: string; callback_url?: string; metadata?: object }
): Promise<ScanUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  if (metadata?.scanner_id) form.append('scanner_id', metadata.scanner_id)
  if (metadata?.callback_url) form.append('callback_url', metadata.callback_url)
  if (metadata?.metadata) form.append('metadata', JSON.stringify(metadata.metadata))

  const key = import.meta.env.VITE_API_KEY
  const h: Record<string, string> = {}
  if (key) h['X-API-Key'] = key

  const res = await fetch(`${BASE}/scans/upload`, {
    method: 'POST',
    headers: h,
    body: form,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `Upload failed: HTTP ${res.status}`)
  }

  return res.json()
}

export async function batchUploadPDF(
  files: File[],
  metadata?: { scanner_id?: string; callback_url?: string }
): Promise<BatchUploadResult> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }
  if (metadata?.scanner_id) form.append('scanner_id', metadata.scanner_id)
  if (metadata?.callback_url) form.append('callback_url', metadata.callback_url)

  const key = import.meta.env.VITE_API_KEY
  const h: Record<string, string> = {}
  if (key) h['X-API-Key'] = key

  const res = await fetch(`${BASE}/scans/batch-upload`, {
    method: 'POST',
    headers: h,
    body: form,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `Batch upload failed: HTTP ${res.status}`)
  }

  return res.json()
}

// ─── API 类型定义 ───

export interface AdminStats {
  total_tasks: number
  today_tasks: number
  failed_tasks: number
  avg_confidence: number | null
  by_status: Record<string, number>
}

export interface QueueItem {
  task_id: string
  filename: string
  status: string
  priority: number
  created_at: string | null
}

export interface AdminQueue {
  queue_length: number
  items: QueueItem[]
}

export interface PaginatedResponse<T> {
  items: T[]
  page: number
  size: number
  total: number
}

export interface ScanTaskSummary {
  task_id: string
  filename: string
  status: string
  page_count: number | null
  confidence_avg: number | null
  created_at: string
  completed_at: string | null
  error_code: string | null
}

export interface TaskStep {
  id: number
  step_name: string
  status: string
  duration_ms: number | null
  retry_count: number
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ScanFile {
  id: number
  file_type: string
  page_no: number | null
  bucket: string
  object_key: string
  size_bytes: number | null
}

export interface ScanTaskDetail {
  task_id: string
  filename: string
  scanner_id: string | null
  source_type: string
  status: string
  priority: number
  file_size: number | null
  file_md5: string | null
  page_count: number | null
  confidence_avg: number | null
  structure_score: number | null
  table_count: number
  heading_count: number
  paragraph_count: number
  callback_url: string | null
  callback_status: string | null
  error_code: string | null
  error_message: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
  steps: TaskStep[]
  files: ScanFile[]
}

export interface ScanUploadResponse {
  task_id: string
  status: string
  filename: string
  message?: string
}

export interface BatchProcessResult {
  dispatched: string[]
  skipped: { task_id: string; reason: string }[]
  failed: { task_id: string; reason: string }[]
}

export interface BatchUploadResult {
  uploaded: ScanUploadResponse[]
  skipped: { filename: string; reason: string }[]
  failed: { filename: string; reason: string }[]
}

export async function batchProcess(taskIds: string[]): Promise<BatchProcessResult> {
  return post<BatchProcessResult>('/scans/process', { task_ids: taskIds })
}

export interface MessageResponse {
  message: string
  success?: boolean
}

export interface TemplateListItem {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface TemplateResponse {
  id: string
  name: string
  description: string | null
  schema_def: Record<string, unknown>
  rules_md: string | null
  generator_code: string | null
  sample_output: string | null
  has_reference_doc: boolean
  created_at: string
  updated_at: string
}

export async function listTemplates(): Promise<TemplateListItem[]> {
  return get<TemplateListItem[]>('/templates/')
}

export async function getTemplate(id: string): Promise<TemplateResponse> {
  return get<TemplateResponse>(`/templates/${id}`)
}

export async function createTemplate(form: FormData): Promise<TemplateResponse> {
  const key = import.meta.env.VITE_API_KEY
  const h: Record<string, string> = {}
  if (key) h['X-API-Key'] = key

  const res = await fetch(`${BASE}/templates/`, {
    method: 'POST',
    headers: h,
    body: form,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `Create template failed: HTTP ${res.status}`)
  }

  return res.json()
}

export async function deleteTemplate(id: string): Promise<void> {
  await del(`/templates/${id}`)
}

export async function updateTemplate(id: string, form: FormData): Promise<TemplateResponse> {
  const key = import.meta.env.VITE_API_KEY
  const h: Record<string, string> = {}
  if (key) h['X-API-Key'] = key

  const res = await fetch(`${BASE}/templates/${id}`, {
    method: 'PUT',
    headers: h,
    body: form,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `Update template failed: HTTP ${res.status}`)
  }

  return res.json()
}

export async function exportWithTemplate(
  taskId: string,
  templateId: string,
  filename: string
): Promise<void> {
  const key = import.meta.env.VITE_API_KEY
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (key) h['X-API-Key'] = key

  const res = await fetch(`${BASE}/templates/${taskId}/export`, {
    method: 'POST',
    headers: h,
    body: JSON.stringify({ template_id: templateId }),
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `Export failed: HTTP ${res.status}`)
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
