<template>
  <div>
    <h2 style="margin: 0 0 20px">系统概览</h2>

    <!-- 统计卡片 -->
    <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
      <n-grid-item>
        <StatCard
          label="总任务数"
          :value="store.stats?.total_tasks ?? '—'"
          :icon="DocumentsOutline"
          color="#2080f0"
        />
      </n-grid-item>
      <n-grid-item>
        <StatCard
          label="今日任务"
          :value="store.stats?.today_tasks ?? '—'"
          :icon="TodayOutline"
          color="#18a058"
        />
      </n-grid-item>
      <n-grid-item>
        <StatCard
          label="失败任务"
          :value="store.stats?.failed_tasks ?? '—'"
          :icon="WarningOutline"
          color="#d03050"
        />
      </n-grid-item>
      <n-grid-item>
        <StatCard
          label="平均置信度"
          :value="statsAvgConf"
          :icon="CheckmarkCircleOutline"
          color="#f0a020"
          :precision="1"
        />
      </n-grid-item>
    </n-grid>

    <!-- 状态分布 + 队列 -->
    <n-grid :cols="2" :x-gap="16" style="margin-top: 20px" responsive="screen">
      <n-grid-item>
        <n-card title="任务状态分布" size="small">
          <div v-if="store.stats?.by_status" style="display: flex; flex-wrap: wrap; gap: 8px">
            <n-tag
              v-for="(count, status) in store.stats.by_status"
              :key="status"
              :type="statusTagType(status)"
              size="medium"
            >
              {{ statusLabel(status) }}: {{ count }}
            </n-tag>
          </div>
          <n-empty v-else description="暂无数据" style="padding: 20px" />
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card title="待处理队列" size="small">
          <n-spin :show="false">
            <n-empty v-if="!queueItems.length" description="队列为空" style="padding: 20px" />
            <n-table v-else :single-line="true" size="small">
              <thead>
                <tr>
                  <th>文件名</th>
                  <th>状态</th>
                  <th>优先级</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in queueItems" :key="item.task_id">
                  <td style="max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                    {{ item.filename }}
                  </td>
                  <td><n-tag :type="statusTagType(item.status)" size="small">{{ statusLabel(item.status) }}</n-tag></td>
                  <td>{{ item.priority }}</td>
                </tr>
              </tbody>
            </n-table>
          </n-spin>
        </n-card>
      </n-grid-item>
    </n-grid>

    <!-- 最近任务 -->
    <n-card title="最近任务" size="small" style="margin-top: 20px">
      <n-spin :show="recentLoading">
        <n-empty v-if="!recentTasks.length" description="暂无任务" style="padding: 20px" />
        <n-table v-else :single-line="true" size="small">
          <thead>
            <tr>
              <th>文件名</th>
              <th>状态</th>
              <th>置信度</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in recentTasks" :key="task.task_id">
              <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ task.filename }}
              </td>
              <td><n-tag :type="statusTagType(task.status)" size="small">{{ statusLabel(task.status) }}</n-tag></td>
              <td>{{ task.confidence_avg != null ? (task.confidence_avg * 100).toFixed(1) + '%' : '—' }}</td>
              <td>{{ formatDate(task.created_at) }}</td>
              <td>
                <n-button size="tiny" quaternary @click="$router.push(`/tasks/${task.task_id}`)">
                  详情
                </n-button>
              </td>
            </tr>
          </tbody>
        </n-table>
      </n-spin>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  NGrid, NGridItem, NCard, NTag, NTable, NButton, NSpin, NEmpty,
} from 'naive-ui'
import {
  DocumentsOutline,
  TodayOutline,
  WarningOutline,
  CheckmarkCircleOutline,
} from '@vicons/ionicons5'
import StatCard from '@/components/StatCard.vue'
import { useScanStore } from '@/stores/scan'
import type { QueueItem, ScanTaskSummary } from '@/api/client'

const store = useScanStore()
const recentTasks = ref<ScanTaskSummary[]>([])
const recentLoading = ref(false)
const queueItems = ref<QueueItem[]>([])

const statsAvgConf = computed(() => {
  if (store.stats?.avg_confidence == null) return '—'
  return (store.stats.avg_confidence * 100).toFixed(1) + '%'
})

async function loadRecent() {
  recentLoading.value = true
  try {
    const { get } = await import('@/api/client')
    const res = await get<{ items: ScanTaskSummary[] }>('/scans', {
      page: '1', size: '5', sort_by: 'created_at', sort_order: 'desc',
    })
    recentTasks.value = res.items
  } finally {
    recentLoading.value = false
  }
}

async function loadQueue() {
  try {
    const { get } = await import('@/api/client')
    const res = await get<{ items: QueueItem[] }>('/admin/queue')
    queueItems.value = res.items || []
  } catch {
    // queue endpoint may not be reachable if backend is down
  }
}

function statusTagType(status: string): 'default' | 'info' | 'success' | 'warning' | 'error' {
  const map: Record<string, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
    received: 'info',
    pending: 'default',
    processing: 'info',
    completed: 'success',
    failed: 'error',
    retrying: 'warning',
  }
  return map[status] || 'default'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    received: '已接收',
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
    retrying: '重试中',
  }
  return map[status] || status
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN')
}

onMounted(() => {
  store.startStatsPolling()
  loadRecent()
  loadQueue()
})

onUnmounted(() => {
  store.stopStatsPolling()
})
</script>
