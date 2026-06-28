<template>
  <div>
    <n-space align="center" justify="space-between" style="margin-bottom: 20px">
      <n-page-header title="证据整理" subtitle="上传素材 → 生成目录 → 智能分析 → 导出文档" />
      <n-space>
        <n-button v-if="!showHomePage" :loading="refreshing" secondary @click="handleRefresh">
          <template #icon><n-icon><RefreshOutline /></n-icon></template>
          刷新
        </n-button>
        <n-button v-if="!showHomePage" secondary @click="handleGoHome">
          <template #icon><n-icon><HomeOutline /></n-icon></template>
          案件列表
        </n-button>
      </n-space>
    </n-space>

    <!-- ═══ 案件首页（独立于步骤条之外） ═══ -->
    <template v-if="showHomePage">
      <n-card v-if="showCreateForm" title="创建证据案件" style="margin-bottom: 16px">
        <n-form ref="formRef" :model="form" label-placement="left" label-width="120">
          <n-form-item label="案件名称" path="case_name">
            <n-input v-model:value="form.case_name" placeholder="例：张三诉XX医院医疗损害赔偿" />
          </n-form-item>
          <n-form-item label="案件类型" path="case_type">
            <n-radio-group v-model:value="form.case_type">
              <n-radio value="injury">医疗损害（伤残）</n-radio>
              <n-radio value="death">医疗损害（死亡）</n-radio>
            </n-radio-group>
          </n-form-item>
          <n-form-item label="是否未成年人（新生儿）" path="is_minor">
            <n-switch v-model:value="form.is_minor" />
          </n-form-item>
          <n-alert type="info" style="margin-top: 4px">
            原被告信息将在上传素材后自动从证据材料中提取，无需手动填写
          </n-alert>
        </n-form>
        <template #action>
          <n-space>
            <n-button @click="showCreateForm = false">取消</n-button>
            <n-button type="primary" :loading="creating" @click="handleCreate">创建案件</n-button>
          </n-space>
        </template>
      </n-card>

      <!-- 已有案件列表 -->
      <n-card title="已有案件">
        <template #header-extra>
          <n-space align="center">
            <n-input v-model:value="caseListSearch" placeholder="搜索案件名称" clearable size="small" style="width: 200px" @update:value="handleCaseListSearch" />
            <n-select v-model:value="caseListStatusFilter" :options="caseStatusOptions" placeholder="状态" clearable size="small" style="width: 120px" @update:value="handleCaseListSearch" />
            <n-button type="primary" @click="showCreateForm = true">
              <template #icon><n-icon><AddOutline /></n-icon></template>
              创建案件
            </n-button>
          </n-space>
        </template>
        <n-data-table
          :columns="caseListColumns"
          :data="filteredCaseList"
          :loading="caseListLoading"
          :bordered="false"
          size="small"
          :scroll-x="isSuperAdmin ? 1100 : 800"
          :pagination="{
            page: caseListPage,
            pageSize: caseListPageSize,
            itemCount: caseListTotal,
            showSizePicker: true,
            pageSizes: [10, 20, 50],
          }"
          @update:page="handleCaseListPageChange"
          @update:page-size="handleCaseListPageSizeChange"
        />
      </n-card>
    </template>

    <!-- ═══ 案件内工作区（步骤条 + 步骤内容） ═══ -->
    <template v-if="!showHomePage">
    <!-- 五步流程 — 使用 @update:current 监听步骤点击（n-step 不支持 @click） -->
    <n-steps :current="currentStep + 1" @update:current="handleStepClick" style="margin-bottom: 24px">
      <n-step title="原始素材预处理" />
      <n-step title="上传素材" />
      <n-step title="赔偿金额计算" />
      <n-step title="证据目录" />
      <n-step title="分析与导出" />
    </n-steps>

    <!-- Step 0: 原始素材预处理 -->
    <Step0Preprocess
      v-if="currentStep === STEP.PREPROCESS"
      :case-id="currentCaseId"
      @next-step="navigateToStep(STEP.UPLOAD)"
      @step0-completed="onStep0Completed"
    />

    <!-- Step 1: 上传素材 -->
    <n-card v-if="currentStep === STEP.UPLOAD" title="上传原始素材">
      <template #header-extra>
        <n-tag :type="statusTagType(currentCase?.status)">{{ statusLabel(currentCase?.status) }}</n-tag>
      </template>
      <div
        class="upload-drop-zone"
        :class="{ 'upload-drop-zone--active': dragOver }"
        @click="triggerFileInput"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="handleDrop"
        style="cursor: pointer; border: 2px dashed #e0e0e6; border-radius: 8px; transition: all 0.3s"
      >
        <div style="padding: 20px 0; text-align: center">
          <n-icon size="48" :depth="3"><CloudUploadOutline /></n-icon>
          <n-text style="font-size: 16px; display: block; margin-top: 8px">
            点击或拖拽文件到此区域上传
          </n-text>
          <n-p depth="3" style="margin: 8px 0 0 0">
            支持 PDF / 图片 / Word 文档，可批量上传
          </n-p>
          <n-spin v-if="uploadingFiles" size="small" style="margin-top: 8px">
            <template #description><n-text depth="3">上传中...</n-text></template>
          </n-spin>
        </div>
        <input
          ref="fileInputRef"
          type="file"
          multiple
          :accept="'.pdf,.jpg,.jpeg,.png,.bmp,.tiff,.doc,.docx'"
          style="display: none"
          @change="handleFileInputChange"
          :disabled="processing"
        />
      </div>

      <!-- 律师信息输入 -->
      <n-divider>律师信息</n-divider>
      <n-space vertical>
        <n-text depth="3">手动输入代理律师姓名和电话（最多2位），将附加在每位原告信息后</n-text>
        <n-grid :cols="2" :x-gap="12">
          <n-gi>
            <n-space align="center">
              <n-input v-model:value="lawyerInfo[0].name" placeholder="律师姓名" style="width: 120px" />
              <n-input v-model:value="lawyerInfo[0].phone" placeholder="电话号码" style="width: 180px" />
            </n-space>
          </n-gi>
          <n-gi>
            <n-space align="center">
              <n-input v-model:value="lawyerInfo[1].name" placeholder="律师姓名" style="width: 120px" />
              <n-input v-model:value="lawyerInfo[1].phone" placeholder="电话号码" style="width: 180px" />
            </n-space>
          </n-gi>
        </n-grid>
        <n-button size="small" type="primary" :loading="savingLawyer" @click="saveLawyerInfo">
          保存律师信息
        </n-button>
      </n-space>

      <!-- 被告联系方式输入 -->
      <n-divider>被告联系方式</n-divider>
      <n-space vertical>
        <n-text depth="3">手动输入被告医院联系电话（OCR无法识别时手动补充，将显示在起诉状中）</n-text>
        <n-space align="center">
          <n-input v-model:value="defendantPhone" placeholder="联系电话" style="width: 180px" />
        </n-space>
        <n-button size="small" type="primary" :loading="savingDefendantPhone" @click="saveDefendantPhone">
          保存被告联系方式
        </n-button>
      </n-space>

      <!-- 已上传材料列表 — 显示每个素材的 OCR 和分类状态 -->
      <n-divider v-if="materials.length > 0">
        已上传材料 ({{ materials.length }})
        <n-text v-if="completedCount > 0" depth="3" style="margin-left: 8px">
          — OCR 完成 {{ completedCount }}/{{ materials.length }}
        </n-text>
      </n-divider>

      <!-- 批量操作栏 -->
      <n-space v-if="materials.length > 0 && selectedMaterialIds.size > 0" align="center" style="margin-bottom: 12px">
        <n-tag type="info" size="small">已选 {{ selectedMaterialIds.size }} 项</n-tag>
        <n-button size="small" type="error" :loading="batchDeleting" @click="handleBatchDelete">
          批量删除 ({{ selectedMaterialIds.size }})
        </n-button>
        <n-button size="small" @click="clearSelection">取消选择</n-button>
      </n-space>

      <n-table v-if="materials.length > 0" :bordered="false" :single-line="false" size="small">
        <thead>
          <tr>
            <th style="width: 40px">
              <n-checkbox
                :checked="isAllSelected"
                :indeterminate="isSomeSelected"
                @update:checked="toggleSelectAll"
              />
            </th>
            <th>文件名</th>
            <th style="width: 100px">大小</th>
            <th style="width: 130px">OCR 状态</th>
            <th style="width: 130px">自动分类</th>
            <th style="width: 140px">手动分类</th>
            <th style="width: 80px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="mat in materials" :key="mat.id" :style="selectedMaterialIds.has(mat.id) ? 'background: var(--n-td-color-hover)' : ''">
            <td>
              <n-checkbox
                :checked="selectedMaterialIds.has(mat.id)"
                @update:checked="(v: boolean) => toggleSelect(mat.id, v)"
              />
            </td>
            <td>
              <n-ellipsis style="max-width: 300px">{{ mat.original_filename || '-' }}</n-ellipsis>
            </td>
            <td>{{ mat.file_size ? (mat.file_size / 1024).toFixed(1) + ' KB' : '-' }}</td>
            <td>
              <n-tooltip v-if="mat.ocr_status === 'failed' && mat.ocr_result?.error" trigger="hover">
                <template #trigger>
                  <n-tag :type="ocrTagType(mat.ocr_status)" size="small" style="cursor: help">
                    {{ ocrStatusLabel(mat.ocr_status) }}
                  </n-tag>
                </template>
                {{ mat.ocr_result.error }}
              </n-tooltip>
              <n-tag v-else :type="ocrTagType(mat.ocr_status)" size="small">
                {{ ocrStatusLabel(mat.ocr_status) }}
              </n-tag>
            </td>
            <td>
              <template v-if="mat.auto_category">
                <n-tooltip v-if="mat.category_confidence && mat.category_confidence < 0.6" trigger="hover">
                  <template #trigger>
                    <n-tag size="small" type="error" style="cursor: help">
                      {{ categoryLabel(mat.auto_category) }}
                      <span> {{ (mat.category_confidence * 100).toFixed(0) }}%</span>
                    </n-tag>
                  </template>
                  自动分类置信度较低（{{ (mat.category_confidence * 100).toFixed(0) }}%），建议在「手动分类」列中修正。
                </n-tooltip>
                <n-tag v-else size="small" :type="mat.category_confidence && mat.category_confidence > 0.8 ? 'success' : 'warning'">
                  {{ categoryLabel(mat.auto_category) }}
                  <span v-if="mat.category_confidence"> {{ (mat.category_confidence * 100).toFixed(0) }}%</span>
                </n-tag>
              </template>
              <n-text v-else depth="3">-</n-text>
            </td>
            <td>
              <n-select
                size="tiny"
                :value="mat.manual_category || mat.auto_category || null"
                :options="categoryOptions"
                :placeholder="mat.auto_category ? '点击修改' : '点击选择'"
                :consistent-menu-width="false"
                :status="(!mat.manual_category && mat.auto_category && mat.category_confidence && mat.category_confidence < 0.6) ? 'warning' : undefined"
                style="min-width: 120px"
                clearable
                @update:value="(v: string) => handleChangeCategory(mat, v)"
              />
            </td>
            <td>
              <n-space :size="4">
                <n-button
                  v-if="mat.page_count && mat.page_count > 1"
                  size="tiny"
                  quaternary
                  type="info"
                  @click="openPagePreview(mat)"
                >
                  预览
                </n-button>
                <n-button
                  v-if="mat.ocr_status === 'failed'"
                  size="tiny"
                  quaternary
                  type="warning"
                  :loading="retryingMaterialId === mat.id"
                  @click="handleRetryOcr(mat.id)"
                >
                  重试
                </n-button>
                <n-button size="tiny" quaternary type="error" @click="handleDeleteMaterial(mat.id)">
                  删除
                </n-button>
              </n-space>
            </td>
          </tr>
        </tbody>
      </n-table>

      <!-- 总进度条 -->
      <n-card v-if="showProgress" size="small" title="OCR + 自动分类 进度" style="margin-top: 16px">
        <n-progress
          type="line"
          :percentage="progressPercent"
          :indicator-placement="'inside'"
          :status="progressStatus"
        />
        <n-space justify="space-between" style="margin-top: 8px">
          <n-text depth="3">
            {{ completedCount }}/{{ materials.length }} 文件已完成
          </n-text>
          <n-button size="small" type="warning" :disabled="!processing" :loading="stoppingProcess" @click="handleStopProcess">
            停止处理
          </n-button>
        </n-space>

        <!-- 各步骤状态 -->
        <n-space vertical style="margin-top: 12px">
          <n-text v-for="step in progressSteps" :key="step.step_name" :type="stepStatusType(step.status)">
            {{ stepLabel(step.step_name) }}：{{ stepStatusLabel(step.status) }}
            <span v-if="step.duration_ms">（{{ (step.duration_ms / 1000).toFixed(1) }}s）</span>
          </n-text>
        </n-space>
      </n-card>

      <template #action>
        <n-space>
          <n-button @click="handleGoHome">返回</n-button>
          <n-button
            v-if="failedCount > 0"
            type="warning"
            :disabled="processing"
            :loading="processing"
            @click="handleRetryFailed"
          >
            重新处理失败素材（{{ failedCount }}）
          </n-button>
          <n-button
            type="primary"
            :disabled="materials.length === 0 || processing"
            :loading="processing"
            @click="handleProcess"
          >
            {{ processing ? '处理中...' : '开始处理（OCR + 自动分类）' }}
          </n-button>
        </n-space>
      </template>
    </n-card>

    <!-- Step 2: 赔偿金额计算 -->
    <n-card v-if="currentStep === STEP.COMPENSATION" title="赔偿金额计算">
      <!-- 相关素材（折叠面板） -->
      <n-collapse style="margin-bottom: 16px">
        <n-collapse-item title="相关素材（医疗费用类）" name="materials">
          <n-table :bordered="false" :single-line="false" size="small">
            <thead>
              <tr><th>文件名</th><th>分类</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="mat in feeReceiptMaterials" :key="mat.id">
                <td>{{ mat.original_filename }}</td>
                <td>{{ mat.effective_category }}</td>
                <td>
                  <n-tag :type="mat.ocr_status === 'completed' ? 'success' : 'warning'" size="small">
                    {{ mat.ocr_status === 'completed' ? '已识别' : '识别中' }}
                  </n-tag>
                </td>
                <td>
                  <n-button size="small" quaternary @click="openPagePreview(mat)">查看</n-button>
                </td>
              </tr>
              <tr v-if="feeReceiptMaterials.length === 0">
                <td colspan="4" style="text-align:center;color:#999">暂无费用类素材</td>
              </tr>
            </tbody>
          </n-table>
        </n-collapse-item>
      </n-collapse>

      <!-- 参数配置 — 按赔偿项目顺序排列（始终显示） -->
      <n-card title="参数配置" size="small" style="margin-bottom: 16px">
        <n-grid :cols="1" :x-gap="12" :y-gap="8" responsive="screen" :cols-s="2" :cols-m="3">
          <!-- ① 误工费：月均工资 + 误工天数 -->
          <n-gi>
            <n-form-item label="上年度职工月均工资(元/月)" label-placement="top">
              <n-input-number v-model:value="compParams.monthly_salary" size="small" :min="0" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="误工天数" label-placement="top">
              <n-input-number v-model:value="compParams.lost_wage_days" size="small" :min="0" style="width:100%" />
            </n-form-item>
          </n-gi>
          <!-- ② 护理费：护理工资 + 护理依赖 + 护理人数 -->
          <n-gi>
            <n-form-item label="护理费平均工资(元/年)" label-placement="top">
              <n-input-number v-model:value="compParams.nursing_annual_salary" size="small" :min="0" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="护理依赖赔付比例" label-placement="top">
              <n-select
                v-model:value="compParams.nursing_dependency_level"
                size="small"
                :options="nursingDependencyOptions"
                style="width:100%"
              />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="护理人员人数" label-placement="top">
              <n-input-number v-model:value="compParams.nursing_person_count" size="small" :min="1" :max="3" style="width:100%" />
            </n-form-item>
          </n-gi>
          <!-- ③ 住院天数（护理/伙食/营养共用） -->
          <n-gi>
            <n-form-item label="住院天数" label-placement="top">
              <n-input-number v-model:value="compParams.hospital_days" size="small" :min="0" style="width:100%" />
            </n-form-item>
          </n-gi>
          <!-- ④ 住院伙食补助 -->
          <n-gi>
            <n-form-item label="住院伙食补助(元/天)" label-placement="top">
              <n-input-number v-model:value="compParams.daily_food_subsidy" size="small" :min="0" style="width:100%" />
            </n-form-item>
          </n-gi>
          <!-- ⑤ 营养费 -->
          <n-gi>
            <n-form-item label="营养费(元/天)" label-placement="top">
              <n-input-number v-model:value="compParams.daily_nutrition" size="small" :min="0" style="width:100%" />
            </n-form-item>
          </n-gi>
          <!-- ⑥ 残疾赔偿金/死亡赔偿金：赔偿年限 + 伤残系数 + 受害人年龄 -->
          <n-gi>
            <n-form-item label="赔偿年限(年)" label-placement="top">
              <n-input-number v-model:value="compParams.compensation_years" size="small" :min="0" :max="30" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="伤残系数" label-placement="top">
              <n-input-number v-model:value="compParams.disability_coefficient" size="small" :min="0" :max="1" :step="0.01" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="受害人年龄" label-placement="top">
              <n-input-number v-model:value="compParams.victim_age" size="small" :min="0" :max="120" placeholder="未填则用赔偿年限" style="width:100%" />
            </n-form-item>
          </n-gi>
        </n-grid>
        <template #action>
          <n-space>
            <n-button size="small" @click="handleSaveParams" :loading="savingParams">保存参数</n-button>
            <n-button type="primary" size="small" @click="handleRecalculate">重新计算</n-button>
          </n-space>
        </template>
      </n-card>

      <!-- 赔偿费用清单表格（计算后显示） -->
      <n-table v-if="compensationData && compensationData.items?.length" :bordered="true" :single-line="false" size="small" style="margin-bottom: 16px">
        <thead>
          <tr>
            <th style="width:40px">序号</th>
            <th>赔偿项目</th>
            <th style="width:150px">金额(元)</th>
            <th>计算依据</th>
            <th>来源素材</th>
            <th style="width:60px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, idx) in compensationData.items" :key="item.fee_type">
            <td>{{ Number(idx) + 1 }}</td>
            <td>{{ item.fee_name }}</td>
            <td>
              <n-input-number
                v-if="editingFeeType === item.fee_type"
                v-model:value="editAmount"
                size="small"
                :min="0"
                :precision="2"
                @blur="exitFeeEdit(item)"
                @keyup.enter="saveFeeEdit(item)"
              />
              <span v-else style="cursor:pointer" @click="startFeeEdit(item)">
                {{ formatMoney(item.manual_amount ?? item.amount) }}
                <n-icon size="14" style="vertical-align:middle;color:#999"><CreateOutline /></n-icon>
              </span>
            </td>
            <td style="font-size:12px;color:#666">{{ item.calculation_basis }}</td>
            <td style="font-size:12px">
              <span v-for="s in item.sources" :key="s.material_id">{{ s.filename }}; </span>
              <span v-if="!item.sources?.length" style="color:#999">-</span>
            </td>
            <td>
              <n-button v-if="item.manual_amount !== null" size="tiny" quaternary type="warning"
                @click="resetFeeEdit(item)">重置</n-button>
            </td>
          </tr>
          <tr style="font-weight:bold;background:#f5f5f5">
            <td colspan="2">合计</td>
            <td>{{ formatMoney(compensationTotal) }}</td>
            <td colspan="2"></td>
            <td>
              <n-button
                size="tiny"
                type="primary"
                :loading="savingCompChanges"
                @click="saveAllCompensationEdits"
              >
                保存修改
              </n-button>
            </td>
          </tr>
        </tbody>
      </n-table>

      <!-- 操作按钮（底部） -->
      <n-space justify="center" style="margin-bottom: 16px">
        <n-button type="primary" :loading="calculatingCompensation" @click="handleCalculateCompensation">
          自动计算赔偿
        </n-button>
        <n-button :disabled="!compensationData" @click="handleExportCompensation">
          导出 Excel
        </n-button>
      </n-space>

      <!-- 未计算提示 -->
      <n-alert v-if="!compensationData" type="info" style="margin-bottom: 16px">
        填写上方参数后点击「自动计算赔偿」生成费用清单
      </n-alert>

      <!-- 底部导航按钮 -->
      <n-divider />
      <n-space justify="space-between">
        <n-button @click="navigateToStep(STEP.UPLOAD)">返回</n-button>
        <n-button type="primary" @click="handleNextToCatalog">下一步：证据目录</n-button>
      </n-space>
    </n-card>

    <!-- Step 3: 证据目录 -->
    <n-card v-if="currentStep === STEP.CATALOG" title="证据目录">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="handleExportCatalogPdf">
            <template #icon><n-icon><DocumentTextOutline /></n-icon></template>
            证据目录
          </n-button>
          <n-button size="small" type="primary" @click="handleExportMaterialsPdf">
            <template #icon><n-icon><DocumentTextOutline /></n-icon></template>
            证据材料
          </n-button>
        </n-space>
      </template>

      <!-- 素材管理（可折叠，任意步骤可删除素材） -->
      <n-collapse style="margin-bottom: 16px">
        <n-collapse-item title="素材管理" name="materials">
          <n-space v-if="materials.length > 0 && selectedMaterialIds.size > 0" align="center" style="margin-bottom: 8px">
            <n-tag type="info" size="small">已选 {{ selectedMaterialIds.size }} 项</n-tag>
            <n-button size="small" type="error" :loading="batchDeleting" @click="handleBatchDelete">
              批量删除 ({{ selectedMaterialIds.size }})
            </n-button>
            <n-button size="small" @click="clearSelection">取消选择</n-button>
          </n-space>
          <n-table v-if="materials.length > 0" :bordered="false" :single-line="false" size="small">
            <thead>
              <tr>
                <th style="width: 40px">
                  <n-checkbox :checked="isAllSelected" :indeterminate="isSomeSelected" @update:checked="toggleSelectAll" />
                </th>
                <th>文件名</th>
                <th style="width: 100px">大小</th>
                <th style="width: 130px">OCR 状态</th>
                <th style="width: 130px">自动分类</th>
                <th style="width: 140px">手动分类</th>
                <th style="width: 80px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="mat in materials" :key="mat.id" :style="selectedMaterialIds.has(mat.id) ? 'background: var(--n-td-color-hover)' : ''">
                <td>
                  <n-checkbox :checked="selectedMaterialIds.has(mat.id)" @update:checked="(v: boolean) => toggleSelect(mat.id, v)" />
                </td>
                <td><n-ellipsis style="max-width: 300px">{{ mat.original_filename || '-' }}</n-ellipsis></td>
                <td>{{ mat.file_size ? (mat.file_size / 1024).toFixed(1) + ' KB' : '-' }}</td>
                <td>
                  <n-tooltip v-if="mat.ocr_status === 'failed' && mat.ocr_result?.error" trigger="hover">
                    <template #trigger>
                      <n-tag :type="ocrTagType(mat.ocr_status)" size="small" style="cursor: help">{{ ocrStatusLabel(mat.ocr_status) }}</n-tag>
                    </template>
                    {{ mat.ocr_result.error }}
                  </n-tooltip>
                  <n-tag v-else :type="ocrTagType(mat.ocr_status)" size="small">{{ ocrStatusLabel(mat.ocr_status) }}</n-tag>
                </td>
                <td>
                  <template v-if="mat.auto_category">
                    <n-tooltip v-if="mat.category_confidence && mat.category_confidence < 0.6" trigger="hover">
                      <template #trigger>
                        <n-tag size="small" type="error" style="cursor: help">
                          {{ categoryLabel(mat.auto_category) }}
                          <span> {{ (mat.category_confidence * 100).toFixed(0) }}%</span>
                        </n-tag>
                      </template>
                      自动分类置信度较低（{{ (mat.category_confidence * 100).toFixed(0) }}%），建议在「手动分类」列中修正。
                    </n-tooltip>
                    <n-tag v-else size="small" :type="mat.category_confidence && mat.category_confidence > 0.8 ? 'success' : 'warning'">
                      {{ categoryLabel(mat.auto_category) }}
                      <span v-if="mat.category_confidence"> {{ (mat.category_confidence * 100).toFixed(0) }}%</span>
                    </n-tag>
                  </template>
                  <n-text v-else depth="3">-</n-text>
                </td>
                <td>
                  <n-select
                    size="tiny"
                    :value="mat.manual_category || mat.auto_category || null"
                    :options="categoryOptions"
                    placeholder="点击选择"
                    :consistent-menu-width="false"
                    style="min-width: 120px"
                    clearable
                    @update:value="(v: string) => handleChangeCategory(mat, v)"
                  />
                </td>
                <td>
                  <n-space :size="4">
                    <n-button v-if="mat.page_count && mat.page_count > 1" size="tiny" quaternary type="info" @click="openPagePreview(mat)">预览</n-button>
                    <n-button size="tiny" quaternary type="error" @click="handleDeleteMaterial(mat.id)">删除</n-button>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </n-table>
          <n-text v-else depth="3">暂无素材</n-text>
          <!-- 上传更多素材按钮 -->
          <div style="margin-top: 12px; text-align: center">
            <n-button size="small" :dashed="true" :loading="uploadingFiles" :disabled="processing" @click="triggerFileInput">
              <template #icon><n-icon><CloudUploadOutline /></n-icon></template>
              上传更多素材
            </n-button>
          </div>
        </n-collapse-item>
      </n-collapse>

      <n-spin :show="catalogLoading">
        <template v-if="catalogGroups.length > 0">
          <n-collapse>
            <n-collapse-item
              v-for="group in catalogGroups"
              :key="group.category"
              :title="`${group.category_name}（${group.items.length} 项）`"
              :name="group.category"
            >
              <n-table :bordered="false" :single-line="false" size="small">
                <thead>
                  <tr>
                    <th style="width: 50px">序号</th>
                    <th style="width: 180px">名称</th>
                    <th>说明</th>
                    <th style="width: 140px">证明目的</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in group.items" :key="item.id">
                    <td>{{ item.catalog_index }}</td>
                    <td>
                      <n-input size="small" :value="item.catalog_title || ''"
                        @update:value="(v: string) => handleUpdateItem(item.id, 'catalog_title', v)" />
                    </td>
                    <td>
                      <n-input size="small" :value="item.catalog_description || ''"
                        @update:value="(v: string) => handleUpdateItem(item.id, 'catalog_description', v)" />
                    </td>
                    <td>
                      <n-input size="small" :value="item.proof_purpose || ''"
                        @update:value="(v: string) => handleUpdateItem(item.id, 'proof_purpose', v)" />
                    </td>
                  </tr>
                </tbody>
              </n-table>
            </n-collapse-item>
          </n-collapse>

          <n-descriptions bordered :column="2" label-placement="left" style="margin-top: 16px" size="small">
            <n-descriptions-item label="费用总计">
              <n-space align="center" :size="4">
                <template v-if="editingCatalogTotal">
                  <n-input-number
                    v-model:value="editCatalogTotalAmount"
                    size="small"
                    :min="0"
                    :precision="2"
                    style="width: 160px"
                    @keyup.enter="saveCatalogTotalEdit"
                  />
                  <n-button size="tiny" type="primary" @click="saveCatalogTotalEdit">保存</n-button>
                  <n-button size="tiny" @click="cancelEditCatalogTotal">取消</n-button>
                </template>
                <template v-else>
                  <span v-if="catalogTotalAmount > 0">¥{{ catalogTotalAmount.toFixed(2) }}</span>
                  <span v-else>——（暂无）</span>
                  <n-button size="tiny" quaternary @click="startEditCatalogTotal">
                    <template #icon><n-icon size="14"><CreateOutline /></n-icon></template>
                  </n-button>
                </template>
              </n-space>
            </n-descriptions-item>
            <n-descriptions-item label="材料总数">{{ totalMaterialCount }} 份</n-descriptions-item>
          </n-descriptions>
        </template>
        <template v-else>
          <n-alert v-if="catalogEmptyReason === 'all_failed'" type="warning" title="OCR识别失败">
            所有上传的材料均OCR识别失败，请检查文件质量（清晰度、分辨率）后重新上传。可返回 Step 1 删除失败材料并重新上传。
          </n-alert>
          <n-empty v-else description="暂无目录数据，请先上传素材并完成处理" />
        </template>
      </n-spin>

      <template #action>
        <n-space>
          <n-button @click="navigateToStep(STEP.COMPENSATION)">返回</n-button>
          <n-button type="primary" @click="handleSaveCatalog">保存目录修改</n-button>
          <n-button type="primary" @click="navigateToStep(STEP.ANALYSIS)">下一步：分析与导出</n-button>
        </n-space>
      </template>
    </n-card>

    <!-- Step 4: 分析与导出 -->
    <n-card v-if="currentStep === STEP.ANALYSIS" title="分析与导出">

      <!-- 素材管理（可折叠，任意步骤可删除素材） -->
      <n-collapse style="margin-bottom: 16px">
        <n-collapse-item title="素材管理" name="materials">
          <n-space v-if="materials.length > 0 && selectedMaterialIds.size > 0" align="center" style="margin-bottom: 8px">
            <n-tag type="info" size="small">已选 {{ selectedMaterialIds.size }} 项</n-tag>
            <n-button size="small" type="error" :loading="batchDeleting" @click="handleBatchDelete">
              批量删除 ({{ selectedMaterialIds.size }})
            </n-button>
            <n-button size="small" @click="clearSelection">取消选择</n-button>
          </n-space>
          <n-table v-if="materials.length > 0" :bordered="false" :single-line="false" size="small">
            <thead>
              <tr>
                <th style="width: 40px">
                  <n-checkbox :checked="isAllSelected" :indeterminate="isSomeSelected" @update:checked="toggleSelectAll" />
                </th>
                <th>文件名</th>
                <th style="width: 100px">大小</th>
                <th style="width: 130px">OCR 状态</th>
                <th style="width: 130px">自动分类</th>
                <th style="width: 140px">手动分类</th>
                <th style="width: 80px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="mat in materials" :key="mat.id" :style="selectedMaterialIds.has(mat.id) ? 'background: var(--n-td-color-hover)' : ''">
                <td>
                  <n-checkbox :checked="selectedMaterialIds.has(mat.id)" @update:checked="(v: boolean) => toggleSelect(mat.id, v)" />
                </td>
                <td><n-ellipsis style="max-width: 300px">{{ mat.original_filename || '-' }}</n-ellipsis></td>
                <td>{{ mat.file_size ? (mat.file_size / 1024).toFixed(1) + ' KB' : '-' }}</td>
                <td>
                  <n-tooltip v-if="mat.ocr_status === 'failed' && mat.ocr_result?.error" trigger="hover">
                    <template #trigger>
                      <n-tag :type="ocrTagType(mat.ocr_status)" size="small" style="cursor: help">{{ ocrStatusLabel(mat.ocr_status) }}</n-tag>
                    </template>
                    {{ mat.ocr_result.error }}
                  </n-tooltip>
                  <n-tag v-else :type="ocrTagType(mat.ocr_status)" size="small">{{ ocrStatusLabel(mat.ocr_status) }}</n-tag>
                </td>
                <td>
                  <template v-if="mat.auto_category">
                    <n-tooltip v-if="mat.category_confidence && mat.category_confidence < 0.6" trigger="hover">
                      <template #trigger>
                        <n-tag size="small" type="error" style="cursor: help">
                          {{ categoryLabel(mat.auto_category) }}
                          <span> {{ (mat.category_confidence * 100).toFixed(0) }}%</span>
                        </n-tag>
                      </template>
                      自动分类置信度较低（{{ (mat.category_confidence * 100).toFixed(0) }}%），建议在「手动分类」列中修正。
                    </n-tooltip>
                    <n-tag v-else size="small" :type="mat.category_confidence && mat.category_confidence > 0.8 ? 'success' : 'warning'">
                      {{ categoryLabel(mat.auto_category) }}
                      <span v-if="mat.category_confidence"> {{ (mat.category_confidence * 100).toFixed(0) }}%</span>
                    </n-tag>
                  </template>
                  <n-text v-else depth="3">-</n-text>
                </td>
                <td>
                  <n-select
                    size="tiny"
                    :value="mat.manual_category || mat.auto_category || null"
                    :options="categoryOptions"
                    placeholder="点击选择"
                    :consistent-menu-width="false"
                    style="min-width: 120px"
                    clearable
                    @update:value="(v: string) => handleChangeCategory(mat, v)"
                  />
                </td>
                <td>
                  <n-space :size="4">
                    <n-button v-if="mat.page_count && mat.page_count > 1" size="tiny" quaternary type="info" @click="openPagePreview(mat)">预览</n-button>
                    <n-button size="tiny" quaternary type="error" @click="handleDeleteMaterial(mat.id)">删除</n-button>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </n-table>
          <n-text v-else depth="3">暂无素材</n-text>
          <!-- 上传更多素材按钮 -->
          <div style="margin-top: 12px; text-align: center">
            <n-button size="small" :dashed="true" :loading="uploadingFiles" :disabled="processing" @click="triggerFileInput">
              <template #icon><n-icon><CloudUploadOutline /></n-icon></template>
              上传更多素材
            </n-button>
          </div>
        </n-collapse-item>
      </n-collapse>

      <n-space vertical>
        <n-card size="small" title="智能分析" embedded>
          <n-space vertical>
            <!-- 状态1: 未分析 — 显示"开始智能分析"可点击 -->
            <n-button
              v-if="!hasAnalysisResult && !analyzing && currentCase?.status !== 'failed'"
              type="primary"
              :loading="analyzing"
              @click="handleStartAnalysis"
            >
              开始智能分析
            </n-button>

            <!-- 状态2: 分析中 — loading -->
            <n-button
              v-if="analyzing"
              type="primary"
              loading
              disabled
            >
              分析中...
            </n-button>

            <!-- 状态3: 分析完成 — "开始"变灰 + "再次分析" -->
            <template v-if="hasAnalysisResult && !analyzing">
              <n-space align="center">
                <n-button disabled>开始智能分析</n-button>
                <n-tag type="success" size="small">✓ 分析完成</n-tag>
              </n-space>
              <n-button type="warning" secondary @click="handleReAnalysis">
                再次智能分析
              </n-button>
            </template>

            <!-- 状态4: 分析失败 — "重新分析"可点击 -->
            <n-button
              v-if="currentCase?.status === 'failed' && !analyzing"
              type="warning"
              @click="handleStartAnalysis"
            >
              重新分析
            </n-button>
          </n-space>

          <template v-if="hasAnalysisResult">
            <n-divider>分析结果摘要</n-divider>

            <!-- 缺失项提示 -->
            <template v-if="analysisResult?.missing_items && Array.isArray(analysisResult.missing_items) && analysisResult.missing_items.length > 0">
              <n-alert type="warning" title="以下证据材料可能缺失" style="margin-bottom: 12px">
                <ul style="margin: 0; padding-left: 20px">
                  <li v-for="(item, idx) in analysisResult!.missing_items" :key="idx">{{ item }}</li>
                </ul>
              </n-alert>
            </template>
            <template v-else-if="analysisResult?.validation_result">
              <n-alert type="success" style="margin-bottom: 12px">
                证据材料完整性校验通过
              </n-alert>
            </template>

            <!-- 分析结果概要 -->
            <n-descriptions bordered :column="2" label-placement="left" size="small">
              <n-descriptions-item
                v-for="(val, key) in analysisSummaryFields"
                :key="String(key)"
                :label="String(key)"
              >
                {{ val }}
              </n-descriptions-item>
            </n-descriptions>

            <!-- 完整分析数据折叠 -->
            <n-collapse style="margin-top: 8px">
              <n-collapse-item title="查看完整分析数据" name="full">
                <n-code :code="JSON.stringify(analysisResult?.analysis_result, null, 2)" language="json" />
              </n-collapse-item>
            </n-collapse>
          </template>
        </n-card>

        <n-card size="small" title="文档导出" embedded>
          <n-alert v-if="!hasAnalysisResult" type="info" style="margin-bottom: 12px">
            请先完成智能分析，然后导出文档
          </n-alert>
          <n-space wrap>
            <n-button :loading="exportingDoc === 'filing'" @click="handleExportFilingEvidence">
              <template #icon><n-icon><DocumentOutline /></n-icon></template>
              立案证据.docx
            </n-button>
            <n-button :loading="exportingDoc === 'complaint'" @click="handleExportComplaint">
              <template #icon><n-icon><DocumentOutline /></n-icon></template>
              民事起诉状.docx
            </n-button>
            <n-button :loading="exportingDoc === 'appraisal'" @click="handleExportAppraisalApp">
              <template #icon><n-icon><DocumentOutline /></n-icon></template>
              司法鉴定申请书.docx
            </n-button>
            <n-button :loading="exportingDoc === 'compensation'" @click="handleExportCompensation">
              <template #icon><n-icon><DocumentOutline /></n-icon></template>
              赔偿费用清单.xlsx
            </n-button>
            <n-button :loading="exportingDoc === 'catalog'" @click="handleExportCatalogPdf">
              <template #icon><n-icon><DocumentTextOutline /></n-icon></template>
              证据目录.pdf
            </n-button>
            <n-button :loading="exportingDoc === 'materials'" @click="handleExportMaterialsPdf">
              <template #icon><n-icon><DocumentTextOutline /></n-icon></template>
              证据材料.pdf
            </n-button>
          </n-space>

          <n-divider>一键打包</n-divider>
          <n-button type="primary" :loading="bundling" @click="handleExportBundle">
            全部打包下载（ZIP）
          </n-button>
        </n-card>
      </n-space>

      <template #action>
        <n-button @click="navigateToStep(STEP.CATALOG)">返回</n-button>
      </template>
    </n-card>


    <!-- 多页文档预览选择抽屉 -->
    <n-drawer v-model:show="showPageDrawer" :width="800" placement="right">
      <n-drawer-content title="页面预览与选择" closable>
        <template v-if="pagePreviewLoading">
          <n-spin size="large" style="display: block; margin: 40px auto" />
        </template>
        <template v-else-if="pagePreviewData">
          <n-alert type="info" style="margin-bottom: 16px">
            点击页面缩略图可选择/取消选择。被选中的页面将被 OCR 处理，未选中的页面将跳过。
            <span v-if="pagePreviewData.selected_pages.length > 0">
              当前已选 <strong>{{ pagePreviewData.selected_pages.length }}</strong> / {{ pagePreviewData.total_pages }} 页。
            </span>
            <span v-else>
              当前未选择页面，处理时将 OCR <strong>全部 {{ pagePreviewData.total_pages }}</strong> 页。
            </span>
          </n-alert>

          <div style="display: flex; flex-wrap: wrap; gap: 12px">
            <div
              v-for="pg in pagePreviewData.pages"
              :key="pg.page"
              style="cursor: pointer; text-align: center; border: 2px solid transparent; border-radius: 8px; padding: 4px; transition: all 0.2s"
              :style="{
                borderColor: pageSelectedSet.has(pg.page) ? '#18a058' : 'transparent',
                background: pageSelectedSet.has(pg.page) ? 'rgba(24,160,88,0.06)' : 'transparent',
              }"
              @click="togglePageSelection(pg.page)"
            >
              <div style="position: relative">
                <img
                  :src="'data:image/jpeg;base64,' + pg.thumbnail_b64"
                  :alt="'第' + pg.page + '页'"
                  style="max-width: 180px; max-height: 240px; border-radius: 4px; display: block"
                />
                <n-tag
                  v-if="pageSelectedSet.has(pg.page)"
                  type="success"
                  size="tiny"
                  style="position: absolute; top: 4px; right: 4px"
                >
                  ✓
                </n-tag>
              </div>
              <n-text depth="3" style="font-size: 12px; margin-top: 4px; display: block">
                第 {{ pg.page }} 页
              </n-text>
            </div>
          </div>
        </template>

        <template #footer>
          <n-space justify="space-between" style="width: 100%">
            <n-space>
              <n-button size="small" @click="selectAllPages">全选</n-button>
              <n-button size="small" @click="clearPageSelection">清除选择（处理全部）</n-button>
            </n-space>
            <n-space>
              <n-button @click="showPageDrawer = false">取消</n-button>
              <n-button type="primary" :loading="savingPageSelection" @click="handleSavePageSelection">
                保存选择
              </n-button>
            </n-space>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- 金额核算提示弹窗 -->
    <n-modal
      v-model:show="showAmountCheckDialog"
      preset="dialog"
      title="金额核算提示"
      positive-text="已核算，继续"
      negative-text="取消"
      @positive-click="confirmAmountCheck"
    >
      <n-space vertical>
        <n-text>请仔细核算赔偿金额数目，确认各项费用准确无误后再继续。</n-text>
        <n-text v-if="compensationTotal > 0" depth="3">
          当前赔偿合计：¥{{ compensationTotal.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
        </n-text>
      </n-space>
    </n-modal>
    </template><!-- end 案件内工作区 -->

    <!-- ═══ 编辑案件弹窗（全局，不依赖工作区显隐） ═══ -->
    <n-modal v-model:show="showEditModal" preset="dialog" title="编辑案件" positive-text="保存" negative-text="取消"
      @positive-click="handleSaveEdit">
      <n-form label-placement="left" label-width="100" style="margin-top: 12px">
        <n-form-item label="案件名称">
          <n-input v-model:value="editForm.case_name" />
        </n-form-item>
        <n-form-item label="案件类型">
          <n-radio-group v-model:value="editForm.case_type">
            <n-radio value="injury">医疗损害（伤残）</n-radio>
            <n-radio value="death">医疗损害（死亡）</n-radio>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="是否未成年人（新生儿）">
          <n-switch v-model:value="editForm.is_minor" />
        </n-form-item>
      </n-form>
    </n-modal>

    <!-- ═══ 分配租户 Modal（仅超管） ═══ -->
    <n-modal v-model:show="assignTenantModalShow" preset="card" title="分配案件到租户" style="width: 460px">
      <n-space vertical>
        <n-text depth="3">
          案件：{{ assignTenantCase?.case_name }}
        </n-text>
        <n-text depth="3" style="font-size: 13px">
          当前租户：{{ assignTenantCase?.tenant_name || '未分配' }}
        </n-text>
        <n-select
          v-model:value="assignTenantValue"
          :options="tenantOptions.map(t => ({ label: t.name, value: t.id }))"
          placeholder="选择目标租户"
          filterable
          clearable
        />
        <n-alert type="info" :bordered="false">
          分配后，该案件将归属于目标租户，目标租户的管理员和成员将能看到并操作此案件。
        </n-alert>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="assignTenantModalShow = false">取消</n-button>
          <n-button type="primary" :loading="assignTenantSaving" @click="submitAssignTenant">
            确认分配
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, onUnmounted, watch, h } from 'vue'
import {
  useMessage,
  useDialog,
  NButton,
  NTag,
  NPageHeader,
  NSteps,
  NStep,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NRadioGroup,
  NRadio,
  NSwitch,
  NUpload,
  NUploadDragger,
  NIcon,
  NText,
  NP,
  NDataTable,
  NProgress,
  NSpace,
  NSpin,
  NCollapse,
  NCollapseItem,
  NTable,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NDivider,
  NCode,
  NAlert,
  NModal,
  NEllipsis,
  NCheckbox,
  NDrawer,
  NDrawerContent,
  NGrid,
  NGi,
  NSelect,
  NTooltip,
  NInputNumber,
} from 'naive-ui'
import {
  CloudUploadOutline,
  DocumentTextOutline,
  DocumentOutline,
  ListOutline,
  HomeOutline,
  RefreshOutline,
  AddOutline,
  CreateOutline,
} from '@vicons/ionicons5'
import * as evidenceApi from '@/api/evidence'
import type {
  EvidenceCaseListItem,
  MaterialResponse,
  CatalogGroup,
  AnalysisResponse,
  PagePreviewResponse,
} from '@/api/evidence'
import Step0Preprocess from '@/views/Step0Preprocess.vue'
import { useAuthStore } from '@/stores/auth'
import { storeToRefs } from 'pinia'
import { listTenantNames, type TenantNameItem } from '@/api/client'

const message = useMessage()
const dialog = useDialog()

// ─── 当前用户（用于超管判断） ───
const authStore = useAuthStore()
const { isSuperAdmin } = storeToRefs(authStore)

// ─── 租户列表（超管分配案件用） ───
const tenantOptions = ref<TenantNameItem[]>([])
const assignTenantModalShow = ref(false)
const assignTenantCase = ref<EvidenceCaseListItem | null>(null)
const assignTenantValue = ref<string | null>(null)
const assignTenantSaving = ref(false)

async function loadTenantOptions() {
  if (!isSuperAdmin.value) return
  try {
    tenantOptions.value = await listTenantNames()
  } catch {
    // 静默失败
  }
}

function openAssignTenantModal(row: EvidenceCaseListItem) {
  assignTenantCase.value = row
  assignTenantValue.value = row.tenant_id || null
  assignTenantModalShow.value = true
}

async function submitAssignTenant() {
  if (!assignTenantCase.value || !assignTenantValue.value) {
    message.warning('请选择要分配的租户')
    return
  }
  assignTenantSaving.value = true
  try {
    await evidenceApi.updateCase(assignTenantCase.value.id, { tenant_id: assignTenantValue.value })
    message.success('案件已分配到指定租户')
    assignTenantModalShow.value = false
    await loadCaseList(caseListPage.value, caseListPageSize.value)
  } catch (e: unknown) {
    message.error((e as Error).message)
  } finally {
    assignTenantSaving.value = false
  }
}

// ─── 步骤常量 ─────────────────────────────────────────────────────────────────

const STEP = {
  PREPROCESS: 0,
  UPLOAD: 1,
  COMPENSATION: 2,
  CATALOG: 3,
  ANALYSIS: 4,
} as const

// ─── 状态 ─────────────────────────────────────────────────────────────────────

const showHomePage = ref(true) // 案件首页（独立于步骤条）
const currentStep = ref<number>(STEP.PREPROCESS)
const currentCase = ref<evidenceApi.EvidenceCase | null>(null)
const showCreateForm = ref(false)

// 步骤0 用的 case id
const currentCaseId = computed(() => currentCase.value?.id || '')

// 步骤0 完成回调 — 刷新案件信息
function onStep0Completed() {
  if (currentCase.value) {
    evidenceApi.getCase(currentCase.value.id).then(res => {
      currentCase.value = res
    }).catch(() => {
      // 静默忽略
    })
  }
}

// 创建表单
const form = ref({
  case_name: '',
  case_type: 'injury' as 'injury' | 'death',
  is_minor: false,
})
const creating = ref(false)

// 上传
const materials = ref<MaterialResponse[]>([])
const processing = ref(false)
const retryingMaterialId = ref<string | null>(null)

// 进度（持久化 — 进度轮询自动恢复）
const showProgress = ref(false)
const progressPercent = ref(0)
const progressSteps = ref<evidenceApi.StepResponse[]>([])
let progressPollTimer: ReturnType<typeof setInterval> | null = null

// 目录
const catalogGroups = ref<CatalogGroup[]>([])
const catalogEmptyReason = ref<string | null>(null)
const catalogTotalAmount = ref(0)
const catalogLoading = ref(false)
const pendingUpdates = ref<Map<string, Record<string, string>>>(new Map())
const catalogDirty = ref(false)
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null

// 分析
const analysisResult = ref<AnalysisResponse | null>(null)
const analyzing = ref(false)
let analysisPollId: ReturnType<typeof setInterval> | null = null
let ocrPollId: ReturnType<typeof setInterval> | null = null

// ── 赔偿计算相关状态 ──
const compensationData = ref<any>(null)
const calculatingCompensation = ref(false)
const savingCompChanges = ref(false)
const savingParams = ref(false)
const feeReceiptMaterials = computed(() =>
  materials.value.filter((m: any) =>
    ['fee_receipt', 'invoice', 'receipt'].includes(m.effective_category) && m.ocr_status === 'completed'
  )
)
const compensationTotal = computed(() => {
  if (!compensationData.value?.items) return 0
  // dependent_living 不计入合计（已包含在残疾/死亡赔偿金中）
  return compensationData.value.items
    .filter((item: any) => item.fee_type !== 'dependent_living')
    .reduce((sum: number, item: any) =>
      sum + (item.manual_amount ?? item.amount), 0
    )
})

/** 护理依赖赔付比例下拉选项 */
const nursingDependencyOptions = [
  { label: '完全护理依赖（100%）', value: 'full' },
  { label: '大部分护理依赖（80%）', value: 'mostly' },
  { label: '部分护理依赖（50%）', value: 'partial' },
]

// 参数编辑
const compParams = reactive<any>({})
const editingFeeType = ref<string | null>(null)
const editAmount = ref<number>(0)

const hasAnalysisResult = computed(() => {
  if (!analysisResult.value?.analysis_result) return false
  return Object.keys(analysisResult.value.analysis_result).length > 0
})

// 导出
const bundling = ref(false)
const exportingDoc = ref<string | null>(null) // 跟踪正在导出的文档类型

// 案件列表
const caseList = ref<EvidenceCaseListItem[]>([])
const caseListLoading = ref(false)

// 编辑弹窗
const showEditModal = ref(false)
const editForm = ref({ id: '', case_name: '', case_type: 'injury' as 'injury' | 'death', is_minor: false })

// 金额核算提示弹窗
const showAmountCheckDialog = ref(false)
const editingCatalogTotal = ref(false)
const editCatalogTotalAmount = ref<number | null>(null)
// 多页文档预览
const showPageDrawer = ref(false)
const pagePreviewLoading = ref(false)
const pagePreviewData = ref<PagePreviewResponse | null>(null)
const pageSelectedSet = ref<Set<number>>(new Set())
const savingPageSelection = ref(false)
let pagePreviewMaterialId = ''

// 状态重置（案件切换时调用）
function _resetAllState() {
  // 清理所有轮询
  stopProgressPoll()
  if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
  if (ocrPollId) { clearInterval(ocrPollId); ocrPollId = null }
  if (autoSaveTimer) { clearTimeout(autoSaveTimer); autoSaveTimer = null }

  // 重置所有状态
  selectedMaterialIds.value = new Set()
  pendingUpdates.value = new Map()
  catalogDirty.value = false
  catalogGroups.value = []
  catalogEmptyReason.value = null
  catalogTotalAmount.value = 0
  analysisResult.value = null
  analyzing.value = false
  processing.value = false
  bundling.value = false
  exportingDoc.value = null
  showProgress.value = false
  retryingMaterialId.value = null
  stoppingProcess.value = false
  materials.value = []
  // 赔偿计算状态重置
  compensationData.value = null
  calculatingCompensation.value = false
  savingCompChanges.value = false
  editingFeeType.value = null
  editAmount.value = 0
  Object.keys(compParams).forEach(k => delete compParams[k])
}

// 律师信息（2组）
const lawyerInfo = ref<{ name: string; phone: string }[]>([
  { name: '', phone: '' },
  { name: '', phone: '' },
])
const savingLawyer = ref(false)

// 被告联系方式
const defendantPhone = ref('')
const savingDefendantPhone = ref(false)

// 是否通过"继续案件"进入（区别于新建案件）
const isContinuedCase = ref(false)

// ─── 计算 ─────────────────────────────────────────────────────────────────────

const totalMaterialCount = computed(() =>
  catalogGroups.value.reduce((sum, g) => sum + g.items.length, 0)
)

const completedCount = computed(() =>
  materials.value.filter(m => m.ocr_status === 'completed').length
)

const failedCount = computed(() =>
  materials.value.filter(m => m.ocr_status === 'failed').length
)

const analysisSummaryFields = computed(() => {
  const result: Record<string, string> = {}
  const ar = analysisResult.value?.analysis_result
  if (!ar || typeof ar !== 'object') return result
  // 从 analysis_result 中提取关键字段做摘要
  const keys = Object.keys(ar)
  for (const key of keys.slice(0, 8)) {
    const val = (ar as Record<string, unknown>)[key]
    if (typeof val === 'string') {
      result[key] = val.length > 200 ? val.slice(0, 200) + '...' : val
    } else if (typeof val === 'number' || typeof val === 'boolean') {
      result[key] = String(val)
    } else if (Array.isArray(val)) {
      result[key] = `${val.length} 项`
    } else if (typeof val === 'object' && val !== null) {
      result[key] = Object.keys(val).length > 0 ? `${Object.keys(val).length} 个字段` : '-'
    }
  }
  return result
})

const progressStatus = computed(() => {
  if (!currentCase.value) return 'default'
  if (currentCase.value.status === 'failed') return 'error'
  if (progressPercent.value >= 100) return 'success'
  return 'default'
})

// ─── 步骤切换 ─────────────────────────────────────────────────────────────

/** 是否可以跳到某步骤（步骤0-4 均可自由切换） */
function canGoStep(step: number): boolean {
  if (!currentCase.value) return false
  return step >= STEP.PREPROCESS && step <= STEP.ANALYSIS
}

/** n-steps @update:current 回调 — 步骤条点击入口 */
function handleStepClick(newStep: number) {
  // n-steps 是 1-based index，STEP 常量是 0-based，需要 -1 转换
  const step = newStep - 1
  if (canGoStep(step)) {
    navigateToStep(step)
  }
}

/** 导航到指定步骤 */
async function navigateToStep(step: number) {
  if (!canGoStep(step)) return

  // 离开证据目录步骤时自动保存目录修改
  if (currentStep.value === STEP.CATALOG && catalogDirty.value && pendingUpdates.value.size > 0) {
    await handleSaveCatalog()
  }

  // 注意：不能用 window.location.hash 保存步骤，因为 AdminLayout 用 :key="$route.fullPath"
  // hash 变化会导致 EvidencePage 组件被销毁重建，所有状态丢失

  // 根据步骤执行相应操作
  if (step === STEP.COMPENSATION) {
    currentStep.value = step
    await loadCompensation()
  } else if (step === STEP.CATALOG) {
    await goStep3()
  } else if (step === STEP.ANALYSIS) {
    await goStep4()
  } else {
    currentStep.value = step
  }
}

/** 返回案件首页 */
function handleGoHome() {
  _resetAllState()
  currentCase.value = null
  currentStep.value = STEP.PREPROCESS
  showHomePage.value = true
  isContinuedCase.value = false
  showCreateForm.value = false
  // 不用 window.location.hash，避免组件重建
  // 重置创建表单
  form.value = { case_name: '', case_type: 'injury', is_minor: false }
}

/** 刷新当前案件数据 */
const refreshing = ref(false)
async function handleRefresh() {
  if (!currentCase.value) return
  refreshing.value = true
  try {
    const res = await evidenceApi.getCase(currentCase.value.id)
    currentCase.value = res
    materials.value = res.materials || []
    // 根据当前步骤刷新对应数据
    if (currentStep.value === STEP.CATALOG || currentStep.value === STEP.ANALYSIS) {
      await loadCatalog()
    }
    if (currentStep.value === STEP.ANALYSIS) {
      try { analysisResult.value = await evidenceApi.getAnalysis(currentCase.value.id) } catch { /* ignore */ }
    }
    if (currentStep.value === STEP.COMPENSATION) {
      await loadCompensation()
    }
    message.success('已刷新')
  } catch (e: unknown) {
    message.error('刷新失败：' + (e as Error).message)
  } finally {
    refreshing.value = false
  }
}

/** 跳到步骤3（加载目录） */
async function goStep3() {
  if (!currentCase.value) return
  currentStep.value = STEP.CATALOG
  await loadCatalog()
}

/** 跳到步骤4（加载目录 + 分析结果） */
async function goStep4() {
  if (!currentCase.value) return
  currentStep.value = STEP.ANALYSIS
  await loadCatalog()
  try { analysisResult.value = await evidenceApi.getAnalysis(currentCase.value.id) } catch { /* ignore */ }
}

// ─── 标签映射 ─────────────────────────────────────────────────────────────────

function statusLabel(status?: string): string {
  const map: Record<string, string> = {
    draft: '草稿', uploading: '上传中', processing: '处理中',
    catalog_ready: '目录已生成', analyzing: '分析中', analysis_done: '分析完成',
    exporting: '导出中', completed: '已完成', failed: '失败',
  }
  return map[status || ''] || status || '未知'
}

function statusTagType(status?: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const map: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    draft: 'default', processing: 'info', catalog_ready: 'success',
    analyzing: 'info', analysis_done: 'success', completed: 'success',
    exporting: 'info', failed: 'error',
  }
  return map[status || ''] || 'default'
}

