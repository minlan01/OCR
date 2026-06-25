<template>
  <div>
    <h2 style="margin: 0 0 20px">用量</h2>

    <n-spin :show="loading">
      <template v-if="usageData">
        <!-- 超管全局汇总 -->
        <template v-if="isSuperAdmin">
          <n-card title="全局统计" size="small" style="margin-bottom: 20px">
            <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
              <n-grid-item>
                <StatCard
                  label="活跃用户"
                  :value="usageData.usage.active_users"
                  :icon="PeopleOutline"
                  color="#2080f0"
                />
              </n-grid-item>
              <n-grid-item>
                <StatCard
                  label="总证据案件"
                  :value="usageData.usage.evidence_cases"
                  :icon="FolderOpenOutline"
                  color="#18a058"
                />
              </n-grid-item>
              <n-grid-item>
                <StatCard
                  label="总扫描任务"
                  :value="usageData.usage.scan_tasks"
                  :icon="ScanOutline"
                  color="#f0a020"
                />
              </n-grid-item>
              <n-grid-item>
                <StatCard
                  label="总存储用量"
                  :value="formatMB(usageData.usage.storage_used_mb) + ' / ' + formatMB(usageData.usage.storage_quota_mb)"
                  :icon="CloudOutline"
                  color="#d03050"
                />
              </n-grid-item>
            </n-grid>
            <n-progress
              type="line"
              :percentage="storagePercent"
              :status="storagePercent >= 90 ? 'error' : storagePercent >= 70 ? 'warning' : 'success'"
              style="margin-top: 12px"
            />
          </n-card>

          <!-- 各租户用量 -->
          <n-card title="各租户用量" size="small">
            <n-data-table
              :columns="tenantUsageColumns"
              :data="tenantUsageData"
              :bordered="false"
              size="small"
            />
          </n-card>
        </template>

        <!-- 非超管：当前租户用量 -->
        <template v-else>
          <n-card :title="usageData.tenant.name + ' - 用量'" size="small" style="margin-bottom: 20px">
            <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
              <n-grid-item>
                <StatCard
                  label="证据案件"
                  :value="usageData.usage.evidence_cases + ' / ' + usageData.tenant.max_cases"
                  :icon="FolderOpenOutline"
                  color="#2080f0"
                />
              </n-grid-item>
              <n-grid-item>
                <StatCard
                  label="扫描任务"
                  :value="usageData.usage.scan_tasks"
                  :icon="ScanOutline"
                  color="#18a058"
                />
              </n-grid-item>
              <n-grid-item>
                <StatCard
                  label="存储用量"
                  :value="formatMB(usageData.usage.storage_used_mb) + ' / ' + formatMB(usageData.usage.storage_quota_mb)"
                  :icon="CloudOutline"
                  color="#f0a020"
                />
              </n-grid-item>
              <n-grid-item>
                <StatCard
                  label="活跃成员"
                  :value="usageData.usage.active_users"
                  :icon="PeopleOutline"
                  color="#d03050"
                />
              </n-grid-item>
            </n-grid>
            <n-progress
              type="line"
              :percentage="storagePercent"
              :status="storagePercent >= 90 ? 'error' : storagePercent >= 70 ? 'warning' : 'success'"
              style="margin-top: 12px"
            />
          </n-card>

          <n-card title="并发处理" size="small">
            <n-space align="center">
              <n-text>当前并发：{{ usageData.usage.concurrent_used }} / {{ usageData.usage.concurrent_max }}</n-text>
              <n-progress
                type="line"
                style="max-width: 300px"
                :percentage="concurrentPercent"
                :status="concurrentPercent >= 90 ? 'error' : concurrentPercent >= 70 ? 'warning' : 'success'"
              />
            </n-space>
          </n-card>
        </template>
      </template>
      <n-empty v-else description="暂无数据" style="padding: 40px" />
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import {
  NCard, NGrid, NGridItem, NSpin, NEmpty, NProgress, NText, NSpace,
  NDataTable, NTag, type DataTableColumns,
} from 'naive-ui'
import {
  FolderOpenOutline,
  ScanOutline,
  CloudOutline,
  PeopleOutline,
} from '@vicons/ionicons5'
import StatCard from '@/components/StatCard.vue'
import { useAuthStore } from '@/stores/auth'
import { storeToRefs } from 'pinia'
import { get, type UsageResponse, type TenantListItem } from '@/api/client'

const authStore = useAuthStore()
const { userInfo, isSuperAdmin } = storeToRefs(authStore)
const usageData = ref<UsageResponse | null>(null)
const loading = ref(false)
const tenantUsageData = ref<TenantListItem[]>([])

const storagePercent = computed(() => {
  if (!usageData.value) return 0
  const u = usageData.value.usage
  if (u.storage_quota_mb <= 0) return 0
  return Math.min(100, Math.round((u.storage_used_mb / u.storage_quota_mb) * 100))
})

const concurrentPercent = computed(() => {
  if (!usageData.value) return 0
  const u = usageData.value.usage
  if (u.concurrent_max <= 0) return 0
  return Math.min(100, Math.round((u.concurrent_used / u.concurrent_max) * 100))
})

const tenantUsageColumns = computed<DataTableColumns<TenantListItem>>(() => [
  { title: '租户', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '套餐',
    key: 'plan',
    render(row) {
      const map: Record<string, string> = { free: '免费版', pro: '专业版', enterprise: '企业版' }
      const typeMap: Record<string, 'default' | 'info' | 'success'> = { free: 'default', pro: 'info', enterprise: 'success' }
      return h(NTag, { type: typeMap[row.plan] || 'default', size: 'small' }, { default: () => map[row.plan] || row.plan })
    },
  },
  { title: '用户数', key: 'user_count', width: 80 },
  { title: '案件数', key: 'case_count', width: 80 },
  { title: '最大案件', key: 'max_cases', width: 90 },
  {
    title: '存储用量',
    key: 'storage',
    render(row) { return `${formatMB(row.storage_used_mb)} / ${formatMB(row.storage_quota_mb)}` },
  },
  {
    title: '状态',
    key: 'status',
    render(row) {
      return h(NTag, { type: row.status === 'active' ? 'success' : 'error', size: 'small' }, {
        default: () => (row.status === 'active' ? '正常' : '已暂停'),
      })
    },
  },
])

async function loadUserInfo(): Promise<void> {
  await authStore.loadUserInfo()
}

async function loadUsage(): Promise<void> {
  loading.value = true
  try {
    usageData.value = await get<UsageResponse>('/admin/usage')
  } catch { /* silent */ } finally {
    loading.value = false
  }
}

async function loadTenantUsage(): Promise<void> {
  if (!isSuperAdmin.value) return
  try {
    const res = await get<{ items: TenantListItem[] }>('/admin/tenants', { page: '1', size: '100' })
    tenantUsageData.value = res.items
  } catch { /* silent */ }
}

function formatMB(mb: number): string {
  if (mb >= 1024) return (mb / 1024).toFixed(1) + 'GB'
  return mb + 'MB'
}

onMounted(async () => {
  await loadUserInfo()
  loadUsage()
  if (isSuperAdmin.value) {
    loadTenantUsage()
  }
})
</script>
