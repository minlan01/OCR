<template>
  <div v-if="uploads.length > 0" style="margin-top: 4px; display: flex; gap: 4px; flex-wrap: wrap">
    <n-tag
      v-for="u in uploads"
      :key="u.id"
      size="small"
      :type="u.ocr_status === 'completed' ? 'success' : u.ocr_status === 'failed' ? 'error' : u.ocr_status === 'processing' ? 'warning' : 'default'"
    >
      {{ u.original_filename || u.file_type }} ({{ u.ocr_status }})
    </n-tag>
  </div>
</template>

<script setup lang="ts">
import { NTag } from 'naive-ui'
import type { ComplaintUpload } from '@/stores/complaint'

defineProps<{
  uploads: ComplaintUpload[]
}>()
</script>
