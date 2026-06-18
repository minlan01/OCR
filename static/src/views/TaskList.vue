<template>
  <div>
    <n-space style="margin: 0 0 16px" align="center" justify="space-between">
      <h2 style="margin: 0">任务列表</h2>
      <n-button size="small" :loading="store.taskLoading" @click="loadTasks">
        <template #icon><n-icon><RefreshOutline /></n-icon></template>
        刷新
      </n-button>
    </n-space>

    <!-- 筛选栏 -->
    <n-space style="margin-bottom: 16px" align="center">
      <n-select
        v-model:value="filterStatus"
        :options="statusOptions"
        placeholder="筛选状态"
        clearable
        style="width: 140px"
        @update:value="onFilterChange"
      />
      <n-input
        v-model:value="filterScanner"
        placeholder="扫描仪编号"
        clearable
        style="width: 180px"
        @clear="onFilterChange"
        @keyup.enter="onFilterChange"
      />
      <n-button size="small" @click="onFilterChange">搜索</n-button>
    </n-space>

    <!-- 表格 -->
    <n-spin :show="store.taskLoading">
      <n-data-table
        :columns="columns"
        :data="store.taskList"
        :pagination="pagination"
        :bordered="false"
        :single-line="false"
        size="small"
        @update:page="onPageChange"
        @update:page-size="onPageSizeChange"
      />
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NDataTable, NTag, NButton, NSelect, NInput, NSpace, NSpin, NPopconfirm, NIcon,
  useMessage,
} from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import { useScanStore } from '@/stores/scan'
import type { ScanTaskSummary } from '@/api/client'

const router = useRouter()
const message = useMessage()
const store = useScanStore()

const filterStatus = ref<string>('')
const filterScanner = ref('')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '已接收', value: 'received' },
  { label: '待处理', value: 'pending' },
  { label: '处理中', value: 'processing' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
  { label: '重试中', value: 'retrying' },
]

const statusLabelMap: Record<string, string> = {
  received: '已接收',
  pending: '待处理',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  retrying: '重试中',
}

const statusTypeMap: Record<string, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
  received: 'info',
  pending: 'default',
  processing: 'info',
  completed: 'success',
  failed: 'error',
  retrying: 'warning',
}

const columns: DataTableColumns<ScanTaskSummary> = [
  {
    title: '文件名',
    key: 'filename',
    ellipsis: { tooltip: true },
    width: 240,
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render(row) {
      return h(NTag, { type: statusTypeMap[row.status] || 'default', size: 'small' }, {
        default: () => statusLabelMap[row.status] || row.status,
      })
    },
  },
  {
    title: '页数',
    key: 'page_count',
    width: 80,
    render(row) {
      return row.page_count ?? '—'
    },
  },
  {
    title: '置信度',
    key: 'confidence_avg',
    width: 100,
    render(row) {
      if (row.confidence_avg == null) return '—'
      return (row.confidence_avg * 100).toFixed(1) + '%'
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 170,
    render(row) {
      return new Date(row.created_at).toLocaleString('zh-CN')
    },
  },
  {
    title: '完成时间',
    key: 'completed_at',
    width: 170,
    render(row) {
      return row.completed_at ? new Date(row.completed_at).toLocaleString('zh-CN') : '—'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    render(row) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, {
            size: 'tiny',
            quaternary: true,
            onClick: () => router.push(`/tasks/${row.task_id}`),
          }, { default: () => '详情' }),
          row.status === 'failed'
            ? h(NPopconfirm, {
                onPositiveClick: () => handleRetry(row.task_id),
              }, {
                default: () => '确认重试？',
                trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'warning' }, { default: () => '重试' }),
              })
            : null,
          h(NPopconfirm, {
            onPositiveClick: () => handleDelete(row.task_id),
          }, {
            default: () => '确认删除？',
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, { default: () => '删除' }),
          }),
        ].filter(Boolean),
      })
    },
  },
]

const pagination = ref({
  page: 1,
  pageSize: 20,
  itemCount: 0,
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
})

async function loadTasks() {
  const params: Record<string, string> = {}
  if (filterStatus.value) params.status = filterStatus.value
  if (filterScanner.value) params.scanner_id = filterScanner.value

  await store.fetchTasks({
    page: pagination.value.page,
    size: pagination.value.pageSize,
    ...params,
  })
  pagination.value.itemCount = store.taskTotal
  pagination.value.page = store.taskPage
}

function onFilterChange() {
  pagination.value.page = 1
  loadTasks()
}

function onPageChange(page: number) {
  pagination.value.page = page
  loadTasks()
}

function onPageSizeChange(size: number) {
  pagination.value.pageSize = size
  pagination.value.page = 1
  loadTasks()
}

async function handleRetry(taskId: string) {
  try {
    await store.retryTask(taskId)
    loadTasks()
  } catch (e: any) {
    message.error('重试失败: ' + e.message)
  }
}

async function handleDelete(taskId: string) {
  try {
    await store.deleteTask(taskId)
    loadTasks()
  } catch (e: any) {
    message.error('删除失败: ' + e.message)
  }
}

onMounted(() => {
  loadTasks()
})
</script>
