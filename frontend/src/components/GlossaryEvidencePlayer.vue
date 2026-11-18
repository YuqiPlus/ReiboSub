<template>
  <div class="glossary-evidence-player" aria-label="术语原声与画面">
    <div class="glossary-evidence-head">
      <b>{{ item.source }} · 原声与画面</b>
      <button class="secondary mini" type="button" @click="$emit('close')">收起播放器</button>
    </div>
    <p v-if="loading" role="status">正在定位证据原句…</p>
    <p v-if="error" class="status bad" role="alert">{{ error }}</p>
    <p v-if="data?.message" class="review-meta">{{ data.message }}</p>
    <template v-if="data?.evidence?.length">
      <div class="toolbar glossary-evidence-choices" aria-label="切换证据位置">
        <button v-for="(evidence, index) in data.evidence" :key="evidence.cue_id" class="secondary mini"
          :class="{ active: selectedIndex === index }" :aria-pressed="selectedIndex === index" type="button"
          @click="selectEvidence(index)">
          第 {{ index + 1 }} 处 · {{ evidenceTime(evidence.start) }}
        </button>
      </div>
      <p v-if="data.truncated" class="review-meta">共找到 {{ data.total_occurrences }} 处，先展示前 12 处。</p>
      <div v-if="selected" class="glossary-evidence-body" :class="{ 'text-only': !data.media }">
      <div v-if="data.media" class="glossary-evidence-media">
        <div class="glossary-evidence-stage" :class="{ 'audio-only': data.media.kind === 'audio' }">
          <component :is="data.media.kind === 'audio' ? 'audio' : 'video'" ref="player" :src="data.media.url"
            controls playsinline preload="metadata" :aria-label="`${item.source}证据片段`"
            @loadedmetadata="onMetadata" @timeupdate="onTimeUpdate" @play="onPlay" @pause="cancelFrame"
            @ended="onTimeUpdate" @ratechange="onTimeUpdate" @error="onMediaError" />
          <div v-if="activeCaptions.length" class="glossary-evidence-overlay" :class="{ 'audio-caption': data.media.kind === 'audio' }">
            <span v-for="cue in activeCaptions" :key="cue.cue_id">{{ cue.text }}</span>
          </div>
        </div>
        <div class="toolbar glossary-evidence-controls">
          <button class="secondary mini" type="button" :disabled="!mediaReady" @click="playSelected">重新播放片段</button>
          <label><input v-model="repeat" type="checkbox" />重复播放</label>
          <label>语速 <select v-model.number="rate" @change="changeRate"><option :value="0.75">0.75 倍</option><option :value="1">正常</option><option :value="1.25">1.25 倍</option></select></label>
          <button class="secondary mini" type="button" :disabled="!mediaReady" @click="togglePadding">{{ padding === 3 ? '扩大上下文（前后各 10 秒）' : '恢复短片段（前后各 3 秒）' }}</button>
        </div>
        <p class="review-meta">{{ windowLabel }} · 按原文字幕定位，播到片段末尾自动停止。画面下方叠加原文供对照，不是已确认译名。</p>
      </div>
      <div class="glossary-evidence-context" aria-label="证据原句前后文">
        <p v-if="!selected.literal_match" class="review-meta">这条证据未直接包含该写法，可能涉及连读、别名或识别错误，请以原声和上下文核对。</p>
        <div v-for="cue in selected.context" :key="cue.cue_id" :class="{ focused: cue.is_evidence }">
          <span>{{ evidenceTime(cue.start) }}{{ cue.is_evidence ? ' · 证据原句' : '' }}</span>
          <p>{{ cue.text }}</p>
        </div>
      </div>
      </div>
      <p v-if="data.missing_ids?.length" class="review-meta">部分旧证据编号已失效，仅展示仍能定位的原句。</p>
    </template>
    <button v-if="!loading && (error || (data?.evidence?.length && !data?.media))" class="secondary mini" type="button" @click="load">重新定位</button>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { evidenceCaptions, evidenceKey, evidenceTime, evidenceWindow } from '../glossaryEvidence.js'

