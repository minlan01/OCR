<template>
  <div>
    <n-space vertical :size="16">
      <n-card size="small">
        <n-space align="center">
          <n-text strong style="font-size: 18px">下载中心</n-text>
          <n-tag type="info" size="small">{{ tasks.length }} 个已完成任务</n-tag>
          <n-space style="margin-left: auto">
            <n-button
              size="small"
              :disabled="checkedIds.length === 0"
              type="success"
              :loading="batchDownloading"
              @click="handleBatchDownload"
            >
              <template #icon><n-icon><DownloadOutline /></n-icon></template>
              批量下载 ({{ checkedIds.length }})
            </n-button>
            <n-button
              size="small"
              :disabled="checkedIds.length === 0"
              type="info"
              @click="openBatchTemplateModal"
            >
              <template #icon><n-icon><DocumentOutline /></n-icon></template>
              批量按模板导出 ({{ checkedIds.length }})
            </n-button>
            <n-button size="small" quaternary @click="fetchCompleted">
              <template #icon><n-icon><RefreshOutline /></n-icon></template>
              刷新
            </n-button>
          </n-space>
        </n-space>
      </n-card>

      <n-card size="small" :bordered="false">
        <n-spin :show="loading">
          <n-alert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 12px" />
          <n-empty v-if="!loading && tasks.length === 0 && !errorMsg" description="暂无已完成的任务，请先上传并处理 PDF" />
          <n-data-table
            v-if="tasks.length > 0"
            :columns="columns"
            :data="tasks"
            :row-key="(row: CompletedTask) => row.task_id"
            :checked-row-keys="checkedIds"
            :single-line="false"
            size="small"
            @update:checked-row-keys="onCheck"
          />
        </n-spin>
      </n-card>
    </n-space>

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
import { ref, computed, h, onMounted } from 'vue'
import {
  NCard, NButton, NIcon, NTag, NText, NSpace, NSpin, NEmpty, NDataTable, NAlert,
  NModal, NSelect, useMessage,
} from 'naive-ui'
import { DownloadOutline, RefreshOutline, DocumentOutline } from '@vicons/ionicons5'
import * as api from '@/api/client'
import type { ScanTaskSummary } from '@/api/client'

interface CompletedTask extends ScanTaskSummary {
  downloading?: boolean
}

const message = useMessage()
const tasks = ref<CompletedTask[]>([])
const loading = ref(false)
const errorMsg = ref('')
const checkedIds = ref<(string | number)[]>([])
const batchDownloading = ref(false)

const showTemplateModal = ref(false)
const templatesLoading = ref(false)
const templateExporting = ref(false)
const availableTemplates = ref<api.TemplateListItem[]>([])
const selectedTemplateId = ref<string | null>(null)
const templateExportTarget = ref<'single' | 'batch'>('single')
const singleExportTaskId = ref<string | null>(null)

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

const columns = [
  { type: 'selection' as const, width: 40 },
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true }, width: 280 },
  { title: '页数', key: 'page_count', width: 60, align: 'center' as const,
    render(row: CompletedTask) { return row.page_count ?? '—' } },
  { title: '置信度', key: 'confidence_avg', width: 80, align: 'center' as const,
    render(row: CompletedTask) {
      if (row.confidence_avg == null) return '—'
      return (row.confidence_avg * 100).toFixed(1) + '%'
    } },
  { title: '完成时间', key: 'completed_at', width: 160,
    render(row: CompletedTask) {
      if (!row.completed_at) return '—'
      return new Date(row.completed_at).toLocaleString('zh-CN')
    } },
  { title: '操作', key: 'actions', width: 200, align: 'center' as const,
    render(row: CompletedTask) {
      return h(NSpace, { size: 4, justify: 'center' }, {
        default: () => [
          h(NButton, {
            size: 'small', type: 'primary',
            loading: row.downloading,
            onClick: () => handleDownloadOne(row),
          }, {
            default: () => '下载 Word',
            icon: () => h(NIcon, null, { default: () => h(DownloadOutline) }),
          }),
          h(NButton, {
            size: 'small', type: 'info',
            onClick: () => openSingleTemplateModal(row),
          }, {
            default: () => '按模板导出',
            icon: () => h(NIcon, null, { default: () => h(DocumentOutline) }),
          }),
        ],
      })
    } },
]

