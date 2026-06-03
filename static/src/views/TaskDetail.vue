<template>
  <div>
    <n-space style="margin-bottom: 16px" align="center">
      <n-button size="small" quaternary @click="$router.back()">
        <template #icon><n-icon><ArrowBackOutline /></n-icon></template>
        返回列表
      </n-button>
      <n-button size="small" :loading="store.detailLoading" @click="handleRefreshDetail">
        <template #icon><n-icon><RefreshOutline /></n-icon></template>
        刷新
      </n-button>
      <n-tag v-if="isPolling" type="info" size="small">自动刷新中...</n-tag>
    </n-space>

    <n-spin :show="store.detailLoading">
      <template v-if="store.currentDetail">
        <n-space vertical :size="16">
          <!-- 基本信息 -->
          <n-card title="基本信息" size="small">
            <n-descriptions :column="2" size="small" bordered>
              <n-descriptions-item label="文件名">{{ store.currentDetail.filename }}</n-descriptions-item>
              <n-descriptions-item label="状态">
                <n-tag :type="statusType(store.currentDetail.status)">{{ statusLabel(store.currentDetail.status) }}</n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="来源类型">{{ store.currentDetail.source_type }}</n-descriptions-item>
              <n-descriptions-item label="扫描仪">{{ store.currentDetail.scanner_id || '—' }}</n-descriptions-item>
              <n-descriptions-item label="文件大小">{{ formatSize(store.currentDetail.file_size) }}</n-descriptions-item>
              <n-descriptions-item label="MD5">
                <n-text code>{{ store.currentDetail.file_md5 || '—' }}</n-text>
              </n-descriptions-item>
              <n-descriptions-item label="创建时间">{{ formatDate(store.currentDetail.created_at) }}</n-descriptions-item>
              <n-descriptions-item label="开始时间">{{ formatDate(store.currentDetail.started_at) }}</n-descriptions-item>
              <n-descriptions-item label="完成时间">{{ formatDate(store.currentDetail.completed_at) }}</n-descriptions-item>
              <n-descriptions-item label="回调地址">{{ store.currentDetail.callback_url || '—' }}</n-descriptions-item>
            </n-descriptions>

            <n-space style="margin-top: 12px">
              <n-button
                v-if="store.currentDetail.status === 'completed'"
                size="small"
                type="primary"
                @click="showResult = !showResult"
              >
                {{ showResult ? '收起结果' : '查看 JSON 结果' }}
              </n-button>
              <n-button
                v-if="store.currentDetail.status === 'completed'"
                size="small"
                type="success"
                :loading="downloading"
                @click="handleDownloadWord"
              >
                <template #icon><n-icon><DownloadOutline /></n-icon></template>
                下载 Word 文档
              </n-button>
              <n-button
                v-if="store.currentDetail.status === 'completed'"
                size="small"
                type="info"
                @click="openTemplateModal"
              >
                <template #icon><n-icon><DocumentOutline /></n-icon></template>
                按模板导出
              </n-button>
              <n-button
                v-if="store.currentDetail.status === 'failed'"
                size="small"
                type="warning"
                @click="handleRetry"
              >
                重试任务
              </n-button>
              <n-popconfirm @positive-click="handleDelete">
                <template #trigger>
                  <n-button size="small" type="error" ghost>删除任务</n-button>
                </template>
                确认删除此任务？
              </n-popconfirm>
            </n-space>
          </n-card>

          <!-- 统计指标 -->
          <n-card title="统计指标" size="small">
            <n-grid :cols="6" :x-gap="12" responsive="screen">
              <n-grid-item>
                <StatCard label="页数" :value="store.currentDetail.page_count ?? '—'" />
              </n-grid-item>
              <n-grid-item>
                <StatCard label="置信度" :value="confDisplay" />
              </n-grid-item>
              <n-grid-item>
                <StatCard label="结构评分" :value="scoreDisplay" />
              </n-grid-item>
              <n-grid-item>
                <StatCard label="表格" :value="store.currentDetail.table_count" />
              </n-grid-item>
              <n-grid-item>
                <StatCard label="标题" :value="store.currentDetail.heading_count" />
              </n-grid-item>
              <n-grid-item>
                <StatCard label="段落" :value="store.currentDetail.paragraph_count" />
              </n-grid-item>
            </n-grid>
          </n-card>

          <!-- 错误信息 -->
          <n-card v-if="store.currentDetail.error_message" title="错误信息" size="small">
            <n-alert type="error" :title="store.currentDetail.error_code || 'ERROR'">
              {{ store.currentDetail.error_message }}
            </n-alert>
          </n-card>

          <!-- 处理步骤 -->
          <n-card title="处理步骤" size="small">
            <StepTimeline :steps="store.currentDetail.steps" />
          </n-card>

          <!-- 文件产物 -->
          <n-card title="文件产物" size="small">
            <n-empty v-if="!store.currentDetail.files.length" description="暂无文件" />
            <n-table v-else :single-line="true" size="small">
              <thead>
                <tr>
                  <th>类型</th>
                  <th>页码</th>
                  <th>Bucket</th>
                  <th>大小</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in store.currentDetail.files" :key="file.id">
                  <td><n-tag size="tiny">{{ file.file_type }}</n-tag></td>
                  <td>{{ file.page_no ?? '—' }}</td>
                  <td>{{ file.bucket }}</td>
                  <td>{{ formatSize(file.size_bytes) }}</td>
                </tr>
              </tbody>
            </n-table>
          </n-card>

          <!-- JSON 结果 -->
          <n-card v-if="showResult" title="结构化结果" size="small">
            <template #header-extra>
              <n-button size="tiny" @click="showResult = false">关闭</n-button>
            </template>
            <n-spin :show="resultLoading">
              <JsonViewer :data="resultData" />
            </n-spin>
          </n-card>
        </n-space>
      </template>

      <n-empty v-else description="任务不存在" style="padding: 60px" />
    </n-spin>

    <!-- 模板导出弹窗 -->
    <n-modal v-model:show="showTemplateModal" preset="card" title="按模板导出 Word" style="max-width: 500px">
      <n-spin :show="templatesLoading">
        <n-empty v-if="!availableTemplates.length" description="暂无可用模板，请先在「模板管理」中上传" />
        <template v-else>
          <n-text style="margin-bottom: 12px; display: block">
            选择模板后，系统将从识别结果中按模板 Schema 提取数据并生成 Word 文档。
          </n-text>
          <n-select
            v-model:value="selectedTemplateId"
            :options="templateOptions"
            placeholder="请选择模板"
          />
          <n-card v-if="selectedTemplateDesc" size="small" style="margin-top: 12px" embedded>
            <n-text depth="3">{{ selectedTemplateDesc }}</n-text>
          </n-card>
        </template>
      </n-spin>
      <template #action>
        <n-space justify="end">
          <n-button @click="showTemplateModal = false">取消</n-button>
          <n-button
            type="primary"
            :loading="templateExporting"
            :disabled="!selectedTemplateId"
            @click="handleTemplateExport"
          >
            确认导出
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NIcon, NCard, NTag, NTable, NDescriptions, NDescriptionsItem,
  NText, NSpin, NEmpty, NSpace, NGrid, NGridItem, NPopconfirm, NAlert,
  NModal, NSelect, useMessage,
} from 'naive-ui'
import { ArrowBackOutline, DownloadOutline, DocumentOutline, RefreshOutline } from '@vicons/ionicons5'
import StatCard from '@/components/StatCard.vue'
import StepTimeline from '@/components/StepTimeline.vue'
import JsonViewer from '@/components/JsonViewer.vue'
import { useScanStore } from '@/stores/scan'
import * as api from '@/api/client'

