<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <div class="login-logo">S</div>
        <h1 class="login-title">ScanStruct</h1>
        <p class="login-subtitle">扫描件智能结构化处理系统</p>
      </div>

      <n-tabs v-model:value="activeTab" type="segment" animated size="large">
        <!-- 登录 -->
        <n-tab-pane name="login" tab="登录">
          <n-form ref="loginFormRef" :model="loginForm" :rules="loginRules" label-placement="top" size="large">
            <n-form-item label="邮箱" path="email">
              <n-input v-model:value="loginForm.email" placeholder="请输入邮箱" :input-props="{ type: 'email' }" @keyup.enter="handleLogin" />
            </n-form-item>
            <n-form-item label="密码" path="password">
              <n-input v-model:value="loginForm.password" type="password" show-password-on="click" placeholder="请输入密码" @keyup.enter="handleLogin" />
            </n-form-item>
            <n-button
              type="primary"
              block
              size="large"
              :loading="loading"
              :disabled="loading"
              strong
              round
              style="margin-top: 8px; height: 44px; font-size: 16px; font-weight: 600;"
              @click="handleLogin"
            >
              登录
            </n-button>
          </n-form>
        </n-tab-pane>

        <!-- 注册 -->
        <n-tab-pane name="register" tab="注册">
          <n-form ref="registerFormRef" :model="registerForm" :rules="registerRules" label-placement="top" size="large">
            <n-form-item label="组织名称" path="tenant_name">
              <n-input v-model:value="registerForm.tenant_name" placeholder="律所/公司名称" />
            </n-form-item>
            <n-form-item label="邮箱" path="email">
              <n-input v-model:value="registerForm.email" placeholder="邮箱地址" :input-props="{ type: 'email' }" />
            </n-form-item>
            <n-form-item label="姓名" path="display_name">
              <n-input v-model:value="registerForm.display_name" placeholder="您的姓名" />
            </n-form-item>
            <n-form-item label="密码" path="password">
              <n-input v-model:value="registerForm.password" type="password" show-password-on="click" placeholder="至少6位" @keyup.enter="handleRegister" />
            </n-form-item>
            <n-button
              type="primary"
              block
              size="large"
              :loading="loading"
              :disabled="loading"
              strong
              round
              style="margin-top: 8px; height: 44px; font-size: 16px; font-weight: 600;"
              @click="handleRegister"
            >
              注册
            </n-button>
          </n-form>
        </n-tab-pane>
      </n-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NTabs,
  NTabPane,
  NForm,
  NFormItem,
  NInput,
  NButton,
  useMessage,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { post, setTokens, isLoggedIn, type TokenResponse } from '@/api/client'

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const activeTab = ref<'login' | 'register'>('login')

// ─── 登录 ───
const loginFormRef = ref<FormInst | null>(null)
const loginForm = reactive({
  email: '',
  password: '',
})
const loginRules: FormRules = {
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  try {
    await loginFormRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    const res = await post<TokenResponse>('/auth/login', loginForm)
    setTokens(res.access_token, res.refresh_token)
    message.success(`欢迎回来，${res.user.display_name}`)
    router.push('/dashboard')
  } catch (e: unknown) {
    const errMsg = e instanceof Error ? e.message : '登录失败，请重试'
    message.error(errMsg)
  } finally {
    loading.value = false
  }
}

// ─── 注册 ───
const registerFormRef = ref<FormInst | null>(null)
const registerForm = reactive({
  tenant_name: '',
  email: '',
  display_name: '',
  password: '',
})
const registerRules: FormRules = {
  tenant_name: [{ required: true, message: '请输入组织名称', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  display_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
  ],
}

async function handleRegister() {
  try {
    await registerFormRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    const res = await post<TokenResponse>('/auth/register', registerForm)
    setTokens(res.access_token, res.refresh_token)
    message.success(`注册成功，欢迎 ${res.user.display_name}`)
    router.push('/dashboard')
  } catch (e: unknown) {
    const errMsg = e instanceof Error ? e.message : '注册失败，请重试'
    message.error(errMsg)
  } finally {
    loading.value = false
  }
}

// 已登录则跳转
onMounted(() => {
  if (isLoggedIn()) {
    router.push('/dashboard')
  }
})
</script>

<style scoped>
.login-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}

.login-card {
  width: 420px;
  max-width: 90vw;
  background: #fff;
  border-radius: 16px;
  padding: 40px 36px 32px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 14px;
  color: #fff;
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 16px;
}

.login-title {
  font-size: 28px;
  font-weight: 800;
  color: #1a1a2e;
  margin: 0 0 8px;
}

.login-subtitle {
  font-size: 14px;
  color: #888;
  margin: 0;
}

:deep(.n-tabs .n-tabs-tab) {
  font-size: 15px;
  font-weight: 500;
}

:deep(.n-form-item-label) {
  font-weight: 500;
}
</style>
