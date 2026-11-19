<template>
  <div class="app-frame" :class="{ 'sidebar-open': sidebarOpen }" @keydown.esc="closeMobileNavigation">
    <button v-if="sidebarOpen" class="sidebar-backdrop" type="button" aria-label="关闭导航" @click="sidebarOpen = false"></button>
    <SideNav :active-view="activeView" :items="navItems" :sessions="agentSessions" :selected-session-id="newAgentDraft ? '' : agentSession?.id || ''" @select="navigateTo" @new-task="openNewAgentDraft" @select-session="openSidebarSession" @close="sidebarOpen = false" />

    <div class="app-content">
      <HeaderBar
        :title="activePage.title"
        :sidebar-open="sidebarOpen"
        @toggle-sidebar="sidebarOpen = !sidebarOpen"
      />

      <main class="workspace" :class="{ 'workspace-single': activeView !== 'jobs' }">
        <section class="workspace-main">
          <div v-if="activeView === 'agent'" class="page-stack">
            <AgentSessionPanel
              v-model:agent-mode="agentMode"
              v-model:url="url"
              v-model:embedded-subtitle-hint="embeddedSubtitleHint"
              v-model:embedded-subtitle-goal="embeddedSubtitleGoal"
              v-model:source-language="agentSourceLanguage"
              v-model:target-language="agentTargetLanguage"
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
              :input-video="newAgentDraft ? '' : agentPreviewVideo"
              v-model:extra-hint="extraHint"
              :session="newAgentDraft ? null : agentSession"
              :sessions="agentSessions"
              :starting="agentStarting"
              :status="agentStatus.text"
              :status-class="agentStatus.class"
              @start-agent="startAgent"
              @answer-agent="answerAgent"
              @cancel-agent="cancelAgent"
              @retry-agent="retryAgent"
              @select-agent="selectAgentSession"
              @open-task-history="activeView = 'task-history'"
              @open-glossary="openGlossaryFromAgent"
              @new-task="openNewAgentDraft"
              @open-view="navigateTo"
            />
          </div>

          <div v-else-if="activeView === 'task-history'" class="page-stack">
            <TaskHistoryPanel
              :tasks="agentTasks"
              :loading="agentTasksLoading"
              :busy-task-id="taskHistoryBusyId"
              :status="taskHistoryStatus.text"
              :status-class="taskHistoryStatus.class"
              @refresh="refreshAgentTasks"
              @continue-task="continueTaskFromHistory"
              @rerun-task="rerunTaskFromHistory"
              @restart-task="restartTaskFromHistory"
              @complete-task="completeTaskFromHistory"
              @reopen-task="reopenTaskFromHistory"
              @delete-task="deleteTaskFromHistory"
              @open-glossary="openTaskHistoryGlossary"
              @open-artifact="openTaskArtifact"
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
              :available-video-formats="availableVideoFormats"
              :video-formats-loading="videoFormatsLoading"
              :video-formats-status="videoFormatsStatus.text"
              :video-formats-status-class="videoFormatsStatus.class"
              :probing="probing"
              :action-busy="linkActionBusy"
              :status="probeStatus.text"
              :status-class="probeStatus.class"
              @probe="probeVideo"
              @load-video-formats="loadVideoFormats"
              @download-video="downloadVideo"
              @download-thumbnail="downloadThumbnail"
              @ocr-full="runOcrFull"
            />

            <VideoInfoPanel
              v-if="probe"
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
              :assets="assets"
              :status="assetStatus.text"
              :status-class="assetStatus.class"
              :upload-busy="materialUploadBusy"
              @refresh="loadAssets(true)"
              @local-ocr="runLocalOcr"
              @open-asr-lab="openAsrLab"
              @upload-media="uploadLocalMedia"
              @register-local-project="registerLocalProject"
              @use-project="useProject"
              @use-video="useVideo"
              @use-audio="useAudio"
              @use-media-asr="openMediaInAsrLab"
              @use-video-ocr="useVideoAndOcr"
              @use-subtitle="useSubtitle"
              @edit-subtitle="editSubtitle"
              @delete-project="deleteDownloadProject"
              @upload-cover="uploadProjectCoverFile"
            />
          </div>

          <div v-else-if="activeView === 'video-overlay'" class="page-stack">
            <VideoOverlayPanel v-model:input-video="localVideo" @open-assets="navigateTo('assets')" @run="runVideoOverlay" />
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
              @refresh-debug-assets="loadAssets(true)"
            />
          </div>

          <div v-else-if="activeView === 'asr-dev'" class="page-stack">
            <AsrLabPanel
              v-model:input-video="localVideo"
              v-model:asr-version="asrLabVersion"
              v-model:test-ranges="asrLabTestRanges"
              v-model:source-language="asrLabSourceLanguage"
              v-model:model-size="asrLabModelSize"
              v-model:speaker-diarization="asrLabSpeakerDiarization"
              v-model:known-speaker-count="asrLabKnownSpeakerCount"
              v-model:hotwords="asrLabHotwords"
              v-model:high-recall="asrLabHighRecall"
              v-model:dual-gpu-parallel="asrLabDualGpuParallel"
              :running="asrLabRunning"
              :review-busy-id="asrLabReviewBusyId"
              :result="asrLabResult"
              :status="asrLabStatus.text"
              :status-class="asrLabStatus.class"
              @open-assets="activeView = 'assets'"
              @run="runAsrLab"
              @copy-status="handleAsrLabCopyStatus"
              @review-decision="handleAsrReviewDecision"
            />
          </div>

          <div v-else-if="activeView === 'subtitles'" class="page-stack">
            <TranslationFlow
              v-model:target-language="subtitleTargetLanguage"
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
              @open-assets="navigateTo('assets')"
            />
          </div>

          <div v-else-if="activeView === 'subtitle-edit'" class="page-stack">
            <SubtitleEditorPanel
              ref="subtitleEditorPanel"
              v-model:subtitle-path="subtitleEditorPath"
              v-model:video-path="subtitleEditorVideoPath"
              :cues="subtitleEditorCues"
              :loading="subtitleEditorLoading"
              :dirty="subtitleEditorDirty"
              :save-ready="subtitleEditorSaveReady"
              :status="subtitleEditorStatus.text"
              :status-class="subtitleEditorStatus.class"
              :prefix-names="subtitlePrefixNames"
              :speaker-candidates="subtitleSpeakerCandidates"
              :selected-speaker-candidate-ids="subtitleSelectedSpeakerCandidateIds"
              :pair-issues="subtitlePairIssues"
              :focused-cue-uid="subtitleFocusedCueUid"
              :can-undo="subtitleEditorUndoStack.length > 0"
              :undo-count="subtitleEditorUndoStack.length"
              @update:prefix-names="subtitlePrefixNames = $event"
              @toggle-speaker-candidate="toggleSubtitleSpeakerCandidate"
              @strip-speaker-candidates="stripDetectedSubtitleSpeakerPrefixes"
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
              @focus-pair-issue="focusSubtitleEditorCue"
              @copy-pair-symbol="copySubtitleEditorPairSymbol"
              @repair-pair-issue="repairSubtitleEditorPairIssue"
              @repair-auto-pair-issues="repairAutomaticSubtitleEditorPairIssues"
              @remove-empty="removeEmptySubtitleEditorCues"
              @strip-prefixes="stripSubtitleEditorPrefixes"
              @undo="undoSubtitleEditorChange"
              @open-assets="navigateTo('assets')"
            />
          </div>

          <div v-else-if="activeView === 'glossary'" class="page-stack">
            <GlossaryReviewPanel
              :target-language="glossaryTargetLanguage"
              v-model:glossary-path="glossaryPath"
              :glossary-editor="glossaryEditor"
              :glossary-items="glossaryItems"
              :loading="glossaryLoading"
              :candidate-status="glossaryCandidateStatus"
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
              @retry-candidates="prepareGlossaryCandidates(loadedGlossaryPath, glossaryLoadGeneration, true)"
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
import { api, deleteJson, getJson, patchJson, uploadMediaFile, uploadProjectCover } from './api'
import SideNav from './components/SideNav.vue'
import HeaderBar from './components/HeaderBar.vue'
import AgentSessionPanel from './components/AgentSessionPanel.vue'
import TaskHistoryPanel from './components/TaskHistoryPanel.vue'
import VideoInputPanel from './components/VideoInputPanel.vue'
import VideoInfoPanel from './components/VideoInfoPanel.vue'
import TranslationFlow from './components/TranslationFlow.vue'
import GlossaryReviewPanel from './components/GlossaryReviewPanel.vue'
import SubtitleEditorPanel from './components/SubtitleEditorPanel.vue'
import AssetLibrary from './components/AssetLibrary.vue'
import VideoOverlayPanel from './components/VideoOverlayPanel.vue'
import OcrDevPanel from './components/OcrDevPanel.vue'
import AsrLabPanel from './components/AsrLabPanel.vue'
import JobSidebar from './components/JobSidebar.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import { copyText } from './clipboard.js'
import { canPresentAgentSession, createAgentSessionPoller } from './agentSessionPolling.js'
import {
  DEFAULT_AGENT_OCR_PIPELINE_VERSION,
  buildAgentOcrPipelinePayload,
  inferAgentOcrPipelineVersion,
} from './agentOcrPipeline.js'
import { createGlossaryReviewAutosave } from './glossaryReviewAutosave.js'
import { mergeGlossaryCandidates } from './glossaryCandidates.js'
import {
  isProbeResponseCurrent,
  looksLikeVideoInput,
  resolveLinkActionUrl,
  selectedVideoFormat,
  shouldClearLinkProbe,
} from './linkToolState.js'
import { translationDefaults } from './translationLanguages.js'
import {
  canReuseOpenedGlossaryReview,
  findGlossaryReviewSession,
  glossaryReviewKey,
  isGlossaryReviewPathForSession,
} from './glossaryReviewFlow.js'
import {
  applyCuePairIssueRepairs,
  applySpeakerPrefixCandidates,
  detectCuePairSymbolIssues,
  detectCueSpeakerPrefixCandidates,
  parsePrefixNames,
  stripCueSpeakerPrefixes,
  stripCueTrailingCommas,
} from './subtitlePrefixTools.js'
import {
  insertSubtitleCueAtTime,
  insertSubtitleCueRelative,
  isSubtitleEditorSavePathReady,
  parseSrtTime,
  renumberSubtitleCues,
  setSubtitleCueBoundary,
} from './subtitleEditorTools.js'

