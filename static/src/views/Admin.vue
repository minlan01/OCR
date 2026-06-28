<template>
  <div>
    <h2 style="margin: 0 0 20px">管理后台</h2>

    <n-tabs type="line" v-model:value="activeTab" @update:value="onTabChange">
      <!-- ═══ Tab 1: 用户管理 ═══ -->
      <n-tab-pane name="users" tab="用户管理">
        <n-space justify="end" style="margin-bottom: 16px">
          <n-button type="primary" @click="openCreateModal">
            <template #icon><n-icon><PersonAddOutline /></n-icon></template>
            添加用户
          </n-button>
        </n-space>

        <n-data-table
          :columns="userColumns"
          :data="userData"
          :loading="usersLoading"
          :pagination="userPagination"
          :bordered="false"
          remote
          @update:page="onUserPageChange"
        />
      </n-tab-pane>

      <!-- ═══ Tab 2: 租户信息 ═══ -->
      <n-tab-pane name="tenant" tab="租户信息">
        <!-- super_admin: 租户列表 -->
        <template v-if="isSuperAdmin">
          <n-space justify="end" style="margin-bottom: 16px">
            <n-button type="primary" @click="openTenantCreateModal">
              <template #icon><n-icon><AddOutline /></n-icon></template>
              添加租户
            </n-button>
          </n-space>
          <n-data-table
            :columns="tenantColumns"
            :data="tenantData"
            :loading="tenantsLoading"
            :pagination="tenantPagination"
            :bordered="false"
            remote
            @update:page="onTenantPageChange"
          />
        </template>

        <!-- 普通管理员: 只读卡片 -->
        <template v-else>
          <n-spin :show="tenantDetailLoading">
            <n-card v-if="tenantDetail" :title="tenantDetail.name" size="small">
              <n-descriptions :column="2" label-placement="left" bordered>
                <n-descriptions-item label="套餐">
                  <n-tag :type="planTagType(tenantDetail.plan)" size="small">
                    {{ planLabel(tenantDetail.plan) }}
                  </n-tag>
                </n-descriptions-item>
                <n-descriptions-item label="状态">
                  <n-tag :type="tenantDetail.status === 'active' ? 'success' : 'error'" size="small">
                    {{ tenantDetail.status === 'active' ? '正常' : '已暂停' }}
                  </n-tag>
                </n-descriptions-item>
                <n-descriptions-item label="最大案件数">{{ tenantDetail.max_cases }}</n-descriptions-item>
                <n-descriptions-item label="最大并发">{{ tenantDetail.max_concurrent }}</n-descriptions-item>
                <n-descriptions-item label="存储配额">{{ formatMB(tenantDetail.storage_quota_mb) }}</n-descriptions-item>
                <n-descriptions-item label="已用存储">{{ formatMB(tenantDetail.storage_used_mb) }}</n-descriptions-item>
                <n-descriptions-item label="用户数">{{ tenantDetail.user_count }}</n-descriptions-item>
                <n-descriptions-item label="案件数">{{ tenantDetail.case_count }}</n-descriptions-item>
              </n-descriptions>
            </n-card>
            <n-empty v-else description="暂无数据" style="padding: 40px" />
          </n-spin>
        </template>
      </n-tab-pane>

      <!-- ═══ Tab 3: 使用量 ═══ -->
      <n-tab-pane name="usage" tab="使用量">
        <n-spin :show="usageLoading">
          <template v-if="usageData">
            <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
              <n-grid-item>
                <n-card size="small" style="text-align: center">
                  <n-statistic label="证据案件" :value="usageData.usage.evidence_cases">
                    <template #suffix>
                      <n-text depth="3" style="font-size: 14px">/ {{ usageData.tenant.max_cases }}</n-text>
                    </template>
                  </n-statistic>
                  <n-progress
                    type="line"
                    :percentage="usagePercent('evidence')"
                    :status="progressStatus(usagePercent('evidence'))"
                    style="margin-top: 8px"
                  />
                </n-card>
              </n-grid-item>
              <n-grid-item>
                <n-card size="small" style="text-align: center">
                  <n-statistic label="扫描任务" :value="usageData.usage.scan_tasks" />
                </n-card>
              </n-grid-item>
              <n-grid-item>
                <n-card size="small" style="text-align: center">
                  <n-statistic label="存储用量">
                    <template #default>
                      <span>{{ formatMB(usageData.usage.storage_used_mb) }}</span>
                    </template>
                    <template #suffix>
                      <n-text depth="3" style="font-size: 14px">/ {{ formatMB(usageData.usage.storage_quota_mb) }}</n-text>
                    </template>
                  </n-statistic>
                  <n-progress
                    type="line"
                    :percentage="usagePercent('storage')"
                    :status="progressStatus(usagePercent('storage'))"
                    style="margin-top: 8px"
                  />
                </n-card>
              </n-grid-item>
              <n-grid-item>
                <n-card size="small" style="text-align: center">
                  <n-statistic label="活跃用户" :value="usageData.usage.active_users" />
                </n-card>
              </n-grid-item>
            </n-grid>

            <n-card title="并发处理" size="small" style="margin-top: 20px">
              <n-space align="center">
                <n-text>当前并发：{{ usageData.usage.concurrent_used }} / {{ usageData.usage.concurrent_max }}</n-text>
                <n-progress
                  type="line"
                  style="max-width: 300px"
                  :percentage="usagePercent('concurrent')"
                  :status="progressStatus(usagePercent('concurrent'))"
                />
              </n-space>
            </n-card>
          </template>
          <n-empty v-else description="暂无数据" style="padding: 40px" />
        </n-spin>
      </n-tab-pane>

      <!-- ═══ Tab 4: OCR 监控（仅 super_admin）═══ -->
      <n-tab-pane v-if="isSuperAdmin" name="ocr" tab="OCR监控">
        <n-spin :show="ocrLoading">
          <n-space justify="space-between" align="center" style="margin-bottom: 16px">
            <n-space align="center" :size="12">
              <n-tag v-if="ocrData" size="small" round :bordered="false" type="info">
                生成于 {{ formatOcrTime(ocrData.generated_at) }}
              </n-tag>
              <n-tag v-if="ocrAutoRefresh" size="small" round :bordered="false" type="success">
                自动刷新中（每{{ ocrRefreshInterval / 60 }}分钟）
              </n-tag>
            </n-space>
            <n-space align="center" :size="12">
              <n-text depth="3" style="font-size: 13px">自动刷新</n-text>
              <n-switch v-model:value="ocrAutoRefresh" size="small" @update:value="onOcrAutoRefreshToggle" />
              <n-select
                v-model:value="ocrRefreshInterval"
                :options="ocrIntervalOptions"
                size="small"
                style="width: 110px"
                :disabled="!ocrAutoRefresh"
                @update:value="onOcrIntervalChange"
              />
              <n-button size="small" @click="loadOcrMonitor" :loading="ocrLoading">
                <template #icon><n-icon><RefreshOutline /></n-icon></template>
                刷新
              </n-button>
            </n-space>
          </n-space>

          <n-alert v-if="ocrError" type="error" style="margin-bottom: 16px" closable @close="ocrError = ''">
            {{ ocrError }}
          </n-alert>

          <template v-if="ocrData">
            <!-- 总览卡片 -->
            <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen" style="margin-bottom: 24px">
              <n-grid-item>
                <n-card size="small"><n-statistic label="案件总数" :value="ocrData.total_cases" /></n-card>
              </n-grid-item>
              <n-grid-item>
                <n-card size="small"><n-statistic label="材料总数" :value="ocrData.total_materials" /></n-card>
              </n-grid-item>
              <n-grid-item>
                <n-card size="small">
                  <n-statistic
                    label="平均置信度"
                    :value="ocrData.avg_confidence !== null ? (ocrData.avg_confidence * 100).toFixed(2) + '%' : '—'"
                  />
                </n-card>
              </n-grid-item>
              <n-grid-item>
                <n-card size="small">
                  <n-statistic label="低质量材料数" :value="ocrData.low_quality_count">
                    <template #suffix>
                      <n-text v-if="ocrData.low_quality_count > 0" type="error" style="font-size: 12px">（需关注）</n-text>
                    </template>
                  </n-statistic>
                </n-card>
              </n-grid-item>
            </n-grid>

            <!-- OCR 状态 + Source Type -->
            <n-grid :cols="2" :x-gap="16" :y-gap="16" responsive="screen" style="margin-bottom: 24px">
              <n-grid-item>
                <n-card title="OCR 处理状态" size="small">
                  <n-space>
                    <n-tag type="success" round>已完成 {{ ocrData.ocr_completed }}</n-tag>
                    <n-tag type="error" round>失败 {{ ocrData.ocr_failed }}</n-tag>
                    <n-tag type="warning" round>待处理 {{ ocrData.ocr_pending }}</n-tag>
                    <n-tag type="info" round>有OCR数据 {{ ocrData.materials_with_ocr }}</n-tag>
                  </n-space>
                </n-card>
              </n-grid-item>
              <n-grid-item>
                <n-card title="来源类型分布" size="small">
                  <n-space>
                    <n-tag v-for="(count, src) in ocrData.source_type_stats" :key="src" round :bordered="false">
                      {{ src }}: {{ count }}
                    </n-tag>
                    <n-text v-if="Object.keys(ocrData.source_type_stats).length === 0" depth="3">暂无数据</n-text>
                  </n-space>
                </n-card>
              </n-grid-item>
            </n-grid>

            <!-- 质量分布 -->
            <n-card title="质量分布" size="small" style="margin-bottom: 24px">
              <n-space vertical>
                <div v-for="bar in ocrQualityBars" :key="bar.label" style="display: flex; align-items: center; gap: 12px">
                  <n-text style="width: 140px; flex-shrink: 0">{{ bar.label }}</n-text>
                  <n-progress type="line" :percentage="bar.percentage" :status="bar.status" style="flex: 1" />
                  <n-text depth="3" style="width: 80px; text-align: right">{{ bar.count }} ({{ bar.percentage }}%)</n-text>
                </div>
              </n-space>
            </n-card>

            <!-- 字段命中率 -->
            <n-card title="关键字段命中率" size="small" style="margin-bottom: 24px">
              <n-space vertical>
                <div v-for="(rate, field) in ocrData.field_hit_rates" :key="field" style="display: flex; align-items: center; gap: 12px">
                  <n-text style="width: 120px; flex-shrink: 0">{{ field }}</n-text>
                  <n-progress type="line" :percentage="Math.round(rate * 100)" :status="rate >= 0.8 ? 'success' : rate >= 0.5 ? 'warning' : 'error'" style="flex: 1" />
                  <n-text depth="3" style="width: 50px; text-align: right">{{ (rate * 100).toFixed(1) }}%</n-text>
                </div>
                <n-text v-if="Object.keys(ocrData.field_hit_rates).length === 0" depth="3">暂无含文本材料</n-text>
              </n-space>
            </n-card>

            <!-- 案件明细表 -->
            <n-card title="案件 OCR 明细" size="small">
              <n-data-table
                :columns="ocrCaseColumns"
                :data="ocrData.cases"
                :pagination="{ pageSize: 10 }"
                :row-key="(row: OcrCaseStat) => row.case_id"
                size="small"
                striped
                :expand="ocrExpandConfig"
              />
            </n-card>
          </template>
          <n-empty v-else-if="!ocrLoading" description="暂无数据" style="padding: 40px" />
        </n-spin>
      </n-tab-pane>
    </n-tabs>

    <!-- ═══ 创建/编辑用户 Modal ═══ -->
    <n-modal v-model:show="userModalShow" preset="card" :title="editingUser ? '编辑用户' : '添加用户'" style="width: 500px">
      <n-form
        ref="userFormRef"
        :model="userForm"
        :rules="userFormRules"
        label-placement="left"
        label-width="80"
      >
        <n-form-item label="邮箱" path="email">
          <n-input
            v-model:value="userForm.email"
            placeholder="user@example.com"
            :disabled="!!editingUser"
          />
        </n-form-item>
        <n-form-item v-if="isSuperAdmin" label="所属租户" path="tenant_id">
          <n-select
            v-model:value="userForm.tenant_id"
            :options="tenantSelectOptions"
            placeholder="选择租户"
            filterable
          />
        </n-form-item>
        <n-form-item label="姓名" path="display_name">
          <n-input v-model:value="userForm.display_name" placeholder="显示名称" />
        </n-form-item>
        <n-form-item v-if="!editingUser" label="密码" path="password">
          <n-input v-model:value="userForm.password" type="password" placeholder="至少6位" show-password-on="click" />
        </n-form-item>
        <n-form-item v-else label="新密码" path="password">
          <n-input v-model:value="userForm.password" type="password" placeholder="留空则不修改密码" show-password-on="click" />
        </n-form-item>
        <n-form-item v-if="editingUser?.role !== 'super_admin'" label="角色" path="role">
          <n-select
            v-model:value="userForm.role"
            :options="roleOptions"
          />
        </n-form-item>
        <n-form-item v-else label="角色">
          <n-tag type="error" size="small">超级管理员</n-tag>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="userModalShow = false">取消</n-button>
          <n-button type="primary" :loading="userSaving" @click="submitUserForm">
            {{ editingUser ? '保存' : '创建' }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- ═══ 编辑/创建租户 Modal ═══ -->
    <n-modal v-model:show="tenantModalShow" preset="card" :title="editingTenantId ? '编辑租户' : '添加租户'" style="width: 520px">
      <n-form
        ref="tenantFormRef"
        :model="tenantForm"
        label-placement="left"
        label-width="100"
      >
        <n-form-item label="租户名称">
          <n-input v-model:value="tenantForm.name" placeholder="租户名称" />
        </n-form-item>
        <n-form-item label="套餐">
          <n-select v-model:value="tenantForm.plan" :options="planOptions" />
        </n-form-item>
        <n-form-item label="最大案件数">
          <n-input-number v-model:value="tenantForm.max_cases" :min="0" style="width: 100%" />
        </n-form-item>
        <n-form-item label="最大并发">
          <n-input-number v-model:value="tenantForm.max_concurrent" :min="1" style="width: 100%" />
        </n-form-item>
        <n-form-item label="存储配额(MB)">
          <n-input-number v-model:value="tenantForm.storage_quota_mb" :min="0" style="width: 100%" />
        </n-form-item>
        <n-form-item label="状态">
          <n-select
            v-model:value="tenantForm.status"
            :options="[
              { label: '正常', value: 'active' },
              { label: '已暂停', value: 'suspended' },
            ]"
          />
        </n-form-item>
        <n-form-item label="功能开关">
          <n-space vertical>
            <n-checkbox v-model:checked="tenantFeatures.evidence">
              证据整理
            </n-checkbox>
            <n-checkbox v-model:checked="tenantFeatures.timeline">
              病历时间整理
            </n-checkbox>
          </n-space>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="tenantModalShow = false">取消</n-button>
          <n-button type="primary" :loading="tenantSaving" @click="submitTenantForm">
            {{ editingTenantId ? '保存' : '创建' }}
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted, onBeforeUnmount } from 'vue'
import {
  NTabs, NTabPane, NButton, NIcon, NDataTable, NSpace, NTag, NModal,
  NForm, NFormItem, NInput, NInputNumber, NSelect, NCard, NStatistic,
  NGrid, NGridItem, NProgress, NDescriptions, NDescriptionsItem, NText,
  NSpin, NEmpty, NCheckbox, NAlert, NSwitch, useMessage, useDialog,
  type DataTableColumns, type FormInst, type FormRules,
} from 'naive-ui'
import {
  PersonAddOutline, CreateOutline, TrashOutline, AddOutline,
  BanOutline, CheckmarkCircleOutline, RefreshOutline,
} from '@vicons/ionicons5'
import {
  getUsage, listUsers, createUser, updateUser, disableUser,
  listTenants, getTenantDetail, updateTenant, createTenant,
  getOcrMonitorStats,
  type UserInfo, type UserListItem, type UserCreateRequest, type UserUpdateRequest,
  type TenantListItem, type TenantDetail, type TenantUpdateRequest, type TenantCreateRequest,
  type UsageResponse,
  type OcrMonitorResponse, type OcrCaseStat, type OcrMaterialStat,
} from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { storeToRefs } from 'pinia'

