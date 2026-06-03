<template>
  <div style="max-height: 600px; overflow: auto">
    <pre
      v-if="data"
      style="
        margin: 0;
        padding: 16px;
        background: #f8f9fa;
        border-radius: 8px;
        font-size: 13px;
        line-height: 1.6;
        white-space: pre-wrap;
        word-break: break-all;
      "
    >{{ formatted }}</pre>
    <n-empty v-else description="暂无数据" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NEmpty } from 'naive-ui'

const props = defineProps<{
  data: unknown
}>()

const formatted = computed(() => {
  if (props.data === null || props.data === undefined) return ''
  try {
    return JSON.stringify(props.data, null, 2)
  } catch {
    return String(props.data)
  }
})
</script>
