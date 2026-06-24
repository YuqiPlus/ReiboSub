<template>
  <header class="topbar">
    <div>
      <div class="eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
    </div>
    <div class="topbar-metrics">
      <span class="metric-chip"><b>{{ metrics.videos }}</b>视频</span>
      <span class="metric-chip"><b>{{ metrics.subtitles }}</b>字幕</span>
      <span class="metric-chip"><b>{{ metrics.jobs }}</b>任务</span>
    </div>
  </header>
</template>

<script setup>
defineProps({
  eyebrow: { type: String, default: '/data/wjq/Video_Translate' },
  title: { type: String, default: 'Video Translate Agent' },
  description: { type: String, default: '下载、提取、纠错、术语审核和字幕翻译工作台。' },
  metrics: { type: Object, default: () => ({ videos: 0, subtitles: 0, jobs: 0 }) },
})
</script>