const url = ref('')
const probe = ref(null)
const probing = ref(false)
const probedInputUrl = ref('')
const linkActionBusy = ref('')
let linkProbeSequence = 0
const titleBox = ref('')
const sourceSrt = ref('')
const subtitleEditorPath = ref('')
const subtitleEditorLoadedPath = ref('')
const subtitleEditorVideoPath = ref('')
const subtitleEditorCues = ref([])
const subtitlePrefixNames = ref('')
const subtitleSpeakerDictionary = ref([])
const subtitleSpeakerCandidates = ref([])
const subtitleSelectedSpeakerCandidateIds = ref([])
const subtitlePairIssues = ref([])
const subtitleFocusedCueUid = ref('')
const subtitleEditorUndoStack = ref([])
const subtitleEditorSavedCues = ref([])
const subtitleEditorPendingFieldEdit = ref(null)
const subtitleEditorLoading = ref(false)
const subtitleEditorDirty = ref(false)
const subtitleEditorSaveReady = computed(() => isSubtitleEditorSavePathReady(
  subtitleEditorPath.value,
  subtitleEditorLoadedPath.value,
))
const glossaryPath = ref('')
const extraHint = ref('')
const glossaryEditor = ref('')
const glossaryItems = ref([])
const glossaryTargetLanguage = ref('zh')
const subtitleTargetLanguage = ref('zh')
const glossaryLoading = ref(false)
const glossaryCandidateStatus = ref({ state: 'ready', total: 0, ready: 0, pending: 0, failed: 0 })
const loadedGlossaryPath = ref('')
const glossaryTextDirty = ref(false)
const glossarySaveState = ref('idle')
const glossaryContinueBusy = ref(false)
let glossaryLoadGeneration = 0
let glossaryLoadFailure = ''
const subtitleTranslationMode = ref('translate_only')
const subtitleConvertFormat = ref('bcc')
const ocrTranslationMode = ref('standard_cleanup')
const ocrScope = ref('bottom')
const ocrExtractionMode = ref('auto')
const ocrShapeMode = ref('horizontal_preferred')
const agentOcrPipelineVersion = ref(DEFAULT_AGENT_OCR_PIPELINE_VERSION)
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
const asrLabSourceLanguage = ref('auto')
const agentMode = ref('autonomous')
const asrLabModelSize = ref('large-v3')
const asrLabVersion = ref('2.0')
const asrLabExperimental = computed(() => ['agent-experimental', 'autonomous-experimental'].includes(asrLabVersion.value))
const asrLabTestRanges = ref([{ start: '00:00', end: '01:30' }])
const asrLabSpeakerDiarization = ref(false)
const asrLabKnownSpeakerCount = ref('auto')
const asrLabHotwords = ref('')
const asrLabHighRecall = ref(true)
const asrLabDualGpuParallel = ref(false)
const asrLabRunning = ref(false)
const asrLabReviewBusyId = ref('')
const asrLabResult = ref(null)
const asrLabJobId = ref('')
const ocrRefinementMode = ref('none')
const thumbnailFormat = ref('jpg')
const videoQuality = ref('1080p')
const availableVideoFormats = ref([])
const videoFormatsTitle = ref('')
const videoFormatsLoading = ref(false)
let videoFormatsRequestSequence = 0
let videoFormatsTimer = null
const embeddedSubtitleHint = ref('unknown')
const embeddedSubtitleGoal = ref('screen_subtitle')
const sourceLanguage = ref('korean')
const agentSourceOverride = ref(null)
const agentTargetOverride = ref(null)
const agentSourceLanguage = computed({
  get: () => agentSourceOverride.value ?? translationDefaults(url.value, sourceLanguage.value).source,
  set: (value) => { agentSourceOverride.value = value },
})
const agentTargetLanguage = computed({
  get: () => agentTargetOverride.value ?? translationDefaults(url.value).target,
  set: (value) => { agentTargetOverride.value = value },
})
const ocrLanguage = ref('auto')
const localVideo = ref('')
const activeJobId = ref('')
const activeView = ref('agent')
const sidebarOpen = ref(window.innerWidth > 760)
const newAgentDraft = ref(false)
const agentSession = ref(null)
const agentSessions = ref([])
const agentTasks = ref([])
const agentTasksLoading = ref(false)
const taskHistoryBusyId = ref('')
const agentStarting = ref(false)
const openedGlossaryReviewKey = ref('')
const openingGlossaryReviewKey = ref('')
const materialUploadBusy = ref(false)
const settingsEditor = ref(null)
const subtitleEditorPanel = ref(null)
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
let settingsModelFetchSequence = 0
const settingsModelFetchTokens = new Map()

const assets = reactive({ videos: [], audios: [], subtitles: [], projects: [], ocr_jobs: [], ocr_debug_folders: [] })
const jobs = reactive({})
const pollTimers = new Map()

