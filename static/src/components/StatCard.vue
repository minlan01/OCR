<template>
  <n-card size="small" :bordered="false" style="text-align: center">
    <n-statistic :label="label" :value="displayValue">
      <template v-if="icon" #prefix>
        <n-icon :color="color" :size="20">
          <component :is="icon" />
        </n-icon>
      </template>
    </n-statistic>
  </n-card>
</template>

<script setup lang="ts">
import { computed, type Component } from 'vue'
import { NCard, NStatistic, NIcon } from 'naive-ui'

const props = defineProps<{
  label: string
  value: number | string
  icon?: Component
  color?: string
  precision?: number
}>()

const displayValue = computed(() => {
  if (typeof props.value === 'number' && props.precision !== undefined) {
    return props.value.toFixed(props.precision)
  }
  return String(props.value)
})
</script>
