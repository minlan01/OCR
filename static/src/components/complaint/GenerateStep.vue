<template>
  <n-card title="生成起诉状" size="small">
    <n-space vertical :size="16">
      <template v-if="!generating && !store.isDocReady">
        <n-text>确认所有信息无误后，点击生成民事起诉状</n-text>
        <n-button type="primary" @click="handleGenerate">
          生成起诉状
        </n-button>
      </template>

      <template v-if="generating">
        <n-spin size="large" description="正在生成起诉状...">
          <div style="min-height: 100px" />
        </n-spin>
      </template>

      <template v-if="store.isDocReady">
        <n-alert type="success" title="起诉状已生成">
          民事起诉状文档已生成完毕，可以下载。
        </n-alert>
        <n-button type="primary" @click="handleDownload">
          下载起诉状 (DOCX)
        </n-button>
        <n-button @click="handleReset">
          创建新案件
        </n-button>
      </template>

      <template v-if="store.currentCase?.status === 'failed'">
        <n-alert type="error" title="生成失败">
          起诉状生成过程中出现错误，请检查信息后重试。
        </n-alert>
        <n-button type="primary" @click="handleGenerate">
          重新生成
        </n-button>
      </template>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  NCard, NSpace, NText, NButton, NAlert, NSpin,
} from 'naive-ui'
import { useComplaintStore } from '@/stores/complaint'

const store = useComplaintStore()
const generating = ref(false)

async function handleGenerate() {
  if (!store.currentCase) return
  generating.value = true
  try {
    await store.generateDoc(store.currentCase.case_id)
    const pollInterval = setInterval(async () => {
      await store.fetchCase(store.currentCase!.case_id)
      if (store.isDocReady || store.currentCase?.status === 'failed') {
        clearInterval(pollInterval)
        generating.value = false
      }
    }, 3000)
  } catch (e: any) {
    console.error('Generate failed:', e.message)
    generating.value = false
  }
}

async function handleDownload() {
  if (!store.currentCase) return
  await store.downloadDoc(store.currentCase.case_id)
}

function handleReset() {
  store.reset()
}
</script>
