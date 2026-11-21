<template>
  <section class="panel asr-lab-panel asr-studio">
    <header class="studio-page-head"><div><span class="studio-kicker">ASR Lab</span><h2>从声音里，还原每一句</h2><p>稳定识别与 Agent 实验分开选择，已有版本和结果继续保留。</p></div></header>
    <div class="lab-version-grid asr-version-grid" role="group" aria-label="ASR 版本"><button v-for="version in ASR_LAB_VERSIONS" :key="version.id" class="lab-version-card" :class="{ selected: asrVersion === version.id, experimental: version.experimental }" :aria-pressed="asrVersion === version.id" :disabled="running" @click="$emit('update:asrVersion', version.id)"><span><b>{{ version.label }}</b><small>{{ version.badge }}</small></span><p>{{ version.description }}</p></button></div>
    <p class="lab-version-detail">{{ currentVersion?.detail }}</p>
    <div class="studio-source-picker"><label for="asrLabInput">视频或音频文件<input id="asrLabInput" :value="inputVideo" :disabled="running" placeholder="选择或填写本地视频、音频路径" @input="$emit('update:inputVideo', $event.target.value)" /></label><button class="secondary" :disabled="running" @click="$emit('open-assets')"><AppIcon name="folder" :size="16" />从素材库选择</button></div>
    <fieldset v-if="!isExperiment" :disabled="running" class="lab-basic-row"><label for="asrLabLanguage">音频语言<select id="asrLabLanguage" :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)"><option value="auto">自动识别</option><option value="korean">韩语</option><option value="japanese">日语</option><option value="chinese">中文</option><option value="english">英语</option></select></label><p>{{ modelSize }} · {{ speakerDiarization ? '区分说话人' : '不区分说话人' }}<template v-if="asrVersion === '2.0'"> · {{ highRecall ? '高召回补漏开启' : '高召回补漏关闭' }}</template></p></fieldset>
    <fieldset v-if="!isExperiment && ['auto', 'chinese'].includes(sourceLanguage)" :disabled="running" class="lab-basic-row"><label>中文输出<select aria-label="ASR 中文输出" :value="chineseScript" @change="$emit('update:chineseScript', $event.target.value)"><option value="simplified">简体中文（默认）</option><option value="traditional">繁體中文</option><option value="original">保留识别原样</option></select></label><p>仅对中文识别结果统一字形，不改变时间轴，原始识别记录保留。</p></fieldset>
    <fieldset v-if="asrVersion === '2.0'" :disabled="running" class="asr-hotwords">
      <label v-if="asrVersion === '2.0'" class="asr-lab-wide-field">
        <span>专名与术语提示（可选）</span>
        <input
          :value="hotwords"
          placeholder="人名、节目名、品牌名，用空格或逗号分隔"
          @input="$emit('update:hotwords', $event.target.value)"
        />
      </label>

    </fieldset>
    <details v-if="!isExperiment" class="studio-disclosure lab-advanced"><summary>识别模型、说话人与补漏参数</summary><fieldset :disabled="running" class="lab-advanced-grid">
      <label v-if="!isExperiment">
        <span>ASR 模型</span>
        <select aria-label="ASR 模型" :value="modelSize" @change="$emit('update:modelSize', $event.target.value)">
          <option value="large-v3">large-v3（质量优先）</option>
          <option value="medium">medium（平衡）</option>
          <option value="small">small（速度优先）</option>
        </select>
      </label>

      <div v-if="asrVersion === '2.0'" class="ocr-dev-timing">
        <div>
          <b>高召回补漏</b>
          <span>推荐开启；第二遍发现缺口后，2.2 只对可疑片段做局部增益重听，可信内容会自动合回。</span>
        </div>
        <button
          class="secondary mini"
          type="button"
          :aria-pressed="highRecall"
          @click="$emit('update:highRecall', !highRecall)"
        >
          {{ highRecall ? '已开启' : '已关闭' }}
        </button>
      </div>
      <div v-if="!isExperiment" class="ocr-dev-timing">
        <div>
          <b>区分说话人（可选）</b>
          <span>只有多人音频需要开启；单人音频保持关闭即可，不影响使用 ASR 2.2。</span>
        </div>
        <button
          class="secondary mini"
          type="button"
          :aria-pressed="speakerDiarization"
          @click="$emit('update:speakerDiarization', !speakerDiarization)"
        >
          {{ speakerDiarization ? '已开启' : '已关闭' }}
        </button>
      </div>
      <label v-if="asrVersion === '2.0' && speakerDiarization">
        <span>已知说话人数</span>
        <select aria-label="已知说话人数" :value="knownSpeakerCount" @change="$emit('update:knownSpeakerCount', $event.target.value)">
          <option value="auto">自动判断</option>
          <option value="1">1 人</option>
          <option value="2">2 人</option>
          <option value="3">3 人</option>
          <option value="4">4 人</option>
          <option value="5">5 人</option>
          <option value="6">6 人</option>
        </select>
      </label>
      <div v-if="asrVersion === '2.0' && speakerDiarization" class="ocr-dev-timing">
        <div>
          <b>双 GPU 并行加速</b>
          <span>默认关闭；仅检测到至少两张 NVIDIA GPU 时使用，否则自动回退单 GPU 顺序执行。</span>
        </div>
        <button
          class="secondary mini"
          type="button"
          :aria-pressed="dualGpuParallel"
          @click="$emit('update:dualGpuParallel', !dualGpuParallel)"
        >
          {{ dualGpuParallel ? '已开启' : '已关闭' }}
        </button>
      </div>

    </fieldset></details>
    <fieldset v-if="isExperiment" :disabled="running" class="experiment-ranges">
      <h3>测试区间</h3>
      <p class="panel-subtitle">当前仅支持韩语。每段5秒到3分钟，最多3段；填写原视频的秒数或分:秒，例如 01:30。只处理选定区间。</p>
      <div v-for="(range, index) in testRanges" :key="index" class="experiment-range-row">
        <label><span>开始</span><input :value="range.start" :aria-label="`片段${index + 1}开始`" @input="updateRange(index, 'start', $event.target.value)" /></label>
        <label><span>结束</span><input :value="range.end" :aria-label="`片段${index + 1}结束`" @input="updateRange(index, 'end', $event.target.value)" /></label>
        <button class="secondary mini" type="button" :disabled="running || testRanges.length === 1" @click="$emit('update:testRanges', testRanges.filter((_, i) => i !== index))">移除</button>
      </div>
      <button class="secondary mini" type="button" :disabled="running || testRanges.length >= 3" @click="$emit('update:testRanges', [...testRanges, { start: '', end: '' }])">添加测试区间</button>
      <p class="panel-subtitle">音频只在本机识别；复核和翻译会调用设置中的模型服务，消耗相应额度。测试结果仍可能有识别和时间轴误差。</p>
    </fieldset>


    <footer class="studio-save-bar operation-run-bar"><span>{{ isExperiment ? '会调用模型服务；实验产物独立保存，不覆盖 2.2。' : '仅提取原文，不翻译、不调用 LLM。' }}</span><button :disabled="running || !inputVideo.trim()" @click="$emit('run')">{{ running ? '正在处理…' : `运行 ${currentVersion?.label || 'ASR'}` }}</button></footer>
    <p v-if="status" class="operation-status" :class="statusClass" role="status">{{ status }}</p>
    <div v-if="result?.kind === 'asr_experiment_lab'" class="asr-lab-output"><span class="lab-result-version">本次结果 · {{ resultVersionLabel }}</span>
      <h3>{{ result.pending_questions ? '字幕草稿已生成 · 有疑点需要确认' : '实验字幕已生成' }}</h3>
      <p>{{ result.cue_count }} 条字幕 · {{ result.pending_questions }} 处待确认 · {{ result.timing_needs_review }} 条时间边界需检查</p>
      <p class="panel-subtitle">{{ result.notice }}</p>
      <p v-if="result.pending_questions && result.human_review_available !== false" class="panel-subtitle">这里下载的是本次初稿；处理疑点后，请从审核页下载更新后的字幕。</p>
      <div class="toolbar">
        <a class="button-link" :href="result.report_url" target="_blank" rel="noopener">{{ result.pending_questions && result.human_review_available !== false ? (result.asr_version === 'autonomous-experimental' ? '确认疑点，让 Agent 继续' : '确认人名，让 Agent 继续') : '打开字幕试听' }}</a>
        <a class="button-link secondary" :href="fileUrl(result.translated_srt)" download>下载中文字幕</a>
        <a class="button-link secondary" :href="fileUrl(result.source_srt)" download>下载韩语字幕</a>
        <a v-if="result.autonomous_trace_url" class="button-link secondary" :href="result.autonomous_trace_url" target="_blank" rel="noopener">查看Agent操作记录</a>
      </div>
    </div>
    <div v-else-if="result" class="asr-lab-output"><span class="lab-result-version">本次结果 · {{ resultVersionLabel }}<template v-if="result.chinese_script && result.chinese_script !== 'original'"> · {{ result.chinese_script === 'traditional' ? '繁體中文' : '简体中文' }}</template></span>
      <div class="section-title">
        <div>
          <h3>识别文本</h3>
          <p class="panel-subtitle">
            {{ result.cue_count || 0 }} 条语音片段
            <template v-if="result.speaker_diarization"> · {{ result.speaker_count || 0 }} 位说话人</template>
          </p>
        </div>
        <div class="toolbar">
          <button class="secondary mini" type="button" :disabled="!result.transcript_text" @click="copyTranscript">复制文本</button>
          <a v-if="result.text_path" class="button-link secondary mini" :href="fileUrl(result.text_path)" download>下载 TXT</a>
          <a v-if="result.speaker_srt" class="button-link secondary mini" :href="fileUrl(result.speaker_srt)" download>带说话人 SRT</a>
          <a v-else-if="result.source_srt" class="button-link secondary mini" :href="fileUrl(result.source_srt)" download>下载 SRT</a>
          <a v-if="result.speaker_turns_path" class="button-link secondary mini" :href="fileUrl(result.speaker_turns_path)" download>分段 JSON</a>
        </div>
      </div>
      <details v-if="result.asr_version === '2.0'" class="studio-disclosure asr-result-metrics"><summary>识别统计与运行信息</summary>
      <div v-if="result.asr_version === '2.0'" class="asr-v2-metrics">
        <div><b>{{ result.word_count || 0 }}</b><span>识别词块</span></div>
        <div :class="{ warning: result.low_confidence_word_count }"><b>{{ result.low_confidence_word_count || 0 }}</b><span>低置信度词块</span></div>
        <div :class="{ warning: result.low_confidence_cue_count }"><b>{{ result.low_confidence_cue_count || 0 }}</b><span>待复核字幕</span></div>
        <div><b>{{ result.recovered_word_count || 0 }}</b><span>补回词块</span></div>
        <div><b>{{ result.focused_recovered_region_count || 0 }}</b><span>定向补回区间</span></div>
        <div :class="{ warning: result.suspected_missing_region_count }"><b>{{ result.suspected_missing_region_count || 0 }}</b><span>疑似漏听区间</span></div>
        <div><b>{{ result.detected_language || '—' }}</b><span>检测语言</span></div>
      </div>
      <p v-if="result.dual_gpu_parallel_requested" class="asr-v2-gpu-note">
        {{ result.dual_gpu_parallel_used
          ? '本次已并行使用两张 GPU：ASR 使用 GPU 0，说话人分离使用 GPU 1。'
          : `本次未启用双 GPU，已自动回退顺序执行（检测到 ${result.available_gpu_count || 0} 张 GPU）。` }}
      </p>
      </details>
      <section
        v-if="result.asr_version === '2.0' && result.suspected_missing_regions?.length"
        class="asr-review-panel"
      >
        <div class="section-title">
          <div>
            <h3>疑似漏听复核</h3>
            <p class="panel-subtitle">这些片段被低阈值识别听到，但证据还不足以自动写入字幕。试听后可修改候选文本，再采纳或忽略。</p>
          </div>
          <span class="asr-review-count">{{ result.suspected_missing_regions.length }} 处待处理</span>
        </div>
        <audio
          ref="reviewAudio"
          :src="fileUrl(result.input_video)"
          preload="metadata"
          controls
          @timeupdate="stopReviewAtBoundary"
          @ended="activeReviewId = ''"
        ></audio>
        <div class="asr-review-list">
          <article
            v-for="(region, index) in result.suspected_missing_regions"
            :key="region.review_id || `${region.start}-${index}`"
            class="asr-review-item"
            :class="{ active: activeReviewId === reviewRegionId(region, index) }"
          >
            <div class="asr-review-time">
              <b>试听 {{ formatClock(reviewStart(region)) }} – {{ formatClock(reviewEnd(region)) }}</b>
              <span>
                候选 {{ formatClock(region.candidate_start ?? region.start) }} – {{ formatClock(region.candidate_end ?? region.end) }}
                · {{ formatProbability(region.average_probability) }}
              </span>
            </div>
            <div class="asr-review-copy">
              <div
                v-if="region.context_before || region.context_after"
                class="asr-review-context"
                aria-label="候选前后文"
              >
                <span>{{ region.context_before || '…' }}</span>
                <mark>{{ reviewTextValue(region, index) || region.text }}</mark>
                <span>{{ region.context_after || '…' }}</span>
              </div>
              <label>
                <span>仅补入缺口的候选文本</span>
                <input
                  :value="reviewTextValue(region, index)"
                  :aria-label="`${formatClock(region.start)} 候选文本`"
                  @input="setReviewText(region, index, $event.target.value)"
                />
              </label>
              <p v-if="region.focused_text && region.focused_text !== region.text">
                缺口局部重听：{{ region.focused_text }}
                <template v-if="region.consensus_similarity != null">
                  · 一致度 {{ Math.round(Number(region.consensus_similarity) * 100) }}%
                </template>
              </p>
              <p v-if="region.focused_context_text" class="asr-review-full-context">
                局部重听整段：{{ region.focused_context_text }}
              </p>
              <p v-else-if="!region.focused_text || region.focused_text === region.text">局部重听仍未达到自动采纳阈值，请以完整试听为准。</p>
            </div>
            <div class="asr-review-actions">
              <button
                class="secondary mini"
                type="button"
                :disabled="reviewBusyId === reviewRegionId(region, index)"
                @click="playReviewRegion(region, index)"
              >
                {{ activeReviewId === reviewRegionId(region, index) ? '停止' : '试听' }}
              </button>
              <button
                class="mini"
                type="button"
                :disabled="reviewBusyId === reviewRegionId(region, index) || !reviewTextValue(region, index).trim()"
                @click="submitReview(region, index, 'accept')"
              >
                {{ reviewBusyId === reviewRegionId(region, index) ? '处理中…' : '采纳' }}
              </button>
              <button
                class="secondary mini"
                type="button"
                :disabled="reviewBusyId === reviewRegionId(region, index)"
                @click="submitReview(region, index, 'ignore')"
              >忽略</button>
            </div>
          </article>
        </div>
      </section>
      <details class="studio-disclosure asr-transcript" :open="!result.suspected_missing_regions?.length"><summary>识别全文</summary><textarea :value="result.transcript_text || ''" readonly aria-label="识别全文" placeholder="识别完成后会在这里显示纯文本"></textarea></details>
      <details class="studio-disclosure asr-result-artifacts"><summary>全部产物、原始数据与路径</summary>
      <div class="asr-lab-paths">
        <div v-if="result.source_sidecar" class="path-row"><span>素材库字幕</span><code>{{ result.source_sidecar }}</code></div>
        <div v-if="result.text_path" class="path-row"><span>{{ result.speaker_diarization ? '标注文本' : '纯文本' }}</span><code>{{ result.text_path }}</code></div>
        <div v-if="result.speaker_srt" class="path-row"><span>标注时间轴</span><code>{{ result.speaker_srt }}</code></div>
        <div v-if="result.source_srt" class="path-row"><span>原始时间轴</span><code>{{ result.source_srt }}</code></div>
        <div v-if="result.plain_text_path" class="path-row"><span>原始文本</span><code>{{ result.plain_text_path }}</code></div>
        <div v-if="result.speaker_turns_path" class="path-row"><span>说话人分段</span><code>{{ result.speaker_turns_path }}</code></div>
        <div v-if="result.raw_source_srt" class="path-row"><span>1:1 原始结果</span><code>{{ result.raw_source_srt }}</code></div>
        <div v-if="result.recovery_raw_source_srt" class="path-row"><span>补漏原始结果</span><code>{{ result.recovery_raw_source_srt }}</code></div>
        <div v-if="result.reviewed_srt" class="path-row"><span>人工复核时间轴</span><code>{{ result.reviewed_srt }}</code></div>
        <div v-if="result.words_path" class="path-row"><span>单词数据</span><code>{{ result.words_path }}</code></div>
        <div v-if="result.quality_path" class="path-row"><span>质量报告</span><code>{{ result.quality_path }}</code></div>
      </div>
      <div v-if="result.asr_version === '2.0'" class="toolbar asr-v2-downloads">
        <a v-if="result.raw_source_srt" class="button-link secondary mini" :href="fileUrl(result.raw_source_srt)" download>原始 SRT</a>
        <a v-if="result.recovery_raw_source_srt" class="button-link secondary mini" :href="fileUrl(result.recovery_raw_source_srt)" download>补漏 SRT</a>
        <a v-if="result.words_path" class="button-link secondary mini" :href="fileUrl(result.words_path)" download>Words JSON</a>
        <a v-if="result.recovery_words_path" class="button-link secondary mini" :href="fileUrl(result.recovery_words_path)" download>补漏 Words</a>
        <a v-if="result.focused_words_path" class="button-link secondary mini" :href="fileUrl(result.focused_words_path)" download>定向重听 Words</a>
        <a v-if="result.segments_path" class="button-link secondary mini" :href="fileUrl(result.segments_path)" download>Segments JSON</a>
        <a v-if="result.recovery_segments_path" class="button-link secondary mini" :href="fileUrl(result.recovery_segments_path)" download>补漏 Segments</a>
        <a v-if="result.focused_segments_path" class="button-link secondary mini" :href="fileUrl(result.focused_segments_path)" download>定向重听 Segments</a>
        <a v-if="result.quality_path" class="button-link secondary mini" :href="fileUrl(result.quality_path)" download>质量报告</a>
      </div>
      </details>
    </div>

  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { copyText } from '../clipboard.js'
