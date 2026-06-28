<template>
  <div>
    <!-- 顶部说明 -->
    <n-alert type="info" style="margin-bottom: 16px" :show-icon="true">
      <n-text strong>步骤0 · 原始素材预处理</n-text>
      <n-p depth="3" style="margin: 4px 0 0 0">
        上传原始素材（图片/PDF），系统自动进行 OCR 识别 + LLM 智能分类（10类费用），并按类别归档。
        PDF 文件将逐页拆分为独立图片并单独分类。支持手动纠正分类。
      </n-p>
    </n-alert>

    <!-- 分类汇总 -->
    <n-card v-if="summary.category_detail.length > 0" title="分类汇总" size="small" style="margin-bottom: 16px">
      <n-space>
        <n-statistic
          v-for="item in summary.category_detail"
          :key="item.category"
          :label="item.category_cn"
          :value="item.count"
        />
      </n-space>
    </n-card>

    <!-- 左右布局：上传区 + 素材列表 -->
    <n-grid :cols="2" :x-gap="16">
      <!-- 左侧上传区 -->
      <n-gi>
        <n-card title="上传原始素材" size="small">
          <n-upload
            ref="uploadRef"
            :max="100"
            multiple
            accept=".jpg,.jpeg,.png,.pdf"
            :default-upload="false"
            @change="handleFileChange"
            v-model:file-list="fileList"
          >
            <n-upload-dragger>
              <div style="padding: 20px 0; text-align: center">
                <n-icon size="40" :depth="3"><CloudUploadOutline /></n-icon>
                <n-text style="font-size: 14px; display: block; margin-top: 8px">
                  点击或拖拽文件到此区域
                </n-text>
                <n-p depth="3" style="margin: 4px 0 0 0; font-size: 12px">
                  支持 JPG / PNG / PDF，单个文件≤50MB
                </n-p>
              </div>
            </n-upload-dragger>
          </n-upload>

          <n-space style="margin-top: 12px" align="center">
            <n-button
              type="primary"
              :loading="uploading"
              :disabled="fileList.length === 0"
              @click="handleUpload"
            >
              <template #icon><n-icon><CloudUploadOutline /></n-icon></template>
              上传 {{ fileList.length > 0 ? `(${fileList.length})` : '' }}
            </n-button>
            <n-text depth="3" style="font-size: 12px">
              上传后点击「开始预处理」进行 OCR + 分类
            </n-text>
          </n-space>
        </n-card>
      </n-gi>

      <!-- 右侧素材列表 -->
      <n-gi>
        <n-card title="素材列表" size="small">
          <template #header-extra>
            <n-space align="center" size="small">
              <n-tag v-if="progress.step0_status === 'completed'" type="success" size="small">已完成</n-tag>
              <n-tag v-else-if="progress.step0_status === 'in_progress'" type="warning" size="small">处理中</n-tag>
              <n-tag v-else-if="progress.step0_status === 'skipped'" type="default" size="small">已跳过</n-tag>
              <n-button size="small" tertiary @click="loadMaterials">刷新</n-button>
            </n-space>
          </template>

          <n-data-table
            :columns="materialColumns"
            :data="materials"
            :loading="materialsLoading"
            :bordered="false"
            size="small"
            :max-height="400"
            :scroll-x="800"
          />
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 底部操作栏 -->
    <n-space style="margin-top: 16px" align="center" justify="center">
      <n-button
        type="primary"
        :loading="preprocessing"
        :disabled="materials.length === 0"
        @click="handleStartPreprocess"
      >
        <template #icon><n-icon><PlayOutline /></n-icon></template>
        开始预处理
      </n-button>

      <n-button
        :disabled="preprocessing"
        @click="handleSkip"
      >
        跳过步骤0
      </n-button>

      <n-button
        v-if="progress.step0_status === 'completed' || progress.step0_status === 'skipped'"
        type="info"
        @click="handleNextStep"
      >
        <template #icon><n-icon><ArrowForwardOutline /></n-icon></template>
        进入步骤1
      </n-button>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import {
  NAlert,
  NCard,
  NSpace,
  NText,
  NP,
  NIcon,
  NGrid,
  NGi,
  NUpload,
  NUploadDragger,
  NButton,
  NDataTable,
  NTag,
  NStatistic,
  NImage,
  NSelect,
  NProgress,
  NTooltip,
  NEllipsis,
  useMessage,
} from 'naive-ui'
import {
  CloudUploadOutline,
  PlayOutline,
  ArrowForwardOutline,
} from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import * as step0Api from '@/api/step0'
import type { Step0MaterialOut, Step0ProgressResponse, Step0SummaryResponse } from '@/api/step0'

