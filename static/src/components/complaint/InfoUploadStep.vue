<template>
  <n-card title="信息上传" size="small">
    <n-space vertical :size="16">
      <n-text depth="3">请上传以下材料，所有项目可按任意顺序上传</n-text>

      <!-- 费用材料缺失提示弹窗 -->
      <n-modal v-model:show="showFeeWarning" preset="dialog" title="费用材料提示" :mask-closable="false">
        <n-text>费用详情置信度低，请核实相关发票内容。建议上传费用发票材料以获得准确的赔偿金额计算。</n-text>
        <template #action>
          <n-button @click="showFeeWarning = false">取消</n-button>
          <n-button type="primary" @click="confirmStartOcr">继续</n-button>
        </template>
      </n-modal>

      <n-card size="small" embedded>
        <template #header>
          <n-text strong>原告信息（必选）</n-text>
        </template>
        <n-text depth="3" style="margin-bottom: 8px; display: block">身份证照片、截图或PDF</n-text>
        <n-upload
          :max="5"
          accept=".pdf,.jpg,.jpeg,.png,.webp"
          :default-upload="false"
          @change="(opts: any) => onFileChange('plaintiff', opts)"
        >
          <n-button size="small">选择文件</n-button>
        </n-upload>
        <UploadStatusTag :uploads="getUploads('plaintiff')" />
      </n-card>

      <n-card v-if="isMinor" size="small" embedded>
        <template #header>
          <n-text strong>法定代理人/监护人信息（必选）</n-text>
        </template>
        <n-text depth="3" style="margin-bottom: 8px; display: block">截图、照片、PDF 或手动输入</n-text>
        <n-upload
          :max="5"
          accept=".pdf,.jpg,.jpeg,.png,.webp"
          :default-upload="false"
          @change="(opts: any) => onFileChange('guardian', opts)"
        >
          <n-button size="small">选择文件</n-button>
        </n-upload>
        <n-input
          v-model:value="manualInputs.guardian"
          type="textarea"
          placeholder="或手动输入监护人信息..."
          :rows="2"
          style="margin-top: 8px"
        />
        <n-button
          v-if="manualInputs.guardian"
          size="tiny"
          style="margin-top: 4px"
          @click="submitManual('guardian')"
        >
          提交手动输入
        </n-button>
        <UploadStatusTag :uploads="getUploads('guardian')" />
      </n-card>

      <n-card size="small" embedded>
        <template #header>
          <n-text strong>被告信息（必选）</n-text>
        </template>
        <n-text depth="3" style="margin-bottom: 8px; display: block">截图、PDF 或手动输入</n-text>
        <n-upload
          :max="5"
          accept=".pdf,.jpg,.jpeg,.png,.webp"
          :default-upload="false"
          @change="(opts: any) => onFileChange('defendant', opts)"
        >
          <n-button size="small">选择文件</n-button>
        </n-upload>
        <n-input
          v-model:value="manualInputs.defendant"
          type="textarea"
          placeholder="或手动输入被告信息..."
          :rows="2"
          style="margin-top: 8px"
        />
        <n-button
          v-if="manualInputs.defendant"
          size="tiny"
          style="margin-top: 4px"
          @click="submitManual('defendant')"
        >
          提交手动输入
        </n-button>
        <UploadStatusTag :uploads="getUploads('defendant')" />
      </n-card>

      <n-card size="small" embedded>
        <template #header>
          <n-text strong>赔偿费用清单（非必选）</n-text>
        </template>
        <n-text depth="3" style="margin-bottom: 8px; display: block">截图、PDF、照片</n-text>
        <n-upload
          :max="5"
          accept=".pdf,.jpg,.jpeg,.png,.webp"
          :default-upload="false"
          @change="(opts: any) => onFileChange('fee', opts)"
        >
          <n-button size="small">选择文件</n-button>
        </n-upload>
        <UploadStatusTag :uploads="getUploads('fee')" />
      </n-card>

      <n-card size="small" embedded>
        <template #header>
          <n-text strong>病历信息（必选）</n-text>
        </template>
        <n-text depth="3" style="margin-bottom: 8px; display: block">PDF（支持500MB以上大文件）或图片</n-text>
        <n-upload
          :max="10"
          accept=".pdf,.jpg,.jpeg,.png,.webp"
          :default-upload="false"
          @change="(opts: any) => onFileChange('medical', opts)"
        >
          <n-button size="small">选择文件</n-button>
        </n-upload>
        <UploadStatusTag :uploads="getUploads('medical')" />
      </n-card>

      <n-button
        type="primary"
        :disabled="!canStartOcr"
        :loading="startingOcr"
        @click="handleStartOcr"
      >
        开始识别
      </n-button>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NCard, NSpace, NText, NButton, NUpload, NInput, NModal,
} from 'naive-ui'
import { useComplaintStore } from '@/stores/complaint'
import type { SlotName } from '@/stores/complaint'
import type { UploadFileInfo } from 'naive-ui'
import UploadStatusTag from './UploadStatusTag.vue'

const store = useComplaintStore()
const startingOcr = ref(false)
const showFeeWarning = ref(false)
const manualInputs = ref<Record<string, string>>({
  guardian: '',
  defendant: '',
})

const isMinor = computed(() => store.currentCase?.is_minor ?? false)

const canStartOcr = computed(() => {
  if (!store.currentCase) return false
  const uploads = store.currentCase.uploads
  const hasPlaintiff = uploads.some(u => u.slot === 'plaintiff')
  const hasDefendant = uploads.some(u => u.slot === 'defendant')
  const hasMedical = uploads.some(u => u.slot === 'medical')
  const hasGuardian = !isMinor.value || uploads.some(u => u.slot === 'guardian')
  return hasPlaintiff && hasDefendant && hasMedical && hasGuardian
})

function getUploads(slot: string) {
  return store.currentCase?.uploads.filter(u => u.slot === slot) ?? []
}

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

async function handleStartOcr() {
  if (!store.currentCase) return
  // 始终弹窗提示用户核实费用材料
  showFeeWarning.value = true
}

async function confirmStartOcr() {
  showFeeWarning.value = false
  await _executeOcr()
}

async function _executeOcr() {
  if (!store.currentCase) return
  startingOcr.value = true
  try {
    await store.startOcr(store.currentCase.case_id)
    store.startPolling(store.currentCase.case_id)
    store.currentStep = 2
  } catch (e: any) {
    console.error('Start OCR failed:', e.message)
  } finally {
    startingOcr.value = false
  }
}
</script>
