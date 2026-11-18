<template>
  <section class="panel link-results-studio" aria-label="链接检测结果">
    <div v-if="!probe" class="studio-empty">还没有检测结果。</div>
    <template v-else>
      <header class="link-result-header"><img v-if="thumbnailPath" :src="fileUrl(thumbnailPath)" alt="" /><div><span class="studio-kicker">检测结果</span><h2>{{ probe.title || '未识别标题' }}</h2><p>{{ manualCount }} 条人工字幕 · {{ autoCount }} 条自动字幕</p></div></header>
      <div v-if="existingProject" class="link-existing-project"><AppIcon name="folder" :size="18" /><span>本地已有素材，可继续使用。</span><button class="secondary mini" @click="$emit('use-project', existingProject)">载入项目</button></div>
      <div v-if="agentPlan" class="link-recommendation"><div><span>来源建议</span><p>{{ routeLabel }}</p></div><button v-if="agentPlan.selected_subtitle" @click="downloadSubtitle(agentPlan.selected_subtitle)">下载推荐字幕</button><button v-else-if="agentPlan.recommended_action === 'run_ocr'" class="secondary" @click="$emit('agent-ocr-full')">提取画面字幕</button><button v-else-if="agentPlan.recommended_action === 'run_asr'" class="secondary" @click="$emit('agent-download-video')">下载视频后使用 ASR</button><button v-else class="secondary" @click="$emit('agent-download-video')">先保存视频</button></div>
      <section class="links-subtitle-tracks"><div class="studio-section-head"><h3>可用字幕</h3><span>中文 / 英文 / 日文 / 韩文</span></div><SubtitleTable v-if="coreSubtitles.length" :items="coreSubtitles" @download="downloadSubtitle" /><p v-else class="links-no-subtitles">没有这些语言的外挂字幕，可使用上方手动 OCR 或字幕助手。</p><details v-if="otherSubtitles.length" class="studio-disclosure"><summary>其他语言 · {{ otherSubtitles.length }} 条</summary><SubtitleTable :items="otherSubtitles" @download="downloadSubtitle" /></details></section>
      <details class="studio-disclosure link-title-details"><summary>中文标题与任务提示</summary><div class="title-tools"><label for="translatedTitle">中文标题<input id="translatedTitle" :value="titleBox" placeholder="标题参考译文" @input="$emit('update:titleBox', $event.target.value)" /></label><div class="toolbar"><button class="secondary" @click="$emit('copy-title')">复制标题</button><button class="secondary" @click="$emit('append-title-hint')">填入任务提示</button></div></div><p v-if="titleStatus" class="status" :class="titleStatusClass" role="status">{{ titleStatus }}</p></details>
      <details class="studio-disclosure link-source-details"><summary>来源与判断详情</summary><p class="path">{{ probe.webpage_url }}</p><p v-if="probe.normalized_url && probe.normalized_url !== probe.webpage_url" class="path">标准链接：{{ probe.normalized_url }}</p><p v-if="existingProject" class="path">本地项目：{{ existingProject.name }}<br />{{ existingProject.path }}</p><p v-if="agentPlan">来源建议置信度：{{ confidenceLabel }}</p><ul v-if="agentPlan?.reasons?.length"><li v-for="reason in agentPlan.reasons" :key="reason">{{ reason }}</li></ul></details>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import SubtitleTable from './SubtitleTable.vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  probe: { type: Object, default: null },
  titleBox: { type: String, default: '' },
  titleStatus: { type: String, default: '' },
  titleStatusClass: { type: String, default: '' },
})

const emit = defineEmits(['update:titleBox', 'download-subtitle', 'copy-title', 'append-title-hint', 'agent-ocr-full', 'agent-download-video', 'use-project'])

const coreLanguagePrefixes = ['zh', 'en', 'ko', 'ja']

const subtitles = computed(() => props.probe?.subtitles || [])
const manualCount = computed(() => subtitles.value.filter((item) => item.kind === 'manual').length)
const autoCount = computed(() => subtitles.value.filter((item) => item.kind === 'auto').length)
const agentPlan = computed(() => props.probe?.agent_plan || null)
const existingProject = computed(() => props.probe?.existing_project || null)
const thumbnailPath = computed(() => props.probe?.thumbnail_path || existingProject.value?.thumbnail || '')
const recommendationLabel = computed(() => {
  if (!props.probe) return ''
  if (props.probe.recommendation === 'manual') return '优先用人工字幕'
  if (props.probe.recommendation === 'auto') return '可用自动字幕'
  return '建议 OCR'
})
const confidenceLabel = computed(() => {
  const value = agentPlan.value?.confidence
  if (typeof value !== 'number') return '待确认'
  return `${Math.round(value * 100)}%`
})
const routeLabel = computed(() => {
  const route = agentPlan.value?.route
  if (route === 'download_target_subtitle') return '检测到中文字幕，推荐直接下载，不需要二次翻译。'
  if (route === 'translate_source_subtitle') return '推荐下载原声作者字幕，再走 glossary 和 LLM 翻译。'
  if (route === 'translate_auto_subtitle') return '推荐下载原声自动字幕，先纠错再翻译。'
  if (route === 'translate_fallback_subtitle') return '没有理想原文字幕，可用中转字幕，但建议人工确认。'
  if (route === 'ocr') return '用户确认画面有内嵌字幕，推荐 OCR。'
  if (route === 'asr') return '用户确认没有内嵌字幕，推荐 ASR。'
  return '没有可靠字幕，建议先做 OCR/ASR 样本诊断。'
})

const sortedSubtitles = computed(() => [...subtitles.value].sort((left, right) => score(left) - score(right)))
const coreSubtitles = computed(() => sortedSubtitles.value.filter(isCoreLanguage))
const otherSubtitles = computed(() => sortedSubtitles.value.filter((item) => !isCoreLanguage(item)))

function isCoreLanguage(item) {
  const lang = String(item.lang || '').toLowerCase()
  return coreLanguagePrefixes.some((prefix) => lang === prefix || lang.startsWith(`${prefix}-`))
}

function score(item) {
  const lang = String(item.lang || '').toLowerCase()
  const langScore = coreLanguagePrefixes.findIndex((prefix) => lang === prefix || lang.startsWith(`${prefix}-`))
  const kindScore = item.kind === 'manual' ? 0 : 20
  return (langScore >= 0 ? langScore : 50) + kindScore
}

function downloadSubtitle(item) {
  emit('download-subtitle', item)
}

function fileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path)}`
}
</script>

