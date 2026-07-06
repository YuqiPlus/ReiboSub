<template>
  <div class="app-frame">
    <SideNav :active-view="activeView" :items="navItems" @select="activeView = $event" />

    <div class="app-content">
      <HeaderBar
        :title="activePage.title"
        :description="activePage.description"
        :metrics="topbarMetrics"
      />

      <main class="workspace">
        <section class="workspace-main">
          <div v-if="activeView === 'agent'" class="page-stack">
            <AgentSessionPanel
              v-model:url="url"
              v-model:embedded-subtitle-hint="embeddedSubtitleHint"
              v-model:source-language="sourceLanguage"
              v-model:ocr-language="ocrLanguage"
              v-model:ocr-scope="ocrScope"
              v-model:ocr-crop-top-ratio="ocrCropTopRatio"
              v-model:ocr-crop-bottom-ratio="ocrCropBottomRatio"
              v-model:ocr-crop-left-ratio="ocrCropLeftRatio"
              v-model:ocr-crop-right-ratio="ocrCropRightRatio"
              :input-video="agentPreviewVideo"
              v-model:ocr-refinement-mode="ocrRefinementMode"
              v-model:extra-hint="extraHint"
              :session="agentSession"
              :sessions="agentSessions"
              :tasks="agentTasks"
              :starting="agentStarting"
              :status="agentStatus.text"
              :status-class="agentStatus.class"
              @start-agent="startAgent"
              @answer-agent="answerAgent"
              @cancel-agent="cancelAgent"
              @retry-agent="retryAgent"
              @select-agent="selectAgentSession"
              @continue-task="continueAgentTask"
              @rerun-task="rerunAgentTask"
              @complete-task="completeAgentTask"
              @reopen-task="reopenAgentTask"
              @delete-task="deleteAgentTask"
              @open-glossary="openGlossaryFromAgent"
            />
          </div>

          <div v-else-if="activeView === 'new-task'" class="page-stack">
            <VideoInputPanel
              v-model:url="url"
              v-model:ocr-translation-mode="ocrTranslationMode"
              v-model:source-language="sourceLanguage"
              v-model:ocr-language="ocrLanguage"
              v-model:ocr-scope="ocrScope"
              v-model:ocr-crop-top-ratio="ocrCropTopRatio"
              v-model:ocr-crop-bottom-ratio="ocrCropBottomRatio"
              v-model:ocr-crop-left-ratio="ocrCropLeftRatio"
              v-model:ocr-crop-right-ratio="ocrCropRightRatio"
              :input-video="localVideo"
              v-model:ocr-refinement-mode="ocrRefinementMode"
              v-model:embedded-subtitle-hint="embeddedSubtitleHint"
              v-model:thumbnail-format="thumbnailFormat"
              v-model:video-quality="videoQuality"
              :probing="probing"
              :status="probeStatus.text"
              :status-class="probeStatus.class"
              @probe="probeVideo"
              @download-video="downloadVideo"
              @download-thumbnail="downloadThumbnail"
              @ocr-full="runOcrFull"
            />

            <VideoInfoPanel
              v-model:title-box="titleBox"
              :probe="probe"
              :title-status="titleStatus.text"
              :title-status-class="titleStatus.class"
              @download-subtitle="downloadSubtitle"
              @copy-title="copyTitle"
              @append-title-hint="appendTitleHint"
              @agent-ocr-full="runOcrFull"
              @agent-download-video="downloadVideo"
              @use-project="useProject"
            />
          </div>

          <div v-else-if="activeView === 'assets'" class="page-stack">
            <AssetLibrary
              v-model:local-video="localVideo"
              v-model:audio-language="audioLanguage"
              v-model:audio-model-size="audioModelSize"
              :assets="assets"
              :status="assetStatus.text"
              :status-class="assetStatus.class"
              @refresh="loadAssets"
              @local-ocr="runLocalOcr"
              @local-audio="runLocalAudio"
              @register-local-project="registerLocalProject"
              @use-project="useProject"
              @use-video="useVideo"
              @use-video-ocr="useVideoAndOcr"
              @use-subtitle="useSubtitle"
              @edit-subtitle="editSubtitle"
              @delete-project="deleteDownloadProject"
            />
          </div>

          <div v-else-if="activeView === 'video-overlay'" class="page-stack">
            <section class="panel overlay-page-intro">
              <div>
                <h2>当前视频</h2>
                <p class="panel-subtitle">从素材里点“选为视频”会直接进入这里，也可以手动改路径。</p>
              </div>
              <div class="path-row">
                <input v-model="localVideo" placeholder="选择或填写要处理的视频路径" />
                <button class="secondary" type="button" @click="activeView = 'assets'">回素材库</button>
              </div>
            </section>
            <VideoOverlayPanel :input-video="localVideo" @run="runVideoOverlay" />
          </div>

          <div v-else-if="activeView === 'subtitles'" class="page-stack">
            <TranslationFlow
              v-model:source-srt="sourceSrt"
              v-model:glossary-path="glossaryPath"
              v-model:extra-hint="extraHint"
              v-model:subtitle-translation-mode="subtitleTranslationMode"
              v-model:subtitle-convert-format="subtitleConvertFormat"
              v-model:source-language="sourceLanguage"
              :status="flowStatus.text"
              :status-class="flowStatus.class"
              @correct-asr="correctAsrSubtitle"
              @generate-glossary="generateGlossary"
              @load-glossary="loadGlossary"
              @translate-subtitle="translateSubtitle"
              @convert-subtitle="convertSubtitle"
            />
          </div>

          <div v-else-if="activeView === 'subtitle-edit'" class="page-stack">
            <SubtitleEditorPanel
              v-model:subtitle-path="subtitleEditorPath"
              :cues="subtitleEditorCues"
              :loading="subtitleEditorLoading"
              :dirty="subtitleEditorDirty"
              :status="subtitleEditorStatus.text"
              :status-class="subtitleEditorStatus.class"
              :prefix-names="subtitlePrefixNames"
              :pair-issues="subtitlePairIssues"
              :focused-cue-uid="subtitleFocusedCueUid"
              :can-undo="subtitleEditorUndoStack.length > 0"
              @update:prefix-names="subtitlePrefixNames = $event"
              @load-subtitle="loadSubtitleEditor"
              @save-subtitle="saveSubtitleEditor(true)"
              @save-subtitle-as="saveSubtitleEditor(false)"
              @update-cue="updateSubtitleEditorCue"
              @delete-cue="deleteSubtitleEditorCue"
              @merge-prev="mergeSubtitleEditorCue($event, 'prev')"
              @merge-next="mergeSubtitleEditorCue($event, 'next')"
              @strip-breaks="stripSubtitleEditorBreaks"
              @strip-all-breaks="stripAllSubtitleEditorBreaks"
              @strip-trailing-commas="stripSubtitleEditorTrailingCommas"
              @detect-pair-issues="detectSubtitleEditorPairIssues"
              @focus-pair-issue="focusSubtitleEditorCue"
              @copy-pair-symbol="copySubtitleEditorPairSymbol"
              @resolve-pair-issue="resolveSubtitleEditorPairIssue"
              @remove-empty="removeEmptySubtitleEditorCues"
              @strip-prefixes="stripSubtitleEditorPrefixes"
              @undo="undoSubtitleEditorChange"
            />
          </div>

          <div v-else-if="activeView === 'glossary'" class="page-stack">
            <GlossaryReviewPanel
              v-model:glossary-path="glossaryPath"
              v-model:glossary-editor="glossaryEditor"
              :glossary-items="glossaryItems"
              :loading="glossaryLoading"
              :status="flowStatus.text"
              :status-class="flowStatus.class"
              @load-glossary="loadGlossary"
              @apply-all-suggestions="applyAllSuggestions"
              @save-glossary-review="saveGlossaryReview"
              @save-glossary-text="saveGlossaryText"
              @update-glossary-zh="updateGlossaryZh"
              @set-glossary-reviewed="setGlossaryReviewed"
              @use-suggestion="useSuggestion"
            />
          </div>

          <div v-else class="page-stack">
            <section class="panel hero-panel">
              <div>
                <h2>任务日志</h2>
                <p class="panel-subtitle">右侧任务抽屉会保持显示当前任务、历史任务、失败原因和输出路径。</p>
              </div>
              <div class="summary-grid">
                <div class="metric"><b>{{ runningJobCount }}</b><span>运行中</span></div>
                <div class="metric"><b>{{ failedJobCount }}</b><span>失败</span></div>
                <div class="metric"><b>{{ doneJobCount }}</b><span>完成</span></div>
              </div>
            </section>
          </div>
        </section>

        <JobSidebar
          class="task-drawer"
          :jobs="jobs"
          :active-job-id="activeJobId"
          @select-job="activeJobId = $event"
          @cancel-job="cancelJob"
          @clear-log="activeJobId = ''"
        />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api, getJson } from './api'
