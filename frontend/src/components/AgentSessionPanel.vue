<template>
  <section class="agent-cockpit">
    <div class="agent-current-panel">
      <div class="agent-hero">
        <div class="agent-hero-copy">
          <div class="eyebrow">当前任务</div>
          <h2>{{ session ? itemLabel(session) : '暂无运行中的 Agent 任务' }}</h2>
          <p v-if="session">{{ phaseLabel }} · {{ statusLabel }}</p>
          <p v-else>在下方新建任务，Agent 会先分析字幕源，再让你确认需要人工决策的步骤。</p>
        </div>
        <div class="agent-live-chip" :class="session?.status || 'idle'">
          <span></span>
          <b>{{ session ? statusLabel : '无当前任务' }}</b>
        </div>
      </div>

      <div v-if="session" class="toolbar agent-current-actions">
        <button v-if="session.retryable" class="secondary mini" type="button" @click="$emit('retry-agent')">重试当前阶段</button>
        <button v-if="session.cancellable" class="danger secondary mini" type="button" @click="$emit('cancel-agent')">中断</button>
      </div>

      <div v-if="operationStatus" class="agent-operation-status" role="status" aria-live="polite">
        <span class="agent-operation-spinner" aria-hidden="true"></span>
        <div>
          <span>当前处理状态</span>
          <b>{{ operationStatus.title }}</b>
          <p>{{ operationStatus.message }}</p>
          <small v-if="operationStatus.detail">{{ operationStatus.detail }}</small>
        </div>
      </div>

      <div v-if="session?.question?.kind" class="agent-question">
        <div class="question-pulse">待你处理</div>
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
        <div v-if="showOcrWorkbench" class="agent-inline-ocr-workbench">
          <div class="agent-inline-ocr-head">
            <div>
              <span>位置操作</span>
              <b>视频已下载，调整 OCR 字幕区域</b>
              <p>首帧会自动加载。直接拖动绿色字幕框，或拖右下角改变大小；调整会自动带入下一步 OCR。</p>
            </div>
            <span class="badge done">视频已就绪 · {{ currentSessionOcrPipeline.label }}</span>
          </div>
          <OcrCropControls
            title="OCR 字幕位置预览"
            :input-video="inputVideo"
            :ocr-scope="currentSessionOcrScope"
            :ocr-extraction-mode="currentSessionOcrPipeline.ocrExtractionMode"
            :ocr-shape-mode="currentSessionOcrPipeline.ocrShapeMode"
            :source-language="sourceLanguage"
            :ocr-language="ocrLanguage"
            :ocr-crop-top-ratio="ocrCropTopRatio"
            :ocr-crop-bottom-ratio="ocrCropBottomRatio"
            :ocr-crop-left-ratio="ocrCropLeftRatio"
            :ocr-crop-right-ratio="ocrCropRightRatio"
            :ocr-exclude-enabled="ocrExcludeEnabled"
            :ocr-exclude-top-ratio="ocrExcludeTopRatio"
            :ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
            :ocr-exclude-left-ratio="ocrExcludeLeftRatio"
            :ocr-exclude-right-ratio="ocrExcludeRightRatio"
            auto-load-preview
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
        <div class="toolbar">
          <button
            v-if="isGlossaryQuestion"
            type="button"
            @click="$emit('open-glossary', { path: session.question.glossary_path, sessionId: session.id })"
          >
            打开 Glossary 审核
          </button>
          <button
            v-for="option in questionOptions"
            :key="option.action"
            type="button"
            :class="{ secondary: !primaryActions.includes(option.action) }"
            @click="$emit('answer-agent', option.action)"
          >
            {{ option.label }}
          </button>
          <button
            v-if="!isGlossaryQuestion && session.question.glossary_path"
            class="secondary"
            type="button"
            @click="$emit('open-glossary', { path: session.question.glossary_path, sessionId: session.id })"
          >
            打开 Glossary 审核
          </button>
        </div>
      </div>

      <div v-if="session" class="agent-stage-card">
        <div class="agent-stage-head">
          <span>六阶段流程</span>
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

      <div v-if="status" class="status agent-status" :class="statusClass">{{ status }}</div>
    </div>

    <details class="agent-launchpad agent-new-task" :open="!session">
      <summary class="section-title">
        <span>
          <b>新建 Agent 任务</b>
          <small>输入链接并选择字幕目标</small>
        </span>
        <span class="badge">{{ session ? '展开' : '待启动' }}</span>
      </summary>

      <div class="agent-command">
        <div class="agent-url-field">
          <label for="agentUrl">YouTube 链接或视频 ID</label>
          <input id="agentUrl" :value="url" placeholder="https://www.youtube.com/watch?v=..." @input="$emit('update:url', $event.target.value)" />
        </div>
        <div class="agent-submit">
          <button type="button" :disabled="starting || !url.trim()" @click="$emit('start-agent')">
            {{ starting ? '启动中' : '启动 Agent' }}
          </button>
        </div>
      </div>

      <div class="agent-context-strip agent-basic-settings">
        <div class="agent-setting">
          <span>字幕目标</span>
          <div class="segmented">
            <button type="button" :class="{ active: embeddedSubtitleGoal === 'screen_subtitle' }" @click="$emit('update:embeddedSubtitleGoal', 'screen_subtitle')">复刻画面</button>
            <button type="button" :class="{ active: embeddedSubtitleGoal === 'full_speech' }" @click="$emit('update:embeddedSubtitleGoal', 'full_speech')">完整听译</button>
          </div>
        </div>
        <div class="agent-setting agent-pipeline-setting">
          <span>需要 OCR 时使用</span>
          <div class="segmented">
            <button type="button" :class="{ active: ocrPipelineVersion === 'v1' }" @click="$emit('update:ocrPipelineVersion', 'v1')">OCR 1.0（旧版）</button>
            <button type="button" :class="{ active: ocrPipelineVersion === 'v2' }" @click="$emit('update:ocrPipelineVersion', 'v2')">OCR 2.0（稳定）</button>
            <button type="button" :class="{ active: ocrPipelineVersion === 'v3' }" @click="$emit('update:ocrPipelineVersion', 'v3')">OCR 3.0（稳定）</button>
          </div>
          <p class="agent-pipeline-note">{{ activeOcrPipeline.description }}</p>
          <p class="agent-pipeline-note">用于整片 OCR 与 ASR + OCR 参考路线；“英文定轴 + 原声 OCR”保留独立流程，直接采用人工字幕时不会运行 OCR。</p>
        </div>
      </div>

      <details class="agent-advanced-settings">
        <summary>高级设置：语言、内嵌字幕、任务提示与 OCR 裁框</summary>
        <div class="agent-context-strip">
          <div class="agent-setting">
            <span>内嵌字幕提示</span>
            <div class="segmented">
              <button type="button" :class="{ active: embeddedSubtitleHint === 'unknown' }" @click="$emit('update:embeddedSubtitleHint', 'unknown')">不清楚</button>
              <button type="button" :class="{ active: embeddedSubtitleHint === 'yes' }" @click="$emit('update:embeddedSubtitleHint', 'yes')">有</button>
              <button type="button" :class="{ active: embeddedSubtitleHint === 'no' }" @click="$emit('update:embeddedSubtitleHint', 'no')">没有</button>
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
            <span>OCR 字幕语言</span>
            <select :value="ocrLanguage" @change="$emit('update:ocrLanguage', $event.target.value)">
              <option value="auto">跟随音源</option>
              <option value="korean">韩语</option>
              <option value="japanese">日语</option>
              <option value="english">英语</option>
              <option value="chinese">中文：只提取</option>
            </select>
          </div>
          <div v-if="ocrPipelineVersion === 'v1'" class="agent-setting">
            <span>OCR 模式</span>
            <div class="segmented">
              <button type="button" :class="{ active: ocrScope !== 'smart_full' }" @click="setOcrMode('limited')">限定区域</button>
              <button type="button" :class="{ active: ocrScope === 'smart_full' }" @click="setOcrMode('smart_full')">全屏辅助</button>
            </div>
          </div>
          <div v-if="inputVideo" class="agent-setting">
            <span>裁剪预设</span>
            <div class="segmented">
              <button type="button" :class="{ active: isCropPreset(0.58) }" @click="applyCropPreset(0.58)">底部</button>
              <button type="button" :class="{ active: isCropPreset(0.38) }" @click="applyCropPreset(0.38)">中下</button>
            </div>
          </div>
          <div class="agent-hint-field">
            <label for="agentHint">任务提示</label>
            <textarea id="agentHint" class="compact-textarea" :value="extraHint" placeholder="人名、节目名、固定译法" @input="$emit('update:extraHint', $event.target.value)" />
          </div>
        </div>

        <div v-if="inputVideo && !showOcrWorkbench" class="agent-ocr-workbench">
          <OcrCropControls
            title="OCR 裁剪预览"
            :input-video="inputVideo"
            :ocr-scope="effectiveOcrScope"
            :ocr-extraction-mode="activeOcrPipeline.ocrExtractionMode"
            :ocr-shape-mode="activeOcrPipeline.ocrShapeMode"
            :source-language="sourceLanguage"
            :ocr-language="ocrLanguage"
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
        <div v-else class="empty">Agent 下载视频后，这里会显示抽帧裁框预览。</div>
      </details>
    </details>

    <details v-if="activeTasks.length" class="agent-session-strip agent-task-section">
      <summary class="section-title">
        <h3>活动视频任务</h3>
        <span class="badge">{{ activeTasks.length }}</span>
      </summary>
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
            <div v-for="stage in task.stage_items || []" :key="stage.id" class="agent-task-stage" :class="taskStageStatusClass(stage, task)">
              <span>{{ taskStageDisplayLabel(stage) }}</span>
              <b>{{ stageStatusLabel(stage, task) }}</b>
              <div class="agent-task-actions">
                <button v-if="stage.id === 'glossary' && stage.glossary_path" class="secondary mini" type="button" @click="$emit('open-glossary', taskGlossaryPayload(task, stage))">{{ taskGlossaryActionLabel(task) }}</button>
                <button v-if="canRerun(stage)" class="secondary mini" type="button" @click="$emit('rerun-task', { taskId: task.id, stage: stage.id })">重跑</button>
              </div>
            </div>
          </div>
        </article>
      </div>
    </details>

    <details v-if="completedTasks.length" class="agent-session-strip completed-task-panel">
      <summary class="section-title">
        <h3>已完成视频任务</h3>
        <span class="badge">{{ completedTasks.length }}</span>
      </summary>
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
            <div v-for="stage in task.stage_items || []" :key="stage.id" class="agent-task-stage" :class="taskStageStatusClass(stage, task)">
              <span>{{ taskStageDisplayLabel(stage) }}</span>
              <b>{{ stageStatusLabel(stage, task) }}</b>
              <div class="agent-task-actions">
                <button v-if="stage.id === 'glossary' && stage.glossary_path" class="secondary mini" type="button" @click="$emit('open-glossary', taskGlossaryPayload(task, stage))">{{ taskGlossaryActionLabel(task) }}</button>
                <button v-if="canRerun(stage)" class="secondary mini" type="button" @click="$emit('rerun-task', { taskId: task.id, stage: stage.id })">重跑</button>
              </div>
            </div>
          </div>
        </article>
      </div>
    </details>

    <details v-if="sessions.length" class="agent-session-strip agent-run-history">
      <summary class="section-title">
        <h3>运行记录</h3>
        <span class="badge">{{ sessions.length }}</span>
      </summary>
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
    </details>

    <details v-if="session" class="agent-session-strip agent-technical-details">
      <summary class="section-title">
        <h3>技术详情与产物</h3>
        <span class="badge">{{ currentJobLabel ? '有底层任务' : `${resultItems.length} 个产物` }}</span>
      </summary>
      <div class="agent-technical-stack">
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
      </div>
    </details>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import OcrCropControls from './OcrCropControls.vue'
