/**
 * ScanStruct API Client
 * 基于 fetch 封装，自动注入 JWT Bearer token（或 X-API-Key），统一错误处理
 */

const BASE = '/api/v1'

// ─── Token 管理 ───

const ACCESS_TOKEN_KEY = 'ss_access_token'
const REFRESH_TOKEN_KEY = 'ss_refresh_token'

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, access)
  localStorage.setItem(REFRESH_TOKEN_KEY, refresh)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

export function isLoggedIn(): boolean {
  return !!getAccessToken()
}

// ─── 记住密码 / 自动登录 ───

const REMEMBER_EMAIL_KEY = 'ss_remember_email'
const REMEMBER_PASSWORD_KEY = 'ss_remember_password'
const AUTO_LOGIN_KEY = 'ss_auto_login'

/** 保存邮箱到 localStorage（不再保存密码，避免明文泄露风险） */
export function saveCredentials(email: string, _password: string): void {
  localStorage.setItem(REMEMBER_EMAIL_KEY, email)
  // 密码不持久化 — 安全第一
}

/** 清除保存的邮箱+密码 */
export function clearSavedCredentials(): void {
  localStorage.removeItem(REMEMBER_EMAIL_KEY)
  localStorage.removeItem(REMEMBER_PASSWORD_KEY)
}

/** 获取保存的邮箱 */
export function getSavedEmail(): string {
  return localStorage.getItem(REMEMBER_EMAIL_KEY) || ''
}

/** 获取保存的密码 — 出于安全考虑不再持久化密码，始终返回空 */
export function getSavedPassword(): string {
  return ''
}

/** 设置/清除自动登录标记 */
export function setAutoLogin(enabled: boolean): void {
  if (enabled) {
    localStorage.setItem(AUTO_LOGIN_KEY, 'true')
  } else {
    localStorage.removeItem(AUTO_LOGIN_KEY)
  }
}

/** 是否启用了自动登录 */
export function isAutoLogin(): boolean {
  return localStorage.getItem(AUTO_LOGIN_KEY) === 'true'
}

/** 是否有保存的凭据 */
export function hasSavedCredentials(): boolean {
  return !!localStorage.getItem(REMEMBER_EMAIL_KEY) && !!localStorage.getItem(REMEMBER_PASSWORD_KEY)
}

// ─── Auth API ───

export interface UserInfo {
  id: string
  email: string
  display_name: string
  role: string
  tenant_id: string
  tenant_name: string
  plan: string
  features: Record<string, boolean> | null
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserInfo
}

async function refreshToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false

  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!res.ok) return false
    const data: TokenResponse = await res.json()
    setTokens(data.access_token, data.refresh_token)
    return true
  } catch {
    return false
  }
}

// ─── 请求头 ───

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }

  // 优先 JWT
  const token = getAccessToken()
  if (token) {
    h['Authorization'] = `Bearer ${token}`
    return h
  }

  // 兜底 API Key（兼容旧模式）
  const key = import.meta.env.VITE_API_KEY
  if (key) {
    h['X-API-Key'] = key
  }
  return h
}

