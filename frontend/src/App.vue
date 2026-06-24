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
              v-model:extra-hint="extraHint"
              :session="agentSession"
              :starting="agentStarting"
              :status="agentStatus.text"
              :status-class="agentStatus.class"
              @start-agent="startAgent"
              @answer-agent="answerAgent"
              @cancel-agent="cancelAgent"
              @open-glossary="openGlossaryFromAgent"
            />
          </div>

          <div v-else-if="activeView === 'new-task'" class="page-stack">
            <VideoInputPanel
              v-model:url="url"
              v-model:ocr-translation-mode="ocrTranslationMode"
              v-model:embedded-subtitle-hint="embeddedSubtitleHint"
              :probing="probing"
              :status="probeStatus.text"
              :status-class="probeStatus.class"
              @probe="probeVideo"
              @download-video="downloadVideo"
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
              @use-video="useVideo"
              @use-video-ocr="useVideoAndOcr"
              @use-subtitle="useSubtitle"
            />
          </div>

          <div v-else-if="activeView === 'subtitles'" class="page-stack">
            <TranslationFlow
              v-model:source-srt="sourceSrt"
              v-model:glossary-path="glossaryPath"
              v-model:extra-hint="extraHint"
              v-model:subtitle-translation-mode="subtitleTranslationMode"
              v-model:subtitle-convert-format="subtitleConvertFormat"
              :status="flowStatus.text"
              :status-class="flowStatus.class"
              @correct-asr="correctAsrSubtitle"
              @generate-glossary="generateGlossary"
              @load-glossary="loadGlossary"
              @translate-subtitle="translateSubtitle"
              @convert-subtitle="convertSubtitle"
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
import { computed, onMounted, reactive, ref } from 'vue'
import { api, getJson } from './api'
import SideNav from './components/SideNav.vue'
import HeaderBar from './components/HeaderBar.vue'
import AgentSessionPanel from './components/AgentSessionPanel.vue'
import VideoInputPanel from './components/VideoInputPanel.vue'
import VideoInfoPanel from './components/VideoInfoPanel.vue'
import TranslationFlow from './components/TranslationFlow.vue'
import GlossaryReviewPanel from './components/GlossaryReviewPanel.vue'
import AssetLibrary from './components/AssetLibrary.vue'
import JobSidebar from './components/JobSidebar.vue'

const url = ref('')
const probe = ref(null)
const probing = ref(false)
const titleBox = ref('')
const sourceSrt = ref('')
const glossaryPath = ref('')
const extraHint = ref('')
const glossaryEditor = ref('')
const glossaryItems = ref([])
const glossaryLoading = ref(false)
const subtitleTranslationMode = ref('translate_only')
const subtitleConvertFormat = ref('bcc')
const ocrTranslationMode = ref('standard_cleanup')
const embeddedSubtitleHint = ref('unknown')
const localVideo = ref('')
const audioLanguage = ref('auto')
const audioModelSize = ref('large-v3')
const activeJobId = ref('')
const activeView = ref('agent')
const agentSession = ref(null)
const agentStarting = ref(false)
let agentPollTimer = null

const assets = reactive({ videos: [], subtitles: [], ocr_jobs: [] })
const jobs = reactive({})
const pollTimers = new Map()

