<template>
  <div style="max-width: 600px; margin: 0 auto;">
    <n-h2>个人中心</n-h2>

    <!-- 基本信息 -->
    <n-card title="基本信息" style="margin-bottom: 24px;">
      <n-form label-placement="left" label-width="80">
        <n-form-item label="邮箱">
          <n-input :value="userInfo?.email || ''" disabled />
        </n-form-item>
        <n-form-item label="角色">
          <n-tag :type="roleTagType" size="small" round>{{ roleLabel }}</n-tag>
        </n-form-item>
        <n-form-item label="组织">
          <n-input :value="userInfo?.tenant_name || ''" disabled />
        </n-form-item>
        <n-form-item label="姓名">
          <n-input v-model:value="displayName" placeholder="请输入姓名" />
        </n-form-item>
        <n-space>
          <n-button type="primary" :loading="savingProfile" @click="handleSaveProfile">
            保存
          </n-button>
        </n-space>
      </n-form>
    </n-card>

    <!-- 修改密码 -->
    <n-card title="修改密码">
      <n-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-placement="left" label-width="100">
        <n-form-item label="当前密码" path="old_password">
          <n-input v-model:value="pwdForm.old_password" type="password" show-password-on="click" placeholder="请输入当前密码" />
        </n-form-item>
        <n-form-item label="新密码" path="new_password">
          <n-input v-model:value="pwdForm.new_password" type="password" show-password-on="click" placeholder="至少6位" />
        </n-form-item>
        <n-form-item label="确认新密码" path="confirm_password">
          <n-input v-model:value="pwdForm.confirm_password" type="password" show-password-on="click" placeholder="再次输入新密码" />
        </n-form-item>
        <n-space>
          <n-button type="primary" :loading="savingPwd" @click="handleChangePassword">
            修改密码
          </n-button>
        </n-space>
      </n-form>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import {
  NH2, NCard, NForm, NFormItem, NInput, NButton, NSpace, NTag,
  useMessage, type FormInst, type FormRules,
} from 'naive-ui'
import { changePassword, updateProfile } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { storeToRefs } from 'pinia'

const message = useMessage()

const authStore = useAuthStore()
const { userInfo } = storeToRefs(authStore)
const displayName = ref('')

async function loadUserInfo() {
  const info = await authStore.loadUserInfo()
  if (info) displayName.value = info.display_name
}

onMounted(loadUserInfo)

// ─── 保存个人信息 ───
const savingProfile = ref(false)

async function handleSaveProfile() {
  if (!displayName.value.trim()) {
    message.warning('请输入姓名')
    return
  }
  savingProfile.value = true
  try {
    await updateProfile(displayName.value.trim())
    message.success('保存成功')
    await loadUserInfo()
  } catch (e: unknown) {
    message.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingProfile.value = false
  }
}

// ─── 修改密码 ───
const pwdFormRef = ref<FormInst | null>(null)
const pwdForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const pwdRules: FormRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string) => value === pwdForm.new_password,
      message: '两次密码不一致',
      trigger: 'blur',
    },
  ],
}

const savingPwd = ref(false)

async function handleChangePassword() {
  try {
    await pwdFormRef.value?.validate()
  } catch (e: any) {
    return
  }
  savingPwd.value = true
  try {
    await changePassword(pwdForm.old_password, pwdForm.new_password)
    message.success('密码修改成功')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm_password = ''
  } catch (e: unknown) {
    message.error(e instanceof Error ? e.message : '密码修改失败')
  } finally {
    savingPwd.value = false
  }
}

// ─── 角色显示 ───
const roleLabel = computed(() => {
  const map: Record<string, string> = {
    super_admin: '超级管理员',
    tenant_admin: '租户管理员',
    member: '普通成员',
  }
  return map[userInfo.value?.role || ''] || userInfo.value?.role || ''
})

const roleTagType = computed(() => {
  const map: Record<string, 'error' | 'info' | 'default'> = {
    super_admin: 'error',
    tenant_admin: 'info',
    member: 'default',
  }
  return map[userInfo.value?.role || ''] || 'default'
})
</script>
