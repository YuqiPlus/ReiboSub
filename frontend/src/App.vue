<template>
  <div class="app-frame">
    <SideNav :active-view="activeView" :items="navItems" @select="activeView = $event" />

    <div class="app-content">
      <HeaderBar
        :title="activePage.title"
        :description="activePage.description"
        :metrics="topbarMetrics"
      />

      <main class="workspace" :class="{ 'workspace-single': activeView !== 'jobs' }">
        <section class="workspace-main">
          <div v-if="activeView === 'agent'" class="page-stack">
            <AgentSessionPanel
              v-model:url="url"
              v-model:embedded-subtitle-hint="embeddedSubtitleHint"
              v-model:embedded-subtitle-goal="embeddedSubtitleGoal"
              v-model:source-language="sourceLanguage"
              v-model:ocr-language="ocrLanguage"
              v-model:ocr-scope="ocrScope"
              v-model:ocr-pipeline-version="agentOcrPipelineVersion"
              v-model:ocr-crop-top-ratio="ocrCropTopRatio"
              v-model:ocr-crop-bottom-ratio="ocrCropBottomRatio"
              v-model:ocr-crop-left-ratio="ocrCropLeftRatio"
              v-model:ocr-crop-right-ratio="ocrCropRightRatio"
              v-model:ocr-exclude-enabled="ocrExcludeEnabled"
              v-model:ocr-exclude-top-ratio="ocrExcludeTopRatio"
              v-model:ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
              v-model:ocr-exclude-left-ratio="ocrExcludeLeftRatio"
              v-model:ocr-exclude-right-ratio="ocrExcludeRightRatio"
              :input-video="agentPreviewVideo"
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
              v-model:ocr-extraction-mode="ocrExtractionMode"
              v-model:ocr-shape-mode="ocrShapeMode"
              v-model:ocr-crop-top-ratio="ocrCropTopRatio"
              v-model:ocr-crop-bottom-ratio="ocrCropBottomRatio"
              v-model:ocr-crop-left-ratio="ocrCropLeftRatio"
              v-model:ocr-crop-right-ratio="ocrCropRightRatio"
              v-model:ocr-exclude-enabled="ocrExcludeEnabled"
              v-model:ocr-exclude-top-ratio="ocrExcludeTopRatio"
              v-model:ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
              v-model:ocr-exclude-left-ratio="ocrExcludeLeftRatio"
              v-model:ocr-exclude-right-ratio="ocrExcludeRightRatio"
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
              :upload-busy="mobileUploadBusy"
              @refresh="loadAssets"
              @local-ocr="runLocalOcr"
              @local-audio="runLocalAudio"
              @upload-asr-translate="uploadAndTranslateMobileVideo"
              @register-local-project="registerLocalProject"
              @use-project="useProject"
              @use-video="useVideo"
              @use-video-ocr="useVideoAndOcr"
              @use-subtitle="useSubtitle"
              @edit-subtitle="editSubtitle"
              @delete-project="deleteDownloadProject"
              @upload-cover="uploadProjectCoverFile"
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

          <div v-else-if="activeView === 'ocr-dev'" class="page-stack">
            <OcrDevPanel
              v-model:input-video="localVideo"
              v-model:source-language="ocrDevSourceLanguage"
              v-model:sample-fps="ocrDevSampleFps"
              v-model:min-confidence="ocrDevMinConfidence"
              v-model:refine-timing-boundaries="ocrDevRefineTimingBoundaries"
              v-model:flicker-smoothing-max-duration-seconds="ocrDevFlickerSmoothingMaxDurationSeconds"
              v-model:llm-cleanup="ocrDevLlmCleanup"
              v-model:source-srt="sourceSrt"
              :debug-folders="assets.ocr_debug_folders"
              :ocr-scope="ocrScope"
              v-model:ocr-extraction-mode="ocrDevExtractionMode"
              v-model:ocr-shape-mode="ocrDevShapeMode"
              v-model:ocr-crop-top-ratio="ocrCropTopRatio"
              v-model:ocr-crop-bottom-ratio="ocrCropBottomRatio"
              v-model:ocr-crop-left-ratio="ocrCropLeftRatio"
              v-model:ocr-crop-right-ratio="ocrCropRightRatio"
              v-model:ocr-exclude-enabled="ocrExcludeEnabled"
              v-model:ocr-exclude-top-ratio="ocrExcludeTopRatio"
              v-model:ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
              v-model:ocr-exclude-left-ratio="ocrExcludeLeftRatio"
              v-model:ocr-exclude-right-ratio="ocrExcludeRightRatio"
              :running="ocrDevRunning"
              :status="ocrDevStatus.text"
              :status-class="ocrDevStatus.class"
              @open-assets="activeView = 'assets'"
              @run="runOcrDevelopmentTest"
              @run-cleanup="runExistingOcrSourceCleanup"
              @rebuild-track-refine="runOcrJsonRebuild"
              @geometry-refine="runOcrGeometryRefine"
              @v3-refine="runOcrV3Refine"
              @layered-refine="runOcrLayeredRefine"
              @refresh-debug-assets="loadAssets"
            />
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
              v-model:video-path="subtitleEditorVideoPath"
              :cues="subtitleEditorCues"
              :loading="subtitleEditorLoading"
              :dirty="subtitleEditorDirty"
              :status="subtitleEditorStatus.text"
              :status-class="subtitleEditorStatus.class"
              :prefix-names="subtitlePrefixNames"
              :pair-issues="subtitlePairIssues"
              :focused-cue-uid="subtitleFocusedCueUid"
              :can-undo="subtitleEditorUndoStack.length > 0"
              :undo-count="subtitleEditorUndoStack.length"
              @update:prefix-names="subtitlePrefixNames = $event"
              @load-subtitle="loadSubtitleEditor"
              @save-subtitle="saveSubtitleEditor(true)"
              @save-subtitle-as="saveSubtitleEditor(false)"
              @begin-cue-edit="beginSubtitleEditorCueEdit"
              @end-cue-edit="endSubtitleEditorCueEdit"
              @update-cue="updateSubtitleEditorCue"
              @add-cue-at-time="addSubtitleEditorCueAtTime"
              @insert-cue="insertSubtitleEditorCue"
              @set-cue-boundary="setSubtitleEditorCueBoundary"
              @nudge-cue="nudgeSubtitleEditorCue"
              @snap-cue="snapSubtitleEditorCue"
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
              :glossary-editor="glossaryEditor"
              :glossary-items="glossaryItems"
              :loading="glossaryLoading"
              :agent-review="agentGlossaryReviewActive"
              :review-ready="glossaryReviewReady"
              :save-state="glossarySaveState"
              :text-dirty="glossaryTextDirty"
              :continue-busy="glossaryContinueBusy"
              :status="flowStatus.text"
              :status-class="flowStatus.class"
              @load-glossary="loadGlossary"
              @apply-all-suggestions="applyAllSuggestions"
              @save-glossary-review="saveGlossaryReview"
              @save-glossary-text="saveGlossaryText"
              @update:glossary-editor="updateGlossaryEditor"
              @update-glossary-zh="updateGlossaryZh"
              @set-glossary-reviewed="setGlossaryReviewed"
              @use-suggestion="useSuggestion"
              @retry-glossary-save="retryGlossaryAutosave"
            />
          </div>

          <div v-else-if="activeView === 'settings'" class="page-stack">
            <SettingsPanel
              :settings="settingsEditor"
              :providers="settingsProviders"
              :models-by-provider="settingsModelsByProvider"
              :model-errors="settingsModelErrors"
              :loading="settingsLoading"
              :saving="settingsSaving"
              :fetching-provider-id="settingsFetchingProviderId"
              :selected-provider-id="settingsConnectionProviderId"
              :provider-management-allowed="settingsCapabilities.provider_management_allowed === true"
              :provider-managing="settingsProviderManaging"
              :connection="settingsProviderConnection"
              :connection-loading="settingsConnectionLoading"
              :connection-saving="settingsConnectionSaving"
              :connection-error="settingsConnectionError"
              :status="settingsStatus.text"
              :status-class="settingsStatus.class"
              @save-settings="saveAppSettings"
              @fetch-models="fetchProviderModels"
              @select-provider="loadProviderConnection"
              @save-connection="saveProviderConnection"
              @create-provider="createSettingsProvider"
              @update-provider="updateSettingsProvider"
              @delete-provider="deleteSettingsProvider"
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
          v-if="activeView === 'jobs'"
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
import { api, deleteJson, getJson, patchJson, uploadProjectCover, uploadVideoFile } from './api'
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
import OcrDevPanel from './components/OcrDevPanel.vue'
import JobSidebar from './components/JobSidebar.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import { copyText } from './clipboard.js'
import { createAgentSessionPoller } from './agentSessionPolling.js'
import { buildAgentOcrPipelinePayload, inferAgentOcrPipelineVersion } from './agentOcrPipeline.js'
import { createGlossaryReviewAutosave } from './glossaryReviewAutosave.js'
import {
  canReuseOpenedGlossaryReview,
  findGlossaryReviewSession,
  glossaryReviewKey,
  isGlossaryReviewPathForSession,
} from './glossaryReviewFlow.js'
import { detectCuePairSymbolIssues, parsePrefixNames, stripCueSpeakerPrefixes, stripCueTrailingCommas } from './subtitlePrefixTools.js'
import {
  insertSubtitleCueAtTime,
  insertSubtitleCueRelative,
  parseSrtTime,
  renumberSubtitleCues,
  setSubtitleCueBoundary,
} from './subtitleEditorTools.js'

