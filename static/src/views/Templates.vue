<template>
  <div>
    <n-space justify="space-between" align="center" style="margin-bottom: 16px">
      <n-h2 style="margin: 0">模板管理</n-h2>
      <n-button type="primary" @click="openCreateModal">
        <template #icon><n-icon><AddOutline /></n-icon></template>
        上传模板
      </n-button>
    </n-space>

    <n-spin :show="loading">
      <n-empty v-if="!templates.length" description="暂无模板，点击右上角上传" style="padding: 60px" />

      <n-grid :cols="2" :x-gap="16" :y-gap="16" responsive="screen">
        <n-grid-item v-for="t in templates" :key="t.id">
          <n-card size="small" hoverable>
            <template #header>{{ t.name }}</template>
            <template #header-extra>
              <n-space :size="4" align="center">
                <n-button size="tiny" type="info" ghost @click="openEditModal(t)">
                  编辑
                </n-button>
                <n-popconfirm @positive-click="handleDelete(t.id)">
                  <template #trigger>
                    <n-button size="tiny" type="error" ghost>删除</n-button>
                  </template>
                  确认删除模板「{{ t.name }}」？
                </n-popconfirm>
              </n-space>
            </template>
            <n-text depth="3">{{ t.description || '无描述' }}</n-text>
            <template #footer>
              <n-text depth="3" style="font-size: 12px">
                创建: {{ formatDate(t.created_at) }} · 更新: {{ formatDate(t.updated_at) }}
              </n-text>
            </template>
          </n-card>
        </n-grid-item>
      </n-grid>
    </n-spin>

    <!-- 上传弹窗 -->
    <n-modal v-model:show="showCreate" preset="card" title="上传新模板" style="max-width: 600px">
      <n-form :model="createForm" label-placement="left" label-width="100">
        <n-form-item label="模板名称" required>
          <n-input v-model:value="createForm.name" placeholder="如：医疗损害诉状" />
        </n-form-item>
        <n-form-item label="模板描述">
          <n-input v-model:value="createForm.description" type="textarea" :rows="2" placeholder="可选" />
        </n-form-item>
        <n-form-item label="Schema 文件" required>
          <n-upload :max="1" accept=".json" :default-upload="false" @change="onCreateSchemaFile">
            <n-button>选择 JSON Schema</n-button>
          </n-upload>
          <n-text v-if="createForm.schemaFile" depth="2" style="margin-left: 8px">
            {{ createForm.schemaFile.name }}
          </n-text>
        </n-form-item>
        <n-form-item label="规则手册">
          <n-upload :max="1" accept=".md,.txt" :default-upload="false" @change="onCreateRulesFile">
            <n-button>选择 Markdown</n-button>
          </n-upload>
          <n-text v-if="createForm.rulesFile" depth="2" style="margin-left: 8px">
            {{ createForm.rulesFile.name }}
          </n-text>
        </n-form-item>
        <n-form-item label="生成器代码">
          <n-upload :max="1" accept=".py" :default-upload="false" @change="onCreateGeneratorFile">
            <n-button>选择 Python 文件</n-button>
          </n-upload>
          <n-text v-if="createForm.generatorFile" depth="2" style="margin-left: 8px">
            {{ createForm.generatorFile.name }}
          </n-text>
        </n-form-item>
        <n-form-item label="参考文书">
          <n-upload :max="1" accept=".docx,.doc" :default-upload="false" @change="onCreateReferenceFile">
            <n-button>选择参考 .docx</n-button>
          </n-upload>
          <n-text v-if="createForm.referenceFile" depth="2" style="margin-left: 8px">
            {{ createForm.referenceFile.name }}
          </n-text>
        </n-form-item>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" :loading="submitting" @click="handleCreate">上传</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 编辑弹窗 -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑模板" style="max-width: 600px">
      <n-spin :show="editLoading">
        <n-form :model="editForm" label-placement="left" label-width="100">
          <n-form-item label="模板名称" required>
            <n-input v-model:value="editForm.name" placeholder="如：医疗损害诉状" />
          </n-form-item>
          <n-form-item label="模板描述">
            <n-input v-model:value="editForm.description" type="textarea" :rows="2" placeholder="可选" />
          </n-form-item>
          <n-form-item label="Schema 文件">
            <n-upload :max="1" accept=".json" :default-upload="false" @change="onEditSchemaFile">
              <n-button>替换 JSON Schema</n-button>
            </n-upload>
            <n-text v-if="editForm.schemaFile" depth="2" style="margin-left: 8px">
              {{ editForm.schemaFile.name }}
            </n-text>
            <n-text v-else-if="editForm.hasSchema" depth="3" style="margin-left: 8px">
              已有 Schema（不上传则保留原值）
            </n-text>
          </n-form-item>
          <n-form-item label="规则手册">
            <n-upload :max="1" accept=".md,.txt" :default-upload="false" @change="onEditRulesFile">
              <n-button>替换规则手册</n-button>
            </n-upload>
            <n-text v-if="editForm.rulesFile" depth="2" style="margin-left: 8px">
              {{ editForm.rulesFile.name }}
            </n-text>
            <n-text v-else-if="editForm.hasRules" depth="3" style="margin-left: 8px">
              已有规则手册（不上传则保留原值）
            </n-text>
          </n-form-item>
          <n-form-item label="生成器代码">
            <n-upload :max="1" accept=".py" :default-upload="false" @change="onEditGeneratorFile">
              <n-button>替换生成器代码</n-button>
            </n-upload>
            <n-text v-if="editForm.generatorFile" depth="2" style="margin-left: 8px">
              {{ editForm.generatorFile.name }}
            </n-text>
            <n-text v-else-if="editForm.hasGenerator" depth="3" style="margin-left: 8px">
              已有生成器代码（不上传则保留原值）
            </n-text>
          </n-form-item>
          <n-form-item label="参考文书">
            <n-upload :max="1" accept=".docx,.doc" :default-upload="false" @change="onEditReferenceFile">
              <n-button>替换参考文书</n-button>
            </n-upload>
            <n-text v-if="editForm.referenceFile" depth="2" style="margin-left: 8px">
              {{ editForm.referenceFile.name }}
            </n-text>
            <n-text v-else-if="editForm.hasReferenceDoc" depth="3" style="margin-left: 8px">
              已有参考文书（不上传则保留原值）
            </n-text>
          </n-form-item>
        </n-form>
      </n-spin>
      <template #action>
        <n-space justify="end">
          <n-button @click="showEdit = false">取消</n-button>
          <n-button type="primary" :loading="submitting" :disabled="editLoading" @click="handleEdit">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NButton, NCard, NEmpty, NForm, NFormItem, NGrid, NGridItem,
  NH2, NIcon, NInput, NModal, NPopconfirm, NSpace, NSpin, NText,
  NUpload, useMessage,
} from 'naive-ui'
import { AddOutline } from '@vicons/ionicons5'
import type { UploadFileInfo } from 'naive-ui'
import * as api from '@/api/client'

