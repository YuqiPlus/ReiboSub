<template>
  <section class="subtitle-toolbox" aria-label="字幕文件工具">
    <header class="subtitle-tools-head"><h3>一个字幕文件，想怎么处理？</h3><p>直接上传，不需要视频、不用创建 Agent 任务。原文件保留，每次操作另存结果。</p></header>
    <div class="subtitle-upload-zone" :class="{ ready: uploadInfo }" @dragover.prevent @drop.prevent="dropFile">
      <AppIcon :name="uploadInfo ? 'book' : 'plus'" :size="24" /><div><strong>{{ uploadInfo?.name || '拖入字幕文件，或点击上传' }}</strong><span>{{ uploadInfo ? `${uploadInfo.cue_count} 条字幕 · ${uploadInfo.format.toUpperCase()}` : 'SRT / VTT / ASS / SSA / BCC / JSON / LRC / TXT · 最大 10 MB' }}</span></div><button class="secondary" type="button" :disabled="busy" @click="fileInput?.click()">{{ uploading ? '正在上传…' : uploadInfo ? '更换文件' : '上传字幕' }}</button><input ref="fileInput" type="file" hidden accept=".srt,.vtt,.ass,.ssa,.bcc,.json,.lrc,.txt" @change="selectFile" />
    </div>
    <details class="studio-disclosure subtitle-encoding"><summary>文件编码与输入预览</summary><label>上传编码<select v-model="encoding" :disabled="busy" aria-label="字幕上传编码"><option value="utf-8-sig">UTF-8（默认）</option><option value="utf-16">UTF-16</option><option value="gb18030">GB18030 / GBK</option><option value="big5">Big5</option></select></label><p>乱码或解码失败时选择正确编码，重新上传；结果统一保存为 UTF-8。</p><pre v-if="uploadInfo">{{ previewText(uploadInfo.preview) }}</pre></details>
    <nav class="subtitle-operation-tabs" aria-label="字幕工具操作"><button v-for="item in operations" :key="item.id" type="button" :aria-pressed="operation === item.id" :class="{ selected: operation === item.id }" :disabled="busy" @click="operation = item.id">{{ item.label }}</button></nav>
    <fieldset :disabled="busy" class="subtitle-tool-fields">
      <template v-if="operation === 'translate'">
        <label>原文语言<select v-model="sourceLanguage" aria-label="字幕工具原文语言"><option value="auto">自动识别</option><option v-for="lang in targetLanguages" :key="lang.id" :value="lang.id">{{ lang.label }}</option></select></label>
        <label>译成<select v-model="targetLanguage" aria-label="字幕工具目标语言"><option v-for="lang in targetLanguages" :key="lang.id" :value="lang.id">{{ lang.id === 'zh' ? '中文（简体）' : lang.label }}</option></select></label>
        <p class="subtitle-tool-note">使用设置中的翻译模型，会消耗对应服务额度。默认只翻译文字，保留时间轴；不强制生成或审核术语表。</p>
        <details class="studio-disclosure subtitle-tool-wide"><summary>翻译方式与固定译名</summary><label>处理方式<select v-model="translationMode"><option value="translate_only">锁定时间轴：只翻译文字</option><option value="standard_cleanup">标准清理：处理重复与残片</option><option value="readability_retime">强力精修：可调整阅读时间</option></select></label><label>补充要求<textarea v-model="hint" maxlength="6000" placeholder="例如：张三固定译为 Zhang San；保留说话人标签。" /></label><p>需要完整术语表审核时，仍可使用原来的「翻译与转换」页面。</p></details>
      </template>
      <template v-else-if="operation === 'convert'"><label>目标格式<select v-model="outputFormat" aria-label="字幕工具目标格式"><option v-for="fmt in formats" :key="fmt" :value="fmt">{{ fmt === 'bcc' ? 'BCC · B 站字幕' : fmt.toUpperCase() }}</option></select></label><p class="subtitle-tool-note">本地格式转换，不调用模型。格式之间的信息能力不同，ASS/SSA 样式、位置和特效不会完整保留；LRC/TXT 也不能保留完整时轴。</p></template>
      <template v-else><label>转换为<select v-model="chineseScript" aria-label="字幕工具简繁方向"><option value="simplified">简体中文</option><option value="traditional">繁體中文</option></select></label><p class="subtitle-tool-note">本地字形转换，不调用模型、不纠正识别错词。保留原格式，只转换字幕文字，保留时间码和 ASS/SSA 样式定义。</p></template>
    </fieldset>
    <p v-if="uploadInfo?.format === 'txt'" class="subtitle-tool-notice">TXT 不含可靠时间轴。翻译及导出带时轴格式时会按每个非空行 3 秒生成临时时轴，请勿直接视为已校准字幕。</p>
    <div class="subtitle-tool-run"><span role="status" :class="{ 'context-error': error || job?.status === 'failed' }">{{ error || statusText }}</span><button v-if="running" class="secondary mini" type="button" :disabled="job.status === 'cancel_requested'" @click="$emit('cancel-job', job.id)">停止处理</button><button type="button" :disabled="busy || !uploadInfo" @click="run">{{ busy ? '正在处理…' : operation === 'translate' ? '翻译字幕' : operation === 'convert' ? '转换格式' : '转换简繁' }}</button></div>
    <section v-if="job?.status === 'done' && outputPath" class="subtitle-tool-result" aria-label="字幕工具结果"><div class="subtitle-result-head"><div><h3>处理完成</h3><p>{{ outputName }}</p></div><a class="button-link" :href="fileUrl(outputPath)" download>下载结果</a><button class="secondary mini" type="button" :disabled="busy" @click="reuseResult">用此结果继续处理</button><button v-if="outputName.toLowerCase().endsWith('.srt')" class="ghost mini" type="button" @click="$emit('edit-subtitle', outputPath, '')">打开精修</button></div><p>结果已另存，未覆盖上传文件。更换操作不会自动重新运行。</p><pre v-if="job.result?.preview">{{ previewText(job.result.preview) }}</pre></section>
    <details v-if="job" class="studio-disclosure subtitle-run-log"><summary>运行记录</summary><pre>{{ (job.logs || []).join('\n') }}</pre></details>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, getJson, uploadSubtitleFile } from '../api.js'
