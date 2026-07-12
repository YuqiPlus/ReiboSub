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
        <div class="agent-setting">
          <span>字幕目标</span>
          <div class="segmented">
            <button type="button" :class="{ active: embeddedSubtitleGoal === 'screen_subtitle' }" @click="$emit('update:embeddedSubtitleGoal', 'screen_subtitle')">复刻画面</button>
            <button type="button" :class="{ active: embeddedSubtitleGoal === 'full_speech' }" @click="$emit('update:embeddedSubtitleGoal', 'full_speech')">完整听译</button>
          </div>
        </div>
        <div class="agent-setting">
          <span>音源语言</span>
          <select :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)">
            <option value="auto">自动</option>
            <option value="korean">韩语</option>
            <option value="japanese">日语</option>
            <option value="english">英语</option>
            <option value="chinese">中文</option>
          </select>
        </div>
        <div class="agent-setting">
          <span>OCR 字幕</span>
          <select :value="ocrLanguage" @change="$emit('update:ocrLanguage', $event.target.value)">
            <option value="auto">跟随音源</option>
            <option value="korean">韩语</option>
            <option value="japanese">日语</option>
            <option value="english">英语</option>
            <option value="chinese">中文：只提取</option>
          </select>
        </div>
        <div v-if="showOcrControls" class="agent-setting">
          <span>OCR 模式</span>
          <div class="segmented">
            <button type="button" :class="{ active: ocrScope !== 'smart_full' }" @click="setOcrMode('limited')">限定区域</button>
            <button type="button" :class="{ active: ocrScope === 'smart_full' }" @click="setOcrMode('smart_full')">全屏辅助</button>
          </div>
        </div>
        <div v-if="showOcrControls" class="agent-setting">
          <span>提取方式</span>
          <div class="segmented">
            <button type="button" :class="{ active: ocrExtractionMode === 'auto' }" @click="$emit('update:ocrExtractionMode', 'auto')">自动主字幕</button>
            <button type="button" :class="{ active: ocrExtractionMode === 'region' }" @click="$emit('update:ocrExtractionMode', 'region')">区域 OCR</button>
          </div>
        </div>
        <div v-if="showOcrControls" class="agent-setting">
          <span>裁剪预设</span>
          <div class="segmented">
            <button type="button" :class="{ active: isCropPreset(0.58) }" @click="applyCropPreset(0.58)">底部</button>
            <button type="button" :class="{ active: isCropPreset(0.38) }" @click="applyCropPreset(0.38)">中下</button>
          </div>
        </div>

        <div v-if="showOcrControls" class="agent-setting">
          <span>原文精修</span>
          <div class="segmented">
            <button type="button" :class="{ active: ocrRefinementMode === 'none' }" @click="$emit('update:ocrRefinementMode', 'none')">关闭</button>
            <button type="button" :class="{ active: ocrRefinementMode === 'llm_boxes' }" @click="$emit('update:ocrRefinementMode', 'llm_boxes')">新版</button>
          </div>
        </div>
        <div class="agent-hint-field">
          <label for="agentHint">任务提示</label>
          <textarea id="agentHint" class="compact-textarea" :value="extraHint" placeholder="人名、节目名、固定译法" @input="$emit('update:extraHint', $event.target.value)" />
        </div>
      </div>

      <div v-if="showOcrControls" class="agent-ocr-workbench">
        <OcrCropControls
          title="OCR 裁剪预览"
          :input-video="inputVideo"
          :ocr-scope="ocrScope"
          :ocr-crop-top-ratio="ocrCropTopRatio"
          :ocr-crop-bottom-ratio="ocrCropBottomRatio"
          :ocr-crop-left-ratio="ocrCropLeftRatio"
          :ocr-crop-right-ratio="ocrCropRightRatio"
          :ocr-exclude-enabled="ocrExcludeEnabled"
          :ocr-exclude-top-ratio="ocrExcludeTopRatio"
          :ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
          :ocr-exclude-left-ratio="ocrExcludeLeftRatio"
          :ocr-exclude-right-ratio="ocrExcludeRightRatio"
          @update:ocr-crop-top-ratio="$emit('update:ocrCropTopRatio', $event)"
          @update:ocr-crop-bottom-ratio="$emit('update:ocrCropBottomRatio', $event)"
          @update:ocr-crop-left-ratio="$emit('update:ocrCropLeftRatio', $event)"
          @update:ocr-crop-right-ratio="$emit('update:ocrCropRightRatio', $event)"
          @update:ocr-exclude-enabled="$emit('update:ocrExcludeEnabled', $event)"
          @update:ocr-exclude-top-ratio="$emit('update:ocrExcludeTopRatio', $event)"
          @update:ocr-exclude-bottom-ratio="$emit('update:ocrExcludeBottomRatio', $event)"
          @update:ocr-exclude-left-ratio="$emit('update:ocrExcludeLeftRatio', $event)"
          @update:ocr-exclude-right-ratio="$emit('update:ocrExcludeRightRatio', $event)"
        />
      </div>
    </div>

    <div v-if="sessions.length" class="agent-session-strip">
      <div class="section-title">
        <h3>Agent 任务</h3>
        <span class="badge">{{ sessions.length }}</span>
      </div>
      <div class="agent-session-list">
        <div
          v-for="item in sessions"
          :key="item.id"
          class="agent-session-card"
          :class="{ active: item.id === session?.id, waiting: item.status === 'waiting', failed: item.status === 'failed' }"
        >
          <button class="agent-session-main" type="button" @click="$emit('select-agent', item.id)">
            <b>{{ itemLabel(item) }}</b>
            <span>{{ item.id }} · {{ sessionPhaseLabel(item.phase) }} · {{ sessionStatusLabel(item.status) }}</span>
          </button>
          <button v-if="item.result?.glossary_path" class="secondary mini" type="button" @click="$emit('open-glossary', { path: item.result.glossary_path, sessionId: item.id })">
            {{ sessionGlossaryActionLabel(item) }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="tasks.length" class="agent-session-strip">
      <div class="section-title">
        <h3>视频任务</h3>
        <span class="badge">{{ activeTasks.length }} 未完成</span>
      </div>
      <div v-if="activeTasks.length" class="agent-task-list">
        <article v-for="task in activeTasks" :key="task.id" class="agent-task-card">
          <div class="agent-task-head">
            <div>
              <b>{{ task.title || task.url || task.id }}</b>
              <span>{{ taskStageLabel(task.current_stage) }} · {{ task.id }}</span>
            </div>
            <div class="agent-task-head-actions">
              <button class="secondary mini" type="button" @click="$emit('continue-task', task.id)">继续</button>
              <button class="secondary mini" type="button" @click="$emit('complete-task', task)">完成流程</button>
              <button class="danger secondary mini" type="button" @click="$emit('delete-task', task)">删除任务</button>
            </div>
          </div>
          <div class="agent-task-stages">
            <div v-for="stage in task.stage_items || []" :key="stage.id" class="agent-task-stage" :class="stage.status || 'pending'">
              <span>{{ stage.label }}</span>
              <b>{{ stageStatusLabel(stage, task) }}</b>
              <div class="agent-task-actions">
                <button v-if="stage.id === 'glossary' && stage.glossary_path" class="secondary mini" type="button" @click="$emit('open-glossary', stage.glossary_path)">{{ taskGlossaryActionLabel(task) }}</button>
                <button v-if="canRerun(stage)" class="secondary mini" type="button" @click="$emit('rerun-task', { taskId: task.id, stage: stage.id })">重跑</button>
              </div>
            </div>
          </div>
        </article>
      </div>
      <div v-else class="empty">没有未完成流程。</div>

      <details v-if="completedTasks.length" class="completed-task-panel">
        <summary><span>已完成流程</span><span class="badge">{{ completedTasks.length }}</span></summary>
        <div class="agent-task-list">
          <article v-for="task in completedTasks" :key="task.id" class="agent-task-card completed">
            <div class="agent-task-head">
              <div>
                <b>{{ task.title || task.url || task.id }}</b>
                <span>{{ taskStageLabel(task.current_stage) }} · {{ completedLabel(task) }} · {{ task.id }}</span>
              </div>
              <div class="agent-task-head-actions">
                <button class="secondary mini" type="button" @click="$emit('reopen-task', task)">恢复</button>
                <button class="secondary mini" type="button" @click="$emit('continue-task', task.id)">继续</button>
                <button class="danger secondary mini" type="button" @click="$emit('delete-task', task)">删除任务</button>
              </div>
            </div>
            <div class="agent-task-stages">
              <div v-for="stage in task.stage_items || []" :key="stage.id" class="agent-task-stage" :class="stage.status || 'pending'">
                <span>{{ stage.label }}</span>
                <b>{{ stageStatusLabel(stage, task) }}</b>
                <div class="agent-task-actions">
                  <button v-if="stage.id === 'glossary' && stage.glossary_path" class="secondary mini" type="button" @click="$emit('open-glossary', stage.glossary_path)">{{ taskGlossaryActionLabel(task) }}</button>
                  <button v-if="canRerun(stage)" class="secondary mini" type="button" @click="$emit('rerun-task', { taskId: task.id, stage: stage.id })">重跑</button>
                </div>
              </div>
            </div>
          </article>
        </div>
      </details>
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
          <div v-if="detectedLanguage" class="agent-selected">
            <span>音源语言</span>
            <b>{{ detectedLanguage }}</b>
          </div>
          <div v-if="agentPlan.selected_subtitle" class="agent-selected">
            <span>推荐字幕</span>
            <b>{{ agentPlan.selected_subtitle.label || agentPlan.selected_subtitle.lang }}</b>
          </div>
          <div v-if="agentPlan.reference_subtitle" class="agent-selected">
            <span>参考字幕</span>
            <b>{{ agentPlan.reference_subtitle.label || agentPlan.reference_subtitle.lang }}</b>
          </div>
          <div v-if="candidateSubtitles.length" class="agent-candidates">
            <span>人工字幕候选</span>
            <div class="candidate-list">
              <b v-for="item in candidateSubtitles" :key="`${item.kind}-${item.lang}`">
                {{ item.label || `${item.lang} · ${item.kind}` }}
              </b>
            </div>
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
          <div v-if="session.question.candidate_subtitles?.length" class="agent-candidates">
            <span>可选字幕</span>
            <div class="candidate-list">
              <b v-for="item in session.question.candidate_subtitles" :key="`${item.kind}-${item.lang}`">
                {{ item.label || `${item.lang} · ${item.kind}` }}
              </b>
            </div>
          </div>
          <div v-if="session.question.glossary_path" class="agent-selected">
            <span>Glossary</span>
            <b>{{ session.question.glossary_path }}</b>
          </div>
          <div v-if="session.question.reusable_ocr" class="agent-selected">
            <span>可复用 OCR</span>
            <b>{{ session.question.reusable_ocr.source_srt }}</b>
            <small>{{ reuseLabel(session.question.reusable_ocr) }}</small>
          </div>
          <div class="toolbar">
            <button
              v-for="option in session.question.options || []"
              :key="option.action"
              :class="{ secondary: !primaryActions.includes(option.action) }"
              @click="$emit('answer-agent', option.action)"
            >
              {{ option.label }}
            </button>
            <button v-if="session.question.glossary_path" class="secondary" @click="$emit('open-glossary', { path: session.question.glossary_path, sessionId: session.id })">打开 Glossary 审核</button>
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
import OcrCropControls from './OcrCropControls.vue'

const props = defineProps({
  url: { type: String, default: '' },
  embeddedSubtitleHint: { type: String, default: 'unknown' },
  embeddedSubtitleGoal: { type: String, default: 'screen_subtitle' },
  sourceLanguage: { type: String, default: 'auto' },
  ocrLanguage: { type: String, default: 'auto' },
  ocrScope: { type: String, default: 'bottom' },
  ocrExtractionMode: { type: String, default: 'auto' },
  inputVideo: { type: String, default: '' },
  ocrCropTopRatio: { type: Number, default: 0.58 },
  ocrCropBottomRatio: { type: Number, default: 0 },
  ocrCropLeftRatio: { type: Number, default: 0 },
  ocrCropRightRatio: { type: Number, default: 0 },
  ocrExcludeEnabled: { type: Boolean, default: false },
  ocrExcludeTopRatio: { type: Number, default: 0.04 },
  ocrExcludeBottomRatio: { type: Number, default: 0.82 },
  ocrExcludeLeftRatio: { type: Number, default: 0.76 },
  ocrExcludeRightRatio: { type: Number, default: 0.02 },
  ocrRefinementMode: { type: String, default: 'none' },
  extraHint: { type: String, default: '' },
  session: { type: Object, default: null },
  sessions: { type: Array, default: () => [] },
  tasks: { type: Array, default: () => [] },
  starting: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

const emit = defineEmits([
  'update:url',
  'update:embeddedSubtitleHint',
  'update:embeddedSubtitleGoal',
  'update:sourceLanguage',
  'update:ocrLanguage',
  'update:ocrScope',
  'update:ocrExtractionMode',
  'update:ocrCropTopRatio',
  'update:ocrCropBottomRatio',
  'update:ocrCropLeftRatio',
  'update:ocrCropRightRatio',
  'update:ocrExcludeEnabled',
  'update:ocrExcludeTopRatio',
  'update:ocrExcludeBottomRatio',
  'update:ocrExcludeLeftRatio',
  'update:ocrExcludeRightRatio',
  'update:ocrRefinementMode',
  'update:extraHint',
  'start-agent',
  'answer-agent',
  'cancel-agent',
  'retry-agent',
  'select-agent',
  'continue-task',
  'rerun-task',
  'complete-task',
  'reopen-task',
  'delete-task',
  'open-glossary',
])

function setOcrMode(mode) {
  emit('update:ocrScope', mode === 'smart_full' ? 'smart_full' : 'bottom')
}

function applyCropPreset(topRatio) {
  emit('update:ocrCropTopRatio', topRatio)
  emit('update:ocrCropBottomRatio', 0)
}

function isCropPreset(topRatio) {
  return Math.abs(Number(props.ocrCropTopRatio || 0) - topRatio) < 0.005
}

const activeTasks = computed(() => props.tasks.filter((task) => !task.is_completed))
const completedTasks = computed(() => props.tasks.filter((task) => task.is_completed))
const showOcrControls = computed(() => Boolean(props.inputVideo || props.session))

const phaseOrder = [
  ['probe', '检测'],
  ['download_video_for_audio_probe', '视频'],
  ['probe_audio_language', '音源'],
  ['confirm_subtitle', '决策'],
  ['confirm_hybrid_ocr_settings', '调框'],
  ['download_subtitle', '取源'],
  ['download_reference_subtitle', '参考'],
  ['dual_subtitle_reference', '融合'],
  ['download_anchor_subtitle', '取源'],
  ['download_video_for_hybrid', '视频'],
  ['hybrid_anchor_ocr', '还原'],
  ['ocr_full', 'OCR'],
  ['confirm_ocr_reuse', '复用'],
  ['audio_asr', 'ASR'],
  ['ocr_reference', 'OCR参考'],
  ['asr_ocr_refine', '校准'],
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
  return sessionPhaseLabel(phase)
})

function sessionPhaseLabel(phase) {
  const labels = {
    created: '等待启动',
    probe: '检测视频和字幕',
    download_video_for_audio_probe: '下载视频用于音源检测',
    download_video_for_preview: '下载视频用于预览',
    probe_audio_language: '检测音源语言',
    confirm_subtitle: '等待确认字幕源',
    confirm_hybrid_ocr_settings: '等待确认 OCR 范围',
    confirm_ocr_reuse: '等待确认是否复用 OCR',
    download_subtitle: '下载字幕',
    download_reference_subtitle: '下载参考字幕',
    dual_subtitle_reference: '韩文主字幕 + 英文参考',
    generate_glossary: '生成 Glossary',
    review_glossary: '等待 Glossary 审核',
    translate: '翻译字幕',
    ocr_full: 'OCR 全流程',
    download_anchor_subtitle: '下载定轴字幕',
    download_video_for_hybrid: '下载视频',
    hybrid_anchor_ocr: '英文定轴 + 韩文 OCR',
    audio_asr: '音频 ASR',
    ocr_reference: 'OCR 参考提取',
    asr_ocr_refine: 'ASR + OCR 校准',
    cancelled: '已中断',
    done: '完成',
  }
  return labels[phase] || phase || '未开始'
}

const primaryActions = ['use_recommended', 'start_hybrid_anchor_ocr', 'continue_after_glossary', 'use_cached_ocr', 'download_video_for_preview', 'run_ocr', 'run_asr', 'run_asr_with_ocr', 'probe_audio_language']

function sessionStatusLabel(status) {
  const labels = {
    running: '运行中',
    waiting: '等待审核/确认',
    done: '完成',
    failed: '失败',
    cancelled: '已中断',
  }
  return labels[status] || status || '未知'
}

function sessionGlossaryActionLabel(item) {
  return item?.status === 'done' ? '查看 Glossary' : '审核 Glossary'
}

function completedLabel(task) {
  if (!task?.completed_at) return '已完成'
  return new Date(task.completed_at * 1000).toLocaleString()
}

function itemLabel(item) {
  const title = item.result?.probe?.title || item.payload?.url || 'Agent 任务'
  return String(title).slice(0, 42)
}

function reuseLabel(item) {
  const matchedBy = item.matched_by === 'url' ? '标准链接匹配' : '标题兼容匹配'
  return `${matchedBy} · ${item.job_id || '历史任务'}`
}

function taskStageLabel(stage) {
  const labels = {
    created: '刚创建',
    probe_done: '已检测',
    ocr_done: 'OCR 已完成',
    glossary_review: '等待 glossary 审核',
    done: '已完成',
    ocr_failed: 'OCR 失败',
    glossary_failed: 'Glossary 失败',
    translate_failed: '翻译失败',
  }
  return labels[stage] || stage || '未开始'
}

function stageStatusLabel(stage, task) {
  if (stage?.id === 'glossary' && stage?.status === 'waiting_review' && taskHasDoneTranslation(task)) {
    return '已用于翻译'
  }
  const status = stage?.status
  const labels = {
    pending: '未开始',
    done: '完成',
    waiting_review: '待审核',
    failed: '失败',
    invalidated: '已失效',
    rerunning: '重跑中',
  }
  return labels[status] || status || '未开始'
}

function taskGlossaryActionLabel(task) {
  return taskHasDoneTranslation(task) ? '查看' : '审核'
}

function taskHasDoneTranslation(task) {
  const stages = task?.stages || {}
  if (stages.translate?.status === 'done' || stages.translate?.translated_srt) return true
  return (task?.stage_items || []).some((stage) => stage.id === 'translate' && stage.status === 'done')
}

function canRerun(stage) {
  return stage.can_rerun !== false && ['ocr', 'glossary', 'translate'].includes(stage.id) && ['done', 'waiting_review', 'failed', 'invalidated'].includes(stage.status)
}

const agentPlan = computed(() => props.session?.result?.agent_plan || null)
const candidateSubtitles = computed(() => agentPlan.value?.candidate_subtitles || props.session?.question?.candidate_subtitles || [])
const detectedLanguage = computed(() => {
  const result = props.session?.result || {}
  if (!result.detected_source_language) return ''
  const confidence = result.detected_source_language_confidence
  if (confidence === undefined || confidence === null || confidence === '') return result.detected_source_language
  return `${result.detected_source_language} · ${(Number(confidence) * 100).toFixed(0)}%`
})

const routeLabel = computed(() => {
  const route = agentPlan.value?.route || ''
  const labels = {
    download_target_subtitle: '直接下载中文字幕',
    translate_source_subtitle: '原声字幕翻译',
    translate_auto_subtitle: '自动字幕纠错翻译',
    translate_fallback_subtitle: '中转字幕翻译',
    dual_subtitle_reference: '韩文主字幕 + 英文参考',
    hybrid_anchor_ocr: '英文定轴 + 韩文 OCR',
    probe_audio_language: '先检测音源语言',
    ocr: 'OCR 翻译',
    asr: 'ASR 翻译',
    asr_ocr_reference: 'ASR 主导 + OCR 参考',
    diagnose_ocr_asr: '等待路线诊断',
  }
  return labels[route] || route || '等待检测'
})

const steps = computed(() => {
  const phase = props.session?.phase || 'created'
  const currentIndex = Math.max(0, phaseOrder.findIndex(([id]) => id === phase))
  return phaseOrder
    .filter(([id]) => !['download_anchor_subtitle', 'download_subtitle', 'download_reference_subtitle', 'dual_subtitle_reference', 'download_video_for_hybrid', 'audio_asr', 'ocr_full'].includes(id) || id === phase)
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
