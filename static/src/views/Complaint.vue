<template>
  <div>
    <h2 style="margin: 0 0 20px">民事起诉状生成</h2>

    <n-steps :current="currentStep" style="margin-bottom: 24px">
      <n-step title="案件配置" />
      <n-step title="可选项" />
      <n-step title="生成起诉状" />
    </n-steps>

    <CaseConfigStep v-if="currentStep === 0" />
    <OptionalStep v-else-if="currentStep === 1" />
    <GenerateStep v-else-if="currentStep === 2" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NSteps, NStep } from 'naive-ui'
import { useComplaintStore } from '@/stores/complaint'
import CaseConfigStep from '@/components/complaint/CaseConfigStep.vue'
import OptionalStep from '@/components/complaint/OptionalStep.vue'
import GenerateStep from '@/components/complaint/GenerateStep.vue'

const store = useComplaintStore()

const currentStep = computed(() => store.currentStep)
</script>