function ocrStatusLabel(s: string): string {
  const map: Record<string, string> = {
    pending: '等待中', running: 'OCR 中', completed: '已完成',
    failed: '失败', skipped: '跳过', not_applicable: '不适用',
  }
  return map[s] || s
}

function ocrTagType(s: string): 'default' | 'info' | 'success' | 'error' | 'warning' {
  const map: Record<string, 'default' | 'info' | 'success' | 'error' | 'warning'> = {
    pending: 'default', running: 'info', completed: 'success',
    failed: 'error', skipped: 'warning', not_applicable: 'default',
  }
  return map[s] || 'default'
}

function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    identity_id_card: '原告身份证', identity_hukou: '户口本', identity_other: '其他身份信息',
    identity_defendant: '被告信息', medical_record: '病历资料', fee_receipt: '医疗费用',
    appraisal: '鉴定意见书', death_certificate: '死亡证明', other_evidence: '其他证据',
    // 兼容旧数据
    identity: '身份证明',
  }
  return map[cat] || cat
}

/** 手动分类下拉选项 */
const categoryOptions = computed(() => {
  const base: { label: string; value: string }[] = [
    { label: '原告身份证', value: 'identity_id_card' },
    { label: '户口本', value: 'identity_hukou' },
    { label: '其他身份信息', value: 'identity_other' },
    { label: '被告信息', value: 'identity_defendant' },
    { label: '死亡证明', value: 'death_certificate' },
    { label: '病历资料', value: 'medical_record' },
    { label: '鉴定意见书', value: 'appraisal' },
    { label: '医疗费用', value: 'fee_receipt' },
    { label: '其他证据', value: 'other_evidence' },
  ]
  return base
})