const url = ref('')
const probe = ref(null)
const probing = ref(false)
const titleBox = ref('')
const sourceSrt = ref('')
const subtitleEditorPath = ref('')
const subtitleEditorVideoPath = ref('')
const subtitleEditorCues = ref([])
const subtitlePrefixNames = ref('')
const subtitlePairIssues = ref([])
const subtitleFocusedCueUid = ref('')
const subtitleEditorUndoStack = ref([])
const subtitleEditorSavedCues = ref([])
const subtitleEditorPendingFieldEdit = ref(null)
const subtitleEditorLoading = ref(false)
const subtitleEditorDirty = ref(false)
const glossaryPath = ref('')
const extraHint = ref('')
const glossaryEditor = ref('')
const glossaryItems = ref([])
const glossaryLoading = ref(false)
const loadedGlossaryPath = ref('')
const glossaryTextDirty = ref(false)
const glossarySaveState = ref('idle')
const glossaryContinueBusy = ref(false)
let glossaryLoadGeneration = 0
const subtitleTranslationMode = ref('translate_only')
const subtitleConvertFormat = ref('bcc')
const ocrTranslationMode = ref('standard_cleanup')
const ocrScope = ref('bottom')
const ocrExtractionMode = ref('auto')
const ocrShapeMode = ref('horizontal_preferred')
const agentOcrPipelineVersion = ref('v2')
const agentRestoredOcrSettings = ref({})
const ocrCropTopRatio = ref(0.58)
const ocrCropBottomRatio = ref(0)
const ocrCropLeftRatio = ref(0)
const ocrCropRightRatio = ref(0)
const ocrExcludeEnabled = ref(false)
const ocrExcludeTopRatio = ref(0.04)
const ocrExcludeBottomRatio = ref(0.82)
const ocrExcludeLeftRatio = ref(0.76)
const ocrExcludeRightRatio = ref(0.02)
const ocrDevSourceLanguage = ref('korean')
const ocrDevExtractionMode = ref('region')
const ocrDevShapeMode = ref('horizontal_preferred')
const ocrDevSampleFps = ref(6)
const ocrDevMinConfidence = ref(30)
const ocrDevRefineTimingBoundaries = ref(true)
const ocrDevFlickerSmoothingMaxDurationSeconds = ref(0.55)
const ocrDevLlmCleanup = ref(true)
const ocrDevRunning = ref(false)
const ocrRefinementMode = ref('none')
const thumbnailFormat = ref('jpg')
const videoQuality = ref('1080p')
const embeddedSubtitleHint = ref('unknown')
const embeddedSubtitleGoal = ref('screen_subtitle')
const sourceLanguage = ref('korean')
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
const openedGlossaryReviewKey = ref('')
const openingGlossaryReviewKey = ref('')
const mobileUploadBusy = ref(false)
const settingsEditor = ref(null)
const settingsProviders = ref([])
const settingsModelsByProvider = ref({})
const settingsModelErrors = ref({})
const settingsLoading = ref(false)
const settingsSaving = ref(false)
const settingsFetchingProviderId = ref('')
const settingsProviderConnection = ref(null)
const settingsConnectionProviderId = ref('')
const settingsConnectionLoading = ref(false)
const settingsConnectionSaving = ref(false)
const settingsConnectionError = ref('')
const settingsCapabilities = ref({})
const settingsProviderManaging = ref(false)

const assets = reactive({ videos: [], subtitles: [], projects: [], ocr_jobs: [], ocr_debug_folders: [] })
const jobs = reactive({})
const pollTimers = new Map()

const probeStatus = reactive({ text: '', class: '' })
const titleStatus = reactive({ text: '', class: '' })
const flowStatus = reactive({ text: '', class: '' })
const subtitleEditorStatus = reactive({ text: '', class: '' })
const ocrDevStatus = reactive({ text: '', class: '' })
const assetStatus = reactive({ text: '', class: '' })
const agentStatus = reactive({ text: '', class: '' })
const settingsStatus = reactive({ text: '', class: '' })

const glossaryAutosave = createGlossaryReviewAutosave({
  save: saveGlossaryAutosavePayload,
  onState: ({ state, error }) => {
    glossarySaveState.value = state
    if (state === 'error') setStatus(flowStatus, `自动保存审核进度失败：${error}`, 'bad')
    if (state === 'saved' && flowStatus.text.startsWith('自动保存审核进度失败')) {
      setStatus(flowStatus, 'Glossary 审核进度已自动保存。', 'ok')
    }
  },
})

const pages = {
  agent: {
    title: 'Agent 字幕流程',
    description: '自动判断字幕来源，提取原文，审核术语并完成翻译。',
  },
  'new-task': {
    title: '链接工具',
    description: '手动检测字幕、下载视频或进入 OCR 全流程。',
  },
  assets: {
    title: '素材库',
    description: '管理已下载视频、字幕文件、OCR 和音频识别输出。',
  },
  'video-overlay': {
    title: '贴图处理',
    description: '给当前视频叠加水印或遮 Logo，输出新视频。',
  },
  subtitles: {
    title: '字幕处理',
    description: '选择源字幕，生成 glossary，翻译为中文外挂字幕。',
  },
  'subtitle-edit': {
    title: '字幕精修',
    description: '逐条修改、合并、删除已生成字幕。',
  },
  glossary: {
    title: '术语审核',
    description: '集中审核人名、昵称、作品名和固定术语。',
  },
  jobs: {
    title: '任务日志',
    description: '查看运行状态、失败原因、输出路径，并终止误点任务。',
  },
  'ocr-dev': {
    title: 'OCR Lab',
    description: '独立维护 OCR V2 / V3，裁框、复跑并比较调试结果。',
  },
  settings: {
    title: '设置中心',
    description: '保存新任务默认语言，选择模型服务配置，并为每个 LLM 模块绑定模型。',
  },
}

const OCR_SCOPE_TOP_DEFAULTS = { bottom: 0.58, expanded: 0.38, smart_full: 0.58 }
const activePage = computed(() => pages[activeView.value] || pages['new-task'])
const glossaryReviewReady = computed(() => Boolean(
  loadedGlossaryPath.value && loadedGlossaryPath.value === glossaryPath.value.trim(),
))
const agentGlossaryReviewActive = computed(() => (
  glossaryReviewReady.value && isGlossaryReviewPathForSession(agentSession.value, loadedGlossaryPath.value)
))
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
const agentPreviewVideo = computed(() => (
  agentSession.value
    ? (agentSession.value.result?.input_video || '')
    : (localVideo.value || '')
))

let skipNextOcrScopeCropReset = false
watch(ocrScope, (scope) => {
  if (skipNextOcrScopeCropReset) {
    skipNextOcrScopeCropReset = false
    return
  }
  ocrCropTopRatio.value = OCR_SCOPE_TOP_DEFAULTS[scope] ?? 0.58
  ocrCropBottomRatio.value = 0
})

const navItems = computed(() => [
  { id: 'agent', group: '日常流程', label: 'Agent 路线', hint: '自动完成字幕', icon: 'A', badge: waitingAgentCount.value ? `${waitingAgentCount.value} 待确认` : runningAgentCount.value || '' },
  { id: 'assets', group: '日常流程', label: '素材库', hint: '项目、视频与字幕', icon: 'M', badge: assets.videos.length + assets.subtitles.length || '' },
  { id: 'subtitle-edit', group: '字幕制作', label: '字幕精修', hint: '新增与微调 SRT', icon: 'E', badge: subtitleEditorCues.value.length || '' },
  { id: 'glossary', group: '字幕制作', label: '术语审核', hint: '人名与固定译法', icon: 'G', badge: glossaryItems.value.length || '' },
  { id: 'subtitles', group: '字幕制作', label: '翻译与转换', hint: '字幕后续处理', icon: 'S', badge: sourceSrt.value ? '已选' : '' },
  { id: 'ocr-dev', group: '实验室', label: 'OCR Lab', hint: 'V2 / V3 独立测试', icon: 'O', badge: '' },
  { id: 'new-task', group: '其他工具', label: '链接检测', hint: '手动下载与 OCR', icon: 'L', badge: probe.value?.subtitles?.length || '' },
  { id: 'video-overlay', group: '其他工具', label: '视频贴图', hint: '水印与遮 Logo', icon: 'V', badge: localVideo.value ? '已选' : '' },
  { id: 'settings', group: '系统', label: '设置', hint: '语言、服务与模型', icon: '⚙', badge: '' },
  { id: 'jobs', group: '系统', label: '任务日志', hint: '进度、错误与输出', icon: 'J', badge: runningJobCount.value || failedJobCount.value || '' },
])

