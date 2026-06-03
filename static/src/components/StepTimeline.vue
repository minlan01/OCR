<template>
  <n-timeline>
    <n-timeline-item
      v-for="step in steps"
      :key="step.id"
      :type="stepType(step.status)"
      :title="step.step_name"
      :time="formatTime(step)"
      :line-type="step.status === 'failed' ? 'dashed' : undefined"
    >
      <template v-if="step.duration_ms">
        <n-tag :type="step.status === 'failed' ? 'error' : step.status === 'completed' ? 'success' : 'default'" size="small">
          {{ formatDuration(step.duration_ms) }}
        </n-tag>
      </template>
      <template v-if="step.error_message">
        <n-text type="error" depth="3" style="display: block; margin-top: 4px; font-size: 12px">
          {{ step.error_message }}
        </n-text>
      </template>
    </n-timeline-item>
  </n-timeline>
</template>

<script setup lang="ts">
import { NTimeline, NTimelineItem, NTag, NText } from 'naive-ui'
import type { TaskStep } from '@/api/client'

defineProps<{
  steps: TaskStep[]
}>()

function stepType(status: string): 'default' | 'info' | 'success' | 'warning' | 'error' {
  const map: Record<string, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
    pending: 'default',
    processing: 'info',
    completed: 'success',
    failed: 'error',
    skipped: 'warning',
  }
  return map[status] || 'default'
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

function formatTime(step: TaskStep): string {
  const t = step.completed_at || step.started_at
  if (!t) return ''
  return new Date(t).toLocaleTimeString('zh-CN')
}
</script>