const message = useMessage()
const dialog = useDialog()

// ─── 当前用户信息（使用全局 auth store） ───
const authStore = useAuthStore()
const { userInfo: currentUser, isSuperAdmin } = storeToRefs(authStore)

const activeTab = ref<'users' | 'tenant' | 'usage' | 'ocr'>('users')

// ═══════════════════════════════════════════
//  Tab 1: 用户管理
// ═══════════════════════════════════════════

const userData = ref<UserListItem[]>([])
const usersLoading = ref(false)
const userPage = ref(1)
const userPageSize = 20
const userTotal = ref(0)

const userPagination = computed(() => ({
  page: userPage.value,
  pageSize: userPageSize,
  itemCount: userTotal.value,
  showSizePicker: false,
}))

async function loadUsers(): Promise<void> {
  usersLoading.value = true
  try {
    const res = await listUsers(userPage.value, userPageSize)
    userData.value = res.items
    userTotal.value = res.total
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    usersLoading.value = false
  }
}

function onUserPageChange(page: number): void {
  userPage.value = page
  loadUsers()
}

function roleTagType(role: string): 'error' | 'info' | 'default' {
  if (role === 'super_admin') return 'error'
  if (role === 'tenant_admin') return 'info'
  return 'default'
}

function roleLabel(role: string): string {
  const map: Record<string, string> = {
    super_admin: '超级管理员',
    tenant_admin: '租户管理员',
    member: '普通成员',
  }
  return map[role] || role
}

