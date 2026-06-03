import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '@/api/client'

export type CaseType = 'injury' | 'death' | 'neonatal'
export type SlotName = 'plaintiff' | 'guardian' | 'defendant' | 'fee' | 'medical' | 'appraisal' | 'staff_error' | 'evidence'

export interface ComplaintUpload {
  id: string
  slot: SlotName
  file_type: string
  original_filename: string | null
  ocr_status: string
  ocr_result: Record<string, unknown>
  extracted_data: Record<string, unknown>
  manual_edit: Record<string, unknown>
  created_at: string
}

export interface ComplaintStep {
  id: number
  step_name: string
  status: string
  duration_ms: number | null
  error_message: string | null
}

export interface ComplaintCase {
  case_id: string
  case_type: CaseType
  is_minor: boolean
  status: string
  generated_doc_path: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  uploads: ComplaintUpload[]
  steps: ComplaintStep[]
}

export interface SlotResult {
  slot: SlotName
  ocr_status: string
  extracted_data: Record<string, unknown>
  manual_edit: Record<string, unknown>
  effective_data: Record<string, unknown>
}

export const useComplaintStore = defineStore('complaint', () => {
  const currentCase = ref<ComplaintCase | null>(null)
  const caseLoading = ref(false)
  const slotResults = ref<SlotResult[]>([])
  const resultsLoading = ref(false)
  const generating = ref(false)

  const currentStep = ref(0)

  const isOcrComplete = computed(() => {
    if (!currentCase.value) return false
    const uploads = currentCase.value.uploads
    if (uploads.length === 0) return false
    return uploads.every(u => ['completed', 'failed', 'skipped'].includes(u.ocr_status))
  })

  const isDocReady = computed(() => {
    return currentCase.value?.status === 'completed' && !!currentCase.value.generated_doc_path
  })

  async function createCase(caseType: CaseType, isMinor: boolean) {
    caseLoading.value = true
    try {
      const res = await api.post<ComplaintCase>('/complaint/cases', {
        case_type: caseType,
        is_minor: isMinor,
      })
      currentCase.value = res
      currentStep.value = 1
      return res
    } finally {
      caseLoading.value = false
    }
  }

  async function fetchCase(caseId: string) {
    caseLoading.value = true
    try {
      currentCase.value = await api.get<ComplaintCase>(`/complaint/cases/${caseId}`)
    } finally {
      caseLoading.value = false
    }
  }

  async function uploadFile(caseId: string, slot: SlotName, file: File) {
    const form = new FormData()
    form.append('slot', slot)
    form.append('file', file)

    const key = import.meta.env.VITE_API_KEY
    const h: Record<string, string> = {}
    if (key) h['X-API-Key'] = key

    const res = await fetch(`/api/v1/complaint/cases/${caseId}/upload`, {
      method: 'POST',
      headers: h,
      body: form,
    })

    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body?.detail || `Upload failed: HTTP ${res.status}`)
    }

    const uploadResult: ComplaintUpload = await res.json()
    if (currentCase.value) {
      const idx = currentCase.value.uploads.findIndex(u => u.id === uploadResult.id)
      if (idx >= 0) {
        currentCase.value.uploads[idx] = uploadResult
      } else {
        currentCase.value.uploads.push(uploadResult)
      }
    }
    return uploadResult
  }

  async function uploadManualInput(caseId: string, slot: SlotName, text: string) {
    const form = new FormData()
    form.append('slot', slot)
    form.append('manual_input', text)

    const key = import.meta.env.VITE_API_KEY
    const h: Record<string, string> = {}
    if (key) h['X-API-Key'] = key

    const res = await fetch(`/api/v1/complaint/cases/${caseId}/upload`, {
      method: 'POST',
      headers: h,
      body: form,
    })

    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body?.detail || `Upload failed: HTTP ${res.status}`)
    }

    const uploadResult: ComplaintUpload = await res.json()
    if (currentCase.value) {
      const idx = currentCase.value.uploads.findIndex(u => u.id === uploadResult.id)
      if (idx >= 0) {
        currentCase.value.uploads[idx] = uploadResult
      } else {
        currentCase.value.uploads.push(uploadResult)
      }
    }
    return uploadResult
  }

  async function startOcr(caseId: string) {
    const res = await api.post<{ case_id: string; message: string; processing_slots: string[] }>(
      `/complaint/cases/${caseId}/start-ocr`
    )
    return res
  }

  async function fetchResults(caseId: string) {
    resultsLoading.value = true
    try {
      const res = await api.get<{ case_id: string; case_type: string; is_minor: boolean; slots: SlotResult[] }>(
        `/complaint/cases/${caseId}/results`
      )
      slotResults.value = res.slots
    } finally {
      resultsLoading.value = false
    }
  }

  async function updateResults(caseId: string, slots: { slot: string; manual_edit: Record<string, unknown> }[]) {
    await api.put(`/complaint/cases/${caseId}/results`, { slots })
  }

  async function generateDoc(caseId: string) {
    generating.value = true
    try {
      const res = await api.post<{ case_id: string; message: string; status: string }>(
        `/complaint/cases/${caseId}/generate`
      )
      return res
    } finally {
      generating.value = false
    }
  }

  async function downloadDoc(caseId: string) {
    await api.downloadBlob(`/complaint/cases/${caseId}/download`, '民事起诉状.docx')
  }

  let pollTimer: ReturnType<typeof setInterval> | null = null

  function startPolling(caseId: string, interval = 3000) {
    fetchCase(caseId)
    pollTimer = setInterval(async () => {
      await fetchCase(caseId)
      if (isOcrComplete.value && pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
    }, interval)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function reset() {
    currentCase.value = null
    slotResults.value = []
    currentStep.value = 0
    generating.value = false
    stopPolling()
  }

  return {
    currentCase, caseLoading, slotResults, resultsLoading,
    generating, currentStep, isOcrComplete, isDocReady,
    createCase, fetchCase, uploadFile, uploadManualInput,
    startOcr, fetchResults, updateResults, generateDoc,
    downloadDoc, startPolling, stopPolling, reset,
  }
})