/** 修改素材分类 */
async function handleChangeCategory(mat: MaterialResponse, newCategory: string | null) {
  if (!currentCase.value) return
  try {
    const res = await evidenceApi.updateMaterial(currentCase.value.id, mat.id, {
      manual_category: newCategory || '',
    })
    // 同步本地素材列表
    const idx = materials.value.findIndex(m => m.id === mat.id)
    if (idx !== -1) {
      materials.value[idx] = res
    }
    if (newCategory) {
      message.success(`手动分类已设为「${categoryLabel(newCategory)}」`)
    } else {
      message.success('已清除手动分类，将使用自动分类')
    }
  } catch (e: unknown) {
    const err = e instanceof Error ? e.message : String(e)
    message.error(err)
  }
}

function stepStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const map: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    pending: 'default', running: 'info', processing: 'info', completed: 'success', failed: 'error', skipped: 'warning',
  }
  return map[status] || 'default'
}

function stepLabel(name: string): string {
  const map: Record<string, string> = {
    ocr: 'OCR 识别',
    classify: '智能分类',
    classify_optimized: '智能分类',
    catalog: '目录生成',
    analyze: '智能分析',
    export: '文档导出',
  }
  return map[name] || name
}

function stepStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '等待中',
    processing: '处理中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
  }
  return map[status] || status
}

