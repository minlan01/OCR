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
        <n-form-item label="姓名" path="display_name">
          <n-input v-model:value="userForm.display_name" placeholder="显示名称" />
        </n-form-item>
        <n-form-item v-if="!editingUser" label="密码" path="password">
          <n-input v-model:value="userForm.password" type="password" placeholder="至少6位" show-password-on="click" />
        </n-form-item>
        <n-form-item v-else label="新密码" path="password">
          <n-input v-model:value="userForm.password" type="password" placeholder="留空则不修改密码" show-password-on="click" />
        </n-form-item>
        <n-form-item label="角色" path="role">
          <n-select
            v-model:value="userForm.role"
            :options="roleOptions"
            :disabled="editingUser?.role === 'super_admin'"
          />
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
import { ref, computed, h, onMounted } from 'vue'
import {
  NTabs, NTabPane, NButton, NIcon, NDataTable, NSpace, NTag, NModal,
  NForm, NFormItem, NInput, NInputNumber, NSelect, NCard, NStatistic,
  NGrid, NGridItem, NProgress, NDescriptions, NDescriptionsItem, NText,
  NSpin, NEmpty, useMessage, useDialog,
  type DataTableColumns, type FormInst, type FormRules,
} from 'naive-ui'
import {
  PersonAddOutline, CreateOutline, TrashOutline, AddOutline,
} from '@vicons/ionicons5'
import {
  getUsage, listUsers, createUser, updateUser, disableUser,
  listTenants, getTenantDetail, updateTenant, createTenant,
  type UserInfo, type UserListItem, type UserCreateRequest, type UserUpdateRequest,
  type TenantListItem, type TenantDetail, type TenantUpdateRequest, type TenantCreateRequest,
  type UsageResponse,
} from '@/api/client'

const message = useMessage()
const dialog = useDialog()

// ─── 当前用户信息 ───
const currentUser = ref<UserInfo | null>(null)
const isSuperAdmin = computed(() => currentUser.value?.role === 'super_admin')

const activeTab = ref<'users' | 'tenant' | 'usage'>('users')

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
    width: 160,
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
      // 禁用（不能禁用自己、不能禁用 super_admin）
      if (row.id !== currentUser.value?.id && row.role !== 'super_admin' && row.is_active) {
        actions.push(
          h(
            NButton,
            {
              size: 'tiny',
              quaternary: true,
              type: 'error',
              onClick: () => confirmDisable(row),
            },
            {
              icon: () => h(NIcon, null, { default: () => h(TrashOutline) }),
              default: () => '禁用',
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
  role: 'member' | 'tenant_admin'
}

const userForm = ref<UserFormState>({
  email: '',
  display_name: '',
  password: '',
  role: 'member',
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

function openCreateModal(): void {
  editingUser.value = null
  userForm.value = { email: '', display_name: '', password: '', role: 'member' }
  userModalShow.value = true
}

function openEditModal(row: UserListItem): void {
  editingUser.value = row
  userForm.value = {
    email: row.email,
    display_name: row.display_name,
    password: '',
    role: row.role === 'super_admin' ? 'member' : (row.role as 'member' | 'tenant_admin'),
  }
  userModalShow.value = true
}

async function submitUserForm(): Promise<void> {
  try {
    await userFormRef.value?.validate()
  } catch {
    return
  }

  userSaving.value = true
  try {
    if (editingUser.value) {
      const payload: UserUpdateRequest = {
        display_name: userForm.value.display_name,
        role: userForm.value.role,
      }
      if (userForm.value.password) {
        payload.password = userForm.value.password
      }
      await updateUser(editingUser.value.id, payload)
      message.success('用户已更新')
    } else {
      const payload: UserCreateRequest = {
        email: userForm.value.email,
        display_name: userForm.value.display_name,
        password: userForm.value.password,
        role: userForm.value.role,
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

function confirmDisable(row: UserListItem): void {
  dialog.warning({
    title: '确认禁用',
    content: `确定要禁用用户 "${row.display_name}" (${row.email}) 吗？禁用后该用户将无法登录。`,
    positiveText: '确认禁用',
    negativeText: '取消',
    async onPositiveClick() {
      try {
        await disableUser(row.id)
        message.success('用户已禁用')
        loadUsers()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
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
  tenantModalShow.value = true
}

async function submitTenantForm(): Promise<void> {
  if (!tenantForm.value.name || !tenantForm.value.name.trim()) {
    message.warning('请输入租户名称')
    return
  }
  tenantSaving.value = true
  try {
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
}

// ─── 初始化 ───
onMounted(async () => {
  // 加载当前用户信息
  try {
    const { get } = await import('@/api/client')
    currentUser.value = await get<UserInfo>('/auth/me')
  } catch {
    // 拦截器会处理
  }

  // 默认加载用户列表
  loadUsers()
})
</script>
