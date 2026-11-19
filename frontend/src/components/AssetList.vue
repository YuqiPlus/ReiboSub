<template>
  <div v-if="!items.length" class="asset-list empty">{{ emptyText }}</div>
  <div v-else class="asset-list">
    <div v-for="item in items" :key="item.path || item.job_id" class="asset-item">
      <div class="asset-name">{{ item.name || item.job_id || item.path }}</div>
      <div class="asset-file-meta"><span v-if="item.role || item.kind">{{ assetRoleLabel(item) }}</span><span v-if="item.linked">任务结果 · {{ item.version_label }}{{ item.is_archived ? ' · 历史版本' : '' }}</span><span v-if="item.size_mb">{{ item.size_mb }} MB</span><span>{{ localModifiedLabel(item) }}</span></div>
      <div class="asset-actions"><slot name="actions" :item="item" /></div>
      <details v-if="item.path" class="asset-file-path"><summary>文件路径</summary><p class="path">{{ item.path }}</p><button class="ghost mini" type="button" @click="copyPath(item.path)">复制路径</button><span v-if="copiedPath === item.path" role="status">{{ copyStatus }}</span></details>
    </div>
  </div>
</template>

<script setup>
import { assetRoleLabel, localModifiedLabel } from '../studioTools.js'
import { ref } from 'vue'
import { copyText } from '../clipboard.js'
defineProps({
  items: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无文件。' },
})

const copiedPath = ref(''), copyStatus = ref('')
async function copyPath(path) {
  const ok = await copyText(path)
  copiedPath.value = path
  copyStatus.value = ok ? '已复制' : '复制失败，请手动选择文本'
}

</script>