function caseTypeLabel(t: string): string {
  return t === 'injury' ? '伤残' : t === 'death' ? '死亡' : t
}

// ─── 进度轮询 ─────────────────────────────────────────────────────────────────

function startProgressPoll(caseId: string) {
  stopProgressPoll()
  progressPollTimer = setInterval(async () => {
    try {
      const p = await evidenceApi.getProgress(caseId)
      progressPercent.value = Math.round(p.progress_percent)
      progressSteps.value = p.steps

      // 同步刷新材料列表获取最新 OCR/分类状态
      try {
        const fresh = await evidenceApi.getCase(caseId)
        materials.value = fresh.materials || []
        // 同步更新 currentCase 状态
        if (currentCase.value) currentCase.value.status = fresh.status
      } catch (e: any) { console.warn('操作失败:', e?.message || e) }

      const doneStatuses = ['catalog_ready', 'analysis_done', 'completed', 'failed']
      if (doneStatuses.includes(p.status)) {
        stopProgressPoll()
        processing.value = false
        if (p.status === 'failed') {
          message.error('OCR识别失败，请检查文件质量（清晰度、分辨率）后重试。可在下方材料列表中对失败材料单独重试OCR，或删除后重新上传。')
          // 自动刷新材料列表，显示失败状态
          try {
            const fresh = await evidenceApi.getCase(caseId)
            materials.value = fresh.materials || []
          } catch (e: any) { console.warn('操作失败:', e?.message || e) }
        } else if (p.status === 'catalog_ready') {
          message.success('OCR识别与分类完成，已生成证据目录')
          currentStep.value = STEP.COMPENSATION
          await loadCompensation()
        } else {
          // analysis_done / completed — 跳到分析步骤
          message.success('OCR识别与分类完成')
          currentStep.value = STEP.ANALYSIS
          await loadCatalog()
          try { analysisResult.value = await evidenceApi.getAnalysis(caseId) } catch { /* ignore */ }
        }
      }
    } catch (e: any) {
      stopProgressPoll()
      processing.value = false
    }
  }, 3000)
}

