/**
 * Evidence Module API Client
 * 证据整理模块全部端点封装
 */
import * as api from './client'

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

export type CaseType = 'injury' | 'death' | 'neonatal'

export interface MaterialResponse {
  id: string
  original_filename: string | null
  file_type: string
  minio_bucket: string | null
  minio_key: string | null
  file_size: number | null
  auto_category: string | null
  manual_category: string | null
  effective_category: string | null
  category_confidence: number | null
  ocr_status: string
  ocr_text: string | null
  ocr_result: Record<string, unknown>
  page_count: number | null
  selected_pages: number[]
  extracted_data: Record<string, unknown>
  manual_edit: Record<string, unknown>
  catalog_index: number | null
  catalog_title: string | null
  catalog_description: string | null
  proof_purpose: string | null
  fee_detail: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface StepResponse {
  id: number
  step_name: string
  status: string
  progress: number
  duration_ms: number | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export interface EvidenceCase {
  id: string
  case_name: string
  case_type: string
  is_minor: boolean
  status: string
  complaint_case_id: string | null
  plaintiff_info: Record<string, unknown>
  defendant_info: Record<string, unknown>
  catalog_data: Record<string, unknown>
  catalog_pdf_path: string | null
  analysis_result: Record<string, unknown>
  validation_result: Record<string, unknown>
  missing_items: Record<string, unknown>
  export_bundle_path: string | null
  export_files: Record<string, unknown>
  lawyer_info: { name: string; phone: string }[]
  metadata: Record<string, unknown>
  materials: MaterialResponse[]
  steps: StepResponse[]
  created_at: string
  updated_at: string
}

export interface EvidenceCaseListItem {
  id: string
  case_name: string
  case_type: string
  is_minor: boolean
  status: string
  created_at: string
  updated_at: string
}

export interface EvidenceCaseListResponse {
  items: EvidenceCaseListItem[]
  total: number
}

export interface ProgressResponse {
  case_id: string
  status: string
  current_step: string | null
  total_steps: number
  completed_steps: number
  progress_percent: number
  steps: StepResponse[]
}

export interface CatalogGroup {
  category: string
  category_name: string
  items: MaterialResponse[]
}

export interface CatalogResponse {
  case_id: string
  case_name: string
  case_type: string
  groups: CatalogGroup[]
  fee_summary: Record<string, unknown>
  total_amount: number
}

export interface AnalysisResponse {
  case_id: string
  status: string
  analysis_result: Record<string, unknown>
  validation_result: Record<string, unknown>
  missing_items: Record<string, unknown>
  error_message: string | null
}

export interface ProcessResponse {
  case_id: string
  message: string
  task_id: string | null
}

export interface ExportBundleResponse {
  case_id: string
  message: string
  bundle_path: string | null
}

// ─── API 调用 ─────────────────────────────────────────────────────────────────

/** 创建证据案件 */
export async function createCase(data: {
  case_name: string
  case_type: CaseType
  is_minor?: boolean
}): Promise<EvidenceCase> {
  return api.post<EvidenceCase>('/evidence/cases', data)
}

/** 获取案件列表 */
export async function listCases(page = 1, size = 20): Promise<EvidenceCaseListResponse> {
  return api.get<EvidenceCaseListResponse>('/evidence/cases', { page: String(page), size: String(size) })
}

/** 获取案件详情 */
export async function getCase(caseId: string): Promise<EvidenceCase> {
  return api.get<EvidenceCase>(`/evidence/cases/${caseId}`)
}

/** 更新案件基本信息 */
export async function updateCase(caseId: string, data: {
  case_name?: string
  case_type?: CaseType
  is_minor?: boolean
  lawyer_info?: { name: string; phone: string }[]
  defendant_phone?: string
}): Promise<EvidenceCase> {
  return api.put<EvidenceCase>(`/evidence/cases/${caseId}`, data)
}

/** 删除案件 */
export async function deleteCase(caseId: string): Promise<{ message: string }> {
  return api.del(`/evidence/cases/${caseId}`)
}

/** 上传原始素材 */
export async function uploadMaterials(caseId: string, files: File[]): Promise<MaterialResponse[]> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }
  const key = import.meta.env.VITE_API_KEY
  const h: Record<string, string> = {}
  if (key) h['X-API-Key'] = key