import SideNav from './components/SideNav.vue'
import HeaderBar from './components/HeaderBar.vue'
import AgentSessionPanel from './components/AgentSessionPanel.vue'
import VideoInputPanel from './components/VideoInputPanel.vue'
import VideoInfoPanel from './components/VideoInfoPanel.vue'
import TranslationFlow from './components/TranslationFlow.vue'
import GlossaryReviewPanel from './components/GlossaryReviewPanel.vue'
import SubtitleEditorPanel from './components/SubtitleEditorPanel.vue'
import AssetLibrary from './components/AssetLibrary.vue'
import VideoOverlayPanel from './components/VideoOverlayPanel.vue'
import JobSidebar from './components/JobSidebar.vue'
import { copyText } from './clipboard.js'
import { createAgentSessionPoller } from './agentSessionPolling.js'
import { detectCuePairSymbolIssues, parsePrefixNames, stripCueSpeakerPrefixes, stripCueTrailingCommas } from './subtitlePrefixTools.js'

const url = ref('')
const probe = ref(null)
const probing = ref(false)
const titleBox = ref('')
const sourceSrt = ref('')
const subtitleEditorPath = ref('')
const subtitleEditorCues = ref([])
const subtitlePrefixNames = ref('')
const subtitlePairIssues = ref([])
const subtitleFocusedCueUid = ref('')
const subtitleEditorUndoStack = ref([])
const subtitleEditorLoading = ref(false)
const subtitleEditorDirty = ref(false)
const glossaryPath = ref('')
const extraHint = ref('')
const glossaryEditor = ref('')
const glossaryItems = ref([])
const glossaryLoading = ref(false)
const subtitleTranslationMode = ref('translate_only')
const subtitleConvertFormat = ref('bcc')
const ocrTranslationMode = ref('standard_cleanup')
const ocrScope = ref('bottom')
const ocrCropTopRatio = ref(0.58)
const ocrCropBottomRatio = ref(0)
const ocrCropLeftRatio = ref(0)
const ocrCropRightRatio = ref(0)
const ocrRefinementMode = ref('none')
const thumbnailFormat = ref('jpg')
const videoQuality = ref('1080p')
const embeddedSubtitleHint = ref('unknown')
const sourceLanguage = ref('auto')
const ocrLanguage = ref('auto')
const localVideo = ref('')
const audioLanguage = ref('auto')
const audioModelSize = ref('large-v3')
const activeJobId = ref('')
const activeView = ref('agent')
const agentSession = ref(null)
const agentSessions = ref([])
const agentTasks = ref([])
const agentStarting = ref(false)

const assets = reactive({ videos: [], subtitles: [], projects: [], ocr_jobs: [] })
const jobs = reactive({})
const pollTimers = new Map()

const probeStatus = reactive({ text: '', class: '' })
const titleStatus = reactive({ text: '', class: '' })
const flowStatus = reactive({ text: '', class: '' })
const subtitleEditorStatus = reactive({ text: '', class: '' })
const assetStatus = reactive({ text: '', class: '' })
const agentStatus = reactive({ text: '', class: '' })