function onCheck(keys: (string | number)[]) { checkedIds.value = keys }

async function fetchCompleted() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api.get<api.PaginatedResponse<ScanTaskSummary>>('/scans', {
      status: 'completed', size: '100', sort_by: 'updated_at', sort_order: 'desc',
    })
    tasks.value = res.items.map(item => ({ ...item, downloading: false }))
  } catch (e: any) {
    errorMsg.value = '加载失败: ' + (e.message || '未知错误')
  } finally { loading.value = false }
}

async function downloadFile(taskId: string, filename: string) {
  const safeName = filename.replace(/\.pdf$/i, '') + '_结构化.docx'
  await api.downloadBlob(`/scans/${taskId}/download?format=docx`, safeName)
}

async function handleDownloadOne(row: CompletedTask) {
  row.downloading = true
  try {
    await downloadFile(row.task_id, row.filename)
    message.success(`「${row.filename}」下载成功`)
  } catch (e: any) {
    message.error('下载失败: ' + (e.message || '未知错误'))
  } finally { row.downloading = false }
}

async function handleBatchDownload() {
  if (checkedIds.value.length === 0) return
  batchDownloading.value = true
  let ok = 0, fail = 0
  try {
    for (const key of checkedIds.value) {
      const taskId = String(key)
      const task = tasks.value.find(t => t.task_id === taskId)
      if (!task) continue
      task.downloading = true
      try {
        await downloadFile(task.task_id, task.filename)
        ok++
        await new Promise(r => setTimeout(r, 300))
      } catch { fail++ }
      finally { task.downloading = false }
    }
    if (fail === 0) message.success(`全部 ${ok} 个文件下载成功`)
    else message.warning(`下载完成：${ok} 成功，${fail} 失败`)
  } finally {
    batchDownloading.value = false
    checkedIds.value = []
  }
}

async function openSingleTemplateModal(row: CompletedTask) {
  templateExportTarget.value = 'single'
  singleExportTaskId.value = row.task_id
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

async function openBatchTemplateModal() {
  if (checkedIds.value.length === 0) return
  templateExportTarget.value = 'batch'
  singleExportTaskId.value = null
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
  if (!selectedTemplateId.value) return
  templateExporting.value = true
  try {
    const tmpl = availableTemplates.value.find(t => t.id === selectedTemplateId.value)
    const tmplName = tmpl?.name || '模板'

    if (templateExportTarget.value === 'single' && singleExportTaskId.value) {
      const task = tasks.value.find(t => t.task_id === singleExportTaskId.value)
      const baseName = task ? task.filename.replace(/\.pdf$/i, '') : 'output'
      const filename = `${baseName}_${tmplName}.docx`
      await api.exportWithTemplate(singleExportTaskId.value, selectedTemplateId.value, filename)
      message.success('模板导出成功')
    } else {
      let ok = 0, fail = 0
      for (const key of checkedIds.value) {
        const taskId = String(key)
        const task = tasks.value.find(t => t.task_id === taskId)
        if (!task) continue
        const baseName = task.filename.replace(/\.pdf$/i, '')
        const filename = `${baseName}_${tmplName}.docx`
        try {
          await api.exportWithTemplate(taskId, selectedTemplateId.value, filename)
          ok++
          await new Promise(r => setTimeout(r, 500))
        } catch { fail++ }
      }
      if (fail === 0) message.success(`全部 ${ok} 个文件模板导出成功`)
      else message.warning(`模板导出完成：${ok} 成功，${fail} 失败`)
      checkedIds.value = []
    }
    showTemplateModal.value = false
  } catch (e: any) {
    message.error('模板导出失败: ' + (e.message || '未知错误'))
  } finally {
    templateExporting.value = false
  }
}

onMounted(() => { fetchCompleted() })
</script>
