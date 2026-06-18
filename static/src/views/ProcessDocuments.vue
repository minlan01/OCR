<template>
  <div>
    <h2 style="margin: 0 0 20px">处理文档</h2>

    <n-card size="small">
      <n-space style="margin-bottom: 16px" align="center" justify="space-between">
        <n-space align="center">
          <n-button size="small" @click="loadTasks">
            <template #icon><n-icon><RefreshOutline /></n-icon></template>
            刷新
          </n-button>
          <n-text depth="3" style="font-size: 13px">
            共 {{ taskList.length }} 个待处理文件
          </n-text>
        </n-space>
        <n-space align="center">
          <n-button size="small" quaternary @click="toggleSelectAll">
            {{ isAllSelected ? '取消全选' : '全选' }}
          </n-button>
          <n-text depth="3" style="font-size: 13px">
            已选 {{ selectedIds.length }} 项
          </n-text>
        </n-space>
      </n-space>

      <n-spin :show="loading">
        <n-empty
          v-if="!loading && taskList.length === 0"
          description="暂无待处理文件，请先上传文件"
          style="padding: 40px 0"
        />

        <n-table v-else :single-line="true" size="small" striped>
          <thead>
            <tr>
              <th style="width: 40px"></th>
              <th>文件名</th>
              <th style="width: 100px">页数</th>
              <th style="width: 170px">上传时间</th>
              <th style="width: 80px">来源</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in taskList" :key="task.task_id">
              <td>
                <n-checkbox
                  :checked="selectedIds.includes(task.task_id)"
                  @update:checked="(v: boolean) => toggleSelect(task.task_id, v)"
                />
              </td>
              <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ task.filename }}
              </td>
              <td>{{ task.page_count }} 页</td>
              <td>{{ formatDate(task.created_at) }}</td>
              <td>
                <n-tag size="small" :type="task.error_code === 'api_upload' ? 'info' : 'default'">
                  {{ getSourceLabel(task.task_id) }}
                </n-tag>
              </td>
            </tr>
          </tbody>
        </n-table>
      </n-spin>

      <n-button
        type="primary"
        size="medium"
        :loading="processing"
        :disabled="selectedIds.length === 0"
        style="margin-top: 20px; width: 100%"
        @click="handleBatchProcess"
      >
        {{ processing ? '识别中...' : `开始识别 (${selectedIds.length} 个文件)` }}
      </n-button>

      <n-alert
        v-if="processResult"
        :type="processResult.failed.length > 0 ? 'warning' : 'success'"
        style="margin-top: 16px"
        closable
        @close="processResult = null"
      >
        <template #header>识别任务已提交</template>
        成功派发: {{ processResult.dispatched.length }} 个
        <template v-if="processResult.skipped.length > 0">
          | 跳过: {{ processResult.skipped.length }} 个
        </template>
        <template v-if="processResult.failed.length > 0">
          | 失败: {{ processResult.failed.length }} 个
        </template>
      </n-alert>

      <n-alert v-if="processError" type="error" style="margin-top: 16px" closable @close="processError = ''">
        {{ processError }}
      </n-alert>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard, NTable, NCheckbox, NButton, NSpace, NText, NTag, NSpin, NEmpty, NAlert, NIcon,
} from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { useScanStore } from '@/stores/scan'
import type { ScanTaskSummary, BatchProcessResult } from '@/api/client'

const store = useScanStore()

const taskList = ref<ScanTaskSummary[]>([])
const selectedIds = ref<string[]>([])
const loading = ref(false)
const processing = ref(false)
const processResult = ref<BatchProcessResult | null>(null)
const processError = ref('')

const isAllSelected = computed(() => {
  return taskList.value.length > 0 && selectedIds.value.length === taskList.value.length
})

function toggleSelect(taskId: string, checked: boolean) {
  if (checked) {
    if (!selectedIds.value.includes(taskId)) {
      selectedIds.value.push(taskId)
    }
  } else {
    selectedIds.value = selectedIds.value.filter(id => id !== taskId)
  }
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = taskList.value.map(t => t.task_id)
  }
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await store.fetchUnprocessedTasks({ size: 100 })
    taskList.value = res.items
    selectedIds.value = selectedIds.value.filter(id =>
      taskList.value.some(t => t.task_id === id)
    )
  } catch (e: any) {
    processError.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function handleBatchProcess() {
  if (selectedIds.value.length === 0) return
  processing.value = true
  processError.value = ''
  processResult.value = null

  try {
    const result = await store.batchProcessTasks(selectedIds.value)
    processResult.value = result
    selectedIds.value = []
    setTimeout(() => loadTasks(), 1500)
  } catch (e: any) {
    processError.value = e.message || '识别派发失败'
  } finally {
    processing.value = false
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN')
}

function formatSize(pageCount: number | null): string {
  if (pageCount == null) return '—'
  return pageCount + ' 页'
}

function getSourceLabel(_taskId: string): string {
  return '上传'
}

onMounted(() => {
  loadTasks()
})
</script>
