<template>
  <n-layout has-sider position="absolute" style="height: 100vh">
    <!-- 侧边栏 -->
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="200"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <n-menu
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        :options="menuOptions"
        :value="activeMenu"
        :expanded-keys="expandedKeys"
        @update:value="onMenuSelect"
        @update:expanded-keys="(keys: string[]) => expandedKeys = keys"
      />
    </n-layout-sider>

    <n-layout>
      <!-- 顶栏 -->
      <n-layout-header bordered style="height: 48px; display: flex; align-items: center; padding: 0 16px">
        <n-text strong style="font-size: 16px">ScanStruct</n-text>
        <n-space v-if="isOcrModule" style="margin-left: 40px">
          <n-button size="small" quaternary @click="refreshCurrent">
            <template #icon><n-icon><RefreshOutline /></n-icon></template>
            刷新
          </n-button>
        </n-space>
        <!-- 用户信息 + 退出 -->
        <n-space align="center" style="margin-left: auto">
          <n-button size="small" quaternary @click="router.push('/profile')">
            <template #icon><n-icon><PersonCircleOutline /></n-icon></template>
            {{ userInfo?.display_name || '个人中心' }}
          </n-button>
          <n-tag v-if="userInfo?.tenant_name" size="small" round :bordered="false" type="info">
            {{ userInfo.tenant_name }}
          </n-tag>
          <n-button size="small" quaternary type="error" @click="handleLogout">
            <template #icon><n-icon><LogOutOutline /></n-icon></template>
            退出
          </n-button>
        </n-space>
      </n-layout-header>

      <!-- 内容区 -->
      <n-layout-content
        style="padding: 24px; overflow-y: auto"
        class="admin-content"
        :native-scrollbar="false"
      >
        <router-view v-slot="{ Component }">
          <component :is="Component" :key="$route.fullPath" />
        </router-view>
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { ref, computed, h, watch, onMounted, type Component } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NLayout,
  NLayoutSider,
  NLayoutHeader,
  NLayoutContent,
  NMenu,
  NButton,
  NIcon,
  NSpace,
  NTag,
} from 'naive-ui'
import {
  SpeedometerOutline,
  StatsChartOutline,
  ListOutline,
  CloudUploadOutline,
  DocumentTextOutline,
  CloudDownloadOutline,
  RefreshOutline,
  DocumentOutline,
  FolderOpenOutline,
  CreateOutline,
  ScanOutline,
  TimeOutline,
  LogOutOutline,
  SettingsOutline,
  PersonCircleOutline,
} from '@vicons/ionicons5'
import { isLoggedIn, clearTokens } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { storeToRefs } from 'pinia'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)

function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const baseMenuOptions = computed(() => {
  const features = userInfo.value?.features
  const role = userInfo.value?.role
  // super_admin 或 features 为 null 时全部显示
  const showAll = !features || role === 'super_admin'

  const options: Array<Record<string, unknown>> = []

  // 概览 — 仅 admin 角色（super_admin / tenant_admin）显示
  if (role === 'super_admin' || role === 'tenant_admin') {
    options.push({ label: '概览', key: '/dashboard', icon: renderIcon(SpeedometerOutline) })
  }

  // 用量 — 所有用户都显示
  options.push({ label: '用量', key: '/usage', icon: renderIcon(StatsChartOutline) })

  options.push({
    label: '普通OCR处理',
    key: 'ocr-group',
    icon: renderIcon(ScanOutline),
    children: [
      { label: '任务列表', key: '/tasks', icon: renderIcon(ListOutline) },
      { label: '上传', key: '/upload', icon: renderIcon(CloudUploadOutline) },
      { label: '处理文档', key: '/process', icon: renderIcon(DocumentTextOutline) },
      { label: '下载中心', key: '/download', icon: renderIcon(CloudDownloadOutline) },
      { label: '模板管理', key: '/templates', icon: renderIcon(DocumentOutline) },
    ],
  })

  if (showAll || features.evidence !== false) {
    options.push({
      label: '证据整理',
      key: 'evidence-group',
      icon: renderIcon(FolderOpenOutline),
      children: [
        { label: '诉状生成', key: '/evidence', icon: renderIcon(CreateOutline) },
      ],
    })
  }

  if (showAll || features.timeline !== false) {
    options.push({
      label: '病历时间整理',
      key: 'timeline-group',
      icon: renderIcon(TimeOutline),
      children: [
        { label: '（即将上线）', key: '/timeline-placeholder', disabled: true },
      ],
    })
  }

  return options
})

const adminMenuItem = {
  label: '管理后台',
  key: '/admin',
  icon: renderIcon(SettingsOutline),
}

// 根据用户角色动态生成菜单（admin 角色才显示管理后台入口）
const menuOptions = computed(() => {
  const isAdmin = userInfo.value?.role === 'tenant_admin' || userInfo.value?.role === 'super_admin'
  return isAdmin ? [...baseMenuOptions.value, adminMenuItem] : baseMenuOptions.value
})

const activeMenu = computed(() => {
  if (route.path.startsWith('/evidence')) return '/evidence'
  if (route.path.startsWith('/usage')) return '/usage'
  if (route.path.startsWith('/tasks')) return '/tasks'
  if (route.path.startsWith('/upload')) return '/upload'
  if (route.path.startsWith('/process')) return '/process'
  if (route.path.startsWith('/download')) return '/download'
  if (route.path.startsWith('/templates')) return '/templates'
  if (route.path.startsWith('/admin')) return '/admin'
  return route.path
})

// 判断当前是否在普通OCR处理模块中
const isOcrModule = computed(() => {
  const ocrPaths = ['/tasks', '/upload', '/process', '/download', '/templates']
  return ocrPaths.some(p => route.path.startsWith(p))
})

// 自动展开包含当前路由的父菜单
const expandedKeys = ref<string[]>([])
watch(activeMenu, (key) => {
  if (key === '/evidence') {
    if (!expandedKeys.value.includes('evidence-group')) expandedKeys.value.push('evidence-group')
  } else if (['/tasks', '/upload', '/process', '/download', '/templates'].includes(key)) {
    if (!expandedKeys.value.includes('ocr-group')) expandedKeys.value.push('ocr-group')
  }
}, { immediate: true })

function onMenuSelect(key: string) {
  // 忽略分组key和占位符
  if (key === 'evidence-group' || key === 'ocr-group' || key === 'timeline-group') return
  if (key === '/timeline-placeholder') return
  router.push(key)
}

function refreshCurrent() {
  router.replace({ path: route.fullPath, query: { ...route.query, _t: Date.now() } })
}

// ─── 用户信息 + 退出 ───
const authStore = useAuthStore()
const { userInfo } = storeToRefs(authStore)

async function loadUserInfo() {
  if (!isLoggedIn()) return
  const info = await authStore.loadUserInfo()
  if (!info) {
    clearTokens()
    router.push('/login')
    return
  }
  // 非 admin 用户默认跳转到用量页面（概览页面对他们不可见）
  if (info.role === 'member' && route.path === '/dashboard') {
    router.replace('/usage')
  }
}

function handleLogout() {
  // 主动退出时清理 token
  clearTokens()
  authStore.clear()
  router.push('/login')
}

onMounted(loadUserInfo)
</script>

<style scoped>
@media (max-width: 768px) {
  .admin-content {
    padding: 12px !important;
  }
}
</style>