onMounted(async () => {
  window.addEventListener('keydown', onSubtitleEditorUndoShortcut)
  window.addEventListener('beforeunload', onGlossaryBeforeUnload)
  await loadAppSettings({ applyDefaults: true })
  loadAssets()
  loadJobs()
  loadAgentSessions()
  loadAgentTasks()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onSubtitleEditorUndoShortcut)
  window.removeEventListener('beforeunload', onGlossaryBeforeUnload)
  glossaryAutosave.destroy()
  agentPoller.cancelAll()
})

async function loadAppSettings({ applyDefaults = false } = {}) {
  settingsLoading.value = true
  try {
    const result = await getJson('/api/settings')
    settingsEditor.value = result.settings || null
    settingsProviders.value = result.providers || []
    settingsCapabilities.value = result.capabilities || {}
    // This map tracks lists already fetched from provider endpoints. Static
    // profile models remain available through SettingsPanel's provider data.
    settingsModelsByProvider.value = {}
    settingsModelErrors.value = {}
    if (applyDefaults) applyAppSettingDefaults(settingsEditor.value)
    const defaultProviderId = String(settingsEditor.value?.defaults?.provider_profile || '').trim()
    if (defaultProviderId) await loadProviderConnection(defaultProviderId, { quiet: true })
    setStatus(settingsStatus, '设置已加载。', 'ok')
  } catch (error) {
    setStatus(settingsStatus, `设置加载失败：${error.message}`, 'bad')
  } finally {
    settingsLoading.value = false
  }
}

function applyAppSettingDefaults(settings) {
  const defaults = settings?.defaults || {}
  if (defaults.source_language) {
    sourceLanguage.value = defaults.source_language
    if (audioLanguage.value === 'auto') audioLanguage.value = defaults.source_language
  }
  if (defaults.ocr_language) ocrLanguage.value = defaults.ocr_language
}

async function saveAppSettings(settings) {
  settingsSaving.value = true
  setStatus(settingsStatus, '正在保存设置...', '')
  try {
    const result = await api('/api/settings', settings || {})
    settingsEditor.value = result.settings || settings
    settingsProviders.value = result.providers || settingsProviders.value
    if (result.capabilities) settingsCapabilities.value = result.capabilities
    const activeProviderIds = new Set(settingsProviders.value.map((provider) => provider.id))
    settingsModelsByProvider.value = Object.fromEntries(
      Object.entries(settingsModelsByProvider.value).filter(([providerId]) => activeProviderIds.has(providerId)),
    )
    applyAppSettingDefaults(settingsEditor.value)
    const defaultProviderId = String(settingsEditor.value?.defaults?.provider_profile || '').trim()
    if (defaultProviderId && defaultProviderId !== settingsConnectionProviderId.value) {
      await loadProviderConnection(defaultProviderId, { quiet: true })
    }
    setStatus(settingsStatus, '设置已保存；之后发起的任务会使用新的默认语言和模型。', 'ok')
  } catch (error) {
    setStatus(settingsStatus, error.message, 'bad')
  } finally {
    settingsSaving.value = false
  }
}

async function loadProviderConnection(providerId, { quiet = false } = {}) {
  const id = String(providerId || '').trim()
  settingsConnectionProviderId.value = id
  settingsProviderConnection.value = null
  settingsConnectionError.value = ''
  if (!id) return

  settingsConnectionLoading.value = true
  try {
    const result = await getJson(`/api/settings/providers/${encodeURIComponent(id)}/connection`)
    if (settingsConnectionProviderId.value !== id) return
    settingsProviderConnection.value = result.connection || result
  } catch (error) {
    if (settingsConnectionProviderId.value !== id) return
    settingsConnectionError.value = error.message
    if (!quiet) setStatus(settingsStatus, `连接配置读取失败：${error.message}`, 'bad')
  } finally {
    if (settingsConnectionProviderId.value === id) settingsConnectionLoading.value = false
  }
}

async function refreshSettingsProviderMetadata() {
  const result = await getJson('/api/settings')
  settingsProviders.value = result.providers || []
  settingsCapabilities.value = result.capabilities || settingsCapabilities.value
  const activeProviderIds = new Set(settingsProviders.value.map((provider) => provider.id))
  settingsModelsByProvider.value = Object.fromEntries(
    Object.entries(settingsModelsByProvider.value).filter(([providerId]) => activeProviderIds.has(providerId)),
  )
}

async function createSettingsProvider(payload = {}) {
  if (settingsProviderManaging.value) return
  const requestedId = String(payload?.id || '').trim()
  const hadProviders = settingsProviders.value.length > 0
  settingsProviderManaging.value = true
  setStatus(settingsStatus, `正在创建服务商 ${requestedId || ''}…`, '')
  try {
    const result = await api('/api/settings/providers', payload)
    settingsProviders.value = result.providers || settingsProviders.value
    if (!hadProviders && result.settings) settingsEditor.value = result.settings
    if (result.capabilities) settingsCapabilities.value = result.capabilities
    const createdId = String(result.provider?.id || requestedId).trim()
    settingsModelsByProvider.value = { ...settingsModelsByProvider.value }
    delete settingsModelsByProvider.value[createdId]
    settingsModelErrors.value = { ...settingsModelErrors.value, [createdId]: '' }
    await loadProviderConnection(createdId, { quiet: true })
    setStatus(settingsStatus, `${createdId} 已创建；可以继续获取模型或绑定到具体模块。`, 'ok')
  } catch (error) {
    setStatus(settingsStatus, error.message, 'bad')
  } finally {
    settingsProviderManaging.value = false
  }
}

async function deleteSettingsProvider({ providerId, replacementProviderId } = {}) {
  const id = String(providerId || '').trim()
  const replacementId = String(replacementProviderId || '').trim()
  if (!id || !replacementId || settingsProviderManaging.value) return
  settingsProviderManaging.value = true
  setStatus(settingsStatus, `正在删除 ${id} 并迁移配置…`, '')
  try {
    const result = await deleteJson(
      `/api/settings/providers/${encodeURIComponent(id)}`,
      { replacement_provider_id: replacementId },
    )
    settingsEditor.value = result.settings || settingsEditor.value
    settingsProviders.value = result.providers || settingsProviders.value.filter((provider) => provider.id !== id)
    if (result.capabilities) settingsCapabilities.value = result.capabilities
    settingsModelsByProvider.value = { ...settingsModelsByProvider.value }
    settingsModelErrors.value = { ...settingsModelErrors.value }
    delete settingsModelsByProvider.value[id]
    delete settingsModelErrors.value[id]
    await loadProviderConnection(replacementId, { quiet: true })
    const affectedCount = Array.isArray(result.affected_tasks) ? result.affected_tasks.length : 0
    setStatus(
      settingsStatus,
      `${id} 已删除；${affectedCount ? `${affectedCount} 个模块及相关默认值已` : '相关配置已'}切换到 ${replacementId}。`,
      'ok',
    )
  } catch (error) {
    setStatus(settingsStatus, error.message, 'bad')
  } finally {
    settingsProviderManaging.value = false
  }
}

async function updateSettingsProvider({ providerId, payload } = {}) {
  const id = String(providerId || '').trim()
  if (!id || settingsProviderManaging.value) return
  settingsProviderManaging.value = true
  setStatus(settingsStatus, `正在更新服务商 ${id}…`, '')
  try {
    const result = await patchJson(
      `/api/settings/providers/${encodeURIComponent(id)}`,
      payload || {},
    )
    settingsProviders.value = result.providers || settingsProviders.value
    if (result.capabilities) settingsCapabilities.value = result.capabilities
    settingsModelsByProvider.value = { ...settingsModelsByProvider.value }
    settingsModelErrors.value = { ...settingsModelErrors.value, [id]: '' }
    delete settingsModelsByProvider.value[id]
    if (settingsConnectionProviderId.value === id) {
      await loadProviderConnection(id, { quiet: true })
    }
    setStatus(settingsStatus, `${id} 的服务商资料已更新；已有模块绑定未被改写。`, 'ok')
  } catch (error) {
    setStatus(settingsStatus, `${id} 更新失败：${error.message}`, 'bad')
  } finally {
    settingsProviderManaging.value = false
  }
}