const pages = {
  agent: {
    title: 'Agent Cockpit',
    description: '输入链接，确认路线，审核术语，交付字幕。',
  },
  'new-task': {
    title: '链接工具',
    description: '手动检测字幕、下载视频或进入 OCR 全流程。',
  },
  assets: {
    title: '素材',
    description: '管理已下载视频、字幕文件、OCR 和音频识别输出。',
  },
  'video-overlay': {
    title: '贴图处理',
    description: '给当前视频叠加水印或遮 Logo，输出新视频。',
  },
  subtitles: {
    title: '字幕工具',
    description: '选择源字幕，生成 glossary，翻译为中文外挂字幕。',
  },
  'subtitle-edit': {
    title: '字幕精修',
    description: '逐条修改、合并、删除已生成字幕。',
  },
  glossary: {
    title: '审核',
    description: '集中审核人名、昵称、作品名和固定术语。',
  },
  jobs: {
    title: '任务日志',
    description: '查看运行状态、失败原因、输出路径，并终止误点任务。',
  },
}

const OCR_SCOPE_TOP_DEFAULTS = { bottom: 0.58, expanded: 0.38, smart_full: 0.58 }
const activePage = computed(() => pages[activeView.value] || pages['new-task'])
const jobList = computed(() => Object.values(jobs))
const runningJobCount = computed(() => jobList.value.filter((job) => ['running', 'cancel_requested'].includes(job.status)).length)
const failedJobCount = computed(() => jobList.value.filter((job) => job.status === 'failed').length)
const doneJobCount = computed(() => jobList.value.filter((job) => job.status === 'done').length)
const waitingAgentCount = computed(() => agentSessions.value.filter((session) => session.status === 'waiting').length)
const runningAgentCount = computed(() => agentSessions.value.filter((session) => session.status === 'running').length)
const topbarMetrics = computed(() => ({
  videos: assets.videos.length,
  subtitles: assets.subtitles.length,
  jobs: jobList.value.length,
}))
const agentPreviewVideo = computed(() => agentSession.value?.result?.input_video || localVideo.value || '')

watch(ocrScope, (scope) => {
  ocrCropTopRatio.value = OCR_SCOPE_TOP_DEFAULTS[scope] ?? 0.58
  ocrCropBottomRatio.value = 0
})

const navItems = computed(() => [
  { id: 'agent', label: 'Agent', hint: '自动编排', icon: 'A', badge: waitingAgentCount.value ? `${waitingAgentCount.value} 待确认` : runningAgentCount.value || '' },
  { id: 'assets', label: '素材', hint: '视频与字幕', icon: 'M', badge: assets.videos.length + assets.subtitles.length || '' },
  { id: 'video-overlay', label: '贴图', hint: '水印与遮 Logo', icon: 'V', badge: localVideo.value ? '已选' : '' },
  { id: 'glossary', label: '审核', hint: 'Glossary', icon: 'G', badge: glossaryItems.value.length || '' },
  { id: 'subtitles', label: '字幕工具', hint: '翻译与转换', icon: 'S', badge: sourceSrt.value ? '已选' : '' },
  { id: 'subtitle-edit', label: '精修', hint: '编辑 SRT', icon: 'E', badge: subtitleEditorCues.value.length || '' },
  { id: 'new-task', label: '链接工具', hint: '检测与下载', icon: 'L', badge: probe.value?.subtitles?.length || '' },
  { id: 'jobs', label: '任务', hint: '日志与输出', icon: 'J', badge: runningJobCount.value || failedJobCount.value || '' },
])

onMounted(() => {
  loadAssets()
  loadJobs()
  loadAgentSessions()
  loadAgentTasks()
})

onUnmounted(() => {
  agentPoller.cancelAll()
})