const userColumns = computed<DataTableColumns<UserListItem>>(() => [
  {
    title: '邮箱',
    key: 'email',
    ellipsis: { tooltip: true },
  },
  {
    title: '姓名',
    key: 'display_name',
  },
  {
    title: '所属租户',
    key: 'tenant_name',
    render(row) {
      return row.tenant_name || '—'
    },
  },
  {
    title: '角色',
    key: 'role',
    render(row) {
      return h(NTag, { type: roleTagType(row.role), size: 'small' }, { default: () => roleLabel(row.role) })
    },
  },
  {
    title: '状态',
    key: 'is_active',
    render(row) {
      return h(
        NTag,
        { type: row.is_active ? 'success' : 'default', size: 'small' },
        { default: () => (row.is_active ? '启用' : '禁用') }
      )
    },
  },
  {
    title: '最后登录',
    key: 'last_login',
    render(row) {
      return row.last_login ? formatDate(row.last_login) : '—'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 220,
    render(row) {
      const actions: ReturnType<typeof h>[] = []
      // 编辑
      actions.push(
        h(
          NButton,
          {
            size: 'tiny',
            quaternary: true,
            type: 'info',
            onClick: () => openEditModal(row),
          },
          {
            icon: () => h(NIcon, null, { default: () => h(CreateOutline) }),
            default: () => '编辑',
          }
        )
      )
      // 禁用/启用（不能操作自己、不能操作 super_admin）
      if (row.id !== currentUser.value?.id && row.role !== 'super_admin') {
        if (row.is_active) {
          actions.push(
            h(
              NButton,
              {
                size: 'tiny',
                quaternary: true,
                type: 'warning',
                onClick: () => confirmDisable(row),
              },
              {
                icon: () => h(NIcon, null, { default: () => h(BanOutline) }),
                default: () => '禁用',
              }
            )
          )
        } else {
          actions.push(
            h(
              NButton,
              {
                size: 'tiny',
                quaternary: true,
                type: 'success',
                onClick: () => enableUser(row),
              },
              {
                icon: () => h(NIcon, null, { default: () => h(CheckmarkCircleOutline) }),
                default: () => '启用',
              }
            )
          )
        }
      }
      // 删除（不能删除自己、不能删除 super_admin）
      if (row.id !== currentUser.value?.id && row.role !== 'super_admin') {
        actions.push(
          h(
            NButton,
            {
              size: 'tiny',
              quaternary: true,
              type: 'error',
              onClick: () => confirmDelete(row),
            },
            {
              icon: () => h(NIcon, null, { default: () => h(TrashOutline) }),
              default: () => '删除',
            }
          )
        )
      }
      return h(NSpace, { size: 'small' }, { default: () => actions })
    },
  },
])

// ─── 用户表单 Modal ───
const userModalShow = ref(false)
const editingUser = ref<UserListItem | null>(null)
const userSaving = ref(false)
const userFormRef = ref<FormInst | null>(null)

interface UserFormState {
  email: string
  display_name: string
  password: string
  role: 'member' | 'tenant_admin' | undefined
  tenant_id: string | null
}

const userForm = ref<UserFormState>({
  email: '',
  display_name: '',
  password: '',
  role: 'member',
  tenant_id: null,
})

const userFormRules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    {
      trigger: 'blur',
      validator: (_rule, value: string) => {
        if (!value) return new Error('请输入邮箱')
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return new Error('邮箱格式不正确')
        return true
      },
    },
  ],
  display_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  password: [
    {
      required: true,
      trigger: 'blur',
      validator(_rule, value: string) {
        if (editingUser.value) return true // 编辑模式不校验密码
        if (!value) return new Error('请输入密码')
        if (value.length < 6) return new Error('密码至少6位')
        return true
      },
    },
  ],
}