export function apiKeyOnlyHeaders(): Record<string, string> {
  // FormData/文件上传等场景：不设 Content-Type，只传 API Key
  const h: Record<string, string> = {}
  const token = getAccessToken()
  if (token) {
    h['Authorization'] = `Bearer ${token}`
  } else {
    const key = import.meta.env.VITE_API_KEY
    if (key) h['X-API-Key'] = key
  }
  return h
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers as Record<string, string> || {}) },
  })

  // 401 → 尝试刷新 token 后重试一次
  if (res.status === 401) {
    const refreshed = await refreshToken()
    if (refreshed) {
      const retryRes = await fetch(url, {
        ...options,
        headers: { ...authHeaders(), ...(options.headers as Record<string, string> || {}) },
      })
      if (retryRes.ok) {
        const text = await retryRes.text()
        return text ? JSON.parse(text) as T : undefined as unknown as T
      }
    }
    // 刷新失败 → 清理 token，跳转登录
    clearTokens()
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    throw new Error('登录已过期，请重新登录')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    let detail = body?.detail || `HTTP ${res.status}`
    // FastAPI 422 验证错误 detail 是数组，需提取 msg
    if (Array.isArray(detail)) {
      detail = detail.map((e: { msg?: string; message?: string }) => e.msg || e.message || JSON.stringify(e)).join('; ')
    } else if (typeof detail === 'object') {
      detail = (detail as { message?: string }).message || JSON.stringify(detail)
    }
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
  const res = await fetch(`${BASE}${path}`, { headers: apiKeyOnlyHeaders() })

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

  const res = await fetch(`${BASE}/scans/upload`, {
    method: 'POST',
    headers: apiKeyOnlyHeaders(),
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

  const res = await fetch(`${BASE}/scans/batch-upload`, {
    method: 'POST',
    headers: apiKeyOnlyHeaders(),
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
  const res = await fetch(`${BASE}/templates/`, {
    method: 'POST',
    headers: apiKeyOnlyHeaders(),
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
  const res = await fetch(`${BASE}/templates/${id}`, {
    method: 'PUT',
    headers: apiKeyOnlyHeaders(),
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
  const h = authHeaders()

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

// ─── Admin API 类型定义 ───

export interface UserListItem {
  id: string
  email: string
  display_name: string
  role: string
  is_active: boolean
  last_login: string | null
  created_at: string
  tenant_id: string | null
  tenant_name: string | null
}

export interface UserResponse {
  id: string
  email: string
  display_name: string
  role: string
  is_active: boolean
  tenant_id: string
}

export interface UserCreateRequest {
  email: string
  display_name: string
  password: string
  role: 'member' | 'tenant_admin'
  tenant_id?: string
}

export interface UserUpdateRequest {
  display_name?: string
  role?: 'member' | 'tenant_admin'
  is_active?: boolean
  password?: string
  tenant_id?: string
}

export interface TenantListItem {
  id: string
  name: string
  plan: string
  max_cases: number
  max_concurrent: number
  storage_quota_mb: number
  storage_used_mb: number
  status: string
  user_count: number
  case_count: number
  created_at: string
  features: Record<string, boolean> | null
}

export interface TenantDetail {
  id: string
  name: string
  plan: string
  max_cases: number
  max_concurrent: number
  storage_quota_mb: number
  storage_used_mb: number
  status: string
  created_at: string
  updated_at: string | null
  user_count: number
  case_count: number
  last_active: string | null
  features: Record<string, boolean> | null
}

export interface TenantUpdateRequest {
  name?: string
  plan?: 'free' | 'pro' | 'enterprise'
  max_cases?: number
  max_concurrent?: number
  storage_quota_mb?: number
  status?: 'active' | 'suspended'
  features?: Record<string, boolean> | null
}

export interface TenantCreateRequest {
  name: string
  plan: 'free' | 'pro' | 'enterprise'
  max_cases: number
  max_concurrent: number
  storage_quota_mb: number
  status: 'active' | 'suspended'
  features?: Record<string, boolean> | null
}

export interface TenantNameItem {
  id: string
  name: string
}

export interface UsageResponse {
  tenant: {
    name: string
    plan: string
    max_cases: number
  }
  usage: {
    evidence_cases: number
    scan_tasks: number
    storage_used_mb: number
    storage_quota_mb: number
    active_users: number
    concurrent_used: number
    concurrent_max: number
  }
}

// ─── Admin API 调用方法 ───

export async function getUsage(): Promise<UsageResponse> {
  return get<UsageResponse>('/admin/usage')
}

export async function listUsers(
  page: number = 1,
  size: number = 20
): Promise<PaginatedResponse<UserListItem>> {
  return get<PaginatedResponse<UserListItem>>('/admin/users', {
    page: String(page),
    size: String(size),
  })
}

export async function createUser(payload: UserCreateRequest): Promise<UserResponse> {
  return post<UserResponse>('/admin/users', payload)
}

export async function updateUser(
  userId: string,
  payload: UserUpdateRequest
): Promise<UserResponse> {
  return put<UserResponse>(`/admin/users/${userId}`, payload)
}

export async function disableUser(userId: string): Promise<MessageResponse> {
  return del<MessageResponse>(`/admin/users/${userId}`)
}

export async function listTenants(
  page: number = 1,
  size: number = 20
): Promise<PaginatedResponse<TenantListItem>> {
  return get<PaginatedResponse<TenantListItem>>('/admin/tenants', {
    page: String(page),
    size: String(size),
  })
}

export async function getTenantDetail(tenantId: string): Promise<TenantDetail> {
  return get<TenantDetail>(`/admin/tenants/${tenantId}`)
}

export async function updateTenant(
  tenantId: string,
  payload: TenantUpdateRequest
): Promise<TenantDetail> {
  return put<TenantDetail>(`/admin/tenants/${tenantId}`, payload)
}

export async function createTenant(payload: TenantCreateRequest): Promise<TenantDetail> {
  return post<TenantDetail>('/admin/tenants', payload)
}

export async function listTenantNames(): Promise<TenantNameItem[]> {
  return get<TenantNameItem[]>('/auth/tenants')
}

// ─── 个人信息 / 密码管理 ───

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await put('/auth/change-password', { old_password: oldPassword, new_password: newPassword })
}

export async function updateProfile(displayName: string): Promise<UserInfo> {
  return put<UserInfo>('/auth/profile', { display_name: displayName })
}
