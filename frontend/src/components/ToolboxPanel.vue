<template>
  <section class="panel toolbox-panel">
    <header class="studio-page-head"><div><span class="studio-kicker">工具箱</span><h2>想做什么，直接开始</h2><p>翻译字幕、转换格式，或从声音里提取对话。不必走完整的字幕任务流程。</p></div></header>
    <div class="toolbox-tabs" role="tablist" aria-label="选择工具">
      <button v-for="tool in TOOLBOX_TOOLS" :id="`tool-tab-${tool.id}`" :key="tool.id" type="button" role="tab" :aria-selected="selected === tool.id" :aria-controls="`tool-pane-${tool.id}`" :tabindex="selected === tool.id ? 0 : -1" :class="{ selected: selected === tool.id }" @click="selected = tool.id" @keydown="moveTab($event, tool.id)"><AppIcon :name="tool.icon" :size="21" /><span><strong>{{ tool.title }}</strong><small>{{ tool.description }}</small></span></button>
    </div>
    <div v-show="selected === 'translate'" id="tool-pane-translate" role="tabpanel" aria-labelledby="tool-tab-translate">
      <ReferenceTranslator title="文本翻译" description="使用设置中的翻译模型 · 支持中、英、日、韩 · Ctrl / ⌘ + Enter 翻译" placeholder="粘贴或输入要翻译的文字" />
    </div>
    <div v-show="selected === 'subtitles'" id="tool-pane-subtitles" role="tabpanel" aria-labelledby="tool-tab-subtitles"><SubtitleToolbox :jobs="jobs" @job-started="$emit('job-started', $event)" @cancel-job="$emit('cancel-job', $event)" @edit-subtitle="(path, video) => $emit('edit-subtitle', path, video)" /></div>
    <div v-show="selected === 'dialogue'" id="tool-pane-dialogue" role="tabpanel" aria-labelledby="tool-tab-dialogue" class="toolbox-workbench">
      <div class="toolbox-section-head"><h3>从声音中提取对话</h3><span class="toolbox-tag">ASR 2.2 · 稳定版</span></div>
      <p class="toolbox-help">提取原语言文字，同时生成 TXT 和 SRT。不翻译，不进入术语审核，也不识别画面上的文字。</p>
      <fieldset :disabled="busy" class="toolbox-fields">
        <label>视频或音频<select v-model="input" aria-label="对话提取素材"><option value="">从素材库选择…</option><option v-for="item in media" :key="item.path" :value="item.path">{{ item.name || item.path.split('/').pop() }}</option><option v-if="input && !media.some(item => item.path === input)" :value="input">{{ input.split('/').pop() }}</option></select></label>
        <label>音频语言<select v-model="language"><option value="auto">自动识别</option><option value="korean">韩语</option><option value="japanese">日语</option><option value="chinese">中文</option><option value="english">英语</option></select></label>
        <label v-if="['auto', 'chinese'].includes(language)">中文输出<select v-model="chineseScript" aria-label="对话提取中文输出"><option value="simplified">简体中文（默认）</option><option value="traditional">繁體中文</option><option value="original">保留识别原样</option></select><small class="toolbox-help">只在识别为中文时生效；不改动时间轴。</small></label>
      </fieldset>
      <div class="toolbox-source-actions"><button class="secondary mini" type="button" :disabled="busy" @click="uploadInput?.click()"><AppIcon name="plus" :size="15" />上传音视频</button><input ref="uploadInput" hidden type="file" accept="video/*,audio/*,.mkv,.flac,.m4a,.wav,.mp3,.mp4,.webm" @change="upload" /><button class="ghost mini" type="button" :disabled="busy" @click="$emit('refresh-assets')">刷新素材</button><button class="ghost mini" type="button" @click="$emit('open-view', 'new-task')">通过链接下载</button></div>
      <fieldset :disabled="busy" class="toolbox-speakers"><label class="toolbox-check"><input v-model="speakers" type="checkbox" />区分说话人</label><label v-if="speakers" class="toolbox-speaker-count">已知说话人数<select v-model="knownSpeakerCount" aria-label="对话提取已知说话人数"><option value="auto">自动判断</option><option v-for="count in 20" :key="count" :value="String(count)">{{ count }} 人</option></select></label></fieldset>
      <p v-if="speakers" class="toolbox-help">知道人数时可直接指定；不确定就选自动判断。需额外准备说话人分离依赖与模型，只会标记 Speaker 1、2…，不会识别真实姓名。</p>
      <details class="studio-disclosure toolbox-advanced"><summary>识别选项与本地路径</summary><fieldset :disabled="busy" class="toolbox-fields">
        <label class="toolbox-wide">服务器文件路径<input v-model="input" placeholder="也可以填写服务允许访问的音视频路径" /></label>
        <label>识别模型<select v-model="model"><option value="large-v3">large-v3 · 质量优先</option><option value="medium">medium · 平衡</option><option value="small">small · 速度优先</option></select></label>
        <label>运行设备<select v-model="device"><option value="cuda">NVIDIA GPU</option><option value="cpu">CPU · 较慢</option></select></label>
        <label class="toolbox-wide">专名提示（可选）<input v-model="hotwords" maxlength="2000" placeholder="人名、节目名或专有词，帮助识别" /></label>
      </fieldset><p class="toolbox-help">需安装 ASR 依赖与 FFmpeg；首次使用可能下载模型。没有可用 GPU 时，请切换 CPU。</p></details>
      <div class="toolbox-run-row"><span role="status" :class="{ 'context-error': error || job?.status === 'failed' }">{{ error || jobMessage }}</span><button v-if="isRunning" class="secondary mini" type="button" :disabled="job?.status === 'cancel_requested'" @click="$emit('cancel-job', job.id)">{{ job?.status === 'cancel_requested' ? '正在停止…' : '停止提取' }}</button><button type="button" :disabled="busy || !input.trim()" @click="extractDialogue">{{ uploading ? '正在上传…' : starting ? '正在启动…' : restoring ? '正在恢复任务…' : isRunning ? '正在提取…' : job?.status === 'done' ? '重新提取' : '开始提取' }}</button></div>
      <section v-if="job?.status === 'done' && result" class="toolbox-result" aria-label="对话提取结果">
        <div class="toolbox-section-head"><h3>对话文字 <small>{{ result.cue_count || 0 }} 个片段<template v-if="result.chinese_script && result.chinese_script !== 'original'"> · {{ result.chinese_script === 'traditional' ? '繁體中文' : '简体中文' }}</template></small></h3><div class="toolbox-source-actions"><button class="secondary mini" type="button" :disabled="!result.transcript_text" @click="copy(result.transcript_text)">复制文字</button><a v-if="result.text_path" class="button-link secondary mini" :href="fileUrl(result.text_path)" download>下载 TXT</a><a v-if="result.source_srt" class="button-link secondary mini" :href="fileUrl(result.source_srt)" download>下载 SRT</a><button v-if="result.source_srt" class="ghost mini" type="button" @click="$emit('edit-subtitle', result.source_srt, result.input_video)">精修与试听</button></div></div>
        <p v-if="result.suspected_missing_region_count" class="toolbox-help">有 {{ result.suspected_missing_region_count }} 处疑似漏听，识别结果未经人工逐字核准，可到 ASR Lab 做进一步复核。</p>
        <textarea :value="result.transcript_text || ''" readonly aria-label="提取的对话文字" />
      </section>
      <details v-if="job" class="studio-disclosure toolbox-advanced"><summary>运行记录 · {{ job.id }}</summary><pre class="toolbox-log">{{ (job.logs || []).join('\n') }}</pre><p v-if="job.error" class="context-error">{{ job.error }}</p></details>
    </div>
    <div v-show="selected === 'transcript'" id="tool-pane-transcript" role="tabpanel" aria-labelledby="tool-tab-transcript" class="toolbox-workbench">
      <div class="toolbox-section-head"><h3>字幕，变回一段文字</h3><label class="toolbox-check"><input v-model="timestamps" type="checkbox" />保留时间段</label></div>
      <p class="toolbox-help">粘贴或打开 SRT / VTT，按原顺序保留字幕内容、重复句和说话者。文件只在浏览器里处理，不上传、不调用模型。</p>
      <div class="toolbox-transcript-grid"><label>字幕内容<textarea v-model="subtitleInput" aria-label="待提取的字幕内容" placeholder="1&#10;00:00:01,000 --> 00:00:03,000&#10;这里是一句对话" /></label><label>纯文本<textarea :value="transcript.text" readonly aria-label="字幕纯文本结果" placeholder="提取后的文字会显示在这里" /></label></div>
      <div class="toolbox-run-row"><span role="status" :class="{ 'context-error': transcriptError }">{{ transcriptError || (transcript.count ? `${transcript.count} 条字幕 · 已提取` : '') }}</span><input ref="subtitleFile" hidden type="file" accept=".srt,.vtt,text/vtt" @change="openSubtitle" /><button type="button" class="secondary mini" @click="subtitleFile?.click()">打开字幕文件</button><button type="button" class="secondary mini" :disabled="!transcript.text" @click="copy(transcript.text)">复制文本</button><button type="button" class="mini" :disabled="!transcript.text" @click="downloadText">下载 TXT</button></div>
    </div>
    <p v-if="copyStatus" role="status" class="toolbox-copy-status">{{ copyStatus }}</p>
    <footer class="toolbox-more"><span>还可以</span><button v-for="link in shortcuts" :key="link.id" class="ghost mini" type="button" @click="$emit('open-view', link.id)"><AppIcon :name="link.icon" :size="16" />{{ link.title }}<AppIcon name="chevron" :size="13" /></button></footer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, getJson, uploadMediaFile } from '../api.js'