async function saveProviderConnection({ providerId, payload } = {}) {
  const id = String(providerId || '').trim()
  if (!id || settingsConnectionSaving.value) return

  settingsConnectionSaving.value = true
  settingsConnectionError.value = ''
  setStatus(settingsStatus, `正在保存 ${id} 的本地连接…`, '')
  try {
    await api(`/api/settings/providers/${encodeURIComponent(id)}/connection`, payload || {})
    await refreshSettingsProviderMetadata()
    await loadProviderConnection(id, { quiet: true })
    // A changed credential or endpoint may produce a different remote list.
    settingsModelsByProvider.value = { ...settingsModelsByProvider.value }
    delete settingsModelsByProvider.value[id]
    settingsModelErrors.value = { ...settingsModelErrors.value, [id]: '' }
    setStatus(settingsStatus, `${id} 的本地连接已保存。`, 'ok')
  } catch (error) {
    settingsConnectionError.value = error.message
    setStatus(settingsStatus, error.message, 'bad')
  } finally {
    settingsConnectionSaving.value = false
  }
}

async function fetchProviderModels(providerId) {
  const id = String(providerId || '').trim()
  if (!id) return
  settingsFetchingProviderId.value = id
  settingsModelErrors.value = { ...settingsModelErrors.value, [id]: '' }
  setStatus(settingsStatus, `正在向 ${id} 获取可用模型...`, '')
  try {
    const result = await getJson(`/api/settings/providers/${encodeURIComponent(id)}/models?refresh=1`)
    if (!settingsProviders.value.some((provider) => String(provider?.id || '') === id)) return
    settingsModelsByProvider.value = {
      ...settingsModelsByProvider.value,
      [id]: result.models || [],
    }
    settingsModelErrors.value = {
      ...settingsModelErrors.value,
      [id]: result.warning || '',
    }
    setStatus(
      settingsStatus,
      result.warning
        ? `远端模型获取失败，已保留本地模型：${result.warning}`
        : `已从 ${id} 获取 ${result.models?.length || 0} 个模型。`,
      result.warning ? 'bad' : 'ok',
    )
  } catch (error) {
    settingsModelErrors.value = { ...settingsModelErrors.value, [id]: error.message }
    setStatus(settingsStatus, error.message, 'bad')
  } finally {
    settingsFetchingProviderId.value = ''
  }
}