const probeStatus = reactive({ text: '', class: '' })
const videoFormatsStatus = reactive({ text: '', class: '' })
const titleStatus = reactive({ text: '', class: '' })
const flowStatus = reactive({ text: '', class: '' })
const subtitleEditorStatus = reactive({ text: '', class: '' })
const ocrDevStatus = reactive({ text: '', class: '' })
const asrLabStatus = reactive({ text: '', class: '' })
const assetStatus = reactive({ text: '', class: '' })
const agentStatus = reactive({ text: '', class: '' })
const taskHistoryStatus = reactive({ text: '', class: '' })
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
    title: '字幕助手',
    description: '自动判断字幕来源，提取原文，审核术语并完成翻译。',
  },
  'task-history': {
    title: '任务历史',
    description: '持久保存 Agent 流程、阶段结果和旧轮次，可继续处理或按阶段重新运行。',
  },
  'new-task': {
    title: '下载与链接',
    description: '粘贴链接即可直接下载；需要字幕信息时再检测，也可进入 OCR 全流程。',
  },
  assets: {
    title: '素材库',
    description: '管理已下载视频、字幕文件、OCR 和音频识别输出。',
  },
  'video-overlay': {
    title: '视频处理',
    description: '镜像、裁剪、调整尺寸，或给当前视频叠加水印与遮挡。',
  },
  subtitles: {
    title: '翻译与转换',
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
  'asr-dev': {
    title: 'ASR Lab',
    description: '测试语音识别；原有 ASR 2.2 提取文本，实验 Agent 可复核、翻译并校准时间轴。',
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
const taskAttentionCount = computed(() => agentTasks.value.filter((task) => {
  if (task.is_completed || task.workflow_status === 'completed') return false
  const current = String(task.current_stage || '')
  const stages = task.stage_items || []
  const failed = task.status === 'failed'
    || task.workflow_status === 'failed'
    || current.endsWith('_failed')
    || stages.some((stage) => stage.status === 'failed')
  if (failed) return false
  if (['waiting', 'needs_input', 'interrupted'].includes(String(task.status || ''))) return true
  if (/(review|confirm|waiting|interrupted|attention)/.test(current)) return true
  return stages.some((stage) => ['waiting', 'waiting_review', 'needs_input', 'interrupted'].includes(stage.status))
}).length)
const agentPreviewVideo = computed(() => (
  agentSession.value
    ? (agentSession.value.result?.input_video || '')
    : (localVideo.value || '')
))

let skipNextOcrScopeCropReset = false
watch(url, (nextUrl, previousUrl) => {
  if (isProbeResponseCurrent(previousUrl, nextUrl)) return
  linkProbeSequence += 1
  videoFormatsRequestSequence += 1
  if (videoFormatsTimer) {
    window.clearTimeout(videoFormatsTimer)
    videoFormatsTimer = null
  }
  availableVideoFormats.value = []
  videoFormatsTitle.value = ''
  videoFormatsLoading.value = false
  setStatus(videoFormatsStatus, '', '')
  if (String(videoQuality.value || '').startsWith('format:')) videoQuality.value = '1080p'
  if (activeView.value === 'new-task') scheduleVideoFormats(nextUrl)
  const clearedProbe = shouldClearLinkProbe(probe.value, probedInputUrl.value, nextUrl)
  if (clearedProbe) {
    probe.value = null
    probedInputUrl.value = ''
    titleBox.value = ''
    setStatus(titleStatus, '', '')
  }
  if (clearedProbe || probing.value) {
    setStatus(
      probeStatus,
      String(nextUrl || '').trim()
        ? '链接已更改。可直接下载；如需字幕信息，请重新检测。'
        : '',
      '',
    )
  }
})

watch(activeView, (view, previousView) => {
  if (view !== previousView) window.scrollTo(0, 0)
  if (view === 'new-task' && !availableVideoFormats.value.length) scheduleVideoFormats(url.value, 150)
  if (view === 'task-history') refreshAgentTasks()
})

watch(subtitleEditorCues, () => {
  refreshSubtitleEditorMechanicalDiagnostics()
})

watch(ocrScope, (scope) => {
  if (skipNextOcrScopeCropReset) {
    skipNextOcrScopeCropReset = false
    return
  }
  ocrCropTopRatio.value = OCR_SCOPE_TOP_DEFAULTS[scope] ?? 0.58
  ocrCropBottomRatio.value = 0
})

const navItems = computed(() => [
  { id: 'agent', group: '日常流程', label: '字幕助手', badge: waitingAgentCount.value ? `${waitingAgentCount.value} 待确认` : runningAgentCount.value || '' },
  { id: 'task-history', group: '日常流程', label: '所有任务', badge: '' },
  { id: 'assets', group: '日常流程', label: '素材库', badge: '' },
  { id: 'new-task', group: '日常流程', label: '下载与链接', badge: '' },
  { id: 'subtitle-edit', group: '字幕工具', label: '字幕精修', badge: '' },
  { id: 'glossary', group: '字幕工具', label: '术语审核', badge: '' },
  { id: 'subtitles', group: '字幕工具', label: '翻译与转换', badge: '' },
  { id: 'video-overlay', group: '字幕工具', label: '视频处理', badge: '' },
  { id: 'ocr-dev', group: '实验室', label: 'OCR Lab', hint: 'V2 / V3 独立测试', icon: 'O', badge: '' },
  { id: 'asr-dev', group: '实验室', label: 'ASR Lab', hint: '提取音频文本', icon: 'R', badge: asrLabRunning.value ? '运行中' : '' },
  { id: 'settings', group: '系统', label: '设置', hint: '语言、服务与模型', icon: '⚙', badge: '' },
  { id: 'jobs', group: '系统', label: '任务日志', hint: '进度、错误与输出', icon: 'J', badge: runningJobCount.value || failedJobCount.value || '' },
])

function navigateTo(view) {
  activeView.value = view
  if (window.innerWidth <= 760) sidebarOpen.value = false
}

function closeMobileNavigation() {
  if (window.innerWidth <= 760 && sidebarOpen.value) {
    sidebarOpen.value = false
    nextTick(() => document.querySelector('[aria-controls="main-sidebar"]')?.focus())
  }
}

function openNewAgentDraft() {
  // Opening a composer is local navigation; existing tasks keep running.
  newAgentDraft.value = true
  url.value = ''
  agentSourceOverride.value = null
  agentTargetOverride.value = null
  extraHint.value = ''
  if (settingsEditor.value) applyAppSettingDefaults(settingsEditor.value)
  setStatus(agentStatus, '', '')
  navigateTo('agent')
  nextTick(() => document.getElementById('agentUrl')?.focus())
}

async function openSidebarSession(sessionId) {
  navigateTo('agent')
  await selectAgentSession(sessionId)
}

watch(() => agentSession.value?.id, () => { newAgentDraft.value = false })

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
  if (videoFormatsTimer) window.clearTimeout(videoFormatsTimer)
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
    settingsModelFetchTokens.clear()
    settingsFetchingProviderId.value = ''
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
    setStatus(settingsStatus, `${createdId} 已创建，正在获取可用模型…`, 'ok')
    await fetchProviderModels(createdId)
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
    settingsModelFetchTokens.delete(id)
    if (settingsFetchingProviderId.value === id) settingsFetchingProviderId.value = ''
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
    settingsModelErrors.value = { ...settingsModelErrors.value, [id]: '' }
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
    setStatus(settingsStatus, `${id} 的本地连接已保存，正在刷新模型…`, 'ok')
    await fetchProviderModels(id)
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
  const requestToken = ++settingsModelFetchSequence
  settingsModelFetchTokens.set(id, requestToken)
  settingsFetchingProviderId.value = id
  settingsModelErrors.value = { ...settingsModelErrors.value, [id]: '' }
  setStatus(settingsStatus, `正在向 ${id} 获取可用模型...`, '')
  try {
    const result = await getJson(`/api/settings/providers/${encodeURIComponent(id)}/models?refresh=1`)
    if (settingsModelFetchTokens.get(id) !== requestToken) return
    if (!settingsProviders.value.some((provider) => String(provider?.id || '') === id)) return
    const discoveredModels = result.source === 'remote' && Array.isArray(result.remote_models)
      ? result.remote_models
      : (result.models || [])
    settingsModelsByProvider.value = {
      ...settingsModelsByProvider.value,
      [id]: discoveredModels,
    }
    settingsModelErrors.value = {
      ...settingsModelErrors.value,
      [id]: result.warning || '',
    }
    setStatus(
      settingsStatus,
      result.warning
        ? `远端模型获取失败，已保留本地模型：${result.warning}`
        : `已从 ${id} 获取 ${discoveredModels.length} 个模型。`,
      result.warning ? 'bad' : 'ok',
    )
  } catch (error) {
    if (settingsModelFetchTokens.get(id) !== requestToken) return
    settingsModelErrors.value = { ...settingsModelErrors.value, [id]: error.message }
    setStatus(settingsStatus, error.message, 'bad')
  } finally {
    if (settingsModelFetchTokens.get(id) === requestToken) {
      settingsModelFetchTokens.delete(id)
      if (settingsFetchingProviderId.value === id) settingsFetchingProviderId.value = ''
    }
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
      agent_mode: agentMode.value,
      url: url.value.trim(),
      embedded_subtitle_hint: embeddedSubtitleHint.value,
      embedded_subtitle_goal: agentMode.value === 'autonomous' ? 'auto' : embeddedSubtitleGoal.value,
      source_language: agentSourceLanguage.value,
      ocr_language: ocrLanguage.value,
      target_language: agentTargetLanguage.value,
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
    newAgentDraft.value = false
    // The new task must become the sole source of restored OCR settings.
    // Otherwise a previously selected V1/V2 task can leak its shape/refinement
    // settings into the first answer sent to this new V3 session.
    restoreAgentOcrPipeline(session)
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
  const structured = action && typeof action === 'object' ? action : { action }
  setStatus(
    agentStatus,
    action === 'download_video_for_preview'
      ? '正在准备或下载视频；完成后会自动加载首帧并显示位置操作。'
      : '已提交回答，Agent 继续处理...',
    '',
  )
  try {
    const sessionOcrPipelineVersion = inferAgentOcrPipelineVersion(agentSession.value?.payload || {})
    const agentOcrPipeline = buildAgentOcrPipelinePayload(sessionOcrPipelineVersion, {
      ocrScope: ocrScope.value,
      restoredSettings: agentRestoredOcrSettings.value,
    })
    const session = await api(`/api/agent/${agentSession.value.id}/answer`, {
      ...structured,
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
    restoreAgentOcrPipeline(session)
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
  return canPresentAgentSession(agentSession.value?.id, sessionId, newAgentDraft.value)
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
      loadAssets(true)
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
    if (!newAgentDraft.value && !agentSession.value?.id && agentSessions.value.length) {
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
  if (newAgentDraft.value) return false
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

async function loadAgentTasks({ throwOnError = false } = {}) {
  try {
    const result = await getJson('/api/agent-tasks')
    agentTasks.value = result.tasks || []
    return agentTasks.value
  } catch (error) {
    agentTasks.value = agentTasks.value || []
    if (throwOnError) throw error
    return agentTasks.value
  }
}

async function refreshAgentTasks() {
  if (agentTasksLoading.value) return
  agentTasksLoading.value = true
  setStatus(taskHistoryStatus, '正在刷新任务历史...', '')
  try {
    const tasks = await loadAgentTasks({ throwOnError: true })
    setStatus(taskHistoryStatus, `已加载 ${tasks.length} 个持久化任务。`, 'ok')
  } catch (error) {
    setStatus(taskHistoryStatus, `任务历史加载失败：${error.message}`, 'bad')
  } finally {
    agentTasksLoading.value = false
  }
}

async function selectAgentSession(sessionId) {
  try {
    const session = await getJson(`/api/agent/${sessionId}`)
    agentSession.value = session
    newAgentDraft.value = false
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

async function continueTaskFromHistory(taskId) {
  if (!taskId || taskHistoryBusyId.value) return
  taskHistoryBusyId.value = String(taskId)
  setStatus(taskHistoryStatus, '正在恢复任务现场...', '')
  try {
    const liveSession = (agentSessions.value || []).find((session) => (
      ['running', 'waiting'].includes(session.status)
      && String(session.result?.task_id || '') === String(taskId)
    ))
    if (liveSession) {
      const openedGlossaryReview = await selectAgentSession(liveSession.id)
      setStatus(taskHistoryStatus, `已切换到正在运行的任务 ${taskId}。`, 'ok')
      if (!openedGlossaryReview) activeView.value = 'agent'
      return
    }
    const continued = await continueAgentTask(taskId)
    if (!continued) throw new Error(agentStatus.text || '任务恢复失败')
    setStatus(taskHistoryStatus, `任务 ${taskId} 已恢复。`, 'ok')
    if (!continued.openedGlossaryReview) activeView.value = 'agent'
  } catch (error) {
    setStatus(taskHistoryStatus, error.message, 'bad')
  } finally {
    taskHistoryBusyId.value = ''
  }
}

function restoreAgentOcrPipeline(session) {
  const payload = session?.payload || {}
  agentRestoredOcrSettings.value = { ...payload }
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
  if (payload.source_language) { sourceLanguage.value = payload.source_language; agentSourceOverride.value = payload.source_language }
  agentTargetOverride.value = payload.target_language || 'zh'
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
    return session
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
    return null
  }
}

async function rerunTaskFromHistory(payload) {
  const taskId = String(payload?.taskId || '')
  const stage = String(payload?.stage || '')
  if (!taskId || !stage || taskHistoryBusyId.value) return
  const task = agentTasks.value.find((item) => String(item?.id || '') === taskId)
  const title = task?.title || taskId
  const stageLabels = { ocr: '原文字幕', glossary: 'Glossary', translate: '中文字幕' }
  const consequences = {
    ocr: '会重新执行原文字幕提取，并使现有 Glossary 和中文字幕失效；这一步可能耗时较长。',
    glossary: '会重新生成 Glossary，并使现有中文字幕失效；生成后需要重新审核。',
    translate: '会重新调用翻译模型，并替换当前轮次的中文字幕产物。',
  }
  const stageLabel = stageLabels[stage] || stage
  if (!window.confirm(`重跑“${title}”的${stageLabel}阶段？\n\n${consequences[stage] || '该阶段及其下游结果会重新生成。'}`)) return
  taskHistoryBusyId.value = taskId
  setStatus(taskHistoryStatus, `正在启动${stageLabel}阶段重跑...`, '')
  try {
    const session = await rerunAgentTask({ taskId, stage })
    if (!session) throw new Error(agentStatus.text || '阶段重跑启动失败')
    setStatus(taskHistoryStatus, `已启动${stageLabel}阶段重跑。`, 'ok')
    activeView.value = 'agent'
  } catch (error) {
    setStatus(taskHistoryStatus, error.message, 'bad')
  } finally {
    taskHistoryBusyId.value = ''
  }
}

async function restartTaskFromHistory(task) {
  const taskId = String(task?.id || task || '')
  if (!taskId || taskHistoryBusyId.value) return
  const title = typeof task === 'object' ? (task.title || task.id) : taskId
  const generation = Number(task?.run_generation || 1)
  if (!window.confirm(`从头重跑：${title}？\n\n当前第 ${generation} 轮的配置和字幕产物会先归档，然后按原任务配置重新开始。`)) return
  taskHistoryBusyId.value = taskId
  setStatus(taskHistoryStatus, '正在归档当前轮次并从头启动...', '')
  try {
    const session = await api(`/api/agent-tasks/${encodeURIComponent(taskId)}/restart`, {})
    agentSession.value = session
    restoreAgentOcrPipeline(session)
    await loadAgentSessions()
    await loadAgentTasks()
    setStatus(agentStatus, `已从头重跑：${title}`, 'ok')
    setStatus(taskHistoryStatus, `已从头重跑：${title}`, 'ok')
    activeView.value = 'agent'
    scheduleAgentPoll(session.id, 500)
  } catch (error) {
    setStatus(taskHistoryStatus, error.message, 'bad')
  } finally {
    taskHistoryBusyId.value = ''
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
    return true
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
    return false
  }
}

async function completeTaskFromHistory(task) {
  const taskId = String(task?.id || task || '')
  if (!taskId || taskHistoryBusyId.value) return
  taskHistoryBusyId.value = taskId
  setStatus(taskHistoryStatus, '正在标记任务完成...', '')
  try {
    const completed = await completeAgentTask(task)
    setStatus(taskHistoryStatus, completed ? '任务已标记完成。' : (agentStatus.text || '操作失败'), completed ? 'ok' : 'bad')
  } finally {
    taskHistoryBusyId.value = ''
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
    return true
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
    return false
  }
}

async function reopenTaskFromHistory(task) {
  const taskId = String(task?.id || task || '')
  if (!taskId || taskHistoryBusyId.value) return
  taskHistoryBusyId.value = taskId
  setStatus(taskHistoryStatus, '正在恢复为活动任务...', '')
  try {
    const reopened = await reopenAgentTask(task)
    setStatus(taskHistoryStatus, reopened ? '任务已恢复为活动状态。' : (agentStatus.text || '操作失败'), reopened ? 'ok' : 'bad')
  } finally {
    taskHistoryBusyId.value = ''
  }
}

async function deleteAgentTask(task) {
  const taskId = typeof task === 'string' ? task : task?.id
  if (!taskId) return
  const title = typeof task === 'object' ? (task.title || task.id) : taskId
  if (!window.confirm(`删除任务档案：${title}？\n\n只删除任务状态和任务目录，不会删除已下载视频。`)) return false
  try {
    await api(`/api/agent-tasks/${taskId}/delete`, {})
    if (agentSession.value?.result?.task_id === taskId) agentSession.value = null
    await loadAgentTasks()
    await loadAgentSessions()
    setStatus(agentStatus, `已删除任务：${title}`, 'ok')
    return true
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
    return false
  }
}

async function deleteTaskFromHistory(task) {
  const taskId = String(task?.id || task || '')
  if (!taskId || taskHistoryBusyId.value) return
  taskHistoryBusyId.value = taskId
  try {
    const deleted = await deleteAgentTask(task)
    if (deleted) setStatus(taskHistoryStatus, '任务档案已删除；下载素材仍然保留。', 'ok')
  } finally {
    taskHistoryBusyId.value = ''
  }
}

async function openTaskHistoryGlossary(payload) {
  const path = typeof payload === 'string' ? payload : payload?.path
  if (!path) {
    setStatus(taskHistoryStatus, '这个阶段没有可打开的 Glossary 文件。', 'bad')
    return
  }
  const loaded = await loadGlossary(path)
  if (!loaded && glossaryLoadFailure) {
    setStatus(taskHistoryStatus, `Glossary 加载失败：${glossaryLoadFailure}`, 'bad')
  }
}

async function openTaskArtifact(payload) {
  const path = String(payload?.path || '')
  if (!path) {
    setStatus(taskHistoryStatus, '这个阶段没有可打开的字幕文件。', 'bad')
    return
  }
  if (payload?.kind === 'source_srt') sourceSrt.value = path
  await editSubtitle({ path })
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
  await loadGlossary(path || '')
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
  if (openingGlossaryReviewKey.value === reviewKey) {
    return true
  }
  openingGlossaryReviewKey.value = reviewKey
  try {
    // Enter the review page immediately; loading/candidate generation is visible
    // there and does not require a separate "open review" click.
    activeView.value = 'glossary'
    const loaded = await loadGlossary(reviewPath)
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

function scheduleVideoFormats(value, delay = 650) {
  if (videoFormatsTimer) window.clearTimeout(videoFormatsTimer)
  videoFormatsTimer = null
  if (!looksLikeVideoInput(value)) return
  const requestedUrl = String(value || '').trim()
  videoFormatsTimer = window.setTimeout(() => {
    videoFormatsTimer = null
    loadVideoFormats({ requestedUrl, automatic: true })
  }, delay)
}

async function loadVideoFormats(options = {}) {
  const requestedUrl = String(options?.requestedUrl || url.value || '').trim()
  if (!requestedUrl) {
    setStatus(videoFormatsStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  if (videoFormatsTimer) {
    window.clearTimeout(videoFormatsTimer)
    videoFormatsTimer = null
  }
  const requestSequence = ++videoFormatsRequestSequence
  videoFormatsLoading.value = true
  setStatus(videoFormatsStatus, '正在读取这个视频实际可下载的画质…', '')
  try {
    const result = await api('/api/download-formats', { url: requestedUrl })
    if (
      requestSequence !== videoFormatsRequestSequence
      || !isProbeResponseCurrent(requestedUrl, url.value)
    ) return
    availableVideoFormats.value = Array.isArray(result.formats) ? result.formats : []
    videoFormatsTitle.value = String(result.title || '')
    if (selectedVideoFormat(availableVideoFormats.value, videoQuality.value) === null
      && String(videoQuality.value || '').startsWith('format:')) {
      videoQuality.value = '1080p'
    }
    const highest = availableVideoFormats.value[0]?.label || ''
    setStatus(
      videoFormatsStatus,
      availableVideoFormats.value.length
        ? `已读取 ${availableVideoFormats.value.length} 种真实格式${highest ? `；最高为 ${highest}` : ''}。`
        : '没有读取到可下载的视频格式，仍可使用快速兼容模式。',
      availableVideoFormats.value.length ? 'ok' : 'bad',
    )
  } catch (error) {
    if (
      requestSequence !== videoFormatsRequestSequence
      || !isProbeResponseCurrent(requestedUrl, url.value)
    ) return
    availableVideoFormats.value = []
    videoFormatsTitle.value = ''
    if (String(videoQuality.value || '').startsWith('format:')) videoQuality.value = '1080p'
    setStatus(videoFormatsStatus, `真实画质读取失败：${error.message}。仍可使用快速兼容模式。`, 'bad')
  } finally {
    if (requestSequence === videoFormatsRequestSequence) videoFormatsLoading.value = false
  }
}

async function probeVideo() {
  const requestedUrl = url.value.trim()
  if (!requestedUrl) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  const requestSequence = ++linkProbeSequence
  probing.value = true
  setStatus(probeStatus, '正在检测字幕与视频信息...', '')
  try {
    const result = await api('/api/probe', {
      url: requestedUrl,
      embedded_subtitle_hint: embeddedSubtitleHint.value,
      source_language: sourceLanguage.value,
      target_language: agentTargetLanguage.value,
    })
    if (requestSequence !== linkProbeSequence || !isProbeResponseCurrent(requestedUrl, url.value)) {
      setStatus(probeStatus, '链接已更改，已忽略上一条链接的检测结果。', '')
      return
    }
    probe.value = result
    probedInputUrl.value = requestedUrl
    if (result.existing_project) {
      setStatus(probeStatus, `检测完成：${result.subtitles?.length || 0} 条字幕轨道；找到本地项目 ${result.existing_project.name}，需要时可在下方手动载入。`, 'ok')
    } else {
      setStatus(probeStatus, `检测完成：${result.subtitles?.length || 0} 条字幕轨道。`, 'ok')
    }
    if (result.title) {
      translateTitle(result.title, { requestedUrl, requestSequence })
    }
  } catch (error) {
    if (requestSequence === linkProbeSequence && isProbeResponseCurrent(requestedUrl, url.value)) {
      setStatus(probeStatus, error.message, 'bad')
    }
  } finally {
    probing.value = false
  }
}

async function translateTitle(title, { requestedUrl = '', requestSequence = 0 } = {}) {
  setStatus(titleStatus, '正在盲翻标题...', '')
  try {
    const result = await api('/api/translate-title', { title })
    if (requestSequence && (
      requestSequence !== linkProbeSequence
      || !isProbeResponseCurrent(requestedUrl, url.value)
    )) return
    titleBox.value = result.zh_title || ''
    setStatus(titleStatus, titleBox.value ? '标题已翻译，可复制或填入任务提示。' : '标题翻译为空。', titleBox.value ? 'ok' : 'bad')
  } catch (error) {
    if (requestSequence && (
      requestSequence !== linkProbeSequence
      || !isProbeResponseCurrent(requestedUrl, url.value)
    )) return
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
  if (linkActionBusy.value) return
  const value = resolveLinkActionUrl(url.value, probe.value?.webpage_url)
  if (!value) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  const exactFormat = selectedVideoFormat(availableVideoFormats.value, videoQuality.value)
  const quickQuality = String(videoQuality.value || '').startsWith('format:') ? '1080p' : videoQuality.value
  const currentProbe = probe.value && isProbeResponseCurrent(probedInputUrl.value, url.value) ? probe.value : null
  linkActionBusy.value = 'download-video'
  setStatus(probeStatus, '正在创建视频下载任务...', '')
  try {
    const payload = {
      url: value,
      title: currentProbe?.title || videoFormatsTitle.value || '',
      thumbnail_format: thumbnailFormat.value,
      quality: quickQuality,
    }
    if (exactFormat) {
      payload.format_id = exactFormat.id
      payload.format_tag = exactFormat.format_tag
      payload.container = exactFormat.container
    }
    const job = await api('/api/jobs/download-video', payload)
    watchJob(job)
    setStatus(probeStatus, `视频下载任务已启动（${exactFormat?.label || '兼容 1080p，优先 H.264 / MP4'}）。页面会留在这里，进度可在“任务日志”查看。`, 'ok')
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  } finally {
    linkActionBusy.value = ''
  }
}

async function downloadThumbnail() {
  if (linkActionBusy.value) return
  const value = resolveLinkActionUrl(url.value, probe.value?.webpage_url)
  if (!value) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  const currentProbe = probe.value && isProbeResponseCurrent(probedInputUrl.value, url.value) ? probe.value : null
  linkActionBusy.value = 'download-thumbnail'
  setStatus(probeStatus, '正在创建封面下载任务...', '')
  try {
    const job = await api('/api/jobs/download-thumbnail', {
      url: value,
      title: currentProbe?.title || titleBox.value || '',
      format: thumbnailFormat.value,
    })
    watchJob(job)
    setStatus(probeStatus, '封面下载任务已启动。页面会留在这里，进度可在“任务日志”查看。', 'ok')
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  } finally {
    linkActionBusy.value = ''
  }
}

async function runOcrFull() {
  if (linkActionBusy.value) return
  const value = resolveLinkActionUrl(url.value, probe.value?.webpage_url)
  if (!value) {
    setStatus(probeStatus, '先输入视频链接或 ID。', 'bad')
    return
  }
  const currentProbe = probe.value && isProbeResponseCurrent(probedInputUrl.value, url.value) ? probe.value : null
  linkActionBusy.value = 'ocr-full'
  setStatus(probeStatus, '正在创建视频下载与 OCR 任务...', '')
  try {
    const job = await api('/api/jobs/ocr-full', {
      url: value,
      title: currentProbe?.title || titleBox.value || '',
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
    setStatus(probeStatus, '视频下载与 OCR 任务已启动。页面会留在这里，进度可在“任务日志”查看。', 'ok')
  } catch (error) {
    setStatus(probeStatus, error.message, 'bad')
  } finally {
    linkActionBusy.value = ''
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

async function runAsrLab() {
  if (!localVideo.value.trim()) {
    setStatus(asrLabStatus, '请先选择本地视频或音频。', 'bad')
    return
  }
  asrLabRunning.value = true
  asrLabResult.value = null
  setStatus(
    asrLabStatus,
    asrLabExperimental.value ? '正在启动独立 Agent 实验…' : asrLabSpeakerDiarization.value
      ? `正在启动 ASR ${asrLabVersion.value === '2.0' ? '2.2' : asrLabVersion.value} 与说话人分离…`
      : `正在启动 ASR ${asrLabVersion.value === '2.0' ? '2.2' : asrLabVersion.value}…`,
    '',
  )
  try {
    const job = await api('/api/jobs/asr-lab', {
      input_video: localVideo.value.trim(),
      asr_version: asrLabVersion.value,
      test_ranges: asrLabExperimental.value ? asrLabTestRanges.value : undefined,
      source_language: asrLabExperimental.value ? 'korean' : asrLabSourceLanguage.value,
      model_size: asrLabModelSize.value,
      speaker_diarization: asrLabSpeakerDiarization.value,
      known_speaker_count: asrLabKnownSpeakerCount.value,
      hotwords: asrLabVersion.value === '2.0' ? asrLabHotwords.value.trim() : '',
      high_recall: asrLabVersion.value === '2.0' && asrLabHighRecall.value,
      dual_gpu_parallel: asrLabVersion.value === '2.0'
        && asrLabSpeakerDiarization.value
        && asrLabDualGpuParallel.value,
      diarization_device: 'auto',
      device: 'cuda',
      compute_type: 'float16',
    })
    asrLabJobId.value = job.id
    if (asrLabExperimental.value) {
      try { localStorage.setItem('reibosub-asr-experiment-job', JSON.stringify({ id: job.id, version: asrLabVersion.value, input_video: localVideo.value, test_ranges: asrLabTestRanges.value })) } catch {}
    }
    watchJob(job)
    setStatus(
      asrLabStatus,
      asrLabExperimental.value ? '实验任务已启动，正在截取所选音频…' : asrLabSpeakerDiarization.value
        ? `ASR ${asrLabVersion.value === '2.0' ? '2.2' : asrLabVersion.value} 与说话人分离任务运行中；完成后会显示 Speaker 标签。`
        : `ASR ${asrLabVersion.value === '2.0' ? '2.2' : asrLabVersion.value} 任务运行中；识别完成后文本会显示在本页。`,
      '',
    )
  } catch (error) {
    asrLabRunning.value = false
    asrLabJobId.value = ''
    setStatus(asrLabStatus, error.message, 'bad')
  }
}

function handleAsrLabCopyStatus(text, className) {
  setStatus(asrLabStatus, text, className)
}

async function handleAsrReviewDecision({ region, action }) {
  const current = asrLabResult.value
  if (!current || !region?.review_id || asrLabReviewBusyId.value) return
  asrLabReviewBusyId.value = region.review_id
  setStatus(
    asrLabStatus,
    action === 'accept'
      ? `正在把 ${region.start.toFixed?.(1) || region.start} 秒处候选内容合回词级时间轴…`
      : '正在记录忽略决定…',
    '',
  )
  try {
    const response = await api('/api/asr-review/decision', {
      source_srt: current.review_source_srt || current.source_srt,
      words_path: current.words_path,
      out: current.reviewed_srt || '',
      review_id: region.review_id,
      action,
      candidate: region,
    })
    const remaining = (current.suspected_missing_regions || [])
      .filter((item) => item.review_id !== region.review_id)
    asrLabResult.value = {
      ...current,
      ...response,
      suspected_missing_regions: remaining,
      suspected_missing_region_count: remaining.length,
      word_count: response.review_word_count || current.word_count,
    }
    if (response.subtitle_path) sourceSrt.value = response.subtitle_path
    setStatus(
      asrLabStatus,
      action === 'accept'
        ? `已采纳候选内容并重新打轴；还有 ${remaining.length} 处待复核，素材文件夹字幕已同步更新。`
        : `已忽略该候选；还有 ${remaining.length} 处待复核。`,
      'ok',
    )
  } catch (error) {
    setStatus(asrLabStatus, error.message, 'bad')
  } finally {
    asrLabReviewBusyId.value = ''
  }
}

function openAsrLab() {
  if (!localVideo.value.trim()) {
    setStatus(assetStatus, '先选择视频或音频素材。', 'bad')
    return
  }
  activeView.value = 'asr-dev'
  setStatus(asrLabStatus, `已选择素材：${localVideo.value}`, 'ok')
}

async function uploadLocalMedia({ file, title }) {
  if (!file) {
    setStatus(assetStatus, '先选择要上传的视频或音频。', 'bad')
    return
  }
  materialUploadBusy.value = true
  setStatus(assetStatus, '正在上传素材...', '')
  try {
    const uploaded = await uploadMediaFile(file, { title })
    localVideo.value = uploaded.input_media || uploaded.input_video || uploaded.input_audio || ''
    await loadAssets()
    const kindLabel = uploaded.media_kind === 'audio' ? '音频' : '视频'
    setStatus(assetStatus, `${kindLabel}素材上传完成，尚未启动任何处理任务。`, 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  } finally {
    materialUploadBusy.value = false
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
    setStatus(assetStatus, '已创建视频处理任务。', 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function registerLocalProject() {
  if (!localVideo.value.trim()) {
    setStatus(assetStatus, '先选择或填写一个本地视频或音频路径。', 'bad')
    return
  }
  try {
    const result = await api('/api/assets/register-local-project', {
      input_media: localVideo.value.trim(),
      title: localVideo.value.split('/').pop()?.replace(/\.[^.]+$/, '') || '',
    })
    await loadAssets()
    setStatus(assetStatus, `已登记素材项目：${result.project?.name || result.project_dir}`, 'ok')
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
      target_language: subtitleTargetLanguage.value,
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

async function loadGlossary(pathOverride) {
  glossaryLoadFailure = ''
  const hasPathOverride = typeof pathOverride === 'string'
  const requestedPath = String(hasPathOverride ? pathOverride : glossaryPath.value).trim()
  if (!requestedPath) {
    glossaryLoadFailure = '未提供 Glossary 路径。'
    setStatus(flowStatus, '先填写 glossary 路径。', 'bad')
    return false
  }
  if (glossaryTextDirty.value && !window.confirm('当前 YAML 有未保存修改。确定放弃这些修改并重新加载吗？')) {
    return false
  }
  const loadGeneration = ++glossaryLoadGeneration
  if (!hasPathOverride) activeView.value = 'glossary'
  glossaryPath.value = requestedPath
  glossaryLoading.value = true
  glossaryCandidateStatus.value = { state: 'ready', total: 0, ready: 0, pending: 0, failed: 0 }
  setStatus(flowStatus, '正在读取术语表...', '')
  try {
    await glossaryAutosave.flush()
    if (loadGeneration !== glossaryLoadGeneration) return false
    const [text, review] = await Promise.all([
      api('/api/read-text', { path: requestedPath }),
      api('/api/read-glossary-items', { path: requestedPath, include_blind_candidates: true }),
    ])
    if (loadGeneration !== glossaryLoadGeneration) return false
    if (!hasPathOverride && glossaryPath.value.trim() !== requestedPath) return false
    glossaryPath.value = requestedPath
    glossaryEditor.value = text.content || ''
    glossaryItems.value = review.items || []
    glossaryTargetLanguage.value = review.target_language || 'zh'
    subtitleTargetLanguage.value = review.target_language || 'zh'
    glossaryCandidateStatus.value = review.candidates || { state: 'ready', total: 0, ready: 0, pending: 0, failed: 0 }
    loadedGlossaryPath.value = requestedPath
    glossaryTextDirty.value = false
    glossaryAutosave.reset('idle')
    setStatus(flowStatus, `已加载 ${glossaryItems.value.length} 条 glossary。`, 'ok')
    activeView.value = 'glossary'
    if (review.candidates?.pending > 0) {
      void prepareGlossaryCandidates(requestedPath, loadGeneration)
    }
    return true
  } catch (error) {
    if (loadGeneration === glossaryLoadGeneration) {
      glossaryLoadFailure = error.message
      setStatus(flowStatus, error.message, 'bad')
    }
    return false
  } finally {
    if (loadGeneration === glossaryLoadGeneration) glossaryLoading.value = false
  }
}

async function prepareGlossaryCandidates(path, generation, retryFailed = false) {
  const isCurrent = () => generation === glossaryLoadGeneration && path === loadedGlossaryPath.value && path === glossaryPath.value.trim()
  if (!path || !isCurrent() || glossaryCandidateStatus.value.state === 'running') return
  glossaryCandidateStatus.value = { ...glossaryCandidateStatus.value, state: 'running' }
  try {
    let job = await api('/api/glossary-candidates/prepare', { path, retry_failed: retryFailed })
    while (['queued', 'running', 'cancel_requested'].includes(job.status)) {
      await new Promise(resolve => window.setTimeout(resolve, 1200))
      if (!isCurrent()) return
      job = await getJson(`/api/jobs/${job.id}`)
    }
    if (!isCurrent()) return
    if (job.status !== 'done') throw new Error('原句参考译文暂未准备成功，仍可直接填写译名。')
    const review = await api('/api/read-glossary-items', { path, include_blind_candidates: true })
    if (!isCurrent()) return
    if (!glossaryTextDirty.value) glossaryItems.value = mergeGlossaryCandidates(glossaryItems.value, review.items)
    glossaryCandidateStatus.value = review.candidates || { state: 'ready' }
  } catch {
    if (isCurrent()) glossaryCandidateStatus.value = { ...glossaryCandidateStatus.value, state: 'partial', failed: Math.max(1, glossaryCandidateStatus.value.failed || 0) }
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
      target_language: subtitleTargetLanguage.value,
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

async function loadAssets(refresh = false) {
  setStatus(assetStatus, refresh ? '正在更新素材索引...' : '正在读取素材列表...', '')
  try {
    const result = await getJson(refresh === true ? '/api/assets?refresh=1' : '/api/assets')
    assets.videos = result.videos || []
    assets.audios = result.audios || []
    assets.subtitles = result.subtitles || []
    assets.projects = result.projects || []
    assets.ocr_jobs = result.ocr_jobs || []
    assets.ocr_debug_folders = result.ocr_debug_folders || []
    setStatus(assetStatus, `已扫描：${assets.projects.length} 个项目，${assets.videos.length} 个视频，${assets.audios.length} 个音频，${assets.subtitles.length} 个字幕。`, 'ok')
  } catch (error) {
    setStatus(assetStatus, error.message, 'bad')
  }
}

async function deleteDownloadProject(project) {
  if (!project?.path) return
  if (!window.confirm(`删除素材项目目录：${project.name || project.path}？\n\n会删除该目录下的视频、音频、字幕、封面和其他文件。`)) return
  try {
    await api('/api/assets/delete-project', { path: project.path })
    if (localVideo.value && localVideo.value.startsWith(project.path)) localVideo.value = ''
    if (sourceSrt.value && sourceSrt.value.startsWith(project.path)) sourceSrt.value = ''
    await loadAssets()
    setStatus(assetStatus, `已删除素材项目目录：${project.name}`, 'ok')
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
    try {
      const saved = JSON.parse(localStorage.getItem('reibosub-asr-experiment-job') || 'null')
      const experiment = saved && loadedJobs.find(job => job.id === saved.id)
      if (experiment) {
        asrLabVersion.value = saved.version === 'autonomous-experimental' ? saved.version : 'agent-experimental'
        localVideo.value = saved.input_video || localVideo.value
        if (Array.isArray(saved.test_ranges)) asrLabTestRanges.value = saved.test_ranges
        asrLabJobId.value = experiment.id
        asrLabRunning.value = ['running', 'queued', 'cancel_requested'].includes(experiment.status)
        if (!asrLabRunning.value) applyJobResult(experiment)
      }
    } catch {}
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
      if (job.id === asrLabJobId.value && asrLabExperimental.value) {
        const stage = [...(job.logs || [])].reverse().find(line => line.includes('experiment_stage: '))
        if (stage) setStatus(asrLabStatus, stage.slice(stage.indexOf('experiment_stage: ') + 18), '')
      }
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
      if (job.id === asrLabJobId.value && asrLabExperimental.value) {
        const stage = [...(job.logs || [])].reverse().find(line => line.includes('experiment_stage: '))
        if (stage) setStatus(asrLabStatus, stage.split('experiment_stage: ').pop(), '')
      }
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
  if (result.kind === 'asr_experiment_lab') {
    asrLabRunning.value = false
    asrLabJobId.value = ''
    asrLabResult.value = result
    setStatus(asrLabStatus, result.pending_questions
      ? `字幕草稿已生成：${result.cue_count} 条，还有 ${result.pending_questions} 处${result.asr_version === 'autonomous-experimental' ? '字幕疑点' : '人名'}需要你确认。`
      : `实验字幕已生成：${result.cue_count} 条，可试听或下载；请留意标记的时间边界。`, 'ok')
    return
  }
  if (result.kind === 'asr_lab' || job.id === asrLabJobId.value) {
    asrLabRunning.value = false
    asrLabJobId.value = ''
    if (job.status === 'done') {
      asrLabResult.value = result
      const speakerSummary = result.speaker_diarization ? `，识别出 ${result.speaker_count || 0} 位说话人` : ''
      const qualitySummary = result.asr_version === '2.0' && result.low_confidence_cue_count
        ? `，${result.low_confidence_cue_count} 条建议复核`
        : ''
      const recoverySummary = result.asr_version === '2.0' && result.high_recall
        ? `，补回 ${result.recovered_word_count || 0} 个词块（${result.recovered_region_count || 0} 处）`
        : ''
      const missingSummary = result.suspected_missing_region_count
        ? `，仍有 ${result.suspected_missing_region_count} 处疑似漏听`
        : ''
      const materialSummary = result.source_sidecar ? '，已保存到素材文件夹' : ''
      setStatus(
        asrLabStatus,
        `ASR ${result.pipeline_version || result.asr_version || '1.0'} 完成，共 ${result.cue_count || 0} 条语音片段${speakerSummary}${recoverySummary}${missingSummary}${qualitySummary}${materialSummary}。`,
        'ok',
      )
    } else {
      setStatus(asrLabStatus, job.error || (job.status === 'cancelled' ? 'ASR 任务已终止。' : 'ASR 任务失败。'), 'bad')
    }
  }
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
    setStatus(assetStatus, `视频处理完成：${result.output_video}`, 'ok')
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
  const primaryMedia = project.primary_video || project.primary_audio
  if (primaryMedia) localVideo.value = primaryMedia
  if (project.source_url) url.value = project.normalized_url || project.source_url
  const sourceSubtitle = (project.subtitles || []).find((item) => item.role === 'source') || (project.subtitles || [])[0]
  if (sourceSubtitle?.path) sourceSrt.value = sourceSubtitle.path
  activeView.value = 'assets'
  setStatus(assetStatus, `已载入项目：${project.name}`, 'ok')
}

function useVideo(path) {
  localVideo.value = path
  activeView.value = 'assets'
  setStatus(assetStatus, `已选择当前视频：${path}`, 'ok')
}

function useAudio(path) {
  localVideo.value = path
  activeView.value = 'assets'
  setStatus(assetStatus, `已选择当前音频：${path}`, 'ok')
}

function openMediaInAsrLab(path) {
  localVideo.value = path
  activeView.value = 'asr-dev'
  setStatus(asrLabStatus, `已选择素材：${path}`, 'ok')
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
  const isSameSubtitle = nextSubtitlePath === subtitleEditorLoadedPath.value
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
  const requestedPath = subtitleEditorPath.value.trim()
  if (!requestedPath) {
    setStatus(subtitleEditorStatus, '先选择或填写字幕路径。', 'bad')
    return
  }
  subtitleEditorLoading.value = true
  setStatus(subtitleEditorStatus, '正在加载字幕...', '')
  try {
    const result = await api('/api/subtitle/read', { path: requestedPath })
    subtitleEditorPath.value = result.path
    subtitleEditorLoadedPath.value = result.path
    subtitleSpeakerDictionary.value = result.speaker_dictionary || []
    subtitleEditorCues.value = renumberSubtitleCues(result.cues || [])
    subtitleEditorSavedCues.value = cloneSubtitleEditorCues(subtitleEditorCues.value)
    if (!subtitleEditorVideoPath.value) subtitleEditorVideoPath.value = inferVideoForSubtitle(result.path)
    subtitleEditorDirty.value = false
    subtitleFocusedCueUid.value = ''
    subtitleEditorUndoStack.value = []
    subtitleEditorPendingFieldEdit.value = null
    const diagnostics = refreshSubtitleEditorMechanicalDiagnostics({ resetSpeakerSelection: true })
    setStatus(
      subtitleEditorStatus,
      `已加载 ${result.count || 0} 条字幕。机械检查：${diagnostics.recommendedSpeakerCueCount} 条可安全去除说话者，${diagnostics.pairIssueCount} 处符号待检查。`,
      diagnostics.pairIssueCount ? 'bad' : 'ok',
    )
  } catch (error) {
    if (subtitleEditorLoadedPath.value) subtitleEditorPath.value = subtitleEditorLoadedPath.value
    setStatus(
      subtitleEditorStatus,
      `${error.message}${subtitleEditorLoadedPath.value ? '；已恢复到当前成功加载的字幕路径。' : ''}`,
      'bad',
    )
  } finally {
    subtitleEditorLoading.value = false
  }
}

async function saveSubtitleEditor(overwrite) {
  if (!subtitleEditorLoadedPath.value) {
    setStatus(subtitleEditorStatus, '先加载字幕。', 'bad')
    return
  }
  if (!subtitleEditorSaveReady.value) {
    setStatus(subtitleEditorStatus, '字幕路径已经改变，请先点击“加载”；当前内容不会写入未加载的文件。', 'bad')
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
      path: subtitleEditorLoadedPath.value,
      overwrite,
      cues: normalizedCues,
    })
    subtitleEditorPath.value = result.path
    subtitleEditorLoadedPath.value = result.path
    sourceSrt.value = result.path
    subtitleEditorCues.value = renumberSubtitleCues(result.cues || [])
    subtitleEditorSavedCues.value = cloneSubtitleEditorCues(subtitleEditorCues.value)
    subtitleEditorDirty.value = false
    subtitleFocusedCueUid.value = ''
    subtitleEditorPendingFieldEdit.value = null
    refreshSubtitleEditorMechanicalDiagnostics()
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

function refreshSubtitleEditorMechanicalDiagnostics({ resetSpeakerSelection = false } = {}) {
  subtitlePairIssues.value = detectCuePairSymbolIssues(subtitleEditorCues.value)
  subtitleSpeakerCandidates.value = detectCueSpeakerPrefixCandidates(
    subtitleEditorCues.value,
    subtitleSpeakerDictionary.value,
  )
  const validIds = new Set(subtitleSpeakerCandidates.value.map((candidate) => candidate.id))
  subtitleSelectedSpeakerCandidateIds.value = resetSpeakerSelection
    ? subtitleSpeakerCandidates.value.filter((candidate) => candidate.recommended).map((candidate) => candidate.id)
    : subtitleSelectedSpeakerCandidateIds.value.filter((id) => validIds.has(id))
  return {
    pairIssueCount: subtitlePairIssues.value.length,
    recommendedSpeakerCueCount: subtitleSpeakerCandidates.value
      .filter((candidate) => candidate.recommended)
      .reduce((count, candidate) => count + Number(candidate.count || 0), 0),
  }
}

function toggleSubtitleSpeakerCandidate({ id, selected }) {
  const values = new Set(subtitleSelectedSpeakerCandidateIds.value)
  if (selected) values.add(id)
  else values.delete(id)
  subtitleSelectedSpeakerCandidateIds.value = [...values]
}

function stripDetectedSubtitleSpeakerPrefixes() {
  if (!subtitleSelectedSpeakerCandidateIds.value.length) {
    setStatus(subtitleEditorStatus, '先勾选要去除的说话者候选。', 'bad')
    return
  }
  const result = applySpeakerPrefixCandidates(
    subtitleEditorCues.value,
    subtitleSpeakerCandidates.value,
    subtitleSelectedSpeakerCandidateIds.value,
  )
  if (!result.changedCueCount) {
    refreshSubtitleEditorMechanicalDiagnostics()
    setStatus(subtitleEditorStatus, '候选内容已经变化，请按当前字幕重新确认。', '')
    return
  }
  pushSubtitleEditorUndo('去除检测到的说话者')
  subtitleEditorCues.value = result.cues
  refreshSubtitleEditorDirty()
  refreshSubtitleEditorMechanicalDiagnostics()
  setStatus(subtitleEditorStatus, `已去除 ${result.removedPrefixCount} 个说话者前缀；如有误可立即撤回。`, 'ok')
}

async function focusSubtitleEditorCue(uid) {
  subtitleFocusedCueUid.value = uid
  await subtitleEditorPanel.value?.revealCue(uid)
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

function repairSubtitleEditorPairIssue(issue) {
  const result = applyCuePairIssueRepairs(
    subtitleEditorCues.value,
    [issue],
    { includeBoundarySuggestions: true },
  )
  if (!result.repairedIssueCount) {
    setStatus(subtitleEditorStatus, '这个问题需要定位后人工调整符号顺序。', 'bad')
    return
  }
  pushSubtitleEditorUndo('修复成对符号')
  subtitleEditorCues.value = result.cues
  refreshSubtitleEditorDirty()
  refreshSubtitleEditorMechanicalDiagnostics()
  setStatus(subtitleEditorStatus, '已应用符号修复；如位置不合适可立即撤回。', 'ok')
}

function repairAutomaticSubtitleEditorPairIssues() {
  const repairable = subtitlePairIssues.value.filter((issue) => issue.autoRepairable)
  const result = applyCuePairIssueRepairs(subtitleEditorCues.value, repairable)
  if (!result.repairedIssueCount) {
    setStatus(subtitleEditorStatus, '当前没有可安全自动修复的全/半角符号错配。', '')
    return
  }
  pushSubtitleEditorUndo('自动修复明确符号错配')
  subtitleEditorCues.value = result.cues
  refreshSubtitleEditorDirty()
  refreshSubtitleEditorMechanicalDiagnostics()
  setStatus(subtitleEditorStatus, `已自动修复 ${result.repairedIssueCount} 处明确符号错配；其余问题仍需确认。`, 'ok')
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