import { copyText } from '../clipboard.js'
import { TOOLBOX_TOOLS, dialoguePayload, mediaChoices, subtitleTranscript, toolJobBusy } from '../toolboxTools.js'
import AppIcon from './AppIcon.vue'
import ReferenceTranslator from './ReferenceTranslator.vue'
import SubtitleToolbox from './SubtitleToolbox.vue'

const props = defineProps({ assets: { type: Object, default: () => ({}) }, jobs: { type: Object, default: () => ({}) } })
const emit = defineEmits(['open-view', 'refresh-assets', 'job-started', 'cancel-job', 'edit-subtitle'])
const selected = ref('translate'), input = ref(''), language = ref('auto'), model = ref('large-v3'), device = ref('cuda')
const chineseScript = ref('simplified')
const hotwords = ref(''), speakers = ref(false), uploadInput = ref(null), subtitleFile = ref(null)
const knownSpeakerCount = ref('auto')
const uploading = ref(false), starting = ref(false), restoring = ref(false), error = ref(''), jobId = ref(''), copyStatus = ref('')
const subtitleInput = ref(''), timestamps = ref(false), subtitleError = ref('')
const media = computed(() => mediaChoices(props.assets))
const job = computed(() => props.jobs[jobId.value])
const result = computed(() => job.value?.result)
watch(() => result.value?.input_video, value => { if (value && !input.value) input.value = value })
watch(subtitleInput, () => { subtitleError.value = '' })
const isRunning = computed(() => toolJobBusy(job.value))
const busy = computed(() => uploading.value || starting.value || restoring.value || isRunning.value)
const jobMessage = computed(() => ({ done: '提取完成，可以复制或下载。', failed: job.value?.error || '提取失败，请展开运行记录查看原因。', cancelled: '已停止；可以重新提取。', cancel_requested: '正在停止任务…', queued: '任务排队中…', running: '正在识别对话；切换页面不会中止任务。' }[job.value?.status] || ''))
const transcript = computed(() => {
  if (!subtitleInput.value.trim()) return { text: '', count: 0 }
  try { return subtitleTranscript(subtitleInput.value, { timestamps: timestamps.value }) } catch { return { text: '', count: 0 } }
})
const transcriptError = computed(() => subtitleError.value || (subtitleInput.value.trim() && !transcript.value.count ? '没有找到有效字幕，请使用 SRT 或 WebVTT 内容。' : ''))
const shortcuts = [{ id: 'new-task', title: '下载音视频', icon: 'download' }, { id: 'subtitles', title: '字幕翻译与转换', icon: 'language' }, { id: 'ocr-dev', title: '画面文字提取', icon: 'scan' }, { id: 'video-overlay', title: '视频处理', icon: 'video' }]
const storageKey = 'reibosub-toolbox-dialogue-job'
let alive = true
onBeforeUnmount(() => { alive = false })
onMounted(async () => {
  let saved
  try { saved = localStorage.getItem(storageKey) } catch { return }
  if (!/^[a-f0-9]{12}$/.test(saved || '')) return
  restoring.value = true
  try {
    const restored = await getJson(`/api/jobs/${saved}`)
    if (!alive) return
    jobId.value = restored.id
    input.value = restored.result?.input_video || ''
    emit('job-started', restored)
  } catch { if (alive) error.value = '上次提取记录暂时无法加载；可以在任务日志中查找。' }
  finally { if (alive) restoring.value = false }
})
function fileUrl(path) { return `/api/file?path=${encodeURIComponent(path)}` }
function moveTab(event, id) {
  const index = TOOLBOX_TOOLS.findIndex(tool => tool.id === id)
  const count = TOOLBOX_TOOLS.length
  const next = { ArrowRight: (index + 1) % count, ArrowLeft: (index + count - 1) % count, Home: 0, End: count - 1 }[event.key]
  if (next === undefined) return
  event.preventDefault(); selected.value = TOOLBOX_TOOLS[next].id
  event.currentTarget.parentElement.querySelector(`#tool-tab-${selected.value}`)?.focus()
}
async function upload(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file || busy.value) return
  uploading.value = true; error.value = ''
  try {
    const uploaded = await uploadMediaFile(file)
    if (!alive) return
    input.value = uploaded.input_media || uploaded.input_video || uploaded.input_audio || ''
    emit('refresh-assets')
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) uploading.value = false }
}
async function extractDialogue() {
  if (busy.value) return
  starting.value = true; error.value = ''; copyStatus.value = ''
  try {
    const started = await api('/api/jobs/asr-lab', dialoguePayload({ input: input.value, language: language.value, model: model.value, device: device.value, hotwords: hotwords.value, speakers: speakers.value, knownSpeakerCount: knownSpeakerCount.value, chineseScript: chineseScript.value }))
    if (!alive) return
    jobId.value = started.id
    try { localStorage.setItem(storageKey, started.id) } catch {}
    emit('job-started', started)
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) starting.value = false }
}
async function copy(text) { copyStatus.value = await copyText(text) ? '已复制文字' : '复制失败，请手动选择文字。' }
async function openSubtitle(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file) return
  subtitleError.value = ''
  if (file.size > 10 * 1024 * 1024) { subtitleError.value = '请使用小于 10 MB 的字幕文件。'; return }
  try { const text = await file.text(); if (alive) subtitleInput.value = text }
  catch { if (alive) subtitleError.value = '字幕文件读取失败，请重试。' }
}
function downloadText() {
  const url = URL.createObjectURL(new Blob([transcript.value.text], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = 'transcript.txt'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<style scoped>
.toolbox-panel { max-width: 1100px; margin: 0 auto; width: 100%; }
.toolbox-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }
.toolbox-tabs button { display: flex; align-items: center; gap: 12px; text-align: left; padding: 18px; background: var(--surface); border: 1px solid var(--line); color: var(--muted); border-radius: 14px; }
.toolbox-tabs button.selected { background: var(--selected-surface); border-color: var(--teal); color: var(--ink); box-shadow: inset 0 0 0 1px var(--teal); }
.toolbox-tabs strong, .toolbox-tabs small { display: block; }.toolbox-tabs strong { font-size: 15px; }.toolbox-tabs small { color: var(--muted); font-size: 12px; font-weight: 400; margin-top: 4px; }
.toolbox-workbench { border: 1px solid var(--line); border-radius: 16px; padding: 22px; background: var(--surface); }
.toolbox-section-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.toolbox-section-head h3 { font-size: 17px; margin: 0; }.toolbox-section-head h3 small { font-size: 12px; color: var(--muted); font-weight: 400; }
.toolbox-tag { font-size: 12px; border: 1px solid var(--line); border-radius: 20px; padding: 4px 10px; color: var(--muted); }
.toolbox-help { color: var(--muted); font-size: 13px; line-height: 1.7; margin: 10px 0 18px; }
.toolbox-fields { border: 0; padding: 0; margin: 0; display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 16px; min-width: 0; }
.toolbox-fields label, .toolbox-transcript-grid label { display: grid; gap: 8px; min-width: 0; font-size: 13px; }.toolbox-wide { grid-column: 1 / -1; }
.toolbox-source-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }.toolbox-workbench > .toolbox-source-actions { margin-top: 12px; }
.toolbox-speakers { border: 0; padding: 0; margin: 18px 0 0; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px; }.toolbox-speaker-count { display: flex; align-items: center; gap: 10px; font-size: 13px; }.toolbox-speaker-count select { width: auto; min-width: 115px; }
.toolbox-advanced { margin-top: 18px; }.toolbox-advanced fieldset { margin-top: 16px; }.toolbox-check { display: flex !important; align-items: center; gap: 8px; font-size: 13px; }.toolbox-check input { width: auto; }
.toolbox-run-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 20px; }.toolbox-run-row > span { margin-right: auto; font-size: 13px; color: var(--muted); }.toolbox-run-row > .context-error { color: var(--danger, #b42318); }
.toolbox-result { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--line); }.toolbox-result textarea { margin-top: 14px; min-height: 280px; }
.toolbox-workbench textarea { width: 100%; resize: vertical; line-height: 1.8; font-size: 14px; }.toolbox-transcript-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }.toolbox-transcript-grid textarea { min-height: 280px; }.toolbox-workbench textarea[readonly] { background: var(--soft); }
.toolbox-log { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; font-size: 12px; }.toolbox-more { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 22px 0 0; color: var(--muted); }.toolbox-more > span { font-size: 12px; margin-right: 8px; }.toolbox-copy-status { font-size: 13px; color: var(--muted); }
@media (max-width: 700px) { .toolbox-tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }.toolbox-tabs button { padding: 12px 9px; gap: 8px; }.toolbox-tabs small { display: none; }.toolbox-fields, .toolbox-transcript-grid { grid-template-columns: minmax(0, 1fr); }.toolbox-workbench { padding: 16px; }.toolbox-tabs strong { font-size: 13px; } }
</style>
