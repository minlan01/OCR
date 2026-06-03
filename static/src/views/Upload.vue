<template>
  <div>
    <h2 style="margin: 0 0 20px">上传扫描件</h2>

    <n-card size="small">
      <n-upload
        multiple
        :max="20"
        accept=".pdf"
        :default-upload="false"
        :show-file-list="true"
        @change="onFileChange"
      >
        <n-upload-dragger>
          <div style="padding: 40px 0">
            <n-icon size="48" color="#2080f0">
              <CloudUploadOutline />
            </n-icon>
            <p style="margin: 12px 0 4px; font-size: 16px; font-weight: 500">
              点击或拖拽 PDF 文件到此处
            </p>
            <p style="margin: 0; font-size: 13px; color: #999">
              支持 PDF 格式，单文件最大 500 MB，最多 20 个文件
            </p>
          </div>
        </n-upload-dragger>
      </n-upload>

      <n-space vertical style="margin-top: 20px; max-width: 480px">
        <n-input v-model:value="scannerId" placeholder="扫描仪编号（可选）" clearable />
        <n-input v-model:value="callbackUrl" placeholder="回调 URL（可选）" clearable />
      </n-space>

      <n-button
        type="primary"
        size="medium"
        :loading="store.uploadProgress"
        :disabled="selectedFiles.length === 0"
        style="margin-top: 20px"
        @click="handleUpload"
      >
        {{ store.uploadProgress ? '上传中...' : `开始上传（${selectedFiles.length} 个文件）` }}
      </n-button>

      <n-alert
        v-if="batchResult"
        :type="batchResult.failed.length > 0 ? 'warning' : 'success'"
        style="margin-top: 16px"
      >
        <template #header>
          上传完成：{{ batchResult.uploaded.length }} 成功
          <span v-if="batchResult.skipped.length">，{{ batchResult.skipped.length }} 跳过</span>
          <span v-if="batchResult.failed.length">，{{ batchResult.failed.length }} 失败</span>
        </template>
        <div v-if="batchResult.uploaded.length" style="margin-top: 4px">
          <div v-for="item in batchResult.uploaded" :key="item.task_id" style="font-size: 13px">
            ✅ {{ item.filename }}
            <span v-if="item.message === 'duplicate_file'" style="color: #f0a020">（文件已存在）</span>
          </div>
        </div>
        <div v-if="batchResult.skipped.length" style="margin-top: 4px">
          <div v-for="item in batchResult.skipped" :key="item.filename" style="font-size: 13px; color: #f0a020">
            ⏭️ {{ item.filename }}：{{ item.reason }}
          </div>
        </div>
        <div v-if="batchResult.failed.length" style="margin-top: 4px">
          <div v-for="item in batchResult.failed" :key="item.filename" style="font-size: 13px; color: #d03050">
            ❌ {{ item.filename }}：{{ item.reason }}
          </div>
        </div>
      </n-alert>

      <n-button
        v-if="batchResult && batchResult.uploaded.length > 0"
        size="small"
        type="primary"
        style="margin-top: 8px"
        @click="$router.push('/process')"
      >
        前往处理文档
      </n-button>

      <n-alert v-if="uploadError" type="error" style="margin-top: 16px" closable @close="uploadError = ''">
        {{ uploadError }}
      </n-alert>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  NCard, NUpload, NUploadDragger, NIcon, NInput, NButton, NSpace, NAlert,
} from 'naive-ui'
import { CloudUploadOutline } from '@vicons/ionicons5'
import { useScanStore } from '@/stores/scan'
import type { UploadFileInfo } from 'naive-ui'
import type { BatchUploadResult } from '@/api/client'

const store = useScanStore()

const selectedFiles = ref<File[]>([])
const scannerId = ref('')
const callbackUrl = ref('')
const batchResult = ref<BatchUploadResult | null>(null)
const uploadError = ref('')

function onFileChange(options: { fileList: UploadFileInfo[] }) {
  selectedFiles.value = options.fileList
    .map(f => f.file)
    .filter((f): f is File => f !== null)
  batchResult.value = null
  uploadError.value = ''
}

async function handleUpload() {
  if (selectedFiles.value.length === 0) return
  uploadError.value = ''
  batchResult.value = null

  try {
    const result = await store.batchUploadFiles(selectedFiles.value, {
      scanner_id: scannerId.value || undefined,
      callback_url: callbackUrl.value || undefined,
    })
    batchResult.value = result
  } catch (e: any) {
    uploadError.value = e.message || '上传失败'
  }
}
</script>