async function startAgent() {
  if (!url.value.trim()) {
    setStatus(agentStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  agentStarting.value = true
  setStatus(agentStatus, 'Agent 正在启动...', '')
  try {
    const session = await api('/api/agent/start', {
      url: url.value.trim(),
      embedded_subtitle_hint: embeddedSubtitleHint.value,
      source_language: sourceLanguage.value,
      ocr_language: ocrLanguage.value,
      target_language: 'zh',
      extra_hint: extraHint.value,
      ocr_translation_mode: ocrTranslationMode.value,
      ocr_scope: ocrScope.value,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_refinement_mode: ocrRefinementMode.value,
    })
    agentSession.value = session
    await loadAgentSessions()
    await loadAgentTasks()
    setStatus(agentStatus, 'Agent 已启动。', 'ok')
    scheduleAgentPoll(session.id, 500)
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  } finally {
    agentStarting.value = false
  }
}

async function answerAgent(action) {
  if (!agentSession.value?.id) return
  setStatus(agentStatus, '已提交回答，Agent 继续处理...', '')
  try {
    const session = await api(`/api/agent/${agentSession.value.id}/answer`, {
      action,
      ocr_scope: ocrScope.value,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      source_language: sourceLanguage.value,
      ocr_language: ocrLanguage.value,
    })
    agentSession.value = session
    await loadAgentSessions()
    await loadAgentTasks()
    scheduleAgentPoll(session.id, 500)
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  }
}

async function cancelAgent() {
  if (!agentSession.value?.id) return
  try {
    const session = await api(`/api/agent/${agentSession.value.id}/cancel`, {})
    agentSession.value = session
    await loadAgentSessions()
    await loadAgentTasks()
    setStatus(agentStatus, '已请求中断 Agent 任务。', 'bad')
    await loadJobs()
  } catch (error) {
    setStatus(agentStatus, `中断失败：${error.message}`, 'bad')
  }
}

async function retryAgent() {
  if (!agentSession.value?.id) return
  setStatus(agentStatus, '正在重试当前 Agent 阶段...', '')
  try {
    const session = await api(`/api/agent/${agentSession.value.id}/retry`, {})
    agentSession.value = session
    await loadAgentSessions()
    await loadAgentTasks()
    scheduleAgentPoll(session.id, 500)
  } catch (error) {
    setStatus(agentStatus, `重试失败：${error.message}`, 'bad')
  }
}

const agentPoller = createAgentSessionPoller({
  setTimeout: window.setTimeout.bind(window),
  clearTimeout: window.clearTimeout.bind(window),
  poll: (sessionId) => pollAgent(sessionId),
})

function scheduleAgentPoll(sessionId, delay = 1000) {
  agentPoller.schedule(sessionId, delay)
}

function syncAgentSessionPolls() {
  for (const session of agentSessions.value || []) {
    if (session.status === 'running') {
      if (!agentPoller.has(session.id)) scheduleAgentPoll(session.id, 1000)
    } else {
      agentPoller.cancel(session.id)
    }
  }
}

function isSelectedAgentSession(sessionId) {
  return !agentSession.value?.id || agentSession.value.id === sessionId
}

async function pollAgent(sessionId) {
  try {
    const session = await getJson(`/api/agent/${sessionId}`)
    const selected = isSelectedAgentSession(sessionId)
    if (selected) {
      agentSession.value = session
      if (session.result?.source_srt) sourceSrt.value = session.result.source_srt
      if (session.result?.translated_srt) setStatus(agentStatus, `Agent 完成：${session.result.translated_srt}`, 'ok')
    }
    await loadAgentSessions()
    await loadAgentTasks()
    if (session.status === 'running') {
      scheduleAgentPoll(sessionId, 1000)
      return
    }
    agentPoller.cancel(sessionId)
    if (session.status === 'waiting') {
      if (selected) setStatus(agentStatus, 'Agent 等待你的确认。', '')
      return
    }
    if (session.status === 'failed') {
      if (selected) setStatus(agentStatus, session.error || 'Agent 失败。', 'bad')
      return
    }
    if (session.status === 'done') {
      if (selected) setStatus(agentStatus, 'Agent 已完成。', 'ok')
      loadAssets()
      await loadAgentSessions()
      await loadAgentTasks()
    }
  } catch (error) {
    if (isSelectedAgentSession(sessionId)) setStatus(agentStatus, error.message, 'bad')
    scheduleAgentPoll(sessionId, 2000)
  }
}

async function loadAgentSessions() {
  try {
    const result = await getJson('/api/agent')
    agentSessions.value = result.sessions || []
    syncAgentSessionPolls()
  } catch {
    agentSessions.value = agentSessions.value || []
  }
}

async function loadAgentTasks() {
  try {
    const result = await getJson('/api/agent-tasks')
    agentTasks.value = result.tasks || []
  } catch {
    agentTasks.value = agentTasks.value || []
  }
}

async function selectAgentSession(sessionId) {
  try {
    const session = await getJson(`/api/agent/${sessionId}`)
    agentSession.value = session
    setStatus(agentStatus, `已切换到 Agent 任务：${session.id}`, '')
    if (session.status === 'running') scheduleAgentPoll(session.id, 500)
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  }
}

async function continueAgentTask(taskId) {
  setStatus(agentStatus, '正在从视频任务继续...', '')
  try {
    const session = await api(`/api/agent-tasks/${taskId}/continue`, {})
    agentSession.value = session
    await loadAgentSessions()
    await loadAgentTasks()
    scheduleAgentPoll(session.id, 500)
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  }
}

async function rerunAgentTask({ taskId, stage }) {
  setStatus(agentStatus, `正在重跑 ${stage} 阶段...`, '')
  try {
    const session = await api(`/api/agent-tasks/${taskId}/rerun`, { stage })
    agentSession.value = session
    await loadAgentSessions()
    await loadAgentTasks()
    scheduleAgentPoll(session.id, 500)
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  }
}

async function completeAgentTask(task) {
  const taskId = typeof task === 'string' ? task : task?.id
  if (!taskId) return
  const title = typeof task === 'object' ? (task.title || task.id) : taskId
  try {
    await api(`/api/agent-tasks/${taskId}/complete`, {})
    await loadAgentTasks()
    setStatus(agentStatus, `已完成流程：${title}`, 'ok')
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  }
}

async function reopenAgentTask(task) {
  const taskId = typeof task === 'string' ? task : task?.id
  if (!taskId) return
  const title = typeof task === 'object' ? (task.title || task.id) : taskId
  try {
    await api(`/api/agent-tasks/${taskId}/reopen`, {})
    await loadAgentTasks()
    setStatus(agentStatus, `已恢复流程：${title}`, 'ok')
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  }
}

async function deleteAgentTask(task) {
  const taskId = typeof task === 'string' ? task : task?.id
  if (!taskId) return
  const title = typeof task === 'object' ? (task.title || task.id) : taskId
  if (!window.confirm(`删除任务档案：${title}？\n\n只删除任务状态和任务目录，不会删除已下载视频。`)) return
  try {
    await api(`/api/agent-tasks/${taskId}/delete`, {})
    if (agentSession.value?.result?.task_id === taskId) agentSession.value = null
    await loadAgentTasks()
    await loadAgentSessions()
    setStatus(agentStatus, `已删除任务：${title}`, 'ok')
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
  }
}

async function openGlossaryFromAgent(payload) {
  const path = typeof payload === 'string' ? payload : payload?.path
  const sessionId = typeof payload === 'object' ? payload?.sessionId : ''
  if (sessionId) await selectAgentSession(sessionId)
  glossaryPath.value = path || ''
  activeView.value = 'glossary'
  await loadGlossary()
}

async function probeVideo() {
  if (!url.value.trim()) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  probing.value = true
  setStatus(probeStatus, '正在检测字幕...', '')
  try {
    probe.value = await api('/api/probe', {
      url: url.value.trim(),
      embedded_subtitle_hint: embeddedSubtitleHint.value,
      source_language: sourceLanguage.value,
      target_language: 'zh',
    })
    if (probe.value.existing_project) {
      useProject(probe.value.existing_project)
      setStatus(probeStatus, `检测完成：${probe.value.subtitles?.length || 0} 条字幕轨道；已绑定本地项目：${probe.value.existing_project.name}`, 'ok')
    } else {
      setStatus(probeStatus, `检测完成：${probe.value.subtitles?.length || 0} 条字幕轨道。`, 'ok')
    }
    if (probe.value.title) {
      translateTitle(probe.value.title)
    }
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  } finally {
    probing.value = false
  }
}

async function translateTitle(title) {
  setStatus(titleStatus, '正在盲翻标题...', '')
  try {
    const result = await api('/api/translate-title', { title })
    titleBox.value = result.zh_title || ''
    setStatus(titleStatus, titleBox.value ? '标题已翻译，可复制或填入任务提示。' : '标题翻译为空。', titleBox.value ? 'ok' : 'bad')
  } catch (error) {
    setStatus(titleStatus, error.message, 'bad')
  }
}

async function downloadSubtitle(item) {
  if (!probe.value?.webpage_url) {
    setStatus(probeStatus, '没有可下载的视频 URL。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/download-subtitle', {
      url: probe.value.webpage_url,
      lang: item.lang,
      kind: item.kind,
    })
    watchJob(job)
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  }
}

async function downloadVideo() {
  const value = (probe.value?.webpage_url || url.value).trim()
  if (!value) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/download-video', { url: value, thumbnail_format: thumbnailFormat.value, quality: videoQuality.value })
    watchJob(job)
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  }
}

async function downloadThumbnail() {
  const value = (probe.value?.webpage_url || url.value).trim()
  if (!value) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/download-thumbnail', {
      url: value,
      title: probe.value?.title || titleBox.value || '',
      format: thumbnailFormat.value,
    })
    watchJob(job)
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  }
}