import { getAgentOcrPipeline, inferAgentOcrPipelineVersion } from '../agentOcrPipeline.js'
import {
  agentOperationPresentation,
  buildAgentFlowSteps,
  presentAgentQuestionOptions,
  routeLabel as formatRouteLabel,
  sessionPhaseLabel,
  shouldShowAgentOcrWorkbench,
} from '../agentFlowPresentation.js'
import { effectiveTaskStageStatus, taskGlossaryOpenPayload, taskHasCurrentTranslation } from '../glossaryReviewFlow.js'

const props = defineProps({
  url: { type: String, default: '' },
  embeddedSubtitleHint: { type: String, default: 'unknown' },
  embeddedSubtitleGoal: { type: String, default: 'screen_subtitle' },
  sourceLanguage: { type: String, default: 'auto' },
  ocrLanguage: { type: String, default: 'auto' },
  ocrScope: { type: String, default: 'bottom' },
  ocrPipelineVersion: { type: String, default: 'v3' },
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
  'update:ocrPipelineVersion',
  'update:ocrCropTopRatio',
  'update:ocrCropBottomRatio',
  'update:ocrCropLeftRatio',
  'update:ocrCropRightRatio',
  'update:ocrExcludeEnabled',
  'update:ocrExcludeTopRatio',
  'update:ocrExcludeBottomRatio',
  'update:ocrExcludeLeftRatio',
  'update:ocrExcludeRightRatio',
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
const activeOcrPipeline = computed(() => getAgentOcrPipeline(props.ocrPipelineVersion))
const effectiveOcrScope = computed(() => ['v2', 'v3'].includes(props.ocrPipelineVersion) ? 'bottom' : props.ocrScope)
const currentSessionOcrPipelineVersion = computed(() => inferAgentOcrPipelineVersion(props.session?.payload || {}))
const currentSessionOcrPipeline = computed(() => getAgentOcrPipeline(currentSessionOcrPipelineVersion.value))
const currentSessionOcrScope = computed(() => (
  ['v2', 'v3'].includes(currentSessionOcrPipelineVersion.value)
    ? 'bottom'
    : (props.session?.payload?.ocr_scope || props.ocrScope)
))

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

const primaryActions = ['use_recommended', 'start_hybrid_anchor_ocr', 'use_cached_ocr', 'download_video_for_preview', 'run_ocr', 'run_asr', 'run_asr_with_ocr', 'probe_audio_language']
const isGlossaryQuestion = computed(() => props.session?.phase === 'review_glossary' || props.session?.question?.kind === 'review_glossary')
const questionOptions = computed(() => presentAgentQuestionOptions(props.session))
const operationStatus = computed(() => agentOperationPresentation(props.session))
const showOcrWorkbench = computed(() => shouldShowAgentOcrWorkbench(props.session, props.inputVideo))

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
    asr_done: 'ASR 原文已完成',
    asr_ocr_done: 'ASR + OCR 原文已完成',
    glossary_review: '等待 glossary 审核',
    done: '已完成',
    ocr_rerun: '正在重跑 OCR',
    glossary_rerun: '正在重跑 Glossary',
    translate_rerun: '正在重跑翻译',
    ocr_failed: 'OCR 失败',
    glossary_failed: 'Glossary 失败',
    translate_failed: '翻译失败',
  }
  return labels[stage] || stage || '未开始'
}