const route = useRoute()
const router = useRouter()
const store = useScanStore()
const message = useMessage()

const showResult = ref(false)
const resultData = ref<unknown>(null)
const resultLoading = ref(false)
const isPolling = ref(false)
const downloading = ref(false)

const showTemplateModal = ref(false)
const templatesLoading = ref(false)
const templateExporting = ref(false)
const availableTemplates = ref<api.TemplateListItem[]>([])
const selectedTemplateId = ref<string | null>(null)

const taskId = route.params.id as string

const templateOptions = computed(() =>
  availableTemplates.value.map(t => ({
    label: t.name,
    value: t.id,
  }))
)

const selectedTemplateDesc = computed(() => {
  if (!selectedTemplateId.value) return null
  const t = availableTemplates.value.find(t => t.id === selectedTemplateId.value)
  return t?.description || null
})

const confDisplay = computed(() => {
  if (store.currentDetail?.confidence_avg == null) return '—'
  return (store.currentDetail.confidence_avg * 100).toFixed(1) + '%'
})

const scoreDisplay = computed(() => {
  if (store.currentDetail?.structure_score == null) return '—'
  return (store.currentDetail.structure_score * 100).toFixed(0) + '%'
})

watch(showResult, async (val) => {
  if (val && !resultData.value) {
    resultLoading.value = true
    try {
      resultData.value = await store.getTaskResult(taskId)
    } catch {
      resultData.value = { error: '无法加载结果' }
    } finally {
      resultLoading.value = false
    }
  }
})