import AppIcon from './AppIcon.vue'
import { ASR_LAB_VERSIONS } from '../labVersions.js'

const props = defineProps({
  inputVideo: { type: String, default: '' },
  asrVersion: { type: String, default: '1.0' },
  testRanges: { type: Array, default: () => [{ start: '00:00', end: '01:30' }] },
  sourceLanguage: { type: String, default: 'auto' },
  chineseScript: { type: String, default: 'simplified' },
  modelSize: { type: String, default: 'large-v3' },
  speakerDiarization: { type: Boolean, default: false },
  knownSpeakerCount: { type: String, default: 'auto' },
  hotwords: { type: String, default: '' },
  highRecall: { type: Boolean, default: true },
  dualGpuParallel: { type: Boolean, default: false },
  running: { type: Boolean, default: false },
  reviewBusyId: { type: String, default: '' },
  result: { type: Object, default: null },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

const emit = defineEmits([
  'update:inputVideo',
  'update:asrVersion',
  'update:testRanges',
  'update:sourceLanguage',
  'update:chineseScript',
  'update:modelSize',
  'update:speakerDiarization',
  'update:knownSpeakerCount',
  'update:hotwords',
  'update:highRecall',
  'update:dualGpuParallel',
  'open-assets',
  'run',
  'copy-status',
  'review-decision',
])

const reviewAudio = ref(null)
const isExperiment = computed(() => ['agent-experimental', 'autonomous-experimental'].includes(props.asrVersion))
const currentVersion = computed(() => ASR_LAB_VERSIONS.find(version => version.id === props.asrVersion))
const resultVersionLabel = computed(() => ASR_LAB_VERSIONS.find(version => version.id === props.result?.asr_version)?.label || `ASR ${props.result?.pipeline_version || props.result?.asr_version || '1.0'}`)
function updateRange(index, key, value) {
  emit('update:testRanges', props.testRanges.map((r, i) => i === index ? { ...r, [key]: value } : r))
}
const activeReviewId = ref('')
const reviewTexts = reactive({})
let reviewStopAt = 0

async function copyTranscript() {
  const ok = await copyText(props.result?.transcript_text || '')
  emit('copy-status', ok ? '识别文本已复制。' : '复制失败，请手动选择文本。', ok ? 'ok' : 'bad')
}

function fileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path || '')}`
}

function reviewRegionId(region, index) {
  return region.review_id || `gap-${index}-${Math.round(Number(region.start || 0) * 1000)}`
}

function reviewTextValue(region, index) {
  const reviewId = reviewRegionId(region, index)
  return Object.prototype.hasOwnProperty.call(reviewTexts, reviewId)
    ? reviewTexts[reviewId]
    : (region.text || '')
}

function setReviewText(region, index, value) {
  reviewTexts[reviewRegionId(region, index)] = value
}

function formatClock(value) {
  const total = Math.max(0, Number(value || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = (total % 60).toFixed(1).padStart(4, '0')
  return hours
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${seconds}`
    : `${String(minutes).padStart(2, '0')}:${seconds}`
}