const message = useMessage()

// ─── Props ───────────────────────────────────────────────────────────────────
const props = defineProps<{
  caseId: string
}>()

const emit = defineEmits<{
  (e: 'next-step'): void
  (e: 'step0-completed'): void
}>()

// ─── 状态 ────────────────────────────────────────────────────────────────────
const uploadRef = ref()
const fileList = ref<any[]>([])
const uploading = ref(false)
const preprocessing = ref(false)
const materialsLoading = ref(false)

const materials = ref<Step0MaterialOut[]>([])
const progress = ref<Step0ProgressResponse>({
  case_id: props.caseId,
  total: 0,
  processed: 0,
  failed: 0,
  pending: 0,
  progress_percent: 0,
  step0_status: 'not_started',
  category_summary: {},
})

const summary = ref<Step0SummaryResponse>({
  case_id: props.caseId,
  category_summary: {},
  category_detail: [],
})

let progressPollTimer: ReturnType<typeof setInterval> | null = null

// ─── 表格列定义 ──────────────────────────────────────────────────────────────

const materialColumns = computed<DataTableColumns<Step0MaterialOut>>(() => [
  {
    title: '缩略图',
    key: 'thumbnail',
    width: 70,
    render(row) {
      return h(NImage, {
        src: step0Api.getThumbnailUrl(props.caseId, row.id),
        width: 50,
        height: 50,
        objectFit: 'cover',
        fallbackSrc: '',
        style: 'border-radius: 4px',
      })
    },
  },
  {
    title: '文件名',
    key: 'original_filename',
    width: 180,
    render(row) {
      return h(NEllipsis, { style: 'max-width: 170px' }, {
        default: () => row.original_filename || '未命名',
        tooltip: () => row.original_filename || '未命名',
      })
    },
  },
  {
    title: 'OCR摘要',
    key: 'ocr_text',
    width: 150,
    render(row) {
      const text = row.ocr_text || ''
      return h(NEllipsis, { style: 'max-width: 140px' }, {
        default: () => text.substring(0, 50) || '—',
        tooltip: () => text.substring(0, 200) || '—',
      })
    },
  },
  {
    title: '分类',
    key: 'step0_fee_category',
    width: 160,
    render(row) {
      return h(NSelect, {
        value: row.step0_fee_category || null,
        options: step0Api.STEP0_CATEGORY_OPTIONS,
        size: 'small',
        placeholder: '未分类',
        onUpdateValue: (val: string) => handleCorrectCategory(row, val),
      })
    },
  },
  {
    title: '置信度',
    key: 'category_confidence',
    width: 100,
    render(row) {
      const conf = row.category_confidence || 0
      const percentage = Math.round(conf * 100)
      const status = conf >= 0.6 ? 'success' : conf >= 0.3 ? 'warning' : 'error'
      return h(NTooltip, {}, {
        trigger: () => h(NProgress, {
          type: 'line',
          percentage,
          status,
          showIndicator: false,
          style: 'width: 70px',
        }),
        default: () => `${percentage}%`,
      })
    },
  },
  {
    title: '状态',
    key: 'ocr_status',
    width: 90,
    render(row) {
      const statusMap: Record<string, { type: 'success' | 'warning' | 'error' | 'default'; text: string }> = {
        completed: { type: 'success', text: '已完成' },
        pending: { type: 'default', text: '待处理' },
        processing: { type: 'warning', text: '处理中' },
        failed: { type: 'error', text: '失败' },
        skipped: { type: 'default', text: '已跳过' },
      }
      const info = statusMap[row.ocr_status] || { type: 'default' as const, text: row.ocr_status }
      const tags = [h(NTag, { type: info.type, size: 'small' }, { default: () => info.text })]
      if (row.step0_needs_review) {
        tags.push(h(NTag, { type: 'warning', size: 'small', style: 'margin-left: 4px' }, { default: () => '需审查' }))
      }
      if (row.step0_corrected) {
        tags.push(h(NTag, { type: 'info', size: 'small', style: 'margin-left: 4px' }, { default: () => '已纠正' }))
      }
      return h('div', { style: 'display: flex; flex-wrap: wrap; gap: 2px' }, tags)
    },
  },
])