function statusType(s: string): 'default' | 'info' | 'success' | 'warning' | 'error' {
  const m: Record<string, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
    received: 'info', pending: 'default', processing: 'info',
    completed: 'success', failed: 'error', retrying: 'warning',
  }
  return m[s] || 'default'
}

function statusLabel(s: string): string {
  const m: Record<string, string> = {
    received: '已接收', pending: '待处理', processing: '处理中',
    completed: '已完成', failed: '失败', retrying: '重试中',
  }
  return m[s] || s
}

function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN')
}

async function handleRetry() {
  try {
    await store.retryTask(taskId)
    store.fetchDetail(taskId)
  } catch (e: any) {
    alert('重试失败: ' + e.message)
  }
}

async function handleDelete() {
  try {
    await store.deleteTask(taskId)
    router.push('/tasks')
  } catch (e: any) {
    alert('删除失败: ' + e.message)
  }
}

async function handleRefreshDetail() {
  try {
    await store.fetchDetail(taskId)
    message.success('已刷新')
  } catch (e: any) {
    message.error('刷新失败: ' + (e.message || '未知错误'))
  }
}

async function handleDownloadWord() {
  if (!store.currentDetail) return
  downloading.value = true
  try {
    await store.downloadWord(taskId, store.currentDetail.filename)
    message.success('Word 文档下载成功')
  } catch (e: any) {
    message.error('下载失败: ' + (e.message || '未知错误'))
  } finally {
    downloading.value = false
  }
}

async function openTemplateModal() {
  showTemplateModal.value = true
  selectedTemplateId.value = null
  templatesLoading.value = true
  try {
    availableTemplates.value = await api.listTemplates()
  } catch (e: any) {
    message.error('加载模板列表失败: ' + e.message)
  } finally {
    templatesLoading.value = false
  }
}

async function handleTemplateExport() {
  if (!selectedTemplateId.value || !store.currentDetail) return
  templateExporting.value = true
  try {
    const tmpl = availableTemplates.value.find(t => t.id === selectedTemplateId.value)
    const tmplName = tmpl?.name || '模板'
    const baseName = store.currentDetail.filename.replace(/\.pdf$/i, '')
    const filename = `${baseName}_${tmplName}.docx`
    await api.exportWithTemplate(taskId, selectedTemplateId.value, filename)
    message.success('模板导出成功')
    showTemplateModal.value = false
  } catch (e: any) {
    message.error('模板导出失败: ' + (e.message || '未知错误'))
  } finally {
    templateExporting.value = false
  }
}

onMounted(() => {
  store.startDetailPolling(taskId)
  isPolling.value = true
})

onUnmounted(() => {
  store.stopDetailPolling()
  isPolling.value = false
})
</script>