const message = useMessage()
const templates = ref<api.TemplateListItem[]>([])
const loading = ref(false)
const submitting = ref(false)

const showCreate = ref(false)
const showEdit = ref(false)
const editLoading = ref(false)
const editingId = ref('')

const createForm = ref({
  name: '',
  description: '',
  schemaFile: null as File | null,
  rulesFile: null as File | null,
  generatorFile: null as File | null,
  referenceFile: null as File | null,
})

const editForm = ref({
  name: '',
  description: '',
  schemaFile: null as File | null,
  rulesFile: null as File | null,
  generatorFile: null as File | null,
  referenceFile: null as File | null,
  hasSchema: false,
  hasRules: false,
  hasGenerator: false,
  hasReferenceDoc: false,
})

function onCreateSchemaFile({ file }: { file: UploadFileInfo }) {
  createForm.value.schemaFile = file.file || null
}
function onCreateRulesFile({ file }: { file: UploadFileInfo }) {
  createForm.value.rulesFile = file.file || null
}
function onCreateGeneratorFile({ file }: { file: UploadFileInfo }) {
  createForm.value.generatorFile = file.file || null
}
function onCreateReferenceFile({ file }: { file: UploadFileInfo }) {
  createForm.value.referenceFile = file.file || null
}

function onEditSchemaFile({ file }: { file: UploadFileInfo }) {
  editForm.value.schemaFile = file.file || null
}
function onEditRulesFile({ file }: { file: UploadFileInfo }) {
  editForm.value.rulesFile = file.file || null
}
function onEditGeneratorFile({ file }: { file: UploadFileInfo }) {
  editForm.value.generatorFile = file.file || null
}
function onEditReferenceFile({ file }: { file: UploadFileInfo }) {
  editForm.value.referenceFile = file.file || null
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN')
}