const roleOptions = [
  { label: '普通成员', value: 'member' },
  { label: '租户管理员', value: 'tenant_admin' },
]

// ─── 超管创建用户时选择的租户列表 ───
const tenantSelectOptions = ref<{ label: string; value: string }[]>([])

async function loadTenantOptionsForSelect(): Promise<void> {
  try {
    const res = await listTenants(1, 100)
    tenantSelectOptions.value = res.items.map((t) => ({ label: t.name, value: t.id }))
  } catch (e: any) {
    // 静默失败
  }
}

function openCreateModal(): void {
  editingUser.value = null
  // 超管创建用户时默认选第一个租户；租户管理员锁定自己的租户
  userForm.value = {
    email: '',
    display_name: '',
    password: '',
    role: 'member',
    tenant_id: isSuperAdmin.value ? (tenantSelectOptions.value[0]?.value ?? null) : (currentUser.value?.tenant_id ?? null),
  }
  userModalShow.value = true
}

function openEditModal(row: UserListItem): void {
  editingUser.value = row
  userForm.value = {
    email: row.email,
    display_name: row.display_name,
    password: '',
    role: row.role === 'super_admin' ? undefined : (row.role as 'member' | 'tenant_admin'),
    tenant_id: row.tenant_id,
  }
  userModalShow.value = true
}