async function startAgent() {
  if (!url.value.trim()) {
    setStatus(agentStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  agentStarting.value = true
  setStatus(agentStatus, 'Agent 正在启动...', '')
  try {
    const agentOcrPipeline = buildAgentOcrPipelinePayload(agentOcrPipelineVersion.value, { ocrScope: ocrScope.value })
    const session = await api('/api/agent/start', {
      url: url.value.trim(),
      embedded_subtitle_hint: embeddedSubtitleHint.value,
      embedded_subtitle_goal: embeddedSubtitleGoal.value,
      source_language: sourceLanguage.value,
      ocr_language: ocrLanguage.value,
      target_language: 'zh',
      extra_hint: extraHint.value,
      ...agentOcrPipeline,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_exclude_enabled: ocrExcludeEnabled.value,
      ocr_exclude_top_ratio: ocrExcludeTopRatio.value,
      ocr_exclude_bottom_ratio: ocrExcludeBottomRatio.value,
      ocr_exclude_left_ratio: ocrExcludeLeftRatio.value,
      ocr_exclude_right_ratio: ocrExcludeRightRatio.value,
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
  setStatus(
    agentStatus,
    action === 'download_video_for_preview'
      ? '正在准备或下载视频；完成后会自动加载首帧并显示位置操作。'
      : '已提交回答，Agent 继续处理...',
    '',
  )
  try {
    const agentOcrPipeline = buildAgentOcrPipelinePayload(agentOcrPipelineVersion.value, {
      ocrScope: ocrScope.value,
      restoredSettings: agentRestoredOcrSettings.value,
    })
    const session = await api(`/api/agent/${agentSession.value.id}/answer`, {
      action,
      ...agentOcrPipeline,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_exclude_enabled: ocrExcludeEnabled.value,
      ocr_exclude_top_ratio: ocrExcludeTopRatio.value,
      ocr_exclude_bottom_ratio: ocrExcludeBottomRatio.value,
      ocr_exclude_left_ratio: ocrExcludeLeftRatio.value,
      ocr_exclude_right_ratio: ocrExcludeRightRatio.value,
      source_language: sourceLanguage.value,
      ocr_language: ocrLanguage.value,
      embedded_subtitle_goal: embeddedSubtitleGoal.value,
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
    let openedGlossaryReview = false
    if (selected) {
      const isNewSelection = !agentSession.value?.id || agentSession.value.id !== session.id
      agentSession.value = session
      if (isNewSelection) restoreAgentOcrPipeline(session)
      if (session.result?.source_srt) sourceSrt.value = session.result.source_srt
      if (session.result?.translated_srt) setStatus(agentStatus, `Agent 完成：${session.result.translated_srt}`, 'ok')
      openedGlossaryReview = await openGlossaryReviewForSession(session)
    }
    await loadAgentSessions()
    await loadAgentTasks()
    if (session.status === 'running') {
      scheduleAgentPoll(sessionId, 1000)
      return
    }
    agentPoller.cancel(sessionId)
    if (session.status === 'waiting') {
      if (selected && !openedGlossaryReview) setStatus(agentStatus, 'Agent 等待你的确认。', '')
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
    await openWaitingGlossaryReviewFromSessions()
    if (!agentSession.value?.id && agentSessions.value.length) {
      const preferred = agentSessions.value.find((session) => ['waiting', 'running'].includes(session.status))
        || agentSessions.value[0]
      agentSession.value = preferred
      restoreAgentOcrPipeline(preferred)
    }
  } catch {
    agentSessions.value = agentSessions.value || []
  }
}

async function openWaitingGlossaryReviewFromSessions() {
  const currentSession = agentSession.value
  const reviewSession = findGlossaryReviewSession(agentSessions.value, currentSession?.id || '')
  if (!reviewSession) return false
  if (currentSession?.status === 'running' && currentSession.id !== reviewSession.id) return false
  if (!currentSession?.id || currentSession.id !== reviewSession.id) {
    agentSession.value = reviewSession
    restoreAgentOcrPipeline(reviewSession)
  }
  return openGlossaryReviewForSession(reviewSession)
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
    restoreAgentOcrPipeline(session)
    setStatus(agentStatus, `已切换到 Agent 任务：${session.id}`, '')
    const openedGlossaryReview = await openGlossaryReviewForSession(session)
    if (session.status === 'running') scheduleAgentPoll(session.id, 500)
    return openedGlossaryReview
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
    return false
  }
}

async function continueAgentTask(taskId) {
  setStatus(agentStatus, '正在从视频任务继续...', '')
  try {
    const session = await api(`/api/agent-tasks/${taskId}/continue`, {})
    agentSession.value = session
    restoreAgentOcrPipeline(session)
    await loadAgentSessions()
    await loadAgentTasks()
    const openedGlossaryReview = await openGlossaryReviewForSession(session)
    if (session.status === 'running') scheduleAgentPoll(session.id, 500)
    return { session, openedGlossaryReview }
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
    return null
  }
}

function restoreAgentOcrPipeline(session) {
  const payload = session?.payload || {}
  agentRestoredOcrSettings.value = { ...payload }
  agentOcrPipelineVersion.value = inferAgentOcrPipelineVersion(payload)
  if (['bottom', 'expanded', 'smart_full'].includes(payload.ocr_scope) && payload.ocr_scope !== ocrScope.value) {
    skipNextOcrScopeCropReset = true
    ocrScope.value = payload.ocr_scope
  }
  const ratioBindings = [
    ['ocr_crop_top_ratio', ocrCropTopRatio],
    ['ocr_crop_bottom_ratio', ocrCropBottomRatio],
    ['ocr_crop_left_ratio', ocrCropLeftRatio],
    ['ocr_crop_right_ratio', ocrCropRightRatio],
    ['ocr_exclude_top_ratio', ocrExcludeTopRatio],
    ['ocr_exclude_bottom_ratio', ocrExcludeBottomRatio],
    ['ocr_exclude_left_ratio', ocrExcludeLeftRatio],
    ['ocr_exclude_right_ratio', ocrExcludeRightRatio],
  ]
  for (const [key, target] of ratioBindings) {
    if (payload[key] === undefined || payload[key] === null || payload[key] === '') continue
    const value = Number(payload[key])
    if (Number.isFinite(value)) target.value = value
  }
  if (typeof payload.ocr_exclude_enabled === 'boolean') ocrExcludeEnabled.value = payload.ocr_exclude_enabled
  if (payload.source_language) sourceLanguage.value = payload.source_language
  if (payload.ocr_language) ocrLanguage.value = payload.ocr_language
  if (payload.embedded_subtitle_goal) embeddedSubtitleGoal.value = payload.embedded_subtitle_goal
}

async function rerunAgentTask({ taskId, stage }) {
  setStatus(agentStatus, `正在重跑 ${stage} 阶段...`, '')
  try {
    const session = await api(`/api/agent-tasks/${taskId}/rerun`, { stage })
    agentSession.value = session
    restoreAgentOcrPipeline(session)
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
  const taskId = typeof payload === 'object' ? payload?.taskId : ''
  if (sessionId && await selectAgentSession(sessionId)) return
  if (taskId) {
    const continued = await continueAgentTask(taskId)
    if (continued?.openedGlossaryReview) return
  }
  glossaryPath.value = path || ''
  activeView.value = 'glossary'
  await loadGlossary()
}

async function openGlossaryReviewForSession(session) {
  const reviewKey = glossaryReviewKey(session)
  if (!reviewKey) {
    if (openedGlossaryReviewKey.value.startsWith(`${session?.id || ''}:`)) openedGlossaryReviewKey.value = ''
    return false
  }
  const reviewPath = session.question.glossary_path || session.result.glossary_path
  if (canReuseOpenedGlossaryReview(
    session,
    openedGlossaryReviewKey.value,
    loadedGlossaryPath.value,
    glossaryPath.value,
  )) {
    activeView.value = 'glossary'
    return true
  }
  if (openingGlossaryReviewKey.value === reviewKey && glossaryPath.value.trim() === reviewPath) {
    activeView.value = 'glossary'
    return true
  }
  openingGlossaryReviewKey.value = reviewKey
  glossaryPath.value = reviewPath
  activeView.value = 'glossary'
  try {
    const loaded = await loadGlossary()
    if (!loaded) return false
    openedGlossaryReviewKey.value = reviewKey
    setStatus(agentStatus, 'Glossary 已生成，已打开审核。保存后 Agent 将继续翻译。', 'ok')
    return true
  } catch {
    return false
  } finally {
    if (openingGlossaryReviewKey.value === reviewKey) openingGlossaryReviewKey.value = ''
  }
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
      ocr_pipeline_version: ocrExtractionMode.value === 'region_v3' ? 'v3' : 'custom',
      translation_mode: ocrTranslationMode.value,
      ocr_scope: ocrScope.value,
      ocr_extraction_mode: ocrExtractionMode.value,
      ocr_shape_mode: ocrShapeMode.value,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_exclude_enabled: ocrExcludeEnabled.value,
      ocr_exclude_top_ratio: ocrExcludeTopRatio.value,
      ocr_exclude_bottom_ratio: ocrExcludeBottomRatio.value,
      ocr_exclude_left_ratio: ocrExcludeLeftRatio.value,
      ocr_exclude_right_ratio: ocrExcludeRightRatio.value,
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
      ocr_pipeline_version: ocrExtractionMode.value === 'region_v3' ? 'v3' : 'custom',
      translation_mode: ocrTranslationMode.value,
      ocr_scope: ocrScope.value,
      ocr_extraction_mode: ocrExtractionMode.value,
      ocr_shape_mode: ocrShapeMode.value,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_exclude_enabled: ocrExcludeEnabled.value,
      ocr_exclude_top_ratio: ocrExcludeTopRatio.value,
      ocr_exclude_bottom_ratio: ocrExcludeBottomRatio.value,
      ocr_exclude_left_ratio: ocrExcludeLeftRatio.value,
      ocr_exclude_right_ratio: ocrExcludeRightRatio.value,
      ocr_refinement_mode: ocrRefinementMode.value,
      source_language: sourceLanguage.value,
      ocr_language: ocrLanguage.value,
    })
    watchJob(job)
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function runOcrDevelopmentTest() {
  if (!localVideo.value.trim()) {
    setStatus(ocrDevStatus, '请先选择本地视频。', 'bad')
    return
  }
  ocrDevRunning.value = true
  setStatus(ocrDevStatus, '正在运行区域 OCR 开发测试…', '')
  try {
    const job = await api('/api/jobs/ocr-dev', {
      input_video: localVideo.value.trim(),
      source_language: ocrDevSourceLanguage.value,
      sample_fps: ocrDevSampleFps.value,
      min_confidence: ocrDevMinConfidence.value,
      refine_timing_boundaries: ocrDevRefineTimingBoundaries.value,
      flicker_smoothing_max_duration_seconds: ocrDevFlickerSmoothingMaxDurationSeconds.value,
      llm_cleanup: ocrDevLlmCleanup.value,
      ocr_scope: ocrScope.value,
      ocr_extraction_mode: ocrDevExtractionMode.value,
      ocr_shape_mode: ocrDevShapeMode.value,
      ocr_crop_top_ratio: ocrCropTopRatio.value,
      ocr_crop_bottom_ratio: ocrCropBottomRatio.value,
      ocr_crop_left_ratio: ocrCropLeftRatio.value,
      ocr_crop_right_ratio: ocrCropRightRatio.value,
      ocr_exclude_enabled: ocrExcludeEnabled.value,
      ocr_exclude_top_ratio: ocrExcludeTopRatio.value,
      ocr_exclude_bottom_ratio: ocrExcludeBottomRatio.value,
      ocr_exclude_left_ratio: ocrExcludeLeftRatio.value,
      ocr_exclude_right_ratio: ocrExcludeRightRatio.value,
    })
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(ocrDevStatus, 'OCR 开发测试已启动；完成后可在任务输出中查看 JSON。', 'ok')
  } catch (error) {
    setStatus(ocrDevStatus, error.message, 'bad')
  } finally {
    ocrDevRunning.value = false
  }
}

async function runExistingOcrSourceCleanup() {
  if (!sourceSrt.value.trim()) {
    setStatus(ocrDevStatus, '请填写已有 source.srt 的路径。', 'bad')
    return
  }
  ocrDevRunning.value = true
  setStatus(ocrDevStatus, '正在对已有 source.srt 进行 LLM 去噪…', '')
  try {
    const job = await api('/api/jobs/ocr-source-cleanup', {
      source_srt: sourceSrt.value.trim(),
    })
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(ocrDevStatus, '字幕去噪已启动；清洗版将写入原文件同目录。', 'ok')
  } catch (error) {
    setStatus(ocrDevStatus, error.message, 'bad')
  } finally {
    ocrDevRunning.value = false
  }
}

async function runOcrJsonRebuild(debugDir) {
  if (!debugDir) return
  ocrDevRunning.value = true
  setStatus(ocrDevStatus, '正在从已有 OCR JSON 重建候选并进行证据型 LLM 精修…', '')
  try {
    const job = await api('/api/jobs/ocr-rebuild-refine', { debug_dir: debugDir })
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(ocrDevStatus, 'JSON 重建已启动；不会重新读取视频。', 'ok')
  } catch (error) {
    setStatus(ocrDevStatus, error.message, 'bad')
  } finally {
    ocrDevRunning.value = false
  }
}

async function runOcrLayeredRefine(debugDir) {
  if (!debugDir) {
    setStatus(ocrDevStatus, '请选择包含 ocr_boxes.json 的调试文件夹。', 'bad')
    return
  }
  const isV3 = assets.ocr_debug_folders.some(
    (folder) => folder.path === debugDir && folder.ocr_lab_version === 'v3',
  )
  ocrDevRunning.value = true
  setStatus(
    ocrDevStatus,
    isV3
      ? '正在复用 3.0 文字精修稿，仅重跑画面字/对白分层…'
      : '正在根据 OCR 文字框分层精修画面字与下方对白…',
    '',
  )
  try {
    const job = await api('/api/jobs/ocr-layered-refine', { debug_dir: debugDir })
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(
      ocrDevStatus,
      isV3
        ? '3.0 分层复跑已启动；不会重新运行 OCR 或文字精修。'
        : '分层精修已启动；完成后将自动选中分层字幕。',
      'ok',
    )
  } catch (error) {
    setStatus(ocrDevStatus, error.message, 'bad')
  } finally {
    ocrDevRunning.value = false
  }
}

async function runOcrGeometryRefine(debugDir) {
  if (!debugDir) {
    setStatus(ocrDevStatus, '请选择包含字幕和 ocr_boxes.json 的调试文件夹。', 'bad')
    return
  }
  ocrDevRunning.value = true
  setStatus(ocrDevStatus, '正在复用已有 OCR 结果进行 3.0 几何 LLM 精修…', '')
  try {
    const job = await api('/api/jobs/ocr-geometry-refine', { debug_dir: debugDir })
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(ocrDevStatus, '几何精修已启动；不会重新运行 OCR。', 'ok')
  } catch (error) {
    setStatus(ocrDevStatus, error.message, 'bad')
  } finally {
    ocrDevRunning.value = false
  }
}

async function runOcrV3Refine(debugDir) {
  if (!debugDir) {
    setStatus(ocrDevStatus, '请选择包含现有 OCR 数据的 3.0 调试文件夹。', 'bad')
    return
  }
  ocrDevRunning.value = true
  setStatus(ocrDevStatus, '正在复用现有 OCR、轨迹和几何数据，执行 3.0 文字 + 分层精修…', '')
  try {
    const job = await api('/api/jobs/ocr-v3-refine', { debug_dir: debugDir })
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(ocrDevStatus, '3.0 成品精修已启动；只复用现有数据，不会重新运行 OCR。', 'ok')
  } catch (error) {
    setStatus(ocrDevStatus, error.message, 'bad')
  } finally {
    ocrDevRunning.value = false
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

async function uploadAndTranslateMobileVideo({ file, title }) {
  if (!file) {
    setStatus(assetStatus, '先选择要上传的视频。', 'bad')
    return
  }
  mobileUploadBusy.value = true
  setStatus(assetStatus, '正在上传视频...', '')
  try {
    const uploaded = await uploadVideoFile(file, { title })
    localVideo.value = uploaded.input_video || ''
    await loadAssets()
    setStatus(assetStatus, '上传完成，正在启动 ASR 翻译...', 'ok')
    const job = await api('/api/jobs/mobile-asr-translate', {
      input_video: localVideo.value,
      language: audioLanguage.value,
      source_language: sourceLanguage.value !== 'auto' ? sourceLanguage.value : audioLanguage.value,
      model_size: audioModelSize.value,
      device: 'cuda',
      compute_type: 'float16',
      translation_mode: 'standard_cleanup',
      extra_hint: extraHint.value,
    })
    watchJob(job)
    activeView.value = 'jobs'
    setStatus(assetStatus, '已创建手机 ASR 翻译任务。', 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  } finally {
    mobileUploadBusy.value = false
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
  const requestedPath = glossaryPath.value.trim()
  if (!requestedPath) {
    setStatus(flowStatus, '先填写 glossary 路径。', 'bad')
    return false
  }
  if (glossaryTextDirty.value && !window.confirm('当前 YAML 有未保存修改。确定放弃这些修改并重新加载吗？')) {
    return false
  }
  const loadGeneration = ++glossaryLoadGeneration
  activeView.value = 'glossary'
  glossaryLoading.value = true
  setStatus(flowStatus, '正在加载 glossary，并生成盲翻候选...', '')
  try {
    await glossaryAutosave.flush()
    if (loadGeneration !== glossaryLoadGeneration) return false
    const [text, review] = await Promise.all([
      api('/api/read-text', { path: requestedPath }),
      api('/api/read-glossary-items', { path: requestedPath, include_blind_candidates: true }),
    ])
    if (loadGeneration !== glossaryLoadGeneration || glossaryPath.value.trim() !== requestedPath) return false
    glossaryEditor.value = text.content || ''
    glossaryItems.value = review.items || []
    loadedGlossaryPath.value = requestedPath
    glossaryTextDirty.value = false
    glossaryAutosave.reset('idle')
    setStatus(flowStatus, `已加载 ${glossaryItems.value.length} 条 glossary。`, 'ok')
    activeView.value = 'glossary'
    return true
  } catch (error) {
    if (loadGeneration === glossaryLoadGeneration) setStatus(flowStatus, error.message, 'bad')
    return false
  } finally {
    if (loadGeneration === glossaryLoadGeneration) glossaryLoading.value = false
  }
}

async function saveGlossaryReview() {
  const path = loadedGlossaryPath.value
  if (!glossaryReviewReady.value || !path) {
    setStatus(flowStatus, '请先成功加载当前路径的 glossary，再保存审核结果。', 'bad')
    return
  }
  const items = cloneGlossaryItems(glossaryItems.value)
  if (agentGlossaryReviewActive.value) {
    await saveAndContinueGlossary({ path, items })
    return
  }
  glossaryContinueBusy.value = true
  try {
    try {
      await glossaryAutosave.flush()
    } catch {
      // The explicit save below retries the complete current snapshot.
    }
    const result = await api('/api/write-glossary-items', {
      path,
      items,
    })
    glossaryEditor.value = result.content || glossaryEditor.value
    glossaryItems.value = result.items || glossaryItems.value
    glossaryAutosave.reset()
    setStatus(flowStatus, 'Glossary 审核结果已保存。', 'ok')
  } catch (error) {
    setStatus(flowStatus, `保存 Glossary 失败：${error.message}`, 'bad')
  } finally {
    glossaryContinueBusy.value = false
  }
}

async function saveGlossaryText() {
  const path = loadedGlossaryPath.value
  if (!glossaryReviewReady.value || !path) {
    setStatus(flowStatus, '请先成功加载当前路径的 glossary，再保存 YAML。', 'bad')
    return
  }
  const content = glossaryEditor.value
  if (agentGlossaryReviewActive.value) {
    await saveAndContinueGlossary({ path, content })
    return
  }
  glossaryContinueBusy.value = true
  try {
    try {
      await glossaryAutosave.flush()
    } catch {
      // The explicit save below retries the complete current snapshot.
    }
    await api('/api/write-text', {
      path,
      content,
    })
    glossaryTextDirty.value = false
    glossaryAutosave.reset()
    await loadGlossary()
    setStatus(flowStatus, 'Glossary YAML 已保存。', 'ok')
  } catch (error) {
    setStatus(flowStatus, `保存 Glossary 失败：${error.message}`, 'bad')
  } finally {
    glossaryContinueBusy.value = false
  }
}

async function saveAndContinueGlossary(payload) {
  glossaryContinueBusy.value = true
  try {
    try {
      await glossaryAutosave.flush()
    } catch {
      // The atomic endpoint below receives the latest complete snapshot.
    }
    setStatus(flowStatus, '正在保存 Glossary 并启动翻译...', '')
    const response = await api('/api/agent/save-glossary-and-continue', payload)
    const session = response.session
    if (!session?.id) throw new Error('服务未返回继续后的 Agent 会话')
    agentSession.value = session
    restoreAgentOcrPipeline(session)
    glossaryTextDirty.value = false
    glossaryAutosave.reset()
    openedGlossaryReviewKey.value = ''
    activeView.value = 'agent'
    setStatus(agentStatus, 'Glossary 已保存，Agent 继续处理翻译...', 'ok')
    await loadAgentSessions()
    await loadAgentTasks()
    scheduleAgentPoll(session.id, 500)
    return true
  } catch (error) {
    activeView.value = 'glossary'
    setStatus(flowStatus, `无法保存并继续翻译：${error.message}。修改仍保留在当前页面。`, 'bad')
    setStatus(agentStatus, `Glossary 继续失败：${error.message}`, 'bad')
    return false
  } finally {
    glossaryContinueBusy.value = false
  }
}

async function saveGlossaryAutosavePayload(payload) {
  const result = await api('/api/write-glossary-items', { path: payload.path, items: payload.items })
  const stillLatest = payload.path === loadedGlossaryPath.value
    && JSON.stringify(payload.items) === JSON.stringify(glossaryItems.value)
  if (stillLatest && !glossaryTextDirty.value && result.content) glossaryEditor.value = result.content
  return result
}

function cloneGlossaryItems(items) {
  return JSON.parse(JSON.stringify(items || []))
}

function currentGlossaryItemsPayload() {
  const path = loadedGlossaryPath.value
  if (!path || !glossaryReviewReady.value) return null
  return { path, items: cloneGlossaryItems(glossaryItems.value) }
}

function scheduleGlossaryItemsAutosave() {
  const payload = currentGlossaryItemsPayload()
  if (payload && !glossaryLoading.value && !glossaryContinueBusy.value) glossaryAutosave.markDirty(payload)
}

function retryGlossaryAutosave() {
  if (glossaryContinueBusy.value) return
  glossaryAutosave.retry()
}

function onGlossaryBeforeUnload(event) {
  if (!glossaryTextDirty.value && !['dirty', 'saving', 'error'].includes(glossarySaveState.value)) return
  event.preventDefault()
  event.returnValue = ''
}

function updateGlossaryEditor(value) {
  glossaryEditor.value = value
  glossaryTextDirty.value = true
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
    assets.ocr_debug_folders = result.ocr_debug_folders || []
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

async function uploadProjectCoverFile({ project, file }) {
  if (!project?.path || !file) return
  setStatus(assetStatus, '正在上传封面...', '')
  try {
    const result = await uploadProjectCover(file, { projectPath: project.path })
    await loadAssets()
    setStatus(assetStatus, `封面已更新：${result.thumbnail_path}`, 'ok')
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
  if (result.source_track_refined_srt) sourceSrt.value = result.source_track_refined_srt
  if (result.source_layered_srt) {
    sourceSrt.value = result.source_layered_srt
    setStatus(ocrDevStatus, `分层精修完成：${result.source_layered_srt}`, 'ok')
  }
  const geometrySrt = result.source_geometry_refined_srt || result.geometry_srt
  if (geometrySrt) {
    sourceSrt.value = geometrySrt
    setStatus(ocrDevStatus, `几何精修完成：${geometrySrt}`, 'ok')
  }
  const v3RefinedSrt = result.source_v3_refined_srt || result.v3_refined_srt
  const v3LayeredSrt = result.source_v3_layered_srt || result.v3_layered_srt
  if (v3RefinedSrt) {
    sourceSrt.value = v3RefinedSrt
    setStatus(ocrDevStatus, `3.0 文字精修完成：${v3RefinedSrt}`, 'ok')
  }
  if (v3LayeredSrt) {
    sourceSrt.value = v3LayeredSrt
    setStatus(ocrDevStatus, `3.0 文字 + 分层精修完成：${v3LayeredSrt}`, 'ok')
  }
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

async function editSubtitle(payload) {
  const path = typeof payload === 'object' ? payload?.path : payload
  const videoPath = typeof payload === 'object' ? payload?.videoPath : ''
  const nextSubtitlePath = path || sourceSrt.value || ''
  const isSameSubtitle = nextSubtitlePath === subtitleEditorPath.value
  subtitleEditorPath.value = nextSubtitlePath
  subtitleEditorVideoPath.value = videoPath || inferVideoForSubtitle(nextSubtitlePath) || (isSameSubtitle ? subtitleEditorVideoPath.value : '')
  activeView.value = 'subtitle-edit'
  if (subtitleEditorPath.value) {
    await loadSubtitleEditor()
  }
}

function inferVideoForSubtitle(path) {
  const subtitlePath = String(path || '')
  if (!subtitlePath) return ''
  const project = (assets.projects || []).find((item) => subtitlePath.startsWith(`${item.path}/`) || subtitlePath === item.path)
  if (project?.primary_video) return project.primary_video
  if (project?.videos?.[0]?.path) return project.videos[0].path
  const ocrJob = (assets.ocr_jobs || []).find((item) => [item.source_srt, item.translated_srt].includes(subtitlePath))
  return ocrJob?.input_video || ''
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
    subtitleEditorCues.value = renumberSubtitleCues(result.cues || [])
    subtitleEditorSavedCues.value = cloneSubtitleEditorCues(subtitleEditorCues.value)
    if (!subtitleEditorVideoPath.value) subtitleEditorVideoPath.value = inferVideoForSubtitle(result.path)
    subtitleEditorDirty.value = false
    subtitlePairIssues.value = []
    subtitleFocusedCueUid.value = ''
    subtitleEditorUndoStack.value = []
    subtitleEditorPendingFieldEdit.value = null
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
  const emptyCueIndex = subtitleEditorCues.value.findIndex((cue) => !String(cue.text || '').trim())
  if (emptyCueIndex >= 0) {
    setStatus(subtitleEditorStatus, `第 ${emptyCueIndex + 1} 条字幕还是空的，请填写文字或删除后再保存。`, 'bad')
    await focusSubtitleEditorCue(subtitleEditorCues.value[emptyCueIndex].uid)
    return
  }
  let normalizedCues
  try {
    normalizedCues = renumberSubtitleCues(subtitleEditorCues.value)
  } catch (error) {
    setStatus(subtitleEditorStatus, error.message, 'bad')
    return
  }
  subtitleEditorLoading.value = true
  setStatus(subtitleEditorStatus, overwrite ? '正在覆盖保存字幕...' : '正在另存 edited 字幕...', '')
  try {
    const result = await api('/api/subtitle/write', {
      path: subtitleEditorPath.value.trim(),
      overwrite,
      cues: normalizedCues,
    })
    subtitleEditorPath.value = result.path
    sourceSrt.value = result.path
    subtitleEditorCues.value = renumberSubtitleCues(result.cues || [])
    subtitleEditorSavedCues.value = cloneSubtitleEditorCues(subtitleEditorCues.value)
    subtitleEditorDirty.value = false
    subtitlePairIssues.value = []
    subtitleFocusedCueUid.value = ''
    subtitleEditorPendingFieldEdit.value = null
    setStatus(subtitleEditorStatus, `已保存 ${result.count || 0} 条字幕：${result.path}`, 'ok')
    await loadAssets()
  } catch (error) {
    setStatus(subtitleEditorStatus, error.message, 'bad')
  } finally {
    subtitleEditorLoading.value = false
  }
}

function beginSubtitleEditorCueEdit({ uid, field }) {
  if (!subtitleEditorCues.value.some((cue) => cue.uid === uid)) return
  if (!['start_time', 'end_time', 'text'].includes(field)) return
  const key = `${uid}:${field}`
  if (subtitleEditorPendingFieldEdit.value?.key === key) return
  subtitleEditorPendingFieldEdit.value = {
    key,
    uid,
    field,
    label: subtitleEditorFieldEditLabel(field),
    cues: cloneSubtitleEditorCues(subtitleEditorCues.value),
    recorded: false,
  }
}

function endSubtitleEditorCueEdit({ uid, field }) {
  if (subtitleEditorPendingFieldEdit.value?.key === `${uid}:${field}`) {
    subtitleEditorPendingFieldEdit.value = null
  }
}

function updateSubtitleEditorCue({ uid, patch }) {
  const target = subtitleEditorCues.value.find((cue) => cue.uid === uid)
  if (!target || !patch || typeof patch !== 'object') return
  const changedFields = Object.keys(patch).filter((field) => target[field] !== patch[field])
  if (!changedFields.length) return

  const pending = subtitleEditorPendingFieldEdit.value
  if (pending && pending.uid === uid && changedFields.includes(pending.field)) {
    if (!pending.recorded) {
      pushSubtitleEditorUndo(pending.label, pending.cues)
      pending.recorded = true
    }
  } else {
    pushSubtitleEditorUndo(subtitleEditorFieldEditLabel(changedFields[0]))
  }

  subtitleEditorCues.value = subtitleEditorCues.value.map((cue) => {
    if (cue.uid !== uid) return cue
    const nextCue = { ...cue, ...patch }
    if (Object.prototype.hasOwnProperty.call(patch, 'start_time')) {
      try {
        nextCue.start = parseSrtTime(patch.start_time)
      } catch {
        // Keep the raw value while the user is still typing; save validates it.
      }
    }
    if (Object.prototype.hasOwnProperty.call(patch, 'end_time')) {
      try {
        nextCue.end = parseSrtTime(patch.end_time)
      } catch {
        // Keep the raw value while the user is still typing; save validates it.
      }
    }
    return nextCue
  })
  refreshSubtitleEditorDirty()
  subtitlePairIssues.value = []
}

function subtitleEditorFieldEditLabel(field) {
  if (field === 'start_time') return '修改开始时间'
  if (field === 'end_time') return '修改结束时间'
  return '修改字幕文字'
}

async function addSubtitleEditorCueAtTime(currentTime) {
  try {
    pushSubtitleEditorUndo('新增字幕')
    const result = insertSubtitleCueAtTime(subtitleEditorCues.value, currentTime)
    applySubtitleEditorMutation(result.cues, result.cueUid)
    setStatus(subtitleEditorStatus, `已在 ${result.cue.start_time} 新增字幕，请填写文字并设置结束时间。`, 'ok')
    await focusSubtitleEditorCue(result.cueUid)
  } catch (error) {
    discardLastSubtitleEditorUndo()
    setStatus(subtitleEditorStatus, error.message, 'bad')
  }
}

async function insertSubtitleEditorCue(uid, direction) {
  try {
    pushSubtitleEditorUndo(direction === 'before' ? '前插字幕' : '后插字幕')
    const result = insertSubtitleCueRelative(subtitleEditorCues.value, uid, direction)
    applySubtitleEditorMutation(result.cues, result.cueUid)
    setStatus(subtitleEditorStatus, `已${direction === 'before' ? '前插' : '后插'}一条字幕，请填写文字。`, 'ok')
    await focusSubtitleEditorCue(result.cueUid)
  } catch (error) {
    discardLastSubtitleEditorUndo()
    setStatus(subtitleEditorStatus, error.message, 'bad')
  }
}

function setSubtitleEditorCueBoundary(uid, boundary, currentTime) {
  try {
    pushSubtitleEditorUndo(boundary === 'start' ? '设置开始时间' : '设置结束时间')
    const result = setSubtitleCueBoundary(subtitleEditorCues.value, uid, boundary, currentTime)
    applySubtitleEditorMutation(result.cues, uid)
    setStatus(subtitleEditorStatus, `已用播放器当前时间设置${boundary === 'start' ? '开始' : '结束'}。`, 'ok')
  } catch (error) {
    discardLastSubtitleEditorUndo()
    setStatus(subtitleEditorStatus, error.message, 'bad')
  }
}

function nudgeSubtitleEditorCue(uid, boundary, delta) {
  const cue = subtitleEditorCues.value.find((item) => item.uid === uid)
  if (!cue) return
  let undoPushed = false
  try {
    const current = parseSrtTime(boundary === 'start' ? cue.start_time : cue.end_time)
    pushSubtitleEditorUndo(`微调${boundary === 'start' ? '开始' : '结束'}时间`)
    undoPushed = true
    const result = setSubtitleCueBoundary(subtitleEditorCues.value, uid, boundary, current + Number(delta || 0))
    applySubtitleEditorMutation(result.cues, uid)
  } catch (error) {
    if (undoPushed) discardLastSubtitleEditorUndo()
    setStatus(subtitleEditorStatus, error.message, 'bad')
  }
}

function snapSubtitleEditorCue(uid, boundary, direction) {
  const index = subtitleEditorCues.value.findIndex((cue) => cue.uid === uid)
  const neighbor = direction === 'prev' ? subtitleEditorCues.value[index - 1] : subtitleEditorCues.value[index + 1]
  if (index < 0 || !neighbor) return
  let undoPushed = false
  try {
    const targetTime = parseSrtTime(direction === 'prev' ? neighbor.end_time : neighbor.start_time)
    pushSubtitleEditorUndo(boundary === 'start' ? '开始时间接上条' : '结束时间接下条')
    undoPushed = true
    const result = setSubtitleCueBoundary(subtitleEditorCues.value, uid, boundary, targetTime)
    applySubtitleEditorMutation(result.cues, uid)
  } catch (error) {
    if (undoPushed) discardLastSubtitleEditorUndo()
    setStatus(subtitleEditorStatus, error.message, 'bad')
  }
}

function applySubtitleEditorMutation(cues, focusedUid = '') {
  subtitleEditorCues.value = renumberSubtitleCues(cues)
  refreshSubtitleEditorDirty()
  subtitlePairIssues.value = []
  subtitleFocusedCueUid.value = focusedUid
}

function discardLastSubtitleEditorUndo() {
  subtitleEditorUndoStack.value = subtitleEditorUndoStack.value.slice(0, -1)
}

function deleteSubtitleEditorCue(uid) {
  if (!subtitleEditorCues.value.some((cue) => cue.uid === uid)) return
  try {
    pushSubtitleEditorUndo('删除字幕')
    applySubtitleEditorMutation(subtitleEditorCues.value.filter((cue) => cue.uid !== uid))
  } catch (error) {
    discardLastSubtitleEditorUndo()
    setStatus(subtitleEditorStatus, error.message, 'bad')
  }
}

function mergeSubtitleEditorCue(uid, direction) {
  const index = subtitleEditorCues.value.findIndex((cue) => cue.uid === uid)
  if (index < 0) return
  const targetIndex = direction === 'prev' ? index - 1 : index + 1
  if (targetIndex < 0 || targetIndex >= subtitleEditorCues.value.length) return
  try {
    pushSubtitleEditorUndo('合并字幕')
    const firstIndex = Math.min(index, targetIndex)
    const secondIndex = Math.max(index, targetIndex)
    const first = subtitleEditorCues.value[firstIndex]
    const second = subtitleEditorCues.value[secondIndex]
    const merged = {
      ...first,
      end: parseSrtTime(second.end_time),
      end_time: second.end_time,
      text: joinSubtitleText(first.text, second.text),
    }
    const next = [...subtitleEditorCues.value]
    next.splice(firstIndex, 2, merged)
    applySubtitleEditorMutation(next, merged.uid)
  } catch (error) {
    discardLastSubtitleEditorUndo()
    setStatus(subtitleEditorStatus, error.message, 'bad')
  }
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
  refreshSubtitleEditorDirty()
}

function stripAllSubtitleEditorBreaks() {
  const next = subtitleEditorCues.value.map((cue) => ({
    ...cue,
    text: normalizeSubtitleLine(cue.text),
  }))
  if (!subtitleCuesChanged(subtitleEditorCues.value, next)) return
  pushSubtitleEditorUndo('全部去异常换行')
  subtitleEditorCues.value = next
  refreshSubtitleEditorDirty()
}

function removeEmptySubtitleEditorCues() {
  const next = subtitleEditorCues.value.filter((cue) => String(cue.text || '').trim())
  if (next.length === subtitleEditorCues.value.length) return
  pushSubtitleEditorUndo('删除空字幕')
  applySubtitleEditorMutation(next)
}

function stripSubtitleEditorTrailingCommas() {
  const result = stripCueTrailingCommas(subtitleEditorCues.value)
  if (!result.changedCueCount) {
    setStatus(subtitleEditorStatus, '未发现结尾逗号。', '')
    return
  }
  pushSubtitleEditorUndo('删除结尾逗号')
  subtitleEditorCues.value = result.cues
  refreshSubtitleEditorDirty()
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
  refreshSubtitleEditorDirty()
  setStatus(subtitleEditorStatus, `已处理 ${result.changedCueCount} 条字幕，删除 ${result.removedPrefixCount} 个名前缀。`, 'ok')
}

function pushSubtitleEditorUndo(label, cues = subtitleEditorCues.value) {
  subtitleEditorUndoStack.value = [
    ...subtitleEditorUndoStack.value,
    {
      label,
      cues: cloneSubtitleEditorCues(cues),
      focusedCueUid: subtitleFocusedCueUid.value,
    },
  ].slice(-50)
}

function undoSubtitleEditorChange() {
  const stack = [...subtitleEditorUndoStack.value]
  const snapshot = stack.pop()
  if (!snapshot) return
  subtitleEditorPendingFieldEdit.value = null
  subtitleEditorUndoStack.value = stack
  subtitleEditorCues.value = cloneSubtitleEditorCues(snapshot.cues)
  subtitlePairIssues.value = []
  subtitleFocusedCueUid.value = subtitleEditorCues.value.some((cue) => cue.uid === snapshot.focusedCueUid)
    ? snapshot.focusedCueUid
    : ''
  refreshSubtitleEditorDirty()
  setStatus(subtitleEditorStatus, `已撤销：${snapshot.label}`, 'ok')
}

function onSubtitleEditorUndoShortcut(event) {
  if (activeView.value !== 'subtitle-edit' || subtitleEditorLoading.value) return
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z' || event.shiftKey || event.altKey) return
  const target = event.target
  if (target instanceof HTMLElement && (target.matches('input, textarea, [contenteditable="true"]') || target.closest('[contenteditable="true"]'))) return
  if (!subtitleEditorUndoStack.value.length) return
  event.preventDefault()
  undoSubtitleEditorChange()
}

function refreshSubtitleEditorDirty() {
  subtitleEditorDirty.value = subtitleCuesChanged(subtitleEditorSavedCues.value, subtitleEditorCues.value)
}

function cloneSubtitleEditorCues(cues) {
  return (cues || []).map((cue) => ({ ...cue }))
}

function subtitleCuesChanged(left, right) {
  const leftCues = left || []
  const rightCues = right || []
  if (leftCues.length !== rightCues.length) return true
  return leftCues.some((cue, index) => cue.text !== rightCues[index]?.text || cue.start_time !== rightCues[index]?.start_time || cue.end_time !== rightCues[index]?.end_time)
}

function normalizeSubtitleLine(text) {
  return String(text || '').replace(/\s*\n+\s*/g, ' ').replace(/[ \t]{2,}/g, ' ').trim()
}

function joinSubtitleText(left, right) {
  return [normalizeSubtitleLine(left), normalizeSubtitleLine(right)].filter(Boolean).join(' ')
}

function updateGlossaryZh({ index, zh }) {
  glossaryItems.value = glossaryItems.value.map((item, itemIndex) => itemIndex === index ? { ...item, zh } : item)
  scheduleGlossaryItemsAutosave()
}

function setGlossaryReviewed({ index, reviewed }) {
  glossaryItems.value = glossaryItems.value.map((item, itemIndex) => itemIndex === index ? { ...item, reviewed } : item)
  scheduleGlossaryItemsAutosave()
}

function useSuggestion(index) {
  const item = glossaryItems.value[index]
  if (!item?.suggested_zh) return
  glossaryItems.value = glossaryItems.value.map((entry, itemIndex) => (
    itemIndex === index ? { ...entry, zh: item.suggested_zh, reviewed: true } : entry
  ))
  scheduleGlossaryItemsAutosave()
}

function applyAllSuggestions() {
  glossaryItems.value = glossaryItems.value.map((item) => {
    if (!item.zh && item.suggested_zh) {
      return { ...item, zh: item.suggested_zh, reviewed: true }
    }
    return item
  })
  scheduleGlossaryItemsAutosave()
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
