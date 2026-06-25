<template>
  <n-card title="OCR 识别进度" size="small">
    <n-space vertical :size="12">
      <n-spin :show="store.caseLoading" description="识别中...">
        <n-space vertical :size="8">
          <div v-for="upload in store.currentCase?.uploads" :key="upload.id" style="display: flex; align-items: center; gap: 8px">
            <n-text style="min-width: 100px">{{ slotLabels[upload.slot] || upload.slot }}</n-text>
            <n-tag
              :type="statusType(upload.ocr_status)"
              size="small"
            >
              {{ statusLabel(upload.ocr_status) }}
            </n-tag>
          </div>
        </n-space>
      </n-spin>

      <template v-if="store.isOcrComplete">
        <n-divider />
        <n-text strong>识别结果</n-text>
        <n-space vertical :size="8">
          <n-card v-for="slot in store.slotResults" :key="slot.slot" size="small" embedded>
            <template #header>
              <n-text>{{ slotLabels[slot.slot] || slot.slot }}</n-text>
            </template>
            <n-input
              type="textarea"
              :value="formatData(slot.effective_data)"
              :rows="4"
              @update:value="(v: string) => updateSlotEdit(slot.slot, v)"
            />
          </n-card>
        </n-space>

        <n-button type="primary" @click="handleConfirmResults">
          确认结果，继续
        </n-button>
      </template>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive } from 'vue'
import {
  NCard, NSpace, NText, NTag, NButton, NDivider, NInput, NSpin,
} from 'naive-ui'
import { useComplaintStore } from '@/stores/complaint'
import type { SlotName } from '@/stores/complaint'

const store = useComplaintStore()

const slotLabels: Record<string, string> = {
  plaintiff: '原告信息',
  guardian: '法定代理人',
  defendant: '被告信息',
  fee: '赔偿费用',
  medical: '病历信息',
  appraisal: '司法鉴定',
  staff_error: '医务核查',
  evidence: '证据材料清单',
}

const statusType = (s: string) => {
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'error'
  if (s === 'processing') return 'warning'
  return 'default'
}

const statusLabel = (s: string) => {
  const map: Record<string, string> = {
    pending: '等待中',
    processing: '识别中',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
  }
  return map[s] || s
}

const slotEdits = reactive<Record<string, string>>({})

function formatData(data: Record<string, unknown>): string {
  if (!data || Object.keys(data).length === 0) return ''
  try {
    return JSON.stringify(data, null, 2)
  } catch (e: any) {
    return String(data)
  }
}

function updateSlotEdit(slot: string, value: string) {
  slotEdits[slot] = value
}

async function handleConfirmResults() {
  if (!store.currentCase) return
  const updates: { slot: string; manual_edit: Record<string, unknown> }[] = []
  for (const [slot, value] of Object.entries(slotEdits)) {
    try {
      updates.push({ slot, manual_edit: JSON.parse(value) })
    } catch (e: any) {
      updates.push({ slot, manual_edit: { raw_text: value } })
    }
  }
  if (updates.length > 0) {
    await store.updateResults(store.currentCase.case_id, updates)
  }
  store.currentStep = 3
}

onMounted(() => {
  if (store.currentCase) {
    store.fetchResults(store.currentCase.case_id)
  }
})

onUnmounted(() => {
  store.stopPolling()
})
</script>
