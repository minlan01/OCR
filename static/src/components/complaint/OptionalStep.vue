<template>
  <n-card title="可选项" size="small">
    <n-space vertical :size="16">
      <n-card size="small" embedded>
        <template #header>司法鉴定书</template>
        <n-radio-group v-model:value="needAppraisal" @update:value="resetUpload('appraisal')">
          <n-radio :value="false">不需要</n-radio>
          <n-radio :value="true">需要</n-radio>
        </n-radio-group>
        <template v-if="needAppraisal">
          <n-upload
            :max="5"
            accept=".pdf,.jpg,.jpeg,.png,.webp"
            :default-upload="false"
            @change="(opts: any) => onFileChange('appraisal', opts)"
          >
            <n-button size="small" style="margin-top: 8px">选择文件</n-button>
          </n-upload>
          <n-input
            v-model:value="manualInputs.appraisal"
            type="textarea"
            placeholder="或手动输入司法鉴定信息..."
            :rows="2"
            style="margin-top: 8px"
          />
          <n-button
            v-if="manualInputs.appraisal"
            size="tiny"
            style="margin-top: 4px"
            @click="submitManual('appraisal')"
          >
            提交手动输入
          </n-button>
        </template>
      </n-card>

      <n-card size="small" embedded>
        <template #header>医务人员过错核查</template>
        <n-radio-group v-model:value="needStaffError" @update:value="resetUpload('staff_error')">
          <n-radio :value="false">不需要</n-radio>
          <n-radio :value="true">需要</n-radio>
        </n-radio-group>
        <template v-if="needStaffError">
          <n-upload
            :max="5"
            accept=".pdf,.jpg,.jpeg,.png,.webp"
            :default-upload="false"
            @change="(opts: any) => onFileChange('staff_error', opts)"
          >
            <n-button size="small" style="margin-top: 8px">选择文件</n-button>
          </n-upload>
          <n-input
            v-model:value="manualInputs.staff_error"
            type="textarea"
            placeholder="或手动输入医务人员过错核查信息..."
            :rows="2"
            style="margin-top: 8px"
          />
          <n-button
            v-if="manualInputs.staff_error"
            size="tiny"
            style="margin-top: 4px"
            @click="submitManual('staff_error')"
          >
            提交手动输入
          </n-button>
        </template>
      </n-card>

      <n-button type="primary" @click="handleContinue">
        {{ hasOptionalUploads ? '识别并继续' : '继续' }}
      </n-button>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NCard, NSpace, NRadioGroup, NRadio, NButton, NUpload, NInput,
} from 'naive-ui'
import { useComplaintStore } from '@/stores/complaint'
import type { SlotName } from '@/stores/complaint'
import type { UploadFileInfo } from 'naive-ui'

const store = useComplaintStore()
const needAppraisal = ref(false)
const needStaffError = ref(false)
const manualInputs = ref<Record<string, string>>({
  appraisal: '',
  staff_error: '',
})

const hasOptionalUploads = computed(() => {
  if (!store.currentCase) return false
  return store.currentCase.uploads.some(u => u.slot === 'appraisal' || u.slot === 'staff_error')
})

function resetUpload(_slot: string) {}

async function onFileChange(slot: SlotName, options: { fileList: UploadFileInfo[] }) {
  const file = options.fileList[options.fileList.length - 1]?.file
  if (!file || !store.currentCase) return
  try {
    await store.uploadFile(store.currentCase.case_id, slot, file as File)
  } catch (e: any) {
    console.error(`Upload failed for slot ${slot}:`, e.message)
  }
}

async function submitManual(slot: SlotName) {
  if (!store.currentCase || !manualInputs.value[slot]) return
  try {
    await store.uploadManualInput(store.currentCase.case_id, slot, manualInputs.value[slot])
    manualInputs.value[slot] = ''
  } catch (e: any) {
    console.error(`Manual input failed for slot ${slot}:`, e.message)
  }
}

async function handleContinue() {
  if (hasOptionalUploads.value && store.currentCase) {
    try {
      await store.startOcr(store.currentCase.case_id)
      store.startPolling(store.currentCase.case_id, 2000)
      await new Promise((resolve, reject) => {
        const MAX_WAIT_MS = 5 * 60 * 1000  // 5 分钟超时
        const startTime = Date.now()
        const check = setInterval(() => {
          if (store.isOcrComplete) {
            clearInterval(check)
            resolve(undefined)
          } else if (Date.now() - startTime > MAX_WAIT_MS) {
            clearInterval(check)
            reject(new Error('OCR 处理超时'))
          }
        }, 2000)
      })
    } catch (e: any) {
      console.error('Optional OCR failed:', e.message)
    }
  }
  store.currentStep = 2
}
</script>