// ─── 方法 ────────────────────────────────────────────────────────────────────

function handleFileChange(data: { fileList: any[] }) {
  fileList.value = data.fileList
}

async function handleUpload() {
  if (fileList.value.length === 0) {
    message.warning('请先选择文件')
    return
  }

  // 提取 File 对象
  const files: File[] = []
  for (const item of fileList.value) {
    if (item.file) {
      files.push(item.file as File)
    }
  }

  if (files.length === 0) {
    message.warning('未找到有效文件')
    return
  }

  uploading.value = true
  try {
    const res = await step0Api.uploadRawMaterials(props.caseId, files)
    message.success(`成功上传 ${res.uploaded_count} 个文件`)
    fileList.value = []
    await loadMaterials()
    await loadProgress()
  } catch (e: unknown) {
    message.error((e as Error).message)
  } finally {
    uploading.value = false
  }
}

async function handleStartPreprocess() {
  if (materials.value.length === 0) {
    message.warning('请先上传素材')
    return
  }

  preprocessing.value = true
  try {
    await step0Api.startPreprocess(props.caseId)
    message.success('预处理已启动，请等待处理完成')
    // 开始轮询进度
    startProgressPolling()
  } catch (e: unknown) {
    message.error((e as Error).message)
    preprocessing.value = false
  }
}

function startProgressPolling() {
  if (progressPollTimer) {
    clearInterval(progressPollTimer)
  }

  progressPollTimer = setInterval(async () => {
    try {
      await loadProgress()
      if (progress.value.progress_percent >= 100 || progress.value.step0_status === 'completed') {
        stopProgressPolling()
        preprocessing.value = false
        message.success('预处理已完成')
        await loadMaterials()
        await loadSummary()
        emit('step0-completed')
      }
    } catch (e) {
      // 静默忽略轮询错误
    }
  }, 2000)
}

function stopProgressPolling() {
  if (progressPollTimer) {
    clearInterval(progressPollTimer)
    progressPollTimer = null
  }
}

async function handleSkip() {
  try {
    await step0Api.skipStep0(props.caseId)
    message.success('已跳过步骤0')
    await loadProgress()
    emit('step0-completed')
  } catch (e: unknown) {
    message.error((e as Error).message)
  }
}

function handleNextStep() {
  emit('next-step')
}

async function handleCorrectCategory(material: Step0MaterialOut, newCategory: string) {
  if (!newCategory || newCategory === material.step0_fee_category) return
  try {
    await step0Api.correctCategory(props.caseId, material.id, newCategory)
    message.success(`已将「${material.original_filename}」分类改为「${step0Api.STEP0_FEE_CATEGORIES[newCategory]}」`)
    await loadMaterials()
    await loadSummary()
  } catch (e: unknown) {
    message.error((e as Error).message)
  }
}

async function loadMaterials() {
  materialsLoading.value = true
  try {
    materials.value = await step0Api.getStep0Materials(props.caseId)
  } catch (e: unknown) {
    // 静默忽略
  } finally {
    materialsLoading.value = false
  }
}

async function loadProgress() {
  try {
    progress.value = await step0Api.getStep0Progress(props.caseId)
  } catch (e: unknown) {
    // 静默忽略
  }
}

async function loadSummary() {
  try {
    summary.value = await step0Api.getStep0Summary(props.caseId)
  } catch (e: unknown) {
    // 静默忽略
  }
}

// ─── 生命周期 ─────────────────────────────────────────────────────────────────

onMounted(async () => {
  await Promise.all([loadMaterials(), loadProgress(), loadSummary()])
})

onUnmounted(() => {
  stopProgressPolling()
})
</script>