function stopProgressPoll() {
  if (progressPollTimer) {
    clearInterval(progressPollTimer)
    progressPollTimer = null
  }
}

// ─── 方法 ─────────────────────────────────────────────────────────────────────

// 创建案件
async function handleCreate() {
  if (!form.value.case_name) { message.warning('请输入案件名称'); return }
  creating.value = true
  // 新建案件模式（不允许步骤条点击跳转）
  isContinuedCase.value = false
  try {
    const res = await evidenceApi.createCase({
      case_name: form.value.case_name,
      case_type: form.value.case_type,
      is_minor: form.value.is_minor,
    })
    currentCase.value = res
    materials.value = res.materials || []
    syncLawyerInfo(res)
    syncDefendantPhone(res)
    currentStep.value = STEP.PREPROCESS
    showHomePage.value = false
    showCreateForm.value = false
    message.success('案件创建成功')
  } catch (e: unknown) {
    message.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

// 上传 — 用户选中的文件一次性上传，不使用队列
const uploadingFiles = ref(false)
const dragOver = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

/** 触发隐藏的 file input */
function triggerFileInput() {
  fileInputRef.value?.click()
}

/** 原生 input change — 用户选完文件后一次性获取全部 */
function handleFileInputChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    const files = Array.from(input.files)
    doUploadFiles(files)
  }
  // 清空 input 以便同一批文件可以再次选择
  input.value = ''
}

/** 拖拽上传 */
function handleDrop(e: DragEvent) {
  dragOver.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    const files = Array.from(e.dataTransfer.files).filter(f => {
      const ext = f.name.toLowerCase().split('.').pop() || ''
      return ['pdf', 'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'doc', 'docx'].includes(ext)
    })
    if (files.length > 0) {
      doUploadFiles(files)
    } else {
      message.warning('不支持的文件格式，请上传 PDF / 图片 / Word 文档')
    }
  }
}

