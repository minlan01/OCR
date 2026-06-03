import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '@/api/client'
import type {
  AdminStats,
  PaginatedResponse,
  ScanTaskSummary,
  ScanTaskDetail,
  ScanUploadResponse,
  BatchProcessResult,
  BatchUploadResult,
} from '@/api/client'

export const useScanStore = defineStore('scan', () => {
  // ─── 状态 ───

  const stats = ref<AdminStats | null>(null)
  const statsLoading = ref(false)

  const taskList = ref<ScanTaskSummary[]>([])
  const taskTotal = ref(0)
  const taskPage = ref(1)
  const taskSize = ref(20)
  const taskLoading = ref(false)

  const currentDetail = ref<ScanTaskDetail | null>(null)
  const detailLoading = ref(false)

  const uploadProgress = ref(false)

  // ─── 轮询 ───

  let statsTimer: ReturnType<typeof setInterval> | null = null
  let detailTimer: ReturnType<typeof setInterval> | null = null

  const isTaskProcessing = computed(() => {
    if (!currentDetail.value) return false
    return ['received', 'pending', 'processing'].includes(currentDetail.value.status)
  })

  // ─── Dashboard ───

  async function fetchStats() {
    statsLoading.value = true
    try {
      stats.value = await api.get<AdminStats>('/admin/stats')
    } finally {
      statsLoading.value = false
    }
  }

  function startStatsPolling(interval = 10_000) {
    fetchStats()
    statsTimer = setInterval(fetchStats, interval)
  }

  function stopStatsPolling() {
    if (statsTimer) {
      clearInterval(statsTimer)
      statsTimer = null
    }
  }

  // ─── 任务列表 ───

  async function fetchTasks(params?: {
    page?: number
    size?: number
    status?: string
    scanner_id?: string
    sort_by?: string
    sort_order?: string
  }) {
    taskLoading.value = true
    try {
      const p: Record<string, string> = {
        page: String(params?.page ?? taskPage.value),
        size: String(params?.size ?? taskSize.value),
      }
      if (params?.status) p.status = params.status
      if (params?.scanner_id) p.scanner_id = params.scanner_id
      if (params?.sort_by) p.sort_by = params.sort_by
      if (params?.sort_order) p.sort_order = params.sort_order

      const res = await api.get<PaginatedResponse<ScanTaskSummary>>('/scans', p)
      taskList.value = res.items
      taskTotal.value = res.total
      taskPage.value = res.page
    } finally {
      taskLoading.value = false
    }
  }

  // ─── 任务详情 ───

  async function fetchDetail(taskId: string) {
    detailLoading.value = true
    try {
      currentDetail.value = await api.get<ScanTaskDetail>(`/scans/${taskId}`)
    } finally {
      detailLoading.value = false
    }
  }

  function startDetailPolling(taskId: string, interval = 3_000) {
    fetchDetail(taskId)
    detailTimer = setInterval(async () => {
      await fetchDetail(taskId)
      // 任务完成/失败后停止轮询
      if (!isTaskProcessing.value && detailTimer) {
        clearInterval(detailTimer)
        detailTimer = null
      }
    }, interval)
  }

  function stopDetailPolling() {
    if (detailTimer) {
      clearInterval(detailTimer)
      detailTimer = null
    }
  }

  // ─── 操作 ───

  async function retryTask(taskId: string, force = false) {
    const params: Record<string, string> = {}
    if (force) params.force = 'true'
    await api.post(`/scans/${taskId}/retry${force ? '?force=true' : ''}`)
  }

  async function deleteTask(taskId: string, keepRaw = false) {
    await api.del(`/scans/${taskId}${keepRaw ? '?keep_raw=true' : ''}`)
  }

  async function getTaskResult(taskId: string): Promise<unknown> {
    return api.get(`/scans/${taskId}/result`)
  }

  async function downloadWord(taskId: string, filename: string): Promise<void> {
    const safeName = filename.replace(/\.pdf$/i, '') + '_结构化.docx'
    await api.downloadBlob(`/scans/${taskId}/download?format=docx`, safeName)
  }

  async function uploadFile(
    file: File,
    meta?: { scanner_id?: string; callback_url?: string; metadata?: object }
  ): Promise<ScanUploadResponse> {
    uploadProgress.value = true
    try {
      return await api.uploadPDF(file, meta)
    } finally {
      uploadProgress.value = false
    }
  }

  async function batchUploadFiles(
    files: File[],
    meta?: { scanner_id?: string; callback_url?: string }
  ): Promise<BatchUploadResult> {
    uploadProgress.value = true
    try {
      return await api.batchUploadPDF(files, meta)
    } finally {
      uploadProgress.value = false
    }
  }

  async function fetchUnprocessedTasks(params?: {
    page?: number
    size?: number
  }): Promise<PaginatedResponse<ScanTaskSummary>> {
    const p: Record<string, string> = {
      page: String(params?.page ?? 1),
      size: String(params?.size ?? 50),
      status: 'received',
      sort_by: 'created_at',
      sort_order: 'desc',
    }
    return api.get<PaginatedResponse<ScanTaskSummary>>('/scans', p)
  }

  async function batchProcessTasks(taskIds: string[]): Promise<BatchProcessResult> {
    return api.batchProcess(taskIds)
  }

  return {
    // state
    stats, statsLoading,
    taskList, taskTotal, taskPage, taskSize, taskLoading,
    currentDetail, detailLoading,
    uploadProgress,
    isTaskProcessing,
    // actions
    fetchStats, startStatsPolling, stopStatsPolling,
    fetchTasks,
    fetchDetail, startDetailPolling, stopDetailPolling,
    retryTask, deleteTask, getTaskResult, downloadWord,
    uploadFile, batchUploadFiles,
    fetchUnprocessedTasks, batchProcessTasks,
  }
})