function taskStageDisplayLabel(stage) {
  return stage?.id === 'ocr' ? '原文字幕' : stage?.label
}

function stageStatusLabel(stage, task) {
  const status = resolvedTaskStageStatus(stage, task)
  if (stage?.id === 'glossary' && status === 'done' && stage?.status === 'waiting_review') return '已用于翻译'
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

function resolvedTaskStageStatus(stage, task) {
  if (stage?.id === 'glossary' && stage?.status === 'waiting_review' && taskHasCurrentTranslation(task)) return 'done'
  let status = effectiveTaskStageStatus(stage, task)
  if (stage?.id === 'ocr' && (!status || status === 'pending')) {
    const asrStage = task?.stages?.asr
    if (asrStage?.status) status = asrStage.status
    else if (task?.stages?.glossary?.source_srt) status = 'done'
  }
  return status || 'pending'
}

function taskStageStatusClass(stage, task) {
  return resolvedTaskStageStatus(stage, task)
}

function taskGlossaryActionLabel(task) {
  return taskHasCurrentTranslation(task) ? '查看' : '审核'
}

function taskGlossaryPayload(task, stage) {
  return taskGlossaryOpenPayload(task, stage)
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
  return formatRouteLabel(route)
})

const steps = computed(() => buildAgentFlowSteps(props.session?.phase || 'created', props.session?.status || ''))

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