import { targetLanguages } from '../translationLanguages.js'
import { toolJobBusy } from '../toolboxTools.js'
import AppIcon from './AppIcon.vue'

const props = defineProps({ jobs: { type: Object, default: () => ({}) } })
const emit = defineEmits(['job-started', 'cancel-job', 'edit-subtitle'])
const operations = [{ id: 'translate', label: '字幕翻译' }, { id: 'convert', label: '格式转换' }, { id: 'script', label: '简繁转换' }]
const formats = ['srt', 'vtt', 'ass', 'ssa', 'bcc', 'json', 'lrc', 'txt']
const fileInput = ref(null), uploadInfo = ref(null), encoding = ref('utf-8-sig'), operation = ref('translate')
const sourceLanguage = ref('auto'), targetLanguage = ref('zh'), translationMode = ref('translate_only'), hint = ref('')
const outputFormat = ref('vtt'), chineseScript = ref('simplified'), jobId = ref('')
const uploading = ref(false), starting = ref(false), restoring = ref(false), error = ref('')
const job = computed(() => props.jobs[jobId.value]), running = computed(() => toolJobBusy(job.value))
const busy = computed(() => uploading.value || starting.value || restoring.value || running.value)
const outputPath = computed(() => job.value?.result?.output_path || job.value?.result?.translated_srt || '')
const outputName = computed(() => outputPath.value.split('/').pop())
const statusText = computed(() => ({ running: '后台处理中，切换页面不会中断。', queued: '排队中…', cancel_requested: '正在停止…', failed: job.value?.error || '处理失败，请查看运行记录。', cancelled: '已停止，可以重新操作。', done: '结果已生成，可以下载。' }[job.value?.status] || (uploadInfo.value ? '文件已就绪，选择操作后开始。' : '请先上传一个字幕文件。')))
const storageKey = 'reibosub-toolbox-subtitle-job'
let alive = true
onBeforeUnmount(() => { alive = false })
function fileUrl(path) { return `/api/file?path=${encodeURIComponent(path)}` }
function previewText(cues = []) { return cues.map(cue => `[${Number(cue.start).toFixed(2)} → ${Number(cue.end).toFixed(2)}]\n${cue.text}`).join('\n\n') }
function remember() {
  try { localStorage.setItem(storageKey, JSON.stringify({ uploadId: uploadInfo.value?.upload_id, jobId: jobId.value, operation: operation.value })) } catch {}
}
onMounted(async () => {
  let saved
  try { saved = JSON.parse(localStorage.getItem(storageKey) || 'null') } catch { return }
  if (!saved || !/^[a-f0-9]{32}$/.test(saved.uploadId || '')) return
  restoring.value = true
  try {
    const info = await getJson(`/api/toolbox/subtitles/uploads/${saved.uploadId}`)
    if (!alive) return
    uploadInfo.value = info
    if (operations.some(item => item.id === saved.operation)) operation.value = saved.operation
    if (/^[a-f0-9]{12}$/.test(saved.jobId || '')) {
      const restored = await getJson(`/api/jobs/${saved.jobId}`)
      if (!alive) return
      jobId.value = restored.id; emit('job-started', restored)
    }
  } catch { if (alive) error.value = '上次的文件或记录暂不可用，请重新上传；已有产物不会被删除。' }
  finally { if (alive) restoring.value = false }
})
async function upload(file, fileEncoding = encoding.value) {
  if (!file || busy.value) return
  if (file.size > 10 * 1024 * 1024) { error.value = '字幕文件最多 10 MB。'; return }
  uploading.value = true; error.value = ''
  uploadInfo.value = null; remember()
  try {
    const info = await uploadSubtitleFile(file, { encoding: fileEncoding })
    if (!alive) return
    uploadInfo.value = info; jobId.value = ''; remember()
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) uploading.value = false }
}
function selectFile(event) { const file = event.target.files?.[0]; event.target.value = ''; upload(file) }
function dropFile(event) {
  if (busy.value) return
  if (event.dataTransfer?.files?.length > 1) { error.value = '请一次上传一个字幕文件。'; return }
  upload(event.dataTransfer?.files?.[0])
}
async function run() {
  if (busy.value || !uploadInfo.value) return
  starting.value = true; error.value = ''
  try {
    const started = await api('/api/toolbox/subtitles', { upload_id: uploadInfo.value.upload_id, operation: operation.value, source_language: sourceLanguage.value, target_language: targetLanguage.value, translation_mode: translationMode.value, extra_prompt: hint.value, format: outputFormat.value, chinese_script: chineseScript.value })
    if (!alive) return
    jobId.value = started.id; remember(); emit('job-started', started)
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) starting.value = false }
}
async function reuseResult() {
  if (busy.value || !outputPath.value) return
  starting.value = true; error.value = ''
  try {
    const response = await fetch(fileUrl(outputPath.value))
    if (!response.ok) throw new Error('无法读取结果文件，请重新下载上传。')
    const blob = await response.blob(), name = outputName.value
    if (!alive) return
    starting.value = false
    await upload(new File([blob], name), 'utf-8-sig')
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) starting.value = false }
}
</script>