async function submitUserForm(): Promise<void> {
  try {
    await userFormRef.value?.validate()
  } catch (e: any) {
    return
  }

  userSaving.value = true
  try {
    if (editingUser.value) {
      const payload: UserUpdateRequest = {
        display_name: userForm.value.display_name,
      }
      // super_admin 不发 role（后端不允许修改角色）
      if (editingUser.value.role !== 'super_admin') {
        payload.role = userForm.value.role
      }
      if (userForm.value.password) {
        payload.password = userForm.value.password
      }
      // 超管编辑时可修改用户所属租户
      if (isSuperAdmin.value && userForm.value.tenant_id) {
        payload.tenant_id = userForm.value.tenant_id
      }
      await updateUser(editingUser.value.id, payload)
      message.success('用户已更新')
    } else {
      const payload: UserCreateRequest = {
        email: userForm.value.email,
        display_name: userForm.value.display_name,
        password: userForm.value.password,
        role: userForm.value.role || 'member',
      }
      // 超管指定租户；租户管理员后端自动绑定自己的租户
      if (isSuperAdmin.value && userForm.value.tenant_id) {
        payload.tenant_id = userForm.value.tenant_id
      }
      await createUser(payload)
      message.success('用户已创建')
    }
    userModalShow.value = false
    loadUsers()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    userSaving.value = false
  }
}

