<template>
  <header class="topbar">
    <div>
      <div v-if="eyebrow" class="eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
    </div>
    <div class="topbar-metrics">
      <span class="metric-chip"><b>{{ metrics.media ?? metrics.videos ?? 0 }}</b>素材</span>
      <span class="metric-chip"><b>{{ metrics.subtitles }}</b>字幕</span>
      <span class="metric-chip"><b>{{ metrics.jobs }}</b>任务</span>
    </div>
  </header>
</template>

<script setup>
defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, default: 'ReiboSub Agent' },
  description: { type: String, default: '下载、提取、纠错、术语审核和字幕翻译工作台。' },
  metrics: { type: Object, default: () => ({ media: 0, subtitles: 0, jobs: 0 }) },
})
</script>