/** 实际执行上传：每 5 个一批提交，跳过已存在的同名文件 */
async function doUploadFiles(files: File[]) {
  if (!currentCase.value || files.length === 0) return

  // 本地去重：跳过和已有材料同名的文件（failed 除外）
  const existingNames = new Set(
    materials.value
      .filter(m => m.ocr_status !== 'failed')
      .map(m => m.original_filename)
  )
  const duplicates = files.filter(f => existingNames.has(f.name))
  const uniqueFiles = files.filter(f => !existingNames.has(f.name))

  if (duplicates.length > 0) {
    message.warning(`跳过 ${duplicates.length} 个已存在的同名文件：${duplicates.map(f => f.name).join('、')}（如需重新上传，请先删除旧文件）`)
  }
  if (uniqueFiles.length === 0) {
    return
  }

  uploadingFiles.value = true
  const BATCH_SIZE = 5
  let totalSuccess = 0
  for (let i = 0; i < uniqueFiles.length; i += BATCH_SIZE) {
    const chunk = uniqueFiles.slice(i, i + BATCH_SIZE)
    try {
      const res = await evidenceApi.uploadMaterials(currentCase.value.id, chunk)
      materials.value.push(...res)
      totalSuccess += chunk.length
    } catch (e: unknown) {
      message.error('上传失败：' + (e as Error).message)
    }
  }
  if (totalSuccess > 0) {
    message.success(`上传成功：${totalSuccess} 个文件`)
  }
  uploadingFiles.value = false
}

// 删除单个材料（删除后重新加载完整案件数据确保一致性）
async function handleDeleteMaterial(materialId: string) {
  if (!currentCase.value) return
  const isStep1 = currentStep.value === STEP.UPLOAD
  dialog.warning({
    title: '确认删除',
    content: isStep1
      ? '确定要删除这个素材文件吗？删除后无法恢复。'
      : '确定要删除这个素材文件吗？删除后证据目录和分析结果将过期，需重新处理。',
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await evidenceApi.deleteMaterial(currentCase.value!.id, materialId)
        // 重新加载完整案件数据（而非仅本地过滤）
        const fresh = await evidenceApi.getCase(currentCase.value!.id)
        materials.value = fresh.materials || []
        selectedMaterialIds.value.delete(materialId)
        message.success('素材已删除')
        // Step 2/3/4 时提示用户重新处理
        if (!isStep1) {
          message.warning('素材已变更，建议返回 Step 1 重新处理以更新证据目录和分析结果')
        }
      } catch (e: unknown) {
        message.error('删除失败：' + (e as Error).message)
      }
    },
  })
}

// 重试单个素材的 OCR
async function handleRetryOcr(materialId: string) {
  if (!currentCase.value) return
  retryingMaterialId.value = materialId
  try {
    await evidenceApi.retryMaterialOcr(currentCase.value.id, materialId)
    message.success('OCR 重试已启动，请稍后刷新查看结果')
    // 启动轮询检查 OCR 状态
    startOcrStatusPoll(materialId)
  } catch (e: unknown) {
    message.error('重试失败：' + (e as Error).message)
  } finally {
    retryingMaterialId.value = null
  }
}

// 轮询检查单个素材的 OCR 状态
function startOcrStatusPoll(materialId: string) {
  // 清理之前的OCR轮询
  if (ocrPollId) { clearInterval(ocrPollId); ocrPollId = null }

  let attempts = 0
  const maxAttempts = 60 // 最多轮询 60 次（约 2 分钟）
  ocrPollId = setInterval(async () => {
    attempts++
    if (attempts > maxAttempts) {
      if (ocrPollId) { clearInterval(ocrPollId); ocrPollId = null }
      return
    }
    try {
      const fresh = await evidenceApi.getCase(currentCase.value!.id)
      const mat = fresh.materials?.find(m => m.id === materialId)
      if (mat && mat.ocr_status !== 'pending' && mat.ocr_status !== 'running') {
        if (ocrPollId) { clearInterval(ocrPollId); ocrPollId = null }
        materials.value = fresh.materials || []
        if (mat.ocr_status === 'completed') {
          message.success('OCR 重试完成')
        } else {
          message.warning('OCR 重试完成，但状态为：' + mat.ocr_status)
        }
      }
    } catch (e: any) {
      // 忽略轮询错误
    }
  }, 2000)
}

// ─── 多选与批量删除 ─────────────────────────────────────────────────────────
const selectedMaterialIds = ref<Set<string>>(new Set())
const batchDeleting = ref(false)

const isAllSelected = computed(() =>
  materials.value.length > 0 && selectedMaterialIds.value.size === materials.value.length
)

const isSomeSelected = computed(() =>
  selectedMaterialIds.value.size > 0 && selectedMaterialIds.value.size < materials.value.length
)

function toggleSelect(materialId: string, checked: boolean) {
  if (checked) {
    selectedMaterialIds.value.add(materialId)
  } else {
    selectedMaterialIds.value.delete(materialId)
  }
  // 触发响应式更新
  selectedMaterialIds.value = new Set(selectedMaterialIds.value)
}

function toggleSelectAll(checked: boolean) {
  if (checked) {
    selectedMaterialIds.value = new Set(materials.value.map(m => m.id))
  } else {
    selectedMaterialIds.value = new Set()
  }
}

function clearSelection() {
  selectedMaterialIds.value = new Set()
}

async function handleBatchDelete() {
  if (!currentCase.value || selectedMaterialIds.value.size === 0) return
  const count = selectedMaterialIds.value.size
  const isStep1 = currentStep.value === STEP.UPLOAD
  dialog.error({
    title: '确认批量删除',
    content: isStep1
      ? `确定要删除选中的 ${count} 个素材文件吗？此操作不可恢复。`
      : `确定要删除选中的 ${count} 个素材文件吗？删除后证据目录和分析结果将过期，需重新处理。`,
    positiveText: '全部删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      batchDeleting.value = true
      let successCount = 0
      let failCount = 0
      const ids = Array.from(selectedMaterialIds.value)
      // 并发删除（Promise.allSettled），比逐个快 5-10 倍
      const results = await Promise.allSettled(
        ids.map(mid => evidenceApi.deleteMaterial(currentCase.value!.id, mid))
      )
      for (const r of results) {
        if (r.status === 'fulfilled') successCount++
        else failCount++
      }
      // 刷新列表
      try {
        const fresh = await evidenceApi.getCase(currentCase.value!.id)
        materials.value = fresh.materials || []
      } catch (e: any) { console.warn('操作失败:', e?.message || e) }
      selectedMaterialIds.value = new Set()
      batchDeleting.value = false
      if (failCount === 0) {
        message.success(`已删除 ${successCount} 个素材`)
        if (!isStep1) {
          message.warning('素材已变更，建议返回 Step 1 重新处理以更新证据目录和分析结果')
        }
      } else {
        message.warning(`成功删除 ${successCount} 个，失败 ${failCount} 个`)
      }
    },
  })
}

// ─── 多页文档预览与选择 ─────────────────────────────────────────────────────

async function openPagePreview(mat: MaterialResponse) {
  if (!currentCase.value) return
  pagePreviewMaterialId = mat.id
  pagePreviewLoading.value = true
  showPageDrawer.value = true
  pagePreviewData.value = null
  pageSelectedSet.value = new Set()

  try {
    const res = await evidenceApi.previewMaterialPages(currentCase.value.id, mat.id)
    pagePreviewData.value = res
    // 恢复已选中的页面
    pageSelectedSet.value = new Set(res.selected_pages || [])
  } catch (e: unknown) {
    message.error('加载预览失败：' + (e as Error).message)
    showPageDrawer.value = false
  } finally {
    pagePreviewLoading.value = false
  }
}

function togglePageSelection(pageNum: number) {
  const newSet = new Set(pageSelectedSet.value)
  if (newSet.has(pageNum)) {
    newSet.delete(pageNum)
  } else {
    newSet.add(pageNum)
  }
  pageSelectedSet.value = newSet
}

function selectAllPages() {
  if (!pagePreviewData.value) return
  pageSelectedSet.value = new Set(pagePreviewData.value.pages.map(p => p.page))
}

function clearPageSelection() {
  pageSelectedSet.value = new Set()
}

async function handleSavePageSelection() {
  if (!currentCase.value || !pagePreviewMaterialId) return
  savingPageSelection.value = true
  try {
    const selected = Array.from(pageSelectedSet.value).sort((a, b) => a - b)
    await evidenceApi.selectMaterialPages(
      currentCase.value.id,
      pagePreviewMaterialId,
      selected
    )
    message.success(
      selected.length > 0
        ? `已选择 ${selected.length} 页`
        : '已重置为处理全部页面'
    )
    showPageDrawer.value = false
  } catch (e: unknown) {
    message.error('保存失败：' + (e as Error).message)
  } finally {
    savingPageSelection.value = false
  }
}

// 开始处理
async function handleProcess() {
  if (!currentCase.value) return
  processing.value = true
  showProgress.value = true
  progressPercent.value = 0
  progressSteps.value = []
  try {
    const res = await evidenceApi.processCase(currentCase.value.id)
    // 如果没有启动新的处理任务（所有素材已完成），显示提示并停止
    if (!res.task_id) {
      message.info(res.message || '所有素材已完成处理，无需重新处理')
      processing.value = false
      showProgress.value = false
      return
    }
    startProgressPoll(currentCase.value.id)
  } catch (e: unknown) {
    message.error((e as Error).message)
    processing.value = false
  }
}

// 重新处理失败/未处理的素材
async function handleRetryFailed() {
  if (!currentCase.value || failedCount.value === 0) return
  processing.value = true
  showProgress.value = true
  progressPercent.value = 0
  progressSteps.value = []
  try {
    const res = await evidenceApi.processCase(currentCase.value.id)
    if (!res.task_id) {
      message.info('没有需要重新处理的素材')
      processing.value = false
      showProgress.value = false
      return
    }
    message.info(`正在重新处理 ${failedCount.value} 个失败素材...`)
    startProgressPoll(currentCase.value.id)
  } catch (e: unknown) {
    message.error((e as Error).message)
    processing.value = false
  }
}

// 停止处理（真正杀掉后端 Celery 任务 + OCR 进程）
const stoppingProcess = ref(false)
async function handleStopProcess() {
  if (!currentCase.value) return
  stoppingProcess.value = true
  try {
    await evidenceApi.cancelCase(currentCase.value.id)
    stopProgressPoll()
    processing.value = false
    message.success('已停止处理，后台 OCR/LLM 进程已终止')
    // 刷新案件数据以反映 failed 状态
    await loadCaseList()
    if (currentCase.value) {
      currentCase.value.status = 'failed'
    }
  } catch (e: unknown) {
    message.error('停止处理失败：' + (e as Error).message)
  } finally {
    stoppingProcess.value = false
  }
}

// 案件列表中的停止按钮（独立于删除）
const cancellingCase = ref<string | null>(null)
async function confirmCancelCase(row: EvidenceCaseListItem) {
  const ACTIVE_STATUSES = ['processing', 'analyzing', 'exporting']
  if (!ACTIVE_STATUSES.includes(row.status)) {
    message.warning('该案件当前不在处理中，无需停止')
    return
  }
  dialog.warning({
    title: '停止处理',
    content: `确定要停止案件「${row.case_name}」的处理吗？所有 OCR 和 LLM 进程将被终止，案件状态将变为"失败"。`,
    positiveText: '停止处理',
    negativeText: '取消',
    onPositiveClick: async () => {
      cancellingCase.value = row.id
      try {
        await evidenceApi.cancelCase(row.id)
        message.success('案件已停止处理')
        await loadCaseList()
      } catch (e: unknown) {
        message.error('停止失败：' + (e as Error).message)
      } finally {
        cancellingCase.value = null
      }
    },
  })
}

// ─── 赔偿计算 ─────────────────────────────────────────────────────────────────