function confirmDelete(row: UserListItem): void {
  dialog.error({
    title: '确认删除',
    content: `确定要删除用户 "${row.display_name}" (${row.email}) 吗？此操作不可恢复，该用户将被永久清除。`,
    positiveText: '确认删除',
    negativeText: '取消',
    async onPositiveClick() {
      try {
        await disableUser(row.id)
        message.success('用户已删除')
        loadUsers()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function confirmDisable(row: UserListItem): void {
  dialog.warning({
    title: '确认禁用',
    content: `确定要禁用用户 "${row.display_name}" (${row.email}) 吗？禁用后该用户将无法登录，但数据保留。可随时重新启用。`,
    positiveText: '确认禁用',
    negativeText: '取消',
    async onPositiveClick() {
      try {
        await updateUser(row.id, { is_active: false })
        message.success('用户已禁用')
        loadUsers()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

async function enableUser(row: UserListItem): Promise<void> {
  try {
    await updateUser(row.id, { is_active: true })
    message.success('用户已启用')
    loadUsers()
  } catch (err) {
    message.error((err as Error).message)
  }
}

// ═══════════════════════════════════════════
//  Tab 2: 租户信息
// ═══════════════════════════════════════════

const tenantData = ref<TenantListItem[]>([])
const tenantsLoading = ref(false)
const tenantPage = ref(1)
const tenantPageSize = 20
const tenantTotal = ref(0)
const tenantDetail = ref<TenantDetail | null>(null)
const tenantDetailLoading = ref(false)

const tenantPagination = computed(() => ({
  page: tenantPage.value,
  pageSize: tenantPageSize,
  itemCount: tenantTotal.value,
  showSizePicker: false,
}))

const planOptions = [
  { label: '免费版', value: 'free' },
  { label: '专业版', value: 'pro' },
  { label: '企业版', value: 'enterprise' },
]

function planLabel(plan: string): string {
  const map: Record<string, string> = { free: '免费版', pro: '专业版', enterprise: '企业版' }
  return map[plan] || plan
}

function planTagType(plan: string): 'default' | 'info' | 'success' {
  if (plan === 'enterprise') return 'success'
  if (plan === 'pro') return 'info'
  return 'default'
}

const tenantColumns = computed<DataTableColumns<TenantListItem>>(() => [
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '套餐',
    key: 'plan',
    render(row) {
      return h(NTag, { type: planTagType(row.plan), size: 'small' }, { default: () => planLabel(row.plan) })
    },
  },
  { title: '用户数', key: 'user_count', width: 80 },
  { title: '案件数', key: 'case_count', width: 80 },
  { title: '最大案件', key: 'max_cases', width: 90 },
  { title: '存储用量', key: 'storage', render(row) { return `${formatMB(row.storage_used_mb)} / ${formatMB(row.storage_quota_mb)}` } },
  {
    title: '状态',
    key: 'status',
    render(row) {
      return h(NTag, { type: row.status === 'active' ? 'success' : 'error', size: 'small' }, {
        default: () => (row.status === 'active' ? '正常' : '已暂停'),
      })
    },
  },
  {
    title: '功能',
    key: 'features',
    render(row) {
      const tags: ReturnType<typeof h>[] = []
      if (row.features?.evidence) tags.push(h(NTag, { size: 'small', type: 'info' }, { default: () => '证据整理' }))
      if (row.features?.timeline) tags.push(h(NTag, { size: 'small', type: 'success' }, { default: () => '时间整理' }))
      if (!tags.length) tags.push(h(NTag, { size: 'small' }, { default: () => '无' }))
      return h(NSpace, { size: 4 }, { default: () => tags })
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    render(row) {
      return h(
        NButton,
        { size: 'tiny', quaternary: true, type: 'info', onClick: () => openTenantEditModal(row) },
        {
          icon: () => h(NIcon, null, { default: () => h(CreateOutline) }),
          default: () => '编辑',
        }
      )
    },
  },
])

async function loadTenants(): Promise<void> {
  tenantsLoading.value = true
  try {
    const res = await listTenants(tenantPage.value, tenantPageSize)
    tenantData.value = res.items
    tenantTotal.value = res.total
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    tenantsLoading.value = false
  }
}

function onTenantPageChange(page: number): void {
  tenantPage.value = page
  loadTenants()
}

async function loadTenantDetail(): Promise<void> {
  if (!currentUser.value?.tenant_id) return
  tenantDetailLoading.value = true
  try {
    tenantDetail.value = await getTenantDetail(currentUser.value.tenant_id)
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    tenantDetailLoading.value = false
  }
}

// ─── 租户编辑 Modal ───
const tenantModalShow = ref(false)
const tenantSaving = ref(false)
const editingTenantId = ref<string>('')

const tenantForm = ref<TenantUpdateRequest>({
  name: '',
  plan: 'free',
  max_cases: 20,
  max_concurrent: 2,
  storage_quota_mb: 2048,
  status: 'active',
})

const tenantFeatures = ref<{ evidence: boolean; timeline: boolean }>({
  evidence: true,
  timeline: false,
})

function openTenantEditModal(row: TenantListItem): void {
  editingTenantId.value = row.id
  tenantForm.value = {
    name: row.name,
    plan: row.plan as 'free' | 'pro' | 'enterprise',
    max_cases: row.max_cases,
    max_concurrent: row.max_concurrent,
    storage_quota_mb: row.storage_quota_mb,
    status: row.status as 'active' | 'suspended',
  }
  tenantFeatures.value = {
    evidence: row.features?.evidence ?? true,
    timeline: row.features?.timeline ?? false,
  }
  tenantModalShow.value = true
}

function openTenantCreateModal(): void {
  editingTenantId.value = ''
  tenantForm.value = {
    name: '',
    plan: 'free',
    max_cases: 20,
    max_concurrent: 2,
    storage_quota_mb: 2048,
    status: 'active',
  }
  tenantFeatures.value = { evidence: true, timeline: false }
  tenantModalShow.value = true
}

async function submitTenantForm(): Promise<void> {
  if (!tenantForm.value.name || !tenantForm.value.name.trim()) {
    message.warning('请输入租户名称')
    return
  }
  tenantSaving.value = true
  try {
    // 将功能开关合并到表单数据中
    tenantForm.value.features = { ...tenantFeatures.value }

    if (editingTenantId.value) {
      await updateTenant(editingTenantId.value, tenantForm.value)
      message.success('租户配置已更新')
    } else {
      await createTenant(tenantForm.value as TenantCreateRequest)
      message.success('租户已创建')
    }
    tenantModalShow.value = false
    loadTenants()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    tenantSaving.value = false
  }
}

// ═══════════════════════════════════════════
//  Tab 3: 使用量
// ═══════════════════════════════════════════

const usageData = ref<UsageResponse | null>(null)
const usageLoading = ref(false)

async function loadUsage(): Promise<void> {
  usageLoading.value = true
  try {
    usageData.value = await getUsage()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    usageLoading.value = false
  }
}

function usagePercent(type: 'evidence' | 'storage' | 'concurrent'): number {
  if (!usageData.value) return 0
  const u = usageData.value.usage
  const t = usageData.value.tenant
  if (type === 'evidence') {
    return t.max_cases > 0 ? Math.min(100, Math.round((u.evidence_cases / t.max_cases) * 100)) : 0
  }
  if (type === 'storage') {
    return u.storage_quota_mb > 0 ? Math.min(100, Math.round((u.storage_used_mb / u.storage_quota_mb) * 100)) : 0
  }
  // concurrent
  return u.concurrent_max > 0 ? Math.min(100, Math.round((u.concurrent_used / u.concurrent_max) * 100)) : 0
}

function progressStatus(percent: number): 'success' | 'warning' | 'error' {
  if (percent >= 90) return 'error'
  if (percent >= 70) return 'warning'
  return 'success'
}

// ═══════════════════════════════════════════
//  工具函数
// ═══════════════════════════════════════════

function formatMB(mb: number): string {
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB'
  return mb + ' MB'
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN')
}

// ─── Tab 切换 ───
function onTabChange(tab: string): void {
  if (tab === 'users') loadUsers()
  else if (tab === 'tenant') {
    if (isSuperAdmin.value) loadTenants()
    else loadTenantDetail()
  }
  else if (tab === 'usage') loadUsage()
  else if (tab === 'ocr') {
    if (!ocrData.value) loadOcrMonitor()
  }
}

// ═══════════════════════════════════════════
//  Tab 4: OCR 监控（仅 super_admin）
// ═══════════════════════════════════════════
const ocrLoading = ref(false)
const ocrError = ref('')
const ocrData = ref<OcrMonitorResponse | null>(null)

// ─── 自动刷新（默认关闭，默认间隔 2 分钟）───
const ocrAutoRefresh = ref(false)
const ocrRefreshInterval = ref(120) // 秒
const ocrIntervalOptions = [
  { label: '30 秒', value: 30 },
  { label: '1 分钟', value: 60 },
  { label: '2 分钟', value: 120 },
  { label: '5 分钟', value: 300 },
]
let ocrRefreshTimer: ReturnType<typeof setInterval> | null = null

function stopOcrAutoRefresh(): void {
  if (ocrRefreshTimer !== null) {
    clearInterval(ocrRefreshTimer)
    ocrRefreshTimer = null
  }
}

function startOcrAutoRefresh(): void {
  stopOcrAutoRefresh()
  ocrRefreshTimer = setInterval(() => {
    // 仅在 OCR Tab 激活且非加载中时刷新，避免无谓请求
    if (activeTab.value === 'ocr' && !ocrLoading.value) {
      loadOcrMonitor()
    }
  }, ocrRefreshInterval.value * 1000)
}

function onOcrAutoRefreshToggle(val: boolean): void {
  if (val) startOcrAutoRefresh()
  else stopOcrAutoRefresh()
}

function onOcrIntervalChange(): void {
  if (ocrAutoRefresh.value) startOcrAutoRefresh()
}

const ocrQualityBars = computed(() => {
  if (!ocrData.value) return []
  const total = ocrData.value.total_materials
  const dist = ocrData.value.quality_distribution
  const items = [
    { label: '高质量 (≥90%)', count: dist.high, status: 'success' as const },
    { label: '中等 (60%~90%)', count: dist.medium, status: 'warning' as const },
    { label: '低质量 (<60%)', count: dist.low, status: 'error' as const },
    { label: '无数据', count: dist.no_data, status: 'default' as const },
  ]
  return items.map(item => ({
    ...item,
    percentage: total > 0 ? Math.round((item.count / total) * 100) : 0,
  }))
})

const ocrExpandedRowKeys = ref<string[]>([])
const ocrExpandConfig = {
  expandedRowKeys: ocrExpandedRowKeys,
  renderExpand: (rowData: OcrCaseStat) => {
    if (!rowData.materials || rowData.materials.length === 0) {
      return h(NEmpty, { description: '无材料', size: 'small' })
    }
    const matColumns: DataTableColumns<OcrMaterialStat> = [
      { title: '文件名', key: 'filename', render: (r: OcrMaterialStat) => r.filename || '—', ellipsis: { tooltip: true } },
      { title: '类型', key: 'file_type', width: 80 },
      { title: '分类', key: 'effective_category', width: 120, render: (r: OcrMaterialStat) => r.effective_category || '—' },
      { title: '状态', key: 'ocr_status', width: 100, render: (r: OcrMaterialStat) => ocrStatusTag(r.ocr_status) },
      { title: '来源', key: 'source_type', width: 100, render: (r: OcrMaterialStat) => r.source_type || '—' },
      { title: 'Block数', key: 'block_count', width: 80 },
      { title: '平均置信度', key: 'avg_confidence', width: 110, render: (r: OcrMaterialStat) => ocrConfidenceText(r.avg_confidence) },
      { title: '最低置信度', key: 'min_confidence', width: 110, render: (r: OcrMaterialStat) => ocrConfidenceText(r.min_confidence) },
      {
        title: '低置信块', key: 'low_conf_count', width: 90,
        render: (r: OcrMaterialStat) => r.low_conf_count > 0 ? h(NText, { type: 'error' }, { default: () => String(r.low_conf_count) }) : '0',
      },
      { title: '字符数', key: 'char_count', width: 80 },
    ]
    return h(NDataTable, {
      columns: matColumns,
      data: rowData.materials,
      size: 'small',
      pagination: false,
      striped: true,
      'row-key': (r: OcrMaterialStat) => r.material_id,
    })
  },
}

const ocrCaseColumns: DataTableColumns<OcrCaseStat> = [
  { title: '案件名称', key: 'case_name', ellipsis: { tooltip: true }, minWidth: 200 },
  { title: '类型', key: 'case_type', width: 80, render: (r: OcrCaseStat) => `${r.case_type}${r.is_minor ? '(未成年)' : ''}` },
  { title: '租户', key: 'tenant_name', width: 120, render: (r: OcrCaseStat) => r.tenant_name || '—' },
  { title: '材料数', key: 'material_count', width: 80, align: 'center' },
  {
    title: '已完成', key: 'ocr_completed', width: 80, align: 'center',
    render: (r: OcrCaseStat) => h(NText, { type: 'success' }, { default: () => String(r.ocr_completed) }),
  },
  {
    title: '失败', key: 'ocr_failed', width: 80, align: 'center',
    render: (r: OcrCaseStat) => r.ocr_failed > 0 ? h(NText, { type: 'error' }, { default: () => String(r.ocr_failed) }) : '0',
  },
  {
    title: '平均置信度', key: 'avg_confidence', width: 120, align: 'center',
    render: (r: OcrCaseStat) => ocrConfidenceText(r.avg_confidence),
  },
  {
    title: '低质量材料', key: 'low_quality_count', width: 110, align: 'center',
    render: (r: OcrCaseStat) => r.low_quality_count > 0 ? h(NText, { type: 'error', strong: true }, { default: () => String(r.low_quality_count) }) : '0',
  },
]

function ocrStatusTag(status: string) {
  const map: Record<string, 'success' | 'error' | 'warning' | 'default'> = {
    completed: 'success', failed: 'error', processing: 'warning',
    pending: 'warning', skipped: 'default', not_applicable: 'default',
  }
  return h(NTag, { size: 'small', type: map[status] || 'default', round: true, bordered: false }, { default: () => status })
}

function ocrConfidenceText(conf: number | null) {
  if (conf === null || conf === undefined) return h(NText, { depth: 3 }, { default: () => '—' })
  const pct = (conf * 100).toFixed(2) + '%'
  const type = conf >= 0.9 ? 'success' : conf >= 0.6 ? 'warning' : 'error'
  return h(NText, { type, strong: conf < 0.6 }, { default: () => pct })
}

function formatOcrTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}

async function loadOcrMonitor(): Promise<void> {
  ocrLoading.value = true
  ocrError.value = ''
  try {
    ocrData.value = await getOcrMonitorStats()
  } catch (e: unknown) {
    ocrError.value = (e as Error).message || '加载失败'
  } finally {
    ocrLoading.value = false
  }
}

// ─── 初始化 ───
onMounted(async () => {
  // 加载当前用户信息（共享 auth store，避免重复请求）
  await authStore.loadUserInfo()

  // 超管预加载租户列表（用于创建用户时选择）
  if (isSuperAdmin.value) {
    loadTenantOptionsForSelect()
  }

  // 默认加载用户列表
  loadUsers()
})

// 组件卸载时清理自动刷新定时器，防止内存泄漏
onBeforeUnmount(() => {
  stopOcrAutoRefresh()
})
</script>
