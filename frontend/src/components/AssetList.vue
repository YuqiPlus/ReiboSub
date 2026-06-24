<template>
  <div v-if="!items.length" class="asset-list empty">{{ emptyText }}</div>
  <div v-else class="asset-list">
    <div v-for="item in items" :key="item.path || item.job_id" class="asset-item">
      <div class="asset-name">{{ item.name || item.job_id || item.path }}</div>
      <div class="muted path">{{ item.path }}</div>
      <div class="muted">{{ item.role || item.kind }} · {{ item.size_mb || 0 }} MB · {{ item.modified_label || '' }}</div>
      <div class="asset-actions"><slot name="actions" :item="item" /></div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无文件。' },
})
</script>