  const res = await fetch(`/api/v1/evidence/cases/${caseId}/upload`, {
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

/** 开始处理（OCR + 分类 + 目录生成） */
export async function processCase(caseId: string): Promise<ProcessResponse> {
  return api.post<ProcessResponse>(`/evidence/cases/${caseId}/process`)
}

/** 获取处理进度 */
export async function getProgress(caseId: string): Promise<ProgressResponse> {
  return api.get<ProgressResponse>(`/evidence/cases/${caseId}/progress`)
}

/** 获取证据目录 */
export async function getCatalog(caseId: string): Promise<CatalogResponse> {
  return api.get<CatalogResponse>(`/evidence/cases/${caseId}/catalog`)
}

/** 更新证据目录 */
export async function updateCatalog(caseId: string, items: {
  material_id: string
  manual_category?: string
  catalog_title?: string
  catalog_description?: string
  proof_purpose?: string
  sort_order?: number
}[]): Promise<void> {
  await api.put(`/evidence/cases/${caseId}/catalog`, { items })
}

/** 更新单个材料 */
export async function updateMaterial(caseId: string, materialId: string, data: {
  manual_category?: string
  catalog_title?: string
  catalog_description?: string
  proof_purpose?: string
  manual_edit?: Record<string, unknown>
}): Promise<MaterialResponse> {
  return api.put<MaterialResponse>(`/evidence/cases/${caseId}/materials/${materialId}`, data)
}

/** 删除材料 */
export async function deleteMaterial(caseId: string, materialId: string): Promise<void> {
  await api.del(`/evidence/cases/${caseId}/materials/${materialId}`)
}

/** 重试单个素材的 OCR */
export async function retryMaterialOcr(caseId: string, materialId: string): Promise<{ message: string }> {
  return api.post<{ message: string }>(`/evidence/cases/${caseId}/materials/${materialId}/retry-ocr`)
}

/** 导出目录 PDF（表格形式） */
export async function exportCatalogPdf(caseId: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/catalog/pdf`, '证据目录.pdf')
}

/** 导出证据材料 PDF（图片网格排版） */
export async function exportMaterialsPdf(caseId: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/materials/pdf`, '证据材料.pdf')
}

/** 开始分析 */
export async function analyzeCase(caseId: string): Promise<ProcessResponse> {
  return api.post<ProcessResponse>(`/evidence/cases/${caseId}/analyze`)
}

/** 获取分析结果 */
export async function getAnalysis(caseId: string): Promise<AnalysisResponse> {
  return api.get<AnalysisResponse>(`/evidence/cases/${caseId}/analysis`)
}

/** 导出立案证据 */
export async function exportFilingEvidence(caseId: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/export/filing-evidence`, '立案证据.docx')
}

/** 导出民事起诉状 */
export async function exportComplaint(caseId: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/export/complaint`, '民事起诉状.docx')
}

/** 导出司法鉴定申请书 */
export async function exportAppraisalApp(caseId: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/export/appraisal-app`, '司法鉴定申请书.docx')
}

/** 导出赔偿费用汇总 */
export async function exportCompensation(caseId: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/export/compensation`, '赔偿费用清单.xlsx')
}

/** 导出指定类型费用明细 */
export async function exportFeeTypeDetail(caseId: string, feeType: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/export/compensation/${feeType}`, `${feeType}.xlsx`)
}

/** 一键打包导出（同步下载 ZIP） */
export async function exportBundle(caseId: string): Promise<void> {
  await api.downloadBlob(`/evidence/cases/${caseId}/export/bundle/download`, '立案立档包.zip')
}

// ─── 多页文档三步工作流 ─────────────────────────────────────────────────────

export interface PagePreview {
  page: number
  width: number
  height: number
  thumbnail_b64: string
  note?: string
}

export interface PagePreviewResponse {
  material_id: string
  file_type: string
  total_pages: number
  selected_pages: number[]
  pages: PagePreview[]
}

/** 第一步：预览多页文档全部页面（缩略图） */
export async function previewMaterialPages(
  caseId: string,
  materialId: string
): Promise<PagePreviewResponse> {
  return api.get<PagePreviewResponse>(
    `/evidence/cases/${caseId}/materials/${materialId}/pages/preview`
  )
}

/** 第二步：选择需要处理的目标页（空列表=处理全部） */
export async function selectMaterialPages(
  caseId: string,
  materialId: string,
  selectedPages: number[]
): Promise<{
  material_id: string
  selected_pages: number[]
  message: string
}> {
  return api.post(
    `/evidence/cases/${caseId}/materials/${materialId}/pages/select`,
    { selected_pages: selectedPages }
  )
}

/** 第三步：提取指定页为高清图像 URL（用于查看或下载） */
export function getExtractPageUrl(
  caseId: string,
  materialId: string,
  pageNum: number,
  dpi = 150
): string {
  const base = import.meta.env.VITE_API_BASE || '/api/v1'
  return `${base}/evidence/cases/${caseId}/materials/${materialId}/pages/${pageNum}/extract?dpi=${dpi}`
}
