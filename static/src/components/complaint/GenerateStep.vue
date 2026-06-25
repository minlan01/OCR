<template>
  <n-card title="生成起诉状" size="small">
    <n-space vertical :size="16">
      <template v-if="!generating && !store.isDocReady">
        <!-- OCR 识别结果展示与编辑 -->
        <template v-if="displaySlots.length > 0">
          <n-text strong style="font-size: 16px">识别结果</n-text>
          <n-text depth="3">以下为各材料槽位的识别结果，可点击编辑后修改</n-text>

          <n-card
            v-for="slot in displaySlots"
            :key="slot.key"
            size="small"
            embedded
          >
            <template #header>
              <n-space align="center" :size="8">
                <n-text strong>{{ slot.label }}</n-text>
                <n-tag :type="slot.status === 'completed' ? 'success' : slot.status === 'failed' ? 'error' : 'warning'" size="small">
                  {{ slot.statusText }}
                </n-tag>
              </n-space>
            </template>

            <template v-if="editingState[slot.key]">
              <n-input
                type="textarea"
                :value="editingState[slot.key].editText"
                @update:value="(v: string) => editingState[slot.key]!.editText = v"
                :rows="6"
                placeholder="编辑识别结果（JSON 格式）..."
              />
              <n-space style="margin-top: 8px">
                <n-button size="small" type="primary" @click="saveSlot(slot)">保存</n-button>
                <n-button size="small" @click="cancelEdit(slot.key)">取消</n-button>
              </n-space>
            </template>
            <template v-else>
              <n-text v-if="slot.displayText" style="white-space: pre-wrap; word-break: break-all">
                {{ slot.displayText }}
              </n-text>
              <n-text v-else depth="3">（无识别结果）</n-text>
              <n-button size="tiny" style="margin-left: 8px" @click="startEdit(slot)">编辑</n-button>
            </template>
          </n-card>
        </template>

        <n-divider style="margin: 4px 0" />

        <n-text>确认所有信息无误后，点击生成民事起诉状</n-text>
        <n-form-item label="手动输入费用总计（元）" :show-feedback="false">
          <n-input-number
            v-model:value="manualTotalFee"
            :min="0"
            :precision="2"
            :step="100"
            placeholder="选填，不填则自动计算"
            clearable
            style="width: 100%"
          />
        </n-form-item>
        <n-button type="primary" @click="handleGenerate">
          生成起诉状
        </n-button>
      </template>

      <template v-if="generating">
        <n-spin size="large" description="正在生成起诉状...">
          <div style="min-height: 100px" />
        </n-spin>
      </template>

      <template v-if="genError">
        <n-alert type="error" title="生成失败" closable @close="genError = ''">
          {{ genError }}
        </n-alert>
      </template>

      <template v-if="store.isDocReady">
        <n-alert type="success" title="起诉状已生成">
          民事起诉状文档已生成完毕，可以下载。
        </n-alert>
        <n-button type="primary" @click="handleDownload">
          下载起诉状 (DOCX)
        </n-button>
        <n-button @click="handleReset">
          创建新案件
        </n-button>
      </template>

      <template v-if="store.currentCase?.status === 'failed'">
        <n-alert type="error" title="生成失败">
          起诉状生成过程中出现错误，请检查信息后重试。
        </n-alert>
        <n-button type="primary" @click="handleGenerate">
          重新生成
        </n-button>
      </template>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import {
  NCard, NSpace, NText, NButton, NAlert, NSpin, NInputNumber, NFormItem,
  NDivider, NInput, NTag,
} from 'naive-ui'
import { useComplaintStore } from '@/stores/complaint'

const store = useComplaintStore()
const generating = ref(false)
const genError = ref('')
const manualTotalFee = ref<number | null>(null)

const SLOT_LABELS: Record<string, string> = {
  plaintiff: '原告信息',
  guardian: '法定代理人/监护人',
  defendant: '被告信息',
  fee: '赔偿费用',
  medical: '病历信息',
  appraisal: '司法鉴定书',
  staff_error: '医务人员过错核查',
  evidence: '证据材料清单',
}

function formatData(data: Record<string, unknown> | null | undefined): string {
  if (!data || Object.keys(data).length === 0) return ''
  return JSON.stringify(data, null, 2)
}

interface SlotDisplay {
  key: string
  label: string
  status: string
  statusText: string
  displayText: string
  rawData: Record<string, unknown>
}

const displaySlots = computed<SlotDisplay[]>(() => {
  return store.slotResults
    .filter(s => s.slot !== 'evidence')
    .map(s => ({
      key: s.slot,
      label: SLOT_LABELS[s.slot] || s.slot,
      status: s.ocr_status,
      statusText: s.ocr_status === 'completed' ? '已识别'
        : s.ocr_status === 'failed' ? '识别失败'
        : s.ocr_status === 'skipped' ? '已跳过'
        : s.ocr_status,
      displayText: formatData(s.effective_data || s.extracted_data),
      rawData: (s.effective_data || s.extracted_data || {}) as Record<string, unknown>,
    }))
})

const editingState = reactive<Record<string, { editing: boolean; editText: string }>>({})

function startEdit(slot: SlotDisplay) {
  editingState[slot.key] = {
    editing: true,
    editText: formatData(slot.rawData),
  }
}

function cancelEdit(key: string) {
  delete editingState[key]
}

async function saveSlot(slot: SlotDisplay) {
  const state = editingState[slot.key]
  if (!state || !store.currentCase) return

  try {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(state.editText)
    } catch {
      parsed = { raw_text: state.editText }
    }

    await store.updateResults(store.currentCase.case_id, [
      { slot: slot.key, manual_edit: parsed },
    ])

    await store.fetchResults(store.currentCase.case_id)
    delete editingState[slot.key]
  } catch (e: any) {
    console.error('Save failed:', e.message)
  }
}

async function handleGenerate() {
  if (!store.currentCase) return
  generating.value = true
  genError.value = ''
  try {
    const feeParam = manualTotalFee.value != null ? manualTotalFee.value : undefined
    await store.generateDoc(store.currentCase.case_id, feeParam)
    // 轮询超时 5 分钟，防止定时器永久运行
    const MAX_POLL_MS = 5 * 60 * 1000
    const startTime = Date.now()
    let timedOut = false
    const pollInterval = setInterval(async () => {
      // 超时保护
      if (Date.now() - startTime > MAX_POLL_MS) {
        clearInterval(pollInterval)
        timedOut = true
        generating.value = false
        genError.value = '生成超时（超过 5 分钟），请稍后重试或检查任务状态'
        return
      }
      // 组件卸载或案件丢失时停止轮询
      if (!store.currentCase) {
        clearInterval(pollInterval)
        generating.value = false
        return
      }
      await store.fetchCase(store.currentCase!.case_id)
      if (store.isDocReady || store.currentCase?.status === 'failed') {
        clearInterval(pollInterval)
        generating.value = false
        if (store.currentCase?.status === 'failed') {
          genError.value = '文档生成失败，请检查案件信息后重试'
        }
      }
    }, 3000)
  } catch (e: any) {
    genError.value = e.message || '生成请求失败'
    console.error('Generate failed:', e.message)
    generating.value = false
  }
}

async function handleDownload() {
  if (!store.currentCase) return
  await store.downloadDoc(store.currentCase.case_id)
}

function handleReset() {
  store.reset()
}

onMounted(async () => {
  if (store.currentCase && store.slotResults.length === 0) {
    try {
      await store.fetchResults(store.currentCase.case_id)
    } catch {
      // results may not be available yet
    }
  }
})
</script>