<style scoped>
.subtitle-toolbox { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 22px; }
.subtitle-tools-head h3, .subtitle-tool-result h3 { margin: 0; font-size: 17px; }.subtitle-tools-head p, .subtitle-toolbox p { color: var(--muted); font-size: 13px; line-height: 1.7; }
.subtitle-upload-zone { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; border: 1px dashed var(--line-strong); border-radius: 12px; padding: 20px; background: var(--soft); margin: 18px 0 12px; }.subtitle-upload-zone > div { flex: 1; min-width: 150px; overflow-wrap: anywhere; }.subtitle-upload-zone strong, .subtitle-upload-zone span { display: block; }.subtitle-upload-zone span { font-size: 12px; color: var(--muted); margin-top: 5px; }.subtitle-upload-zone.ready { border-style: solid; }
.subtitle-operation-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 22px 0 18px; }.subtitle-operation-tabs button { background: var(--soft); color: var(--muted); border: 1px solid var(--line); padding: 9px 18px; }.subtitle-operation-tabs button.selected { background: var(--selected-surface); color: var(--teal-dark); border-color: var(--teal); }
.subtitle-tool-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; border: 0; padding: 0; margin: 0; min-width: 0; }.subtitle-tool-fields label { display: grid; gap: 8px; min-width: 0; font-size: 13px; }.subtitle-tool-wide, .subtitle-tool-note { grid-column: 1 / -1; }.subtitle-tool-wide label { margin: 12px 0; }.subtitle-tool-wide textarea { min-height: 90px; resize: vertical; }.subtitle-tool-note { margin: 0; }
.subtitle-tool-run { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 22px; }.subtitle-tool-run span { margin-right: auto; font-size: 13px; color: var(--muted); }.subtitle-tool-run .context-error { color: var(--red); }.subtitle-tool-notice { background: var(--amber-soft); padding: 10px 14px; border-radius: 10px; }
.subtitle-tool-result { border-top: 1px solid var(--line); padding-top: 20px; margin-top: 24px; }.subtitle-result-head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }.subtitle-result-head > div { flex: 1; min-width: 150px; overflow-wrap: anywhere; }.subtitle-result-head p { margin: 5px 0 0; }.subtitle-toolbox pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; font-size: 12px; background: var(--soft); padding: 12px; border-radius: 10px; }.subtitle-encoding label { display: flex; align-items: center; gap: 12px; margin-top: 12px; font-size: 13px; }.subtitle-encoding select { width: auto; }.subtitle-run-log { margin-top: 18px; }
@media (max-width: 640px) { .subtitle-toolbox { padding: 16px; }.subtitle-tool-fields { grid-template-columns: minmax(0, 1fr); }.subtitle-upload-zone { padding: 14px; }.subtitle-operation-tabs button { padding: 8px 12px; } }
</style>