function formatMoney(val: number | string): string {
  const num = typeof val === 'string' ? parseFloat(val) : val
  if (isNaN(num)) return '0.00'
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 构建干净的参数对象，去除 undefined/null 值 */
function buildCleanParams(): Record<string, any> {
  const clean: Record<string, any> = {}
  for (const [k, v] of Object.entries(compParams)) {
    if (v !== undefined && v !== null) {
      clean[k] = v
    }
  }
  return clean
}

/** 保存参数到后端（不重新计算） */
async function handleSaveParams() {
  if (!currentCase.value) return
  savingParams.value = true
  try {
    await evidenceApi.updateCompensation(currentCase.value.id, {
      items: [],
      params: buildCleanParams(),
    })
    message.success('参数已保存')
  } catch (e: any) {
    message.error('保存参数失败: ' + (e.message || '未知错误'))
  } finally {
    savingParams.value = false
  }
}

async function handleCalculateCompensation() {
  if (!currentCase.value) return
  calculatingCompensation.value = true
  try {
    const res = await evidenceApi.calculateCompensation(currentCase.value.id, buildCleanParams())
    compensationData.value = res
    // 只更新计算结果，不覆盖用户正在编辑的参数
  } catch (e: any) {
    message.error('计算失败: ' + (e.message || '未知错误'))
  } finally {
    calculatingCompensation.value = false
  }
}

function startFeeEdit(item: any) {
  editingFeeType.value = item.fee_type
  editAmount.value = item.manual_amount ?? item.amount
}

/** blur 时仅更新本地数据并退出编辑模式（不触发后端请求），统一用底部"保存修改"按钮 */
function exitFeeEdit(item: any) {
  editingFeeType.value = null
  if (!compensationData.value) return
  const target = compensationData.value.items.find((i: any) => i.fee_type === item.fee_type)
  if (target) {
    target.manual_amount = editAmount.value != null ? Number(editAmount.value) : null
  }
}

/** Enter 键保存单条（立即触发后端请求） */
async function saveFeeEdit(item: any) {
  exitFeeEdit(item)
  if (!currentCase.value || !compensationData.value) return

  // 保存到后端
  try {
    const updateItems = compensationData.value.items.map((i: any) => ({
      fee_type: i.fee_type,
      manual_amount: i.manual_amount != null ? Number(i.manual_amount) : null,
    }))
    await evidenceApi.updateCompensation(currentCase.value.id, { items: updateItems })
  } catch (e: any) {
    message.error('保存失败')
  }
}

async function resetFeeEdit(item: any) {
  const target = compensationData.value?.items?.find((i: any) => i.fee_type === item.fee_type)
  if (target) {
    target.manual_amount = null
    // 保存到后端
    if (currentCase.value && compensationData.value) {
      const updateItems = compensationData.value.items.map((i: any) => ({
        fee_type: i.fee_type,
        manual_amount: i.manual_amount != null ? Number(i.manual_amount) : null,
      }))
      try {
        await evidenceApi.updateCompensation(currentCase.value.id, { items: updateItems })
      } catch (e: any) {
        message.error('赔偿金额保存失败: ' + (e?.message || e))
      }
    }
  }
}

async function handleRecalculate() {
  if (!currentCase.value) return
  calculatingCompensation.value = true
  try {
    const res = await evidenceApi.calculateCompensation(currentCase.value.id, buildCleanParams())
    compensationData.value = res
    // 只更新计算结果，不覆盖用户正在编辑的参数
  } catch (e: any) {
    message.error('重新计算失败')
  } finally {
    calculatingCompensation.value = false
  }
}

/** 批量保存所有赔偿金额修改（含合计） */
async function saveAllCompensationEdits() {
  if (!currentCase.value || !compensationData.value) return
  savingCompChanges.value = true
  try {
    const updateItems = compensationData.value.items.map((i: any) => ({
      fee_type: i.fee_type,
      manual_amount: i.manual_amount != null ? Number(i.manual_amount) : null,
    }))
    const total = compensationTotal.value
    await evidenceApi.updateCompensation(currentCase.value.id, {
      items: updateItems,
      manual_total: Number(total),
    })
    message.success('金额修改已保存')
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || '未知错误'))
  } finally {
    savingCompChanges.value = false
  }
}

/** 点击"下一步：证据目录" — 先弹窗提示核算金额 */
function handleNextToCatalog() {
  showAmountCheckDialog.value = true
}

/** 确认核算金额后继续 — 自动保存所有金额到后端，再跳转第三步 */
async function confirmAmountCheck() {
  showAmountCheckDialog.value = false
  if (!currentCase.value || !compensationData.value) {
    navigateToStep(STEP.CATALOG)
    return
  }
  // 将当前所有金额（含手动修改）保存到后端，并同步 total_amount
  try {
    const total = compensationTotal.value
    await evidenceApi.updateCompensation(currentCase.value.id, {
      items: compensationData.value.items.map((i: any) => ({
        fee_type: i.fee_type,
        manual_amount: i.manual_amount != null ? Number(i.manual_amount) : null,
      })),
      manual_total: Number(total),
    })
  } catch { /* 静默失败，不阻塞跳转 */ }
  await navigateToStep(STEP.CATALOG)
}

/** 开始编辑费用总计 */
function startEditCatalogTotal() {
  editCatalogTotalAmount.value = catalogTotalAmount.value
  editingCatalogTotal.value = true
}

/** 保存费用总计手动修改 */
async function saveCatalogTotalEdit() {
  editingCatalogTotal.value = false
  if (!currentCase.value || editCatalogTotalAmount.value == null) return

  const newValue = editCatalogTotalAmount.value
  catalogTotalAmount.value = newValue

  // 保存到后端
  try {
    await evidenceApi.updateCompensation(currentCase.value.id, {
      items: [],
      manual_total: newValue,
    })
    message.success('费用总计已更新')
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || '未知错误'))
  }
}

/** 取消编辑费用总计 */
function cancelEditCatalogTotal() {
  editingCatalogTotal.value = false
  editCatalogTotalAmount.value = null
}

/** 将后端返回的 params 中的字符串值转为数字（n-input-number 需要 number 类型） */
function parseNumericParams(params: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {}
  for (const [k, v] of Object.entries(params)) {
    out[k] = typeof v === 'string' ? Number(v) : v
  }
  return out
}

async function loadCompensation() {
  if (!currentCase.value) return
  try {
    const res = await evidenceApi.getCompensation(currentCase.value.id)
    if (res.compensation_data && res.compensation_data.items) {
      // 后端 JSONB 中 amount/manual_amount 可能是字符串，统一转为数字
      const data = res.compensation_data
      for (const item of data.items) {
        if (item.amount != null) item.amount = Number(item.amount)
        if (item.manual_amount != null) item.manual_amount = Number(item.manual_amount)
      }
      if (data.total_amount != null) data.total_amount = Number(data.total_amount)
      if (data.manual_total != null) data.manual_total = Number(data.manual_total)
      compensationData.value = data
      if (data.params) {
        const parsed = parseNumericParams(data.params || {})
        // 向后兼容：旧 case 数据可能用 nursing_monthly_salary，折算为年薪
        if (parsed.nursing_annual_salary === undefined || parsed.nursing_annual_salary === null) {
          if (parsed.nursing_monthly_salary != null) {
            parsed.nursing_annual_salary = Number(parsed.nursing_monthly_salary) * 12
          } else {
            parsed.nursing_annual_salary = (parsed.monthly_salary ?? 8500) * 12
          }
        }
        delete parsed.nursing_monthly_salary
        // 向后兼容：新参数默认值
        if (!parsed.nursing_dependency_level) {
          parsed.nursing_dependency_level = 'full'
        }
        if (parsed.nursing_person_count === undefined || parsed.nursing_person_count === null) {
          parsed.nursing_person_count = 1
        }
        if (parsed.victim_age === undefined || parsed.victim_age === null) {
          parsed.victim_age = 0
        }
        Object.keys(compParams).forEach(k => delete compParams[k])
        Object.assign(compParams, parsed)
      }
    }
  } catch (e: any) { console.warn('操作失败:', e?.message || e) }
}

// 智能分析（新入口函数）
function handleStartAnalysis() {
  handleAnalyze()
}

function handleReAnalysis() {
  dialog.warning({
    title: '确认重新分析',
    content: '重新分析将覆盖已有分析结果，是否继续？',
    positiveText: '确认重新分析',
    negativeText: '取消',
    onPositiveClick: () => {
      handleStartAnalysis()
    },
  })
}

// 加载目录
async function loadCatalog() {
  if (!currentCase.value) return
  catalogLoading.value = true
  try {
    const res = await evidenceApi.getCatalog(currentCase.value.id)
    catalogGroups.value = res.groups
    // 优先使用第二步赔偿计算结果，否则用 OCR 提取的费用
    catalogTotalAmount.value = res.compensation_total ?? res.total_amount
    catalogEmptyReason.value = (res as any).empty_reason || null
  } catch (e: unknown) { message.error((e as Error).message) }
  finally { catalogLoading.value = false }
}

// 目录项编辑
function handleUpdateItem(materialId: string, field: string, value: string) {
  const existing = pendingUpdates.value.get(materialId) || {}
  existing[field] = value
  pendingUpdates.value.set(materialId, existing)
  catalogDirty.value = true  // 标记有未保存的修改
}

// 保存目录
async function handleSaveCatalog() {
  if (!currentCase.value || pendingUpdates.value.size === 0) { message.info('无修改需要保存'); catalogDirty.value = false; return }
  try {
    const items = Array.from(pendingUpdates.value.entries()).map(([mid, data]) => ({ material_id: mid, ...data }))
    await evidenceApi.updateCatalog(currentCase.value.id, items)
    pendingUpdates.value.clear()
    catalogDirty.value = false
    message.success('目录已保存')
    await loadCatalog()
  } catch (e: unknown) { message.error((e as Error).message) }
}

// 分析
async function handleAnalyze() {
  if (!currentCase.value) return
  analyzing.value = true
  let attempts = 0
  let pollErrors = 0 // 连续轮询失败计数
  const maxAttempts = 200 // 最多轮询 200 次 × 3秒 = 10分钟
  const maxPollErrors = 3 // 连续失败3次才终止轮询
  try {
    await evidenceApi.analyzeCase(currentCase.value.id)
    analysisPollId = setInterval(async () => {
      attempts++
      if (attempts > maxAttempts) {
        if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
        analyzing.value = false
        message.warning('分析耗时较长，后台仍在处理中。您可以先处理其他案件，稍后返回查看结果。')
        return
      }
      try {
        const res = await evidenceApi.getAnalysis(currentCase.value!.id)
        pollErrors = 0 // 成功后重置连续失败计数
        if (['analysis_done', 'completed', 'exporting'].includes(res.status)) {
          analysisResult.value = res; analyzing.value = false
          if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
          message.success('分析完成')
        } else if (res.status === 'failed') {
          analyzing.value = false
          if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
          const errorMsg = res.error_message || '未知原因'
          message.error(`分析失败：${errorMsg}。请检查素材完整性后重试。`)
        }
      } catch (e: any) {
        pollErrors++
        if (pollErrors >= maxPollErrors) {
          // 连续失败多次才终止，单次网络抖动不会中断
          console.warn(`Analysis polling failed ${pollErrors} times consecutively, stopping`)
          if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
          analyzing.value = false
          message.warning('网络连接不稳定，请刷新页面后查看分析状态。')
        }
        // 连续失败未达阈值，继续轮询
      }
    }, 3000)
  } catch (e: unknown) { message.error((e as Error).message); analyzing.value = false }
}

// 导出
async function handleExportFilingEvidence() {
  if (!currentCase.value) return
  exportingDoc.value = 'filing'
  try { await evidenceApi.exportFilingEvidence(currentCase.value.id); message.success('导出成功') }
  catch (e: unknown) { message.error((e as Error).message) }
  finally { exportingDoc.value = null }
}
async function handleExportComplaint() {
  if (!currentCase.value) return

  // 检查是否有待补充的字段
  if (analysisResult.value) {
    const pendingFields: string[] = []
    const ar = analysisResult.value.analysis_result as Record<string, any> || {}
    const defendantName = ar.defendant_name as string || ''
    if (defendantName.includes('[待补充]') || defendantName.includes('（待补充）')) {
      pendingFields.push('被告医院名称')
    }
    const courtName = ar.court_name as string || ''
    if (courtName.includes('[待补充]') || courtName.includes('（待补充）')) {
      pendingFields.push('受理法院')
    }
    // 检查段落
    for (let i = 1; i <= 5; i++) {
      const para = ar[`paragraph_${i}`] as string || ''
      if (para.includes('[待补充]') || para.includes('（待补充）')) {
        pendingFields.push(`第${i}段`)
      }
    }

    if (pendingFields.length > 0) {
      const confirmed = await new Promise<boolean>(resolve => {
        dialog.warning({
          title: '文档包含待补充内容',
          content: `以下字段尚未完善：${pendingFields.join('、')}。导出后请手动补充。是否继续导出？`,
          positiveText: '继续导出',
          negativeText: '取消',
          onPositiveClick: () => resolve(true),
          onNegativeClick: () => resolve(false),
        })
      })
      if (!confirmed) return
    }
  }

  exportingDoc.value = 'complaint'
  try { await evidenceApi.exportComplaint(currentCase.value.id); message.success('导出成功') }
  catch (e: unknown) { message.error((e as Error).message) }
  finally { exportingDoc.value = null }
}
async function handleExportAppraisalApp() {
  if (!currentCase.value) return
  exportingDoc.value = 'appraisal'
  try { await evidenceApi.exportAppraisalApp(currentCase.value.id); message.success('导出成功') }
  catch (e: unknown) { message.error((e as Error).message) }
  finally { exportingDoc.value = null }
}
async function handleExportCompensation() {
  if (!currentCase.value) return
  exportingDoc.value = 'compensation'
  try {
    // 将当前编辑的金额数据通过 POST 传给后端，后端保存后生成 ZIP 包返回
    const items = (compensationData.value?.items || []).map((i: any) => ({
      fee_type: i.fee_type,
      manual_amount: i.manual_amount != null ? Number(i.manual_amount) : null,
    }))
    const total = compensationTotal.value
    await evidenceApi.exportCompensationZip(currentCase.value.id, {
      items,
      manual_total: Number(total),
    })
    message.success('导出成功')
  } catch (e: unknown) { message.error((e as Error).message) }
  finally { exportingDoc.value = null }
}
async function handleExportCatalogPdf() {
  if (!currentCase.value) return
  exportingDoc.value = 'catalog'
  try { await evidenceApi.exportCatalogPdf(currentCase.value.id); message.success('导出成功') }
  catch (e: unknown) { message.error((e as Error).message) }
  finally { exportingDoc.value = null }
}
async function handleExportMaterialsPdf() {
  if (!currentCase.value) return
  exportingDoc.value = 'materials'
  try { await evidenceApi.exportMaterialsPdf(currentCase.value.id); message.success('导出成功') }
  catch (e: unknown) { message.error((e as Error).message) }
  finally { exportingDoc.value = null }
}

