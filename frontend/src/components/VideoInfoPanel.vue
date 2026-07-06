<template>
  <section class="panel">
    <div class="panel-head">
      <h2>检测结果</h2>
      <span v-if="probe" class="badge" :class="probe.recommendation">{{ recommendationLabel }}</span>
    </div>

    <div v-if="!probe" class="empty">还没有检测结果。</div>
    <div v-else class="stack">
      <div class="info-block">
        <div v-if="thumbnailPath" class="probe-cover">
          <img :src="fileUrl(thumbnailPath)" alt="" />
        </div>
        <div class="video-title">{{ probe.title || '未识别标题' }}</div>
        <div class="muted path">{{ probe.webpage_url }}</div>
        <div v-if="probe.normalized_url && probe.normalized_url !== probe.webpage_url" class="muted path">标准链接：{{ probe.normalized_url }}</div>
        <div class="summary-grid">
          <div class="metric"><b>{{ probe.subtitles?.length || 0 }}</b><span>字幕轨道</span></div>
          <div class="metric"><b>{{ manualCount }}</b><span>人工字幕</span></div>
          <div class="metric"><b>{{ autoCount }}</b><span>自动字幕</span></div>
        </div>
      </div>

      <div v-if="existingProject" class="agent-card">
        <div class="agent-card-head">
          <div>
            <h3>已找到本地项目</h3>
            <p>{{ existingProject.name }}</p>
          </div>
          <span class="badge">{{ existingProject.source_type === 'youtube' ? 'YouTube' : '本地' }}</span>
        </div>
        <div class="muted path">{{ existingProject.path }}</div>
        <div class="toolbar">
          <button class="secondary" @click="$emit('use-project', existingProject)">载入项目继续处理</button>
        </div>
      </div>

      <div v-if="agentPlan" class="agent-card">
        <div class="agent-card-head">
          <div>
            <h3>Agent 推荐</h3>
            <p>{{ routeLabel }}</p>
          </div>
          <span class="badge">{{ confidenceLabel }}</span>
        </div>
        <div v-if="agentPlan.selected_subtitle" class="agent-selected">
          <span>推荐字幕</span>
          <b>{{ agentPlan.selected_subtitle.label || agentPlan.selected_subtitle.lang }}</b>
        </div>
        <ul v-if="agentPlan.reasons?.length" class="reason-list">
          <li v-for="reason in agentPlan.reasons" :key="reason">{{ reason }}</li>
        </ul>
        <div class="toolbar">
          <button v-if="agentPlan.selected_subtitle" @click="downloadSubtitle(agentPlan.selected_subtitle)">下载推荐字幕</button>
          <button v-else-if="agentPlan.recommended_action === 'run_ocr'" class="warning" @click="$emit('agent-ocr-full')">按推荐跑 OCR</button>
          <button v-else-if="agentPlan.recommended_action === 'run_asr'" class="secondary" @click="$emit('agent-download-video')">先下载视频再 ASR</button>
          <button v-else class="secondary" @click="$emit('agent-download-video')">先下载视频再诊断</button>
        </div>
      </div>

      <div class="title-tools">
        <div>
          <label for="translatedTitle">中文标题</label>
          <input id="translatedTitle" :value="titleBox" placeholder="检测标题后自动盲翻，可复制到任务提示" @input="$emit('update:titleBox', $event.target.value)" />
        </div>
        <div class="toolbar">
          <button class="secondary" @click="$emit('copy-title')">复制</button>
          <button class="secondary" @click="$emit('append-title-hint')">填入提示</button>
        </div>
      </div>
      <div class="status" :class="titleStatusClass">{{ titleStatus }}</div>

      <div class="subtitle-section">
        <div class="section-title">
          <h3>常用字幕</h3>
          <span class="muted">只展开中 / 英 / 日 / 韩，其它语言折叠</span>
        </div>
        <SubtitleTable v-if="coreSubtitles.length" :items="coreSubtitles" @download="downloadSubtitle" />
        <div v-else class="empty">没有中 / 英 / 日 / 韩字幕。</div>

        <details v-if="otherSubtitles.length" class="more-subtitles">
          <summary><span>其它字幕</span><span class="badge">{{ otherSubtitles.length }}</span></summary>
          <SubtitleTable :items="otherSubtitles" @download="downloadSubtitle" />
        </details>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import SubtitleTable from './SubtitleTable.vue'

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