async function runOcrFull() {
  const value = (probe.value?.webpage_url || url.value).trim()
  if (!value) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/ocr-full', {
      url: value,
      title: probe.value?.title || titleBox.value || '',
      extra_hint: extraHint.value,
      translation_mode: ocrTranslationMode.value,
      ocr_scope: ocrScope.value,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_refinement_mode: ocrRefinementMode.value,
      source_language: sourceLanguage.value,
      ocr_language: ocrLanguage.value,
    })
    watchJob(job)
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  }
}

async function runLocalOcr() {
  if (!localVideo.value.trim()) {
    setStatus(assetStatus, '先选择本地视频。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/ocr-local', {
      input_video: localVideo.value.trim(),
      extra_hint: extraHint.value,
      translation_mode: ocrTranslationMode.value,
      ocr_scope: ocrScope.value,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_refinement_mode: ocrRefinementMode.value,
      source_language: sourceLanguage.value,
      ocr_language: ocrLanguage.value,
    })
    watchJob(job)
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function runLocalAudio() {
  if (!localVideo.value.trim()) {
    setStatus(assetStatus, '先选择本地视频。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/audio-local', {
      input_video: localVideo.value.trim(),
      language: audioLanguage.value,
      source_language: sourceLanguage.value,
      model_size: audioModelSize.value,
      device: 'cuda',
      compute_type: 'float16',
    })
    watchJob(job)
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function runVideoOverlay(payload) {
  if (!payload?.input_video) {
    setStatus(assetStatus, '先选择本地视频。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/video-overlay', payload)
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(assetStatus, '已创建视频贴图处理任务。', 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function registerLocalProject() {
  if (!localVideo.value.trim()) {
    setStatus(assetStatus, '先选择或填写一个本地视频路径。', 'bad')
    return
  }
  try {
    const result = await api('/api/assets/register-local-project', {
      input_video: localVideo.value.trim(),
      title: localVideo.value.split('/').pop()?.replace(/\.[^.]+$/, '') || '',
    })
    await loadAssets()
    setStatus(assetStatus, `已登记视频项目：${result.project?.name || result.project_dir}`, 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function generateGlossary() {
  if (!sourceSrt.value.trim()) {
    setStatus(flowStatus, '先选择源字幕。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/generate-glossary', {
      source_srt: sourceSrt.value.trim(),
      source_language: sourceLanguage.value,
      extra_hint: extraHint.value,
    })
    watchJob(job)
    activeView.value = 'jobs'
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  }
}

async function correctAsrSubtitle() {
  if (!sourceSrt.value.trim()) {
    setStatus(flowStatus, '先选择 ASR 生成的源字幕。', 'bad')
    return
  }
  try {
    const payload = {
      source_srt: sourceSrt.value.trim(),
      glossary: glossaryPath.value.trim(),
      source_language: sourceLanguage.value,
      extra_hint: extraHint.value,
    }
    const job = await api('/api/jobs/correct-asr-subtitle', payload)
    watchJob(job)
    activeView.value = 'jobs'
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  }
}

async function loadGlossary() {
  if (!glossaryPath.value.trim()) {
    setStatus(flowStatus, '先填写 glossary 路径。', 'bad')
    return
  }
  activeView.value = 'glossary'
  glossaryLoading.value = true
  glossaryItems.value = []
  setStatus(flowStatus, '正在加载 glossary，并生成盲翻候选...', '')
  try {
    const [text, review] = await Promise.all([
      api('/api/read-text', { path: glossaryPath.value.trim() }),
      api('/api/read-glossary-items', { path: glossaryPath.value.trim(), include_blind_candidates: true }),
    ])
    glossaryEditor.value = text.content || ''
    glossaryItems.value = review.items || []
    setStatus(flowStatus, `已加载 ${glossaryItems.value.length} 条 glossary。`, 'ok')
    activeView.value = 'glossary'
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  } finally {
    glossaryLoading.value = false
  }
}

async function saveGlossaryReview() {
  if (!glossaryPath.value.trim()) {
    setStatus(flowStatus, '先填写 glossary 路径。', 'bad')
    return
  }
  try {
    const result = await api('/api/write-glossary-items', {
      path: glossaryPath.value.trim(),
      items: glossaryItems.value,
    })
    glossaryEditor.value = result.content || glossaryEditor.value
    glossaryItems.value = result.items || glossaryItems.value
    await continueAfterGlossarySave()
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  }
}

async function saveGlossaryText() {
  if (!glossaryPath.value.trim()) {
    setStatus(flowStatus, '先填写 glossary 路径。', 'bad')
    return
  }
  try {
    await api('/api/write-text', {
      path: glossaryPath.value.trim(),
      content: glossaryEditor.value,
    })
    await loadGlossary()
    await continueAfterGlossarySave()
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  }
}

async function continueAfterGlossarySave() {
  const path = glossaryPath.value.trim()
  if (!path) return false
  try {
    setStatus(flowStatus, 'Glossary 已保存，正在让 Agent 继续处理...', '')
    const session = await api('/api/agent/continue-glossary', { glossary_path: path })
    agentSession.value = session
    activeView.value = 'agent'
    setStatus(agentStatus, 'Glossary 已保存，Agent 继续处理翻译...', 'ok')
    await loadAgentSessions()
    await loadAgentTasks()
    scheduleAgentPoll(session.id, 500)
    return true
  } catch (error) {
    setStatus(flowStatus, `Glossary 已保存；没有匹配到可继续的 Agent 流程：${error.message}`, 'ok')
    return false
  }
}

async function translateSubtitle() {
  if (!sourceSrt.value.trim()) {
    setStatus(flowStatus, '先选择源字幕。', 'bad')
    return
  }
  try {
    const payload = {
      source_srt: sourceSrt.value.trim(),
      glossary: glossaryPath.value.trim(),
      translation_mode: subtitleTranslationMode.value,
      source_language: sourceLanguage.value,
    }
    const job = await api('/api/jobs/translate-subtitle', payload)
    watchJob(job)
    activeView.value = 'jobs'
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  }
}

async function convertSubtitle() {
  if (!sourceSrt.value.trim()) {
    setStatus(flowStatus, '先选择要转换的字幕。', 'bad')
    return
  }
  try {
    const job = await api('/api/jobs/convert-subtitle', {
      source: sourceSrt.value.trim(),
      format: subtitleConvertFormat.value,
    })
    watchJob(job)
    activeView.value = 'jobs'
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  }
}

async function loadAssets() {
  setStatus(assetStatus, '正在扫描本地素材...', '')
  try {
    const result = await getJson('/api/assets')
    assets.videos = result.videos || []
    assets.subtitles = result.subtitles || []
    assets.projects = result.projects || []
    assets.ocr_jobs = result.ocr_jobs || []
    setStatus(assetStatus, `已扫描：${assets.projects.length} 个项目，${assets.videos.length} 个视频，${assets.subtitles.length} 个字幕。`, 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function deleteDownloadProject(project) {
  if (!project?.path) return
  if (!window.confirm(`删除已下载视频项目目录：${project.name || project.path}？\n\n会删除该目录下的视频、字幕、封面和其他文件。`)) return
  try {
    await api('/api/assets/delete-project', { path: project.path })
    if (localVideo.value && localVideo.value.startsWith(project.path)) localVideo.value = ''
    if (sourceSrt.value && sourceSrt.value.startsWith(project.path)) sourceSrt.value = ''
    await loadAssets()
    setStatus(assetStatus, `已删除视频项目目录：${project.name}`, 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function loadJobs() {
  try {
    const result = await getJson('/api/jobs')
    const loadedJobs = result.jobs || []
    for (const job of loadedJobs) {
      jobs[job.id] = job
      if (['running', 'cancel_requested'].includes(job.status)) {
        schedulePoll(job.id, 1000)
      }
    }
    if (!activeJobId.value && loadedJobs.length) {
      const runningJob = loadedJobs.find((job) => ['running', 'cancel_requested'].includes(job.status))
      activeJobId.value = (runningJob || loadedJobs[0]).id
    }
  } catch (error) {
    setStatus(flowStatus, `任务列表加载失败：${error.message}`, 'bad')
  }
}

async function cancelJob(jobId) {
  try {
    const job = await api(`/api/jobs/${jobId}/cancel`, {})
    jobs[job.id] = job
    if (['running', 'cancel_requested'].includes(job.status)) {
      schedulePoll(job.id, 1000)
    }
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
  }
}

function watchJob(job) {
  jobs[job.id] = job
  activeJobId.value = job.id
  schedulePoll(job.id, 250)
}

function schedulePoll(jobId, delay) {
  if (pollTimers.has(jobId)) {
    clearTimeout(pollTimers.get(jobId))
  }
  const timer = setTimeout(() => pollJob(jobId), delay)
  pollTimers.set(jobId, timer)
}

async function pollJob(jobId) {
  try {
    const job = await getJson(`/api/jobs/${jobId}`)
    jobs[job.id] = job
    if (['running', 'cancel_requested'].includes(job.status)) {
      schedulePoll(job.id, 1000)
      return
    }
    pollTimers.delete(job.id)
    applyJobResult(job)
    if (job.status === 'done') {
      loadAssets()
    }
  } catch (error) {
    const existing = jobs[jobId]
    if (existing && ['running', 'cancel_requested'].includes(existing.status)) {
      jobs[jobId] = {
        ...existing,
        logs: [
          ...(existing.logs || []),
          `poll_error: ${error.message}`,
          'poll_retry: 2秒后继续刷新任务状态',
        ].slice(-500),
        updated_at: Date.now() / 1000,
      }
      setStatus(flowStatus, `任务状态刷新失败，正在重试：${error.message}`, 'bad')
      schedulePoll(jobId, 2000)
      return
    }
    setStatus(flowStatus, error.message, 'bad')
  }
}

function applyJobResult(job) {
  const result = job.result || {}
  if (result.subtitle_path) sourceSrt.value = result.subtitle_path
  if (result.source_srt) sourceSrt.value = result.source_srt
  if (result.input_video) localVideo.value = result.input_video
  if (result.output_video) {
    localVideo.value = result.output_video
    setStatus(assetStatus, `视频贴图处理完成：${result.output_video}`, 'ok')
  }
  if (result.glossary_path) {
    if (activeView.value !== 'glossary' || !glossaryPath.value.trim() || glossaryPath.value === result.glossary_path) {
      glossaryPath.value = result.glossary_path
      glossaryEditor.value = result.content || glossaryEditor.value
      loadGlossary()
      activeView.value = 'glossary'
    } else {
      setStatus(flowStatus, `新的 glossary 已生成：${result.glossary_path}。当前审核页未被切换。`, 'ok')
    }
  }
  if (result.translated_srt) {
    setStatus(flowStatus, `翻译完成：${result.translated_srt}`, 'ok')
  }
  if (result.converted_subtitle) {
    sourceSrt.value = result.converted_subtitle
    setStatus(flowStatus, `格式转换完成：${result.converted_subtitle}`, 'ok')
  }
  if (job.status === 'failed') {
    setStatus(flowStatus, job.error || '任务失败。', 'bad')
  }
}

function useProject(project) {
  if (!project) return
  if (project.primary_video) localVideo.value = project.primary_video
  if (project.source_url) url.value = project.normalized_url || project.source_url
  const sourceSubtitle = (project.subtitles || []).find((item) => item.role === 'source') || (project.subtitles || [])[0]
  if (sourceSubtitle?.path) sourceSrt.value = sourceSubtitle.path
  activeView.value = 'assets'
  setStatus(assetStatus, `已载入项目：${project.name}`, 'ok')
}

function useVideo(path) {
  localVideo.value = path
  activeView.value = 'video-overlay'
  setStatus(assetStatus, `已选择视频，进入贴图处理：${path}`, 'ok')
}

function useVideoAndOcr(path) {
  useVideo(path)
  runLocalOcr()
}

function useSubtitle(path) {
  sourceSrt.value = path
  activeView.value = 'subtitles'
  setStatus(flowStatus, `已选择源字幕：${path}`, 'ok')
}

async function editSubtitle(path) {
  subtitleEditorPath.value = path || sourceSrt.value || ''
  activeView.value = 'subtitle-edit'
  if (subtitleEditorPath.value) {
    await loadSubtitleEditor()
  }
}

async function loadSubtitleEditor() {
  if (!subtitleEditorPath.value.trim()) {
    setStatus(subtitleEditorStatus, '先选择或填写字幕路径。', 'bad')
    return
  }
  subtitleEditorLoading.value = true
  setStatus(subtitleEditorStatus, '正在加载字幕...', '')
  try {
    const result = await api('/api/subtitle/read', { path: subtitleEditorPath.value.trim() })
    subtitleEditorPath.value = result.path
    subtitleEditorCues.value = (result.cues || []).map((cue, index) => ({
      ...cue,
      uid: `${Date.now()}-${index}`,
    }))
    subtitleEditorDirty.value = false
    subtitlePairIssues.value = []
    subtitleFocusedCueUid.value = ''
    subtitleEditorUndoStack.value = []
    setStatus(subtitleEditorStatus, `已加载 ${result.count || 0} 条字幕。`, 'ok')
  } catch (error) {
    setStatus(subtitleEditorStatus, error.message, 'bad')
  } finally {
    subtitleEditorLoading.value = false
  }
}

async function saveSubtitleEditor(overwrite) {
  if (!subtitleEditorPath.value.trim()) {
    setStatus(subtitleEditorStatus, '先加载字幕。', 'bad')
    return
  }
  subtitleEditorLoading.value = true
  setStatus(subtitleEditorStatus, overwrite ? '正在覆盖保存字幕...' : '正在另存 edited 字幕...', '')
  try {
    const result = await api('/api/subtitle/write', {
      path: subtitleEditorPath.value.trim(),
      overwrite,
      cues: subtitleEditorCues.value,
    })
    subtitleEditorPath.value = result.path
    sourceSrt.value = result.path
    subtitleEditorCues.value = (result.cues || []).map((cue, index) => ({
      ...cue,
      uid: `${Date.now()}-${index}`,
    }))
    subtitleEditorDirty.value = false
    subtitlePairIssues.value = []
    subtitleFocusedCueUid.value = ''
    subtitleEditorUndoStack.value = []
    setStatus(subtitleEditorStatus, `已保存 ${result.count || 0} 条字幕：${result.path}`, 'ok')
    await loadAssets()
  } catch (error) {
    setStatus(subtitleEditorStatus, error.message, 'bad')
  } finally {
    subtitleEditorLoading.value = false
  }
}

function updateSubtitleEditorCue({ uid, patch }) {
  subtitleEditorCues.value = subtitleEditorCues.value.map((cue) => (
    cue.uid === uid ? { ...cue, ...patch } : cue
  ))
  subtitleEditorDirty.value = true
}

function deleteSubtitleEditorCue(uid) {
  if (!subtitleEditorCues.value.some((cue) => cue.uid === uid)) return
  pushSubtitleEditorUndo('删除字幕')
  subtitleEditorCues.value = subtitleEditorCues.value.filter((cue) => cue.uid !== uid)
  subtitleEditorDirty.value = true
}

function mergeSubtitleEditorCue(uid, direction) {
  const index = subtitleEditorCues.value.findIndex((cue) => cue.uid === uid)
  if (index < 0) return
  const targetIndex = direction === 'prev' ? index - 1 : index + 1
  if (targetIndex < 0 || targetIndex >= subtitleEditorCues.value.length) return
  pushSubtitleEditorUndo('合并字幕')
  const firstIndex = Math.min(index, targetIndex)
  const secondIndex = Math.max(index, targetIndex)
  const first = subtitleEditorCues.value[firstIndex]
  const second = subtitleEditorCues.value[secondIndex]
  const merged = {
    ...first,
    end: second.end,
    end_time: second.end_time,
    text: joinSubtitleText(first.text, second.text),
  }
  const next = [...subtitleEditorCues.value]
  next.splice(firstIndex, 2, merged)
  subtitleEditorCues.value = next
  subtitleEditorDirty.value = true
}

function stripSubtitleEditorBreaks(uid) {
  const target = subtitleEditorCues.value.find((cue) => cue.uid === uid)
  if (!target) return
  const normalized = normalizeSubtitleLine(target.text)
  if (normalized === target.text) return
  pushSubtitleEditorUndo('去换行')
  subtitleEditorCues.value = subtitleEditorCues.value.map((cue) => (
    cue.uid === uid ? { ...cue, text: normalized } : cue
  ))
  subtitleEditorDirty.value = true
}

function stripAllSubtitleEditorBreaks() {
  const next = subtitleEditorCues.value.map((cue) => ({
    ...cue,
    text: normalizeSubtitleLine(cue.text),
  }))
  if (!subtitleCuesChanged(subtitleEditorCues.value, next)) return
  pushSubtitleEditorUndo('全部去异常换行')
  subtitleEditorCues.value = next
  subtitleEditorDirty.value = true
}

function removeEmptySubtitleEditorCues() {
  const next = subtitleEditorCues.value.filter((cue) => String(cue.text || '').trim())
  if (next.length === subtitleEditorCues.value.length) return
  pushSubtitleEditorUndo('删除空字幕')
  subtitleEditorCues.value = next
  subtitleEditorDirty.value = true
}

function stripSubtitleEditorTrailingCommas() {
  const result = stripCueTrailingCommas(subtitleEditorCues.value)
  if (!result.changedCueCount) {
    setStatus(subtitleEditorStatus, '未发现结尾逗号。', '')
    return
  }
  pushSubtitleEditorUndo('删除结尾逗号')
  subtitleEditorCues.value = result.cues
  subtitleEditorDirty.value = true
  setStatus(subtitleEditorStatus, `已处理 ${result.changedCueCount} 条字幕，删除 ${result.removedCommaCount} 个结尾逗号。`, 'ok')
}

function detectSubtitleEditorPairIssues() {
  const issues = detectCuePairSymbolIssues(subtitleEditorCues.value)
  subtitlePairIssues.value = issues
  subtitleFocusedCueUid.value = ''
  if (issues.length) {
    setStatus(subtitleEditorStatus, `检测到 ${issues.length} 处半边符号，请定位后手动修。`, 'bad')
  } else {
    setStatus(subtitleEditorStatus, '未发现半边符号。', 'ok')
  }
}

async function focusSubtitleEditorCue(uid) {
  subtitleFocusedCueUid.value = uid
  await nextTick()
  const selector = `[data-subtitle-textarea="${cssEscape(uid)}"]`
  const textarea = document.querySelector(selector)
  if (textarea) {
    textarea.scrollIntoView({ behavior: 'smooth', block: 'center' })
    textarea.focus()
  }
}

async function copySubtitleEditorPairSymbol(symbol) {
  const ok = await copyText(symbol)
  setStatus(subtitleEditorStatus, ok ? `已复制缺失符号：${symbol}` : '复制失败，请手动输入缺失符号。', ok ? 'ok' : 'bad')
}

function resolveSubtitleEditorPairIssue(issue) {
  const key = pairIssueKey(issue)
  subtitlePairIssues.value = subtitlePairIssues.value.filter((item) => pairIssueKey(item) !== key)
  if (subtitleFocusedCueUid.value === issue.uid) subtitleFocusedCueUid.value = ''
  setStatus(subtitleEditorStatus, subtitlePairIssues.value.length ? `已标记处理，还剩 ${subtitlePairIssues.value.length} 处。` : '半边符号问题已全部标记处理。', 'ok')
}

function pairIssueKey(issue) {
  return `${issue.uid}|${issue.missingSymbol}|${issue.type}`
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(String(value))
  return String(value).replace(/"/g, '\"')
}

function stripSubtitleEditorPrefixes() {
  const names = parsePrefixNames(subtitlePrefixNames.value)
  if (!names.length) {
    setStatus(subtitleEditorStatus, '先输入要删除的名前缀。', 'bad')
    return
  }
  const result = stripCueSpeakerPrefixes(subtitleEditorCues.value, names)
  if (!result.changedCueCount) {
    setStatus(subtitleEditorStatus, `未发现“${names.join(' / ')} + 空格或冒号”的开头前缀。`, '')
    return
  }
  pushSubtitleEditorUndo('删除名前缀')
  subtitleEditorCues.value = result.cues
  subtitleEditorDirty.value = true
  setStatus(subtitleEditorStatus, `已处理 ${result.changedCueCount} 条字幕，删除 ${result.removedPrefixCount} 个名前缀。`, 'ok')
}

function pushSubtitleEditorUndo(label) {
  subtitleEditorUndoStack.value = [
    ...subtitleEditorUndoStack.value,
    { label, cues: cloneSubtitleEditorCues(subtitleEditorCues.value) },
  ].slice(-25)
}

function undoSubtitleEditorChange() {
  const stack = [...subtitleEditorUndoStack.value]
  const snapshot = stack.pop()
  if (!snapshot) return
  subtitleEditorUndoStack.value = stack
  subtitleEditorCues.value = cloneSubtitleEditorCues(snapshot.cues)
  subtitleEditorDirty.value = true
  setStatus(subtitleEditorStatus, `已撤销：${snapshot.label}`, 'ok')
}

function cloneSubtitleEditorCues(cues) {
  return (cues || []).map((cue) => ({ ...cue }))
}

function subtitleCuesChanged(left, right) {
  if (left.length !== right.length) return true
  return left.some((cue, index) => cue.text !== right[index]?.text || cue.start_time !== right[index]?.start_time || cue.end_time !== right[index]?.end_time)
}

function normalizeSubtitleLine(text) {
  return String(text || '').replace(/\s*\n+\s*/g, ' ').replace(/[ \t]{2,}/g, ' ').trim()
}

function joinSubtitleText(left, right) {
  return [normalizeSubtitleLine(left), normalizeSubtitleLine(right)].filter(Boolean).join(' ')
}

function updateGlossaryZh({ index, zh }) {
  glossaryItems.value = glossaryItems.value.map((item, itemIndex) => itemIndex === index ? { ...item, zh } : item)
}

function setGlossaryReviewed({ index, reviewed }) {
  glossaryItems.value = glossaryItems.value.map((item, itemIndex) => itemIndex === index ? { ...item, reviewed } : item)
}

function useSuggestion(index) {
  const item = glossaryItems.value[index]
  if (!item?.suggested_zh) return
  glossaryItems.value = glossaryItems.value.map((entry, itemIndex) => (
    itemIndex === index ? { ...entry, zh: item.suggested_zh, reviewed: true } : entry
  ))
}

function applyAllSuggestions() {
  glossaryItems.value = glossaryItems.value.map((item) => {
    if (!item.zh && item.suggested_zh) {
      return { ...item, zh: item.suggested_zh, reviewed: true }
    }
    return item
  })
}

function appendTitleHint() {
  if (!titleBox.value.trim()) return
  const addition = `视频标题参考：${titleBox.value.trim()}`
  extraHint.value = extraHint.value.trim() ? `${extraHint.value.trim()}\n${addition}` : addition
}

async function copyTitle() {
  if (titleBox.value) {
    await navigator.clipboard?.writeText(titleBox.value)
    setStatus(titleStatus, '中文标题已复制。', 'ok')
  }
}

function setStatus(target, text, className) {
  target.text = text
  target.class = className || ''
}
</script>