async function handleExportBundle() {
  if (!currentCase.value) return
  bundling.value = true
  try { await evidenceApi.exportBundle(currentCase.value.id); message.success('打包下载完成') }
  catch (e: unknown) { message.error((e as Error).message) }
  finally { bundling.value = false }
}

// ─── 案件列表操作 ─────────────────────────────────────────────────────────────

const caseListPage = ref(1)
const caseListTotal = ref(0)
const caseListPageSize = ref(20)

async function loadCaseList(page = 1, size = 20) {
  caseListLoading.value = true
  try {
    const res = await evidenceApi.listCases(page, size)
    caseList.value = res.items
    caseListPage.value = page
    caseListPageSize.value = size
    caseListTotal.value = res.total || res.items.length
  } catch (e: any) {
    console.error('加载案件列表失败:', e.message || e)
  } finally {
    caseListLoading.value = false
  }
}

async function handleCaseListPageChange(page: number) {
  await loadCaseList(page, caseListPageSize.value)
}

async function handleCaseListPageSizeChange(pageSize: number) {
  await loadCaseList(1, pageSize)
}

// ─── 案件搜索/筛选 ───
const caseListSearch = ref('')
const caseListStatusFilter = ref<string | null>(null)
const caseStatusOptions = [
  { label: '处理中', value: 'processing' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
  { label: '待处理', value: 'pending' },
]

let _searchDebounce: ReturnType<typeof setTimeout> | null = null
function handleCaseListSearch() {
  if (_searchDebounce) clearTimeout(_searchDebounce)
  _searchDebounce = setTimeout(() => {
    applyCaseListFilter()
  }, 300)
}

function applyCaseListFilter() {
  // 前端过滤已加载的案件（后端API暂不支持搜索参数）
  loadCaseList(1, caseListPageSize.value)
}

// 计算属性：过滤后的案件列表
const filteredCaseList = computed(() => {
  let result = caseList.value
  if (caseListSearch.value) {
    const q = caseListSearch.value.toLowerCase()
    result = result.filter((c: any) => c.case_name?.toLowerCase().includes(q))
  }
  if (caseListStatusFilter.value) {
    result = result.filter((c: any) => c.status === caseListStatusFilter.value)
  }
  return result
})

async function continueCase(caseId: string) {
  // 切换案件前清理所有状态，防止数据泄漏
  _resetAllState()
  // 标记为"继续案件"模式
  isContinuedCase.value = true
  // 隐藏首页（案件列表弹窗已废弃，showCaseListModal 仅保留为兼容性占位）
  showHomePage.value = false

  try {
    const res = await evidenceApi.getCase(caseId)
    currentCase.value = res
    materials.value = res.materials || []
    if (['catalog_ready'].includes(res.status)) {
      currentStep.value = STEP.COMPENSATION; await loadCompensation()
    } else if (['analysis_done', 'completed', 'exporting'].includes(res.status)) {
      currentStep.value = STEP.ANALYSIS; await loadCatalog()
      try { analysisResult.value = await evidenceApi.getAnalysis(caseId) } catch { /* ignore */ }
    } else if (['analyzing'].includes(res.status)) {
      currentStep.value = STEP.ANALYSIS; await loadCatalog()
      analyzing.value = true
      // 恢复分析轮询（使用模块级变量追踪）
      analysisPollId = setInterval(async () => {
        try {
          const ar = await evidenceApi.getAnalysis(caseId)
          if (['analysis_done', 'completed', 'exporting'].includes(ar.status)) {
            analysisResult.value = ar; analyzing.value = false
            if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
            message.success('分析完成')
          } else if (ar.status === 'failed') {
            analyzing.value = false
            if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
            const errorMsg = ar.error_message || '未知原因'
            message.error(`分析失败：${errorMsg}`)
          }
        } catch (e: any) {
          if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
          analyzing.value = false
        }
      }, 3000)
    } else if (res.status === 'processing') {
      // 恢复进度轮询（后台 Celery 任务不会因为退出而中断）
      currentStep.value = STEP.UPLOAD
      showProgress.value = true
      processing.value = true
      startProgressPoll(caseId)
    } else {
      // step0_status != 'completed' 时默认停在步骤0
      const step0Status = (res.metadata || {}).step0_status
      if (step0Status && step0Status !== 'completed' && step0Status !== 'skipped') {
        currentStep.value = STEP.PREPROCESS
      } else {
        currentStep.value = STEP.UPLOAD
      }
    }
    message.info('已加载案件：' + res.case_name)
    // 同步律师信息到本地状态
    syncLawyerInfo(res)
    syncDefendantPhone(res)
  } catch (e: unknown) { message.error((e as Error).message) }
}

/** 从案件数据同步律师信息到本地输入框 */
function syncLawyerInfo(caseData: evidenceApi.EvidenceCase) {
  const info = caseData.lawyer_info || []
  lawyerInfo.value = [
    { name: info[0]?.name || '', phone: info[0]?.phone || '' },
    { name: info[1]?.name || '', phone: info[1]?.phone || '' },
  ]
}

/** 从案件数据同步被告联系方式到本地输入框 */
function syncDefendantPhone(caseData: evidenceApi.EvidenceCase) {
  defendantPhone.value = (caseData.defendant_info as Record<string, string>)?.phone || ''
}

/** 保存被告联系方式到后端 */
async function saveDefendantPhone() {
  if (!currentCase.value) return
  try {
    savingDefendantPhone.value = true
    const res = await evidenceApi.updateCase(currentCase.value.id, {
      defendant_phone: defendantPhone.value
    })
    currentCase.value = res
    syncDefendantPhone(res)
    message.success('被告联系方式已保存')
  } catch (e: unknown) {
    const err = e instanceof Error ? e.message : String(e)
    message.error(err)
  } finally {
    savingDefendantPhone.value = false
  }
}

/** 保存律师信息到后端 */
async function saveLawyerInfo() {
  if (!currentCase.value) return
  // 过滤掉空的律师信息
  const filtered = lawyerInfo.value.filter(l => l.name.trim() || l.phone.trim())
  try {
    savingLawyer.value = true
    const res = await evidenceApi.updateCase(currentCase.value.id, { lawyer_info: filtered })
    currentCase.value = res
    syncLawyerInfo(res)
    syncDefendantPhone(res)
    message.success('律师信息已保存')
  } catch (e: unknown) {
    const err = e instanceof Error ? e.message : String(e)
    message.error(err)
  } finally {
    savingLawyer.value = false
  }
}

function openEditModal(row: EvidenceCaseListItem) {
  editForm.value = { id: row.id, case_name: row.case_name, case_type: row.case_type as 'injury' | 'death', is_minor: row.is_minor }
  showEditModal.value = true
}

async function handleSaveEdit() {
  try {
    await evidenceApi.updateCase(editForm.value.id, {
      case_name: editForm.value.case_name,
      case_type: editForm.value.case_type,
      is_minor: editForm.value.is_minor,
    })
    message.success('案件已更新')
    await loadCaseList()
  } catch (e: unknown) {
    message.error((e as Error).message)
  }
}

function confirmDeleteCase(row: EvidenceCaseListItem) {
  const ACTIVE_STATUSES = ['processing', 'analyzing', 'exporting']
  if (ACTIVE_STATUSES.includes(row.status)) {
    dialog.warning({
      title: '无法删除',
      content: `案件「${row.case_name}」正在处理中，请先点击"停止"按钮终止处理后再删除。`,
      positiveText: '知道了',
    })
    return
  }

  dialog.error({
    title: '确认删除',
    content: `确定要删除案件「${row.case_name}」吗？所有素材和进度将一并删除，此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await evidenceApi.deleteCase(row.id)
        message.success('案件已删除')
        await loadCaseList()
      } catch (e: unknown) {
        message.error((e as Error).message)
      }
    },
  })
}

// ─── 表格列 ───────────────────────────────────────────────────────────────────

const caseListColumns = computed(() => {
  const cols: any[] = [
    { title: '案件名称', key: 'case_name', minWidth: 180, ellipsis: { tooltip: true } },
    { title: '类型', key: 'case_type', width: 80, render: (row: EvidenceCaseListItem) => caseTypeLabel(row.case_type) },
    { title: '状态', key: 'status', width: 100, render: (row: EvidenceCaseListItem) => h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => statusLabel(row.status) }) },
  ]
  // 超管额外显示租户列
  if (isSuperAdmin.value) {
    cols.push({
      title: '租户',
      key: 'tenant_name',
      width: 140,
      ellipsis: { tooltip: true },
      render: (row: EvidenceCaseListItem) => row.tenant_name ? h(NTag, { size: 'small', type: 'info', bordered: false }, { default: () => row.tenant_name }) : h(NText, { depth: 3 }, { default: () => '未分配' }),
    })
  }
  cols.push(
    { title: '创建时间', key: 'created_at', width: 150, render: (row: EvidenceCaseListItem) => new Date(row.created_at).toLocaleString() },
    {
      title: '操作', key: 'action', width: isSuperAdmin.value ? 320 : 240,
      render: (row: EvidenceCaseListItem) => {
        const ACTIVE_STATUSES = ['processing', 'analyzing', 'exporting']
        const isActive = ACTIVE_STATUSES.includes(row.status)
        const buttons: ReturnType<typeof h>[] = [
          h(NButton, { size: 'small', type: 'primary', onClick: () => continueCase(row.id) }, { default: () => '继续' }),
          h(NButton, { size: 'small', onClick: () => openEditModal(row) }, { default: () => '编辑' }),
        ]
        if (isActive) {
          buttons.push(
            h(NButton, { size: 'small', type: 'warning', loading: cancellingCase.value === row.id, onClick: () => confirmCancelCase(row) }, { default: () => '停止' }),
          )
        }
        // 超管显示分配按钮
        if (isSuperAdmin.value) {
          buttons.push(
            h(NButton, { size: 'small', type: 'info', ghost: true, onClick: () => openAssignTenantModal(row) }, { default: () => '分配' }),
          )
        }
        buttons.push(
          h(NButton, { size: 'small', type: 'error', onClick: () => confirmDeleteCase(row) }, { default: () => '删除' }),
        )
        return h(NSpace, { size: 'small' }, { default: () => buttons })
      },
    },
  )
  return cols
})

// ─── 生命周期 ─────────────────────────────────────────────────────────────────

onMounted(async () => {
  // 页面关闭/刷新时提醒未保存的目录修改
  window.addEventListener('beforeunload', _beforeUnloadHandler)
  // 加载当前用户信息（超管判断依赖 userInfo.role）
  await authStore.loadUserInfo()
  // 超管加载租户选项（用于分配案件）
  await loadTenantOptions()
  await loadCaseList()
  // 尝试从 sessionStorage 恢复未完成的案件状态（若有）
  const savedCaseId = sessionStorage.getItem('evidence_current_case_id')
  const savedStep = sessionStorage.getItem('evidence_current_step')
  if (savedCaseId) {
    try {
      const c = await evidenceApi.getCase(savedCaseId)
      currentCase.value = c
      isContinuedCase.value = true
      showHomePage.value = false
      if (savedStep) currentStep.value = Number(savedStep)
    } catch (e: any) {
      // 案件不存在或权限问题 — 清理 sessionStorage
      sessionStorage.removeItem('evidence_current_case_id')
      sessionStorage.removeItem('evidence_current_step')
    }
  }
})

// 监听案件和步骤变化，保存到 sessionStorage
watch([currentCase, currentStep], ([newCase, newStep]) => {
  if (newCase) {
    sessionStorage.setItem('evidence_current_case_id', newCase.id)
    sessionStorage.setItem('evidence_current_step', String(newStep))
  } else {
    sessionStorage.removeItem('evidence_current_case_id')
    sessionStorage.removeItem('evidence_current_step')
  }
})

onUnmounted(() => {
  stopProgressPoll()
  if (analysisPollId) { clearInterval(analysisPollId); analysisPollId = null }
  if (ocrPollId) { clearInterval(ocrPollId); ocrPollId = null }
  if (autoSaveTimer) { clearTimeout(autoSaveTimer); autoSaveTimer = null }
  window.removeEventListener('beforeunload', _beforeUnloadHandler)
})

function _beforeUnloadHandler(e: BeforeUnloadEvent) {
  if (catalogDirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}
</script>

<style scoped>
.upload-drop-zone:hover {
  border-color: #36ad6a !important;
  background: rgba(54, 173, 106, 0.04);
}
.upload-drop-zone--active {
  border-color: #36ad6a !important;
  background: rgba(54, 173, 106, 0.08);
}
</style>
