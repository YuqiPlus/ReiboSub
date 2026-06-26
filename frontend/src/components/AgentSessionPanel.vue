<template>
  <section class="agent-cockpit">
    <div class="agent-launchpad">
      <div class="agent-hero">
        <div class="agent-hero-copy">
          <div class="eyebrow">Agent Cockpit</div>
          <h2>YouTube 字幕制作 Agent</h2>
          <p>贴入链接后，Agent 会检测字幕源、选择路线、生成 glossary、等待你审核，并交付可播放字幕。</p>
        </div>
        <div class="agent-live-chip" :class="session?.status || 'idle'">
          <span></span>
          <b>{{ session ? statusLabel : '待启动' }}</b>
        </div>
      </div>

      <div class="agent-command">
        <div class="agent-url-field">
          <label for="agentUrl">YouTube 链接或视频 ID</label>
          <input id="agentUrl" :value="url" placeholder="https://www.youtube.com/watch?v=..." @input="$emit('update:url', $event.target.value)" />
        </div>
        <div class="agent-submit">
          <button :disabled="starting || !url.trim()" @click="$emit('start-agent')">
            {{ starting ? '启动中' : '启动 Agent' }}
          </button>
          <button v-if="session?.retryable" class="secondary mini" @click="$emit('retry-agent')">重试当前阶段</button>
          <button v-if="session?.cancellable" class="danger secondary mini" @click="$emit('cancel-agent')">中断</button>
        </div>
      </div>

      <div class="agent-context-strip">
        <div class="agent-setting">
          <span>内嵌字幕</span>
          <div class="segmented">
            <button type="button" :class="{ active: embeddedSubtitleHint === 'unknown' }" @click="$emit('update:embeddedSubtitleHint', 'unknown')">不清楚</button>
            <button type="button" :class="{ active: embeddedSubtitleHint === 'yes' }" @click="$emit('update:embeddedSubtitleHint', 'yes')">有</button>
            <button type="button" :class="{ active: embeddedSubtitleHint === 'no' }" @click="$emit('update:embeddedSubtitleHint', 'no')">没有</button>
          </div>
        </div>
        <div class="agent-hint-field">
          <label for="agentHint">任务提示</label>
          <textarea id="agentHint" class="compact-textarea" :value="extraHint" placeholder="人名、节目名、固定译法" @input="$emit('update:extraHint', $event.target.value)" />
        </div>
      </div>
    </div>

    <div v-if="status" class="status agent-status" :class="statusClass">{{ status }}</div>

    <div class="agent-board">
      <div class="agent-main">
        <div class="agent-stage-card">
          <div class="agent-stage-head">
            <span>当前阶段</span>
            <b>{{ phaseLabel }}</b>
          </div>
          <div class="agent-rail">
            <div v-for="step in steps" :key="step.id" class="agent-step" :class="step.state">
              <span>{{ step.index }}</span>
              <b>{{ step.label }}</b>
            </div>
          </div>
        </div>

        <div v-if="agentPlan" class="agent-decision-card">
          <div>
            <span>Agent 判断</span>
            <h3>{{ routeLabel }}</h3>
          </div>
          <p v-if="agentPlan.reasons?.length">{{ agentPlan.reasons[0] }}</p>
          <div v-if="agentPlan.selected_subtitle" class="agent-selected">
            <span>推荐字幕</span>
            <b>{{ agentPlan.selected_subtitle.label || agentPlan.selected_subtitle.lang }}</b>
          </div>
        </div>

        <div v-if="session?.question?.kind" class="agent-question">
          <div class="question-pulse">待你确认</div>
          <h3>{{ session.question.title || '需要确认' }}</h3>
          <p>{{ session.question.message }}</p>
          <div v-if="session.question.selected_subtitle" class="agent-selected">
            <span>字幕</span>
            <b>{{ session.question.selected_subtitle.label || session.question.selected_subtitle.lang }}</b>
          </div>
          <div v-if="session.question.glossary_path" class="agent-selected">
            <span>Glossary</span>
            <b>{{ session.question.glossary_path }}</b>
          </div>
          <div class="toolbar">
            <button
              v-for="option in session.question.options || []"
              :key="option.action"
              :class="{ secondary: option.action !== 'use_recommended' && option.action !== 'continue_after_glossary' }"
              @click="$emit('answer-agent', option.action)"
            >
              {{ option.label }}
            </button>
            <button v-if="session.question.glossary_path" class="secondary" @click="$emit('open-glossary', session.question.glossary_path)">打开 Glossary 审核</button>
          </div>
        </div>
      </div>

      <aside class="agent-side">
        <div v-if="currentJobLabel" class="agent-monitor">
          <span>底层任务</span>
          <b>{{ currentJobLabel }}</b>
          <pre v-if="currentJobLogs.length">{{ currentJobLogs.join('\n') }}</pre>
        </div>

        <div v-if="resultItems.length" class="agent-outputs">
          <h3>产物</h3>
          <div v-for="item in resultItems" :key="item.label" class="path-row">
            <span>{{ item.label }}</span>
            <code>{{ item.value }}</code>
          </div>
        </div>

        <div class="agent-log">
          <h3>时间线</h3>
          <ol>
            <li v-for="(line, index) in sessionLogs" :key="`${index}-${line}`">{{ line }}</li>
          </ol>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  url: { type: String, default: '' },
  embeddedSubtitleHint: { type: String, default: 'unknown' },
  extraHint: { type: String, default: '' },
  session: { type: Object, default: null },
  starting: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