async function fetchTemplates() {
  loading.value = true
  try {
    templates.value = await api.listTemplates()
  } catch (e: any) {
    message.error('加载模板失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  createForm.value = { name: '', description: '', schemaFile: null, rulesFile: null, generatorFile: null, referenceFile: null }
  showCreate.value = true
}

async function handleCreate() {
  if (!createForm.value.name) {
    message.warning('请输入模板名称')
    return
  }
  if (!createForm.value.schemaFile) {
    message.warning('请选择 Schema 文件')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', createForm.value.name)
    fd.append('description', createForm.value.description)
    fd.append('schema_file', createForm.value.schemaFile)
    if (createForm.value.rulesFile) fd.append('rules_file', createForm.value.rulesFile)
    if (createForm.value.generatorFile) fd.append('generator_file', createForm.value.generatorFile)
    if (createForm.value.referenceFile) fd.append('reference_file', createForm.value.referenceFile)

    await api.createTemplate(fd)
    message.success('模板上传成功')
    showCreate.value = false
    await fetchTemplates()
  } catch (e: any) {
    message.error('上传失败: ' + e.message)
  } finally {
    submitting.value = false
  }
}

async function openEditModal(t: api.TemplateListItem) {
  editingId.value = t.id
  editForm.value = {
    name: t.name,
    description: t.description || '',
    schemaFile: null,
    rulesFile: null,
    generatorFile: null,
    referenceFile: null,
    hasSchema: false,
    hasRules: false,
    hasGenerator: false,
    hasReferenceDoc: false,
  }
  showEdit.value = true
  editLoading.value = true
  try {
    const detail = await api.getTemplate(t.id)
    editForm.value.hasSchema = !!detail.schema_def && Object.keys(detail.schema_def).length > 0
    editForm.value.hasRules = !!detail.rules_md
    editForm.value.hasGenerator = !!detail.generator_code
    editForm.value.hasReferenceDoc = !!detail.has_reference_doc
  } catch (e: any) {
    message.error('加载模板详情失败: ' + e.message)
  } finally {
    editLoading.value = false
  }
}

async function handleEdit() {
  if (!editForm.value.name) {
    message.warning('请输入模板名称')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', editForm.value.name)
    fd.append('description', editForm.value.description)
    if (editForm.value.schemaFile) fd.append('schema_file', editForm.value.schemaFile)
    if (editForm.value.rulesFile) fd.append('rules_file', editForm.value.rulesFile)
    if (editForm.value.generatorFile) fd.append('generator_file', editForm.value.generatorFile)
    if (editForm.value.referenceFile) fd.append('reference_file', editForm.value.referenceFile)

    await api.updateTemplate(editingId.value, fd)
    message.success('模板更新成功')
    showEdit.value = false
    await fetchTemplates()
  } catch (e: any) {
    message.error('更新失败: ' + e.message)
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: string) {
  try {
    await api.deleteTemplate(id)
    message.success('模板已删除')
    await fetchTemplates()
  } catch (e: any) {
    message.error('删除失败: ' + e.message)
  }
}

onMounted(fetchTemplates)
</script>
