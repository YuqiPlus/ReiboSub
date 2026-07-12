<template>
  <div v-if="!items.length" class="asset-list empty">{{ emptyText }}</div>
  <div v-else class="asset-list">
    <div v-for="item in items" :key="item.path || item.job_id" class="asset-item">
      <div class="asset-name">{{ item.name || item.job_id || item.path }}</div>
      <div class="muted path">{{ item.path }}</div>
      <div class="muted">{{ item.role || item.kind }} · {{ item.size_mb || 0 }} MB · {{ localModifiedLabel(item) }}</div>
      <div class="asset-actions"><slot name="actions" :item="item" /></div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无文件。' },
})

function localModifiedLabel(item) {
  const modifiedAt = Number(item?.modified_at || 0)
  if (!Number.isFinite(modifiedAt) || modifiedAt <= 0) return item?.modified_label || ''
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(modifiedAt * 1000))
}
</script>
