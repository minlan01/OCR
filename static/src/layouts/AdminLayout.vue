<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
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
        <n-message-provider>
        <n-dialog-provider>
        <!-- 顶栏 -->
        <n-layout-header bordered style="height: 48px; display: flex; align-items: center; padding: 0 16px">
          <n-text strong style="font-size: 16px">ScanStruct Admin</n-text>
          <n-space v-if="isOcrModule" style="margin-left: auto">
            <n-button size="small" quaternary @click="refreshCurrent">
              <template #icon><n-icon><RefreshOutline /></n-icon></template>
              刷新
            </n-button>
          </n-space>
        </n-layout-header>

        <!-- 内容区 -->
        <n-layout-content
          style="padding: 24px; overflow-y: auto"
          :native-scrollbar="false"
        >
          <router-view v-slot="{ Component }">
            <component :is="Component" :key="$route.fullPath" />
          </router-view>
        </n-layout-content>
        </n-dialog-provider>
        </n-message-provider>
      </n-layout>
    </n-layout>
  </n-config-provider>
</template>

<script setup lang="ts">
import { ref, computed, h, watch, type Component } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NConfigProvider,
  NLayout,
  NLayoutSider,
  NLayoutHeader,
  NLayoutContent,
  NMenu,
  NButton,
  NIcon,
  NText,
  NSpace,
  NMessageProvider,
  NDialogProvider,
  zhCN,
  dateZhCN,
} from 'naive-ui'
import {
  SpeedometerOutline,
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
} from '@vicons/ionicons5'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)

function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = [
  { label: '概览', key: '/dashboard', icon: renderIcon(SpeedometerOutline) },
  {
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
  },
  {
    label: '证据整理',
    key: 'evidence-group',
    icon: renderIcon(FolderOpenOutline),
    children: [
      { label: '诉状生成', key: '/evidence', icon: renderIcon(CreateOutline) },
    ],
  },
  {
    label: '病历时间整理',
    key: 'timeline-group',
    icon: renderIcon(TimeOutline),
    children: [
      { label: '（即将上线）', key: '/timeline-placeholder', disabled: true },
    ],
  },
]

const activeMenu = computed(() => {
  if (route.path.startsWith('/evidence')) return '/evidence'
  if (route.path.startsWith('/tasks')) return '/tasks'
  if (route.path.startsWith('/upload')) return '/upload'
  if (route.path.startsWith('/process')) return '/process'
  if (route.path.startsWith('/download')) return '/download'
  if (route.path.startsWith('/templates')) return '/templates'
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
</script>
