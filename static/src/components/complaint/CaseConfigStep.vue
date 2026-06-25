<template>
  <n-card title="案件配置" size="small">
    <n-space vertical :size="16">
      <div>
        <n-text>案件类型</n-text>
        <n-radio-group v-model:value="caseType" style="margin-left: 12px">
          <n-radio-button value="injury">伤残</n-radio-button>
          <n-radio-button value="death">死亡</n-radio-button>
          <n-radio-button value="neonatal">新生儿</n-radio-button>
        </n-radio-group>
      </div>
      <div>
        <n-text>是否未成年</n-text>
        <n-radio-group v-model:value="isMinor" style="margin-left: 12px">
          <n-radio-button :value="false">否</n-radio-button>
          <n-radio-button :value="true">是</n-radio-button>
        </n-radio-group>
      </div>

      <n-divider style="margin: 4px 0" />

      <n-card size="small" embedded>
        <template #header>
          <n-text strong>证据材料清单</n-text>
        </template>
        <n-text depth="3" style="margin-bottom: 8px; display: block">
          上传证据材料清单文件，支持 Word、Excel、PPT、PDF、图片格式，也可手动输入
        </n-text>
        <n-upload
          :max="10"
          accept=".docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.jpg,.jpeg,.png,.webp"
          :default-upload="false"
          @change="onFileChange"
        >
          <n-button size="small">选择文件</n-button>
        </n-upload>
        <n-input
          v-model:value="manualInput"
          type="textarea"
          placeholder="或手动输入证据材料清单..."
          :rows="4"
          style="margin-top: 8px"
        />
        <div v-if="pendingFiles.length > 0" style="margin-top: 8px">
          <n-text depth="3">已选择 {{ pendingFiles.length }} 个文件</n-text>
        </div>
      </n-card>

      <n-button
        type="primary"
        :loading="creating"
        :disabled="pendingFiles.length === 0 && !manualInput.trim()"
        @click="handleCreate"
      >
        {{ creating ? '创建并识别中...' : '创建案件并识别证据清单' }}
      </n-button>

      <template v-if="ocrRunning">
        <n-divider style="margin: 4px 0" />
        <n-spin description="正在识别证据材料清单...">
          <div style="min-height: 60px" />
        </n-spin>
      </template>

      <template v-if="ocrError">
        <n-divider style="margin: 4px 0" />
        <n-alert type="error" title="识别失败" closable @close="ocrError = ''">
          <n-text>{{ ocrError }}</n-text>
        </n-alert>
      </template>

      <template v-if="ocrDone">
        <n-divider style="margin: 4px 0" />
        <n-alert type="success" title="证据材料清单识别完成">
          <n-text>识别结果如下，可编辑修正后继续</n-text>
        </n-alert>
        <n-card size="small" embedded style="margin-top: 8px">
          <template #header>证据材料清单</template>
          <n-input
            type="textarea"
            :value="evidenceText"
            :rows="8"
            @update:value="(v: string) => evidenceText = v"
          />
        </n-card>
        <n-button type="primary" style="margin-top: 8px" @click="handleConfirm">
          确认结果，继续
        </n-button>
      </template>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NCard, NSpace, NText, NRadioGroup, NRadioButton, NButton,
  NUpload, NInput, NDivider, NSpin, NAlert,
} from 'naive-ui'
import { useComplaintStore } from '@/stores/complaint'
import type { SlotName } from '@/stores/complaint'
import type { UploadFileInfo } from 'naive-ui'

const store = useComplaintStore()
const caseType = ref<'injury' | 'death' | 'neonatal'>('injury')
const isMinor = ref(false)
const manualInput = ref('')
const pendingFiles = ref<File[]>([])
const creating = ref(false)
const ocrRunning = ref(false)
const ocrDone = ref(false)
const ocrError = ref('')
const evidenceText = ref('')

function onFileChange(options: { fileList: UploadFileInfo[] }) {
  const file = options.fileList[options.fileList.length - 1]?.file
  if (file) {
    pendingFiles.value.push(file as File)
  }
}

async function handleCreate() {
  creating.value = true
  try {
    const caseData = await store.createCase(caseType.value, isMinor.value)
    if (!caseData) return
    const caseId = caseData.case_id

    for (const file of pendingFiles.value) {
      try {
        await store.uploadFile(caseId, 'evidence' as SlotName, file)
      } catch (e: any) {
        console.error('Evidence upload failed:', e.message)
      }
    }

    if (manualInput.value.trim()) {
      try {
        await store.uploadManualInput(caseId, 'evidence' as SlotName, manualInput.value)
        manualInput.value = ''
      } catch (e: any) {
        console.error('Manual input failed:', e.message)
      }
    }

    try {
      await store.startOcr(caseId)
    } catch (e: any) {
      ocrError.value = `启动 OCR 失败: ${e.message || e}`
      console.error('Start OCR failed:', e.message)
      return
    }

    ocrRunning.value = true
    store.startPolling(caseId, 3000)

    try {
      await new Promise<void>((resolve, reject) => {
        const MAX_WAIT_MS = 5 * 60 * 1000  // 5 分钟超时
        const startTime = Date.now()
        const check = setInterval(() => {
          if (store.isOcrComplete) {
            clearInterval(check)
            resolve()
          } else if (Date.now() - startTime > MAX_WAIT_MS) {
            clearInterval(check)
            reject(new Error('OCR 处理超时'))
          }
        }, 2000)
      })
    } catch (e: any) {
      ocrError.value = e.message || 'OCR 处理失败'
      ocrRunning.value = false
      store.stopPolling()
      return
    }

    store.stopPolling()
    ocrRunning.value = false
    ocrDone.value = true

    await store.fetchResults(caseId)
    const evidenceSlot = store.slotResults.find(s => s.slot === 'evidence')
    if (evidenceSlot) {
      const data = evidenceSlot.effective_data
      evidenceText.value = data && Object.keys(data).length > 0
        ? JSON.stringify(data, null, 2)
        : evidenceSlot.extracted_data
          ? JSON.stringify(evidenceSlot.extracted_data, null, 2)
          : ''
    }
  } catch (e: any) {
    console.error('Create case failed:', e.message)
  } finally {
    creating.value = false
  }
}

async function handleConfirm() {
  if (store.currentCase && evidenceText.value) {
    try {
      const parsed = JSON.parse(evidenceText.value)
      await store.updateResults(store.currentCase.case_id, [
        { slot: 'evidence', manual_edit: parsed },
      ])
    } catch (e: any) {
      await store.updateResults(store.currentCase.case_id, [
        { slot: 'evidence', manual_edit: { raw_text: evidenceText.value } },
      ])
    }
  }
  store.currentStep = 1
}
</script>
