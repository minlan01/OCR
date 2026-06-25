<template>
  <div>
    <h2 style="margin: 0 0 20px">概览</h2>

    <!-- 系统统计（仅 admin 可见） -->
    <template v-if="isAdmin">
      <!-- 超管：全局统计 + 各租户概览 -->
      <template v-if="isSuperAdmin">
        <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
          <n-grid-item>
            <StatCard
              label="总用户"
              :value="totalUsers"
              :icon="PeopleOutline"
              color="#2080f0"
            />
          </n-grid-item>
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
        </n-grid>

        <!-- 租户概览 -->
        <n-card title="租户概览" size="small" style="margin-top: 20px">
          <n-data-table
            :columns="tenantOverviewColumns"
            :data="tenantData"
            :bordered="false"
            size="small"
          />
        </n-card>
      </template>

      <!-- 租户管理员：本租户数据 -->
      <template v-else>
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
            />
          </n-grid-item>
        </n-grid>
      </template>

      <!-- 状态分布 + 队列（所有 admin 可见） -->
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
    </template>

    <!-- 非 admin 用户看到的引导内容 -->
    <template v-else>
      <n-card title="欢迎使用 ScanStruct" size="medium">
        <n-space vertical>
          <n-text>您当前的身份是普通成员，以下是您可以使用的功能：</n-text>
          <n-space>
            <n-button type="primary" @click="$router.push('/usage')">查看用量</n-button>
            <n-button @click="$router.push('/upload')">上传文件</n-button>
            <n-button @click="$router.push('/tasks')">任务列表</n-button>
          </n-space>
          <n-text depth="3">如需管理权限，请联系系统管理员。</n-text>
        </n-space>
      </n-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, h } from 'vue'
import {
  NGrid, NGridItem, NCard, NTag, NTable, NButton, NSpin, NEmpty, NDataTable,
  NSpace, NText,
} from 'naive-ui'
import {
  DocumentsOutline,
  TodayOutline,
  WarningOutline,
  CheckmarkCircleOutline,
  PeopleOutline,
} from '@vicons/ionicons5'
import StatCard from '@/components/StatCard.vue'
import { useScanStore } from '@/stores/scan'
import { useAuthStore } from '@/stores/auth'
import { storeToRefs } from 'pinia'
import { get, type QueueItem, type ScanTaskSummary, type TenantListItem } from '@/api/client'

const store = useScanStore()
const recentTasks = ref<ScanTaskSummary[]>([])
const recentLoading = ref(false)
const queueItems = ref<QueueItem[]>([])
const totalUsers = ref(0)
const tenantData = ref<TenantListItem[]>([])

// ─── 用户信息与权限（使用全局 auth store） ───
const authStore = useAuthStore()
const { userInfo, isAdmin, isSuperAdmin } = storeToRefs(authStore)

const statsAvgConf = computed(() => {
  if (store.stats?.avg_confidence == null) return '—'
  return (store.stats.avg_confidence * 100).toFixed(1) + '%'
})

// ─── 超管租户概览表格列 ───
const tenantOverviewColumns = computed(() => [
  { title: '租户', key: 'name', ellipsis: { tooltip: true } },
  { title: '用户数', key: 'user_count', width: 80 },
  { title: '案件数', key: 'case_count', width: 80 },
  {
    title: '存储用量',
    key: 'storage',
    render(row: TenantListItem) {
      const pct = row.storage_quota_mb > 0
        ? Math.min(100, Math.round((row.storage_used_mb / row.storage_quota_mb) * 100))
        : 0
      return `${(row.storage_used_mb / 1024).toFixed(1)}GB / ${(row.storage_quota_mb / 1024).toFixed(1)}GB (${pct}%)`
    },
  },
  {
    title: '状态',
    key: 'status',
    render(row: TenantListItem) {
      return h(NTag, { type: row.status === 'active' ? 'success' : 'error', size: 'small' }, {
        default: () => (row.status === 'active' ? '正常' : '已暂停'),
      })
    },
  },
])

async function loadUserInfo(): Promise<void> {
  await authStore.loadUserInfo()
}

async function loadRecent() {
  recentLoading.value = true
  try {
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
    const res = await get<{ items: QueueItem[] }>('/admin/queue')
    queueItems.value = res.items || []
  } catch (e: any) {
    // queue endpoint may not be reachable
  }
}

async function loadTotalUsers() {
  if (!isSuperAdmin.value) return
  try {
    const res = await get<{ total: number }>('/admin/users', { page: '1', size: '1' })
    totalUsers.value = res.total
  } catch { /* silent */ }
}

async function loadTenantData() {
  if (!isSuperAdmin.value) return
  try {
    const res = await get<{ items: TenantListItem[] }>('/admin/tenants', { page: '1', size: '100' })
    tenantData.value = res.items
  } catch { /* silent */ }
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
  loadUserInfo()
})

// watch userInfo 变化，admin 加载统计
watch(isAdmin, (val) => {
  if (val) {
    store.startStatsPolling()
    loadRecent()
    loadQueue()
    if (isSuperAdmin.value) {
      loadTotalUsers()
      loadTenantData()
    }
  }
}, { immediate: true })

onUnmounted(() => {
  store.stopStatsPolling()
})
</script>