function formatProbability(value) {
  if (value == null || Number.isNaN(Number(value))) return '置信度未知'
  return `候选置信度 ${Math.round(Number(value) * 100)}%`
}

function reviewStart(region) {
  if (region.review_start != null) return Number(region.review_start)
  return Math.max(0, Number(region.start || 0) - 1.8)
}

function reviewEnd(region) {
  if (region.review_end != null) return Number(region.review_end)
  return Number(region.end || 0) + 1.8
}

async function playReviewRegion(region, index) {
  const audio = reviewAudio.value
  if (!audio) return
  const reviewId = reviewRegionId(region, index)
  if (activeReviewId.value === reviewId && !audio.paused) {
    audio.pause()
    activeReviewId.value = ''
    return
  }
  activeReviewId.value = reviewId
  reviewStopAt = reviewEnd(region)
  try {
    await waitForAudioMetadata(audio)
    audio.currentTime = reviewStart(region)
    await audio.play()
  } catch {
    activeReviewId.value = ''
  }
}

function waitForAudioMetadata(audio) {
  if (audio.readyState >= 1) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup()
      reject(new Error('audio metadata timeout'))
    }, 5000)
    const cleanup = () => {
      window.clearTimeout(timeout)
      audio.removeEventListener('loadedmetadata', handleLoaded)
      audio.removeEventListener('error', handleError)
    }
    const handleLoaded = () => {
      cleanup()
      resolve()
    }
    const handleError = () => {
      cleanup()
      reject(new Error('audio metadata failed'))
    }
    audio.addEventListener('loadedmetadata', handleLoaded, { once: true })
    audio.addEventListener('error', handleError, { once: true })
    audio.load()
  })
}

function stopReviewAtBoundary() {
  const audio = reviewAudio.value
  if (!audio || !activeReviewId.value) return
  if (audio.currentTime >= reviewStopAt) {
    audio.pause()
    activeReviewId.value = ''
  }
}

function submitReview(region, index, action) {
  const reviewId = reviewRegionId(region, index)
  const editedText = reviewTextValue(region, index).trim()
  emit('review-decision', {
    action,
    region: {
      ...region,
      review_id: reviewId,
      text: editedText || region.text || '（忽略）',
    },
  })
}

onBeforeUnmount(() => {
  reviewAudio.value?.pause()
})
</script>

<style scoped>
.experiment-ranges { margin: 18px 0; padding: 16px; border: 1px solid var(--border, #dce2ec); border-radius: 12px; }
.experiment-range-row { display: flex; align-items: end; gap: 12px; margin: 12px 0; }
.experiment-range-row label { flex: 1; min-width: 0; display: grid; gap: 5px; }
.experiment-range-row input { width: 100%; min-width: 0; }
@media (max-width: 600px) { .experiment-range-row { gap: 7px; flex-wrap: wrap; } }
</style>