const props = defineProps({ path: { type: String, required: true }, item: { type: Object, required: true } })
defineEmits(['close'])
const player = ref(null), data = ref(null), loading = ref(false), error = ref('')
const selectedIndex = ref(0), padding = ref(3), rate = ref(1), repeat = ref(false), currentTime = ref(0), mediaReady = ref(false)
const mediaDuration = ref(null)
let controller, generation = 0, playGeneration = 0, frame, boundedWindow = null, stopped = false
const selected = computed(() => data.value?.evidence?.[selectedIndex.value])
const activeCaptions = computed(() => evidenceCaptions(selected.value?.context, currentTime.value))
const windowLabel = computed(() => {
  try {
    const w = evidenceWindow(selected.value, { padding: padding.value, duration: mediaDuration.value })
    return `${evidenceTime(w.start)}—${evidenceTime(w.end)}`
  } catch { return '' }
})

function cancelFrame() { if (frame) cancelAnimationFrame(frame); frame = null }
function stop() { ++playGeneration; cancelFrame(); player.value?.pause(); boundedWindow = null; stopped = true }

async function load() {
  controller?.abort(); controller = new AbortController()
  const token = ++generation
  stop(); data.value = null; error.value = ''; loading.value = true; mediaReady.value = false; mediaDuration.value = null
  selectedIndex.value = 0; padding.value = 3; repeat.value = false
  try {
    const response = await fetch('/api/glossary-evidence', { method: 'POST', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: props.path, section: props.item.section, index: props.item.index, source: props.item.source }) })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || '无法定位证据片段。')
    if (token !== generation) return
    data.value = result
  } catch (e) {
    if (token === generation && e.name !== 'AbortError') error.value = e.message || '证据片段加载失败，请重试。'
  } finally { if (token === generation) loading.value = false }
}

function onMetadata() { mediaReady.value = true; mediaDuration.value = player.value?.duration; playSelected() }
async function playSelected() {
  const media = player.value
  if (!media || !mediaReady.value || !selected.value) return
  const token = ++playGeneration
  cancelFrame(); media.pause(); error.value = ''
  try {
    boundedWindow = evidenceWindow(selected.value, { padding: padding.value, duration: media.duration })
    media.currentTime = boundedWindow.start; currentTime.value = boundedWindow.start
    media.playbackRate = rate.value; stopped = false
    await media.play()
  } catch (e) {
    if (token !== playGeneration || e.name === 'AbortError') return
    error.value = e.name === 'NotAllowedError' ? '浏览器未自动开始播放，请点击视频中的播放按钮。' : e.message || '无法播放片段，请检查媒体格式。'
  }
}
function onPlay() {
  if (!boundedWindow) return
  if (stopped || player.value.currentTime < boundedWindow.start || player.value.currentTime >= boundedWindow.end) {
    player.value.currentTime = boundedWindow.start; stopped = false
  }
  tick()
}
function tick() {
  cancelFrame(); onTimeUpdate()
  if (player.value && !player.value.paused) frame = requestAnimationFrame(tick)
}
function onTimeUpdate() {
  const media = player.value
  if (!media) return
  currentTime.value = media.currentTime
  if (boundedWindow && !stopped && !media.seeking && media.currentTime >= boundedWindow.end - 0.015) {
    media.pause(); media.currentTime = boundedWindow.end; currentTime.value = boundedWindow.end; stopped = true
    if (repeat.value) void playSelected()
  }
}
function onMediaError() { stop(); mediaReady.value = false; error.value = '媒体加载失败或浏览器不支持该格式，请检查本地素材后重试。' }
async function selectEvidence(index) { stop(); selectedIndex.value = index; await nextTick(); await playSelected() }
async function togglePadding() { padding.value = padding.value === 3 ? 10 : 3; await playSelected() }
function changeRate() { if (player.value) player.value.playbackRate = rate.value }
watch(() => JSON.stringify([props.path, evidenceKey(props.item)]), load, { immediate: true })
onBeforeUnmount(() => { ++generation; controller?.abort(); stop() })
</script>