const probeStatus = reactive({ text: '', class: '' })
const titleStatus = reactive({ text: '', class: '' })
const flowStatus = reactive({ text: '', class: '' })
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
  subtitles: {
    title: '字幕工具',
    description: '选择源字幕，生成 glossary，翻译为中文外挂字幕。',
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

const activePage = computed(() => pages[activeView.value] || pages['new-task'])
const jobList = computed(() => Object.values(jobs))
const runningJobCount = computed(() => jobList.value.filter((job) => ['running', 'cancel_requested'].includes(job.status)).length)
const failedJobCount = computed(() => jobList.value.filter((job) => job.status === 'failed').length)
const doneJobCount = computed(() => jobList.value.filter((job) => job.status === 'done').length)
const topbarMetrics = computed(() => ({
  videos: assets.videos.length,
  subtitles: assets.subtitles.length,
  jobs: jobList.value.length,
}))
const navItems = computed(() => [
  { id: 'agent', label: 'Agent', hint: '自动编排', icon: 'A', badge: agentSession.value?.status === 'waiting' ? '待确认' : '' },
  { id: 'assets', label: '素材', hint: '视频与字幕', icon: 'M', badge: assets.videos.length + assets.subtitles.length || '' },
  { id: 'glossary', label: '审核', hint: 'Glossary', icon: 'G', badge: glossaryItems.value.length || '' },
  { id: 'subtitles', label: '字幕工具', hint: '翻译与转换', icon: 'S', badge: sourceSrt.value ? '已选' : '' },
  { id: 'new-task', label: '链接工具', hint: '检测与下载', icon: 'L', badge: probe.value?.subtitles?.length || '' },
  { id: 'jobs', label: '任务', hint: '日志与输出', icon: 'J', badge: runningJobCount.value || failedJobCount.value || '' },
])

onMounted(() => {
  loadAssets()
  loadJobs()
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
      target_language: 'zh',
      extra_hint: extraHint.value,
      ocr_translation_mode: ocrTranslationMode.value,
    })
    agentSession.value = session
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
    const session = await api(`/api/agent/${agentSession.value.id}/answer`, { action })
    agentSession.value = session
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
    setStatus(agentStatus, '已请求中断 Agent 任务。', 'bad')
    await loadJobs()
  } catch (error) {
    setStatus(agentStatus, `中断失败：${error.message}`, 'bad')
  }
}

function scheduleAgentPoll(sessionId, delay = 1000) {
  if (agentPollTimer) clearTimeout(agentPollTimer)
  agentPollTimer = setTimeout(() => pollAgent(sessionId), delay)
}

async function pollAgent(sessionId) {
  try {
    const session = await getJson(`/api/agent/${sessionId}`)
    agentSession.value = session
    if (session.result?.source_srt) sourceSrt.value = session.result.source_srt
    if (session.result?.glossary_path) glossaryPath.value = session.result.glossary_path
    if (session.result?.translated_srt) setStatus(agentStatus, `Agent 完成：${session.result.translated_srt}`, 'ok')
    if (session.status === 'running') {
      scheduleAgentPoll(sessionId, 1000)
      return
    }
    if (session.status === 'waiting') {
      setStatus(agentStatus, 'Agent 等待你的确认。', '')
      return
    }
    if (session.status === 'failed') {
      setStatus(agentStatus, session.error || 'Agent 失败。', 'bad')
      return
    }
    if (session.status === 'done') {
      setStatus(agentStatus, 'Agent 已完成。', 'ok')
      loadAssets()
    }
  } catch (error) {
    setStatus(agentStatus, error.message, 'bad')
    scheduleAgentPoll(sessionId, 2000)
  }
}

async function openGlossaryFromAgent(path) {
  glossaryPath.value = path
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
      target_language: 'zh',
    })
    setStatus(probeStatus, `检测完成：${probe.value.subtitles?.length || 0} 条字幕轨道。`, 'ok')
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
    const job = await api('/api/jobs/download-video', { url: value })
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
      model_size: audioModelSize.value,
      device: 'cuda',
      compute_type: 'float16',
    })
    watchJob(job)
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
      source_language: 'korean',
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
    setStatus(flowStatus, 'Glossary 审核结果已保存。', 'ok')
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
    setStatus(flowStatus, 'Glossary YAML 已保存。', 'ok')
  } catch (error) {
    setStatus(flowStatus, error.message, 'bad')
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
    assets.ocr_jobs = result.ocr_jobs || []
    setStatus(assetStatus, `已扫描：${assets.videos.length} 个视频，${assets.subtitles.length} 个字幕。`, 'ok')
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
  if (result.glossary_path) {
    glossaryPath.value = result.glossary_path
    glossaryEditor.value = result.content || glossaryEditor.value
    loadGlossary()
    activeView.value = 'glossary'
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

function useVideo(path) {
  localVideo.value = path
  activeView.value = 'assets'
  setStatus(assetStatus, `已选择视频：${path}`, 'ok')
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