defineEmits([
  'update:url',
  'update:embeddedSubtitleHint',
  'update:extraHint',
  'start-agent',
  'answer-agent',
  'cancel-agent',
  'retry-agent',
  'open-glossary',
])

const phaseOrder = [
  ['probe', '检测'],
  ['confirm_subtitle', '决策'],
  ['download_subtitle', '取源'],
  ['download_anchor_subtitle', '取源'],
  ['download_video_for_hybrid', '视频'],
  ['hybrid_anchor_ocr', '还原'],
  ['ocr_full', 'OCR'],
  ['audio_asr', 'ASR'],
  ['generate_glossary', '术语'],
  ['review_glossary', '审核'],
  ['translate', '翻译'],
  ['done', '完成'],
]

const statusLabel = computed(() => {
  if (!props.session) return ''
  if (props.session.status === 'running') return '运行中'
  if (props.session.status === 'waiting') return '等待确认'
  if (props.session.status === 'done') return '完成'
  if (props.session.status === 'failed') return '失败'
  if (props.session.status === 'cancelled') return '已取消'
  return props.session.status
})

const phaseLabel = computed(() => {
  const phase = props.session?.phase || ''
  const labels = {
    created: '等待启动',
    probe: '检测视频和字幕',
    confirm_subtitle: '等待确认字幕源',
    download_subtitle: '下载字幕',
    generate_glossary: '生成 Glossary',
    review_glossary: '等待 Glossary 审核',
    translate: '翻译字幕',
    ocr_full: 'OCR 全流程',
    download_anchor_subtitle: '下载定轴字幕',
    download_video_for_hybrid: '下载视频',
    hybrid_anchor_ocr: '英文定轴 + 韩文 OCR',
    audio_asr: '音频 ASR',
    cancelled: '已中断',
    done: '完成',
  }
  return labels[phase] || phase || '未开始'
})

const agentPlan = computed(() => props.session?.result?.agent_plan || null)

const routeLabel = computed(() => {
  const route = agentPlan.value?.route || ''
  const labels = {
    download_target_subtitle: '直接下载中文字幕',
    translate_source_subtitle: '原声字幕翻译',
    translate_auto_subtitle: '自动字幕纠错翻译',
    translate_fallback_subtitle: '中转字幕翻译',
    hybrid_anchor_ocr: '英文定轴 + 韩文 OCR',
    ocr: 'OCR 翻译',
    asr: 'ASR 翻译',
    diagnose_ocr_asr: '等待路线诊断',
  }
  return labels[route] || route || '等待检测'
})

const steps = computed(() => {
  const phase = props.session?.phase || 'created'
  const currentIndex = Math.max(0, phaseOrder.findIndex(([id]) => id === phase))
  return phaseOrder
    .filter(([id]) => !['download_anchor_subtitle', 'download_subtitle', 'download_video_for_hybrid', 'audio_asr', 'ocr_full'].includes(id) || id === phase)
    .slice(0, 7)
    .map(([id, label], index) => {
      const orderIndex = phaseOrder.findIndex(([stepId]) => stepId === id)
      let state = 'upcoming'
      if (props.session?.status === 'failed' && id === phase) state = 'failed'
      else if (props.session?.status === 'cancelled' && id === phase) state = 'failed'
      else if (orderIndex < currentIndex) state = 'done'
      else if (id === phase) state = 'active'
      return { id, label, index: index + 1, state }
    })
})

const resultItems = computed(() => {
  const result = props.session?.result || {}
  return [
    ['源字幕', result.source_srt],
    ['Glossary', result.glossary_path],
    ['中文字幕', result.translated_srt],
    ['视频', result.input_video],
    ['标准链接', result.normalized_url],
  ]
    .filter(([, value]) => value)
    .map(([label, value]) => ({ label, value }))
})

const currentJobLabel = computed(() => {
  const result = props.session?.result || {}
  if (!result.current_job_name) return ''
  return `${result.current_job_name} · ${result.current_job_status || 'running'}`
})

const currentJobLogs = computed(() => props.session?.result?.current_job_logs || [])
const sessionLogs = computed(() => props.session?.logs || ['等待任务启动'])
</script>
