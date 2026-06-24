<template>
  <section class="panel primary-panel">
    <div class="panel-head">
      <h2>输入视频</h2>
      <span class="muted">先检测字幕，有原生字幕就不用 OCR 时间轴</span>
    </div>
    <div class="url-row">
      <div>
        <label for="url">YouTube 链接或视频 ID</label>
        <input id="url" :value="url" placeholder="https://www.youtube.com/watch?v=..." @input="$emit('update:url', $event.target.value)" />
      </div>
      <button :disabled="probing" @click="$emit('probe')">检测字幕</button>
    </div>
    <div class="mode-row">
      <label>画面内嵌字幕</label>
      <div class="segmented">
        <button type="button" :class="{ active: embeddedSubtitleHint === 'unknown' }" @click="$emit('update:embeddedSubtitleHint', 'unknown')">不清楚</button>
        <button type="button" :class="{ active: embeddedSubtitleHint === 'yes' }" @click="$emit('update:embeddedSubtitleHint', 'yes')">有</button>
        <button type="button" :class="{ active: embeddedSubtitleHint === 'no' }" @click="$emit('update:embeddedSubtitleHint', 'no')">没有</button>
      </div>
      <span class="muted">没有可用字幕时，Agent 会用这个判断节省 OCR/ASR 诊断时间</span>
    </div>
    <div class="toolbar">
      <button class="secondary" @click="$emit('download-video')">下载视频</button>
      <button class="warning" @click="$emit('ocr-full')">下载视频并 OCR 翻译</button>
    </div>
    <div class="mode-row">
      <label for="ocrTranslationMode">OCR 翻译处理模式</label>
      <select id="ocrTranslationMode" :value="ocrTranslationMode" @change="$emit('update:ocrTranslationMode', $event.target.value)">
        <option value="translate_only">锁定时间轴：只翻译文本</option>
        <option value="standard_cleanup">标准清理：去重复和残片</option>
        <option value="readability_retime">强力精修：优化阅读时长</option>
      </select>
      <span class="muted">内嵌字幕稳定时选锁定时间轴；OCR 有闪字/残片时选标准或强力</span>
    </div>
    <div class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
defineProps({
  url: { type: String, default: '' },
  ocrTranslationMode: { type: String, default: 'standard_cleanup' },
  embeddedSubtitleHint: { type: String, default: 'unknown' },
  probing: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})
defineEmits(['update:url', 'update:ocrTranslationMode', 'update:embeddedSubtitleHint', 'probe', 'download-video', 'ocr-full'])
</script>
