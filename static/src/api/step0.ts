/**
 * Step0 预处理模块 API Client
 * 封装步骤0 全部端点
 */
import * as api from './client'
import { apiKeyOnlyHeaders, getAccessToken, setTokens, getRefreshToken } from './client'

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

export interface Step0MaterialOut {
  id: string
  original_filename: string | null
  file_type: string
  file_size: number | null
  ocr_status: string
  ocr_text: string | null
  auto_category: string | null
  manual_category: string | null
  effective_category: string | null
  category_confidence: number | null
  step0_fee_category: string | null
  step0_fee_category_cn: string | null
  step0_page_number: number | null
  step0_parent_material_id: string | null
  step0_corrected: boolean
  step0_needs_review: boolean
  step0_archived_key: string | null
  created_at: string
  updated_at: string
}

export interface Step0UploadResponse {
  case_id: string
  uploaded_count: number
  materials: Step0MaterialOut[]
}

export interface Step0PreprocessResponse {
  case_id: string
  message: string
  task_id: string | null
}

export interface Step0ProgressResponse {
  case_id: string
  total: number
  processed: number
  failed: number
  pending: number
  progress_percent: number
  step0_status: string
  category_summary: Record<string, number>
}

export interface Step0SummaryCategory {
  category: string
  category_cn: string
  count: number
}

export interface Step0SummaryResponse {
  case_id: string
  category_summary: Record<string, number>
  category_detail: Step0SummaryCategory[]
}

export interface Step0SkipResponse {
  case_id: string
  message: string
}

// ─── 10 类费用分类常量 ───────────────────────────────────────────────────────

export const STEP0_FEE_CATEGORIES: Record<string, string> = {
  fee_medical: '医疗费',
  fee_lost_income: '误工费',
  fee_nursing: '护理费',
  fee_hospital_food: '住院伙食补助费',
  fee_nutrition: '营养费',
  fee_compensation: '赔偿金',
  fee_dependent: '被扶养人生活费',
  fee_transport: '交通住宿费',
  fee_appraisal: '鉴定费',
  fee_mental: '精神损害抚慰金',
}

export const STEP0_CATEGORY_OPTIONS = Object.entries(STEP0_FEE_CATEGORIES).map(
  ([key, label]) => ({ label, value: key })
)

// ─── API 调用 ─────────────────────────────────────────────────────────────────

/** 上传原始素材 */
export async function uploadRawMaterials(
  caseId: string,
  files: File[]
): Promise<Step0UploadResponse> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }

  const url = `/api/v1/evidence/cases/${caseId}/step0/upload`
  const doFetch = () => fetch(url, {
    method: 'POST',
    headers: apiKeyOnlyHeaders(),
    body: form,
  })

  let res = await doFetch()

  // 401 → 尝试刷新 token 后重试
  if (res.status === 401) {
    const refresh = getRefreshToken()
    if (refresh) {
      try {
        const refreshRes = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        })
        if (refreshRes.ok) {
          const data = await refreshRes.json()
          setTokens(data.access_token, data.refresh_token)
          res = await doFetch()
        }
      } catch {
        // ignore
      }
    }
    if (!res.ok) {
      throw new Error('登录已过期，请重新登录')
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `Upload failed: HTTP ${res.status}`)
  }

  return res.json()
}

/** 启动预处理 */
export async function startPreprocess(caseId: string): Promise<Step0PreprocessResponse> {
  return api.post<Step0PreprocessResponse>(`/evidence/cases/${caseId}/step0/preprocess`)
}

/** 获取预处理进度 */
export async function getStep0Progress(caseId: string): Promise<Step0ProgressResponse> {
  return api.get<Step0ProgressResponse>(`/evidence/cases/${caseId}/step0/progress`)
}

/** 获取步骤0 素材列表 */
export async function getStep0Materials(caseId: string): Promise<Step0MaterialOut[]> {
  return api.get<Step0MaterialOut[]>(`/evidence/cases/${caseId}/step0/materials`)
}

/** 手动纠正分类 */
export async function correctCategory(
  caseId: string,
  materialId: string,
  newCategory: string
): Promise<Step0MaterialOut> {
  return api.put<Step0MaterialOut>(
    `/evidence/cases/${caseId}/step0/materials/${materialId}/category`,
    { new_category: newCategory }
  )
}

/** 跳过步骤0 */
export async function skipStep0(caseId: string): Promise<Step0SkipResponse> {
  return api.post<Step0SkipResponse>(`/evidence/cases/${caseId}/step0/skip`)
}

/** 获取分类汇总 */
export async function getStep0Summary(caseId: string): Promise<Step0SummaryResponse> {
  return api.get<Step0SummaryResponse>(`/evidence/cases/${caseId}/step0/summary`)
}

/** 获取缩略图 URL（直接返回 API 路径，用于 <img> src） */
export function getThumbnailUrl(caseId: string, materialId: string): string {
  return `/api/v1/evidence/cases/${caseId}/step0/materials/${materialId}/thumbnail`
}
