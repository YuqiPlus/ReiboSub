<template>
  <div class="ocr-crop-panel">
    <div class="crop-header">
      <div>
        <b>{{ title }}</b>
        <span>亮区会参与底部主 OCR；智能全屏辅助仍保留全画面。</span>
      </div>
      <button class="secondary mini" type="button" :disabled="loading || !inputVideo" @click="loadPreview">
        {{ preview.image_data_url ? (loading ? '换帧中' : '换一帧') : (loading ? '抽帧中' : '抽一帧预览') }}
      </button>
    </div>

    <div class="crop-tune-panel">
      <div class="crop-controls grid-crop">
        <div class="crop-field">
          <span>上</span>
          <button type="button" class="crop-value-step" aria-label="减少上边界" @click="stepTop(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrCropTopRatio)" @input="onTopInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加上边界" @click="stepTop(1)">＋</button>
          <b>%</b>
        </div>
        <div class="crop-field">
          <span>下</span>
          <button type="button" class="crop-value-step" aria-label="减少下边界" @click="stepBottom(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrCropBottomRatio)" @input="onBottomInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加下边界" @click="stepBottom(1)">＋</button>
          <b>%</b>
        </div>
        <div class="crop-field">
          <span>左</span>
          <button type="button" class="crop-value-step" aria-label="减少左边界" @click="stepLeft(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrCropLeftRatio)" @input="onLeftInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加左边界" @click="stepLeft(1)">＋</button>
          <b>%</b>
        </div>
        <div class="crop-field">
          <span>右</span>
          <button type="button" class="crop-value-step" aria-label="减少右边界" @click="stepRight(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrCropRightRatio)" @input="onRightInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加右边界" @click="stepRight(1)">＋</button>
          <b>%</b>
        </div>
      </div>

      <div class="crop-joystick" aria-label="OCR 裁剪微调">
        <div class="crop-step-switch" aria-label="微调步长">
          <button v-for="step in nudgeSteps" :key="step" type="button" :class="{ active: nudgeStep === step }" @click="nudgeStep = step">{{ ratioToPercent(step) }}%</button>
        </div>
        <div class="crop-pad" aria-label="移动亮区">
          <span></span>
          <button type="button" aria-label="上移亮区" @click="nudgeWindow(0, -nudgeStep)">↑</button>
          <span></span>
          <button type="button" aria-label="左移亮区" @click="nudgeWindow(-nudgeStep, 0)">←</button>
          <button type="button" aria-label="缩小亮区" @click="resizeWindow(-nudgeStep)">−</button>
          <button type="button" aria-label="右移亮区" @click="nudgeWindow(nudgeStep, 0)">→</button>
          <span></span>
          <button type="button" aria-label="下移亮区" @click="nudgeWindow(0, nudgeStep)">↓</button>
          <button type="button" aria-label="扩大亮区" @click="resizeWindow(nudgeStep)">＋</button>
        </div>
      </div>
    </div>

    <div v-if="!inputVideo" class="muted crop-note">下载或选择视频后才能抽帧预览。</div>
    <div v-else-if="preview.image_data_url" class="crop-preview-wrap">
      <div class="crop-preview">
        <img :src="preview.image_data_url" alt="OCR crop preview" />
        <div class="crop-shade top" :style="topShadeStyle"></div>
        <div class="crop-shade bottom" :style="bottomShadeStyle"></div>
        <div class="crop-shade left" :style="leftShadeStyle"></div>
        <div class="crop-shade right" :style="rightShadeStyle"></div>
        <div class="crop-window" :style="windowStyle"></div>
      </div>
      <div class="crop-preview-meta">
        <span>预览帧 {{ previewTimeLabel }}</span>
        <span v-if="preview.width && preview.height">{{ preview.width }} × {{ preview.height }}</span>
      </div>
    </div>
    <div v-if="error" class="status bad">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api'

const props = defineProps({
  title: { type: String, default: 'OCR 裁剪区域' },
  inputVideo: { type: String, default: '' },
  ocrScope: { type: String, default: 'bottom' },
  ocrCropTopRatio: { type: Number, default: 0.58 },
  ocrCropBottomRatio: { type: Number, default: 0 },
  ocrCropLeftRatio: { type: Number, default: 0 },
  ocrCropRightRatio: { type: Number, default: 0 },
})

const emit = defineEmits([
  'update:ocrCropTopRatio',
  'update:ocrCropBottomRatio',
  'update:ocrCropLeftRatio',
  'update:ocrCropRightRatio',
])

const preview = reactive({ image_data_url: '', time_seconds: 0, duration_seconds: 0, width: 0, height: 0 })
const loading = ref(false)
const error = ref('')
const nudgeSteps = [0.01, 0.03, 0.05]
const nudgeStep = ref(0.03)

const topPct = computed(() => ratioToPercent(props.ocrCropTopRatio))
const bottomPct = computed(() => ratioToPercent(props.ocrCropBottomRatio))
const leftPct = computed(() => ratioToPercent(props.ocrCropLeftRatio))
const rightPct = computed(() => ratioToPercent(props.ocrCropRightRatio))
const keepTop = computed(() => topPct.value)
const keepBottom = computed(() => 100 - bottomPct.value)
const keepLeft = computed(() => leftPct.value)
const keepRight = computed(() => 100 - rightPct.value)

const windowStyle = computed(() => ({
  left: `${keepLeft.value}%`,
  top: `${keepTop.value}%`,
  width: `${Math.max(0, keepRight.value - keepLeft.value)}%`,
  height: `${Math.max(0, keepBottom.value - keepTop.value)}%`,
}))
const topShadeStyle = computed(() => ({ left: 0, top: 0, width: '100%', height: `${keepTop.value}%` }))
const bottomShadeStyle = computed(() => ({ left: 0, top: `${keepBottom.value}%`, width: '100%', height: `${100 - keepBottom.value}%` }))
const leftShadeStyle = computed(() => ({ left: 0, top: `${keepTop.value}%`, width: `${keepLeft.value}%`, height: `${Math.max(0, keepBottom.value - keepTop.value)}%` }))
const rightShadeStyle = computed(() => ({ left: `${keepRight.value}%`, top: `${keepTop.value}%`, width: `${100 - keepRight.value}%`, height: `${Math.max(0, keepBottom.value - keepTop.value)}%` }))
const previewTimeLabel = computed(() => formatTime(preview.time_seconds))

function ratioToPercent(value) {
  return Math.round(Number(value || 0) * 100)
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)))
}

function emitRatio(eventName, value, maxPercent = 45) {
  const percent = clamp(parsePercent(value), 0, maxPercent)
  emit(eventName, Number((percent / 100).toFixed(4)))
}

function parsePercent(value) {
  const normalized = String(value ?? '').replace(/[^0-9.]/g, '')
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : 0
}

function stepPercent(eventName, currentRatio, direction, maxPercent = 45) {
  const current = ratioToPercent(currentRatio)
  const step = Math.max(1, ratioToPercent(nudgeStep.value))
  emitRatio(eventName, current + direction * step, maxPercent)
}

function onTopInput(event) {
  emitRatio('update:ocrCropTopRatio', event.target.value, 95)
}

function onBottomInput(event) {
  emitRatio('update:ocrCropBottomRatio', event.target.value, 95)
}

function onLeftInput(event) {
  emitRatio('update:ocrCropLeftRatio', event.target.value)
}

function onRightInput(event) {
  emitRatio('update:ocrCropRightRatio', event.target.value)
}

function stepTop(direction) {
  stepPercent('update:ocrCropTopRatio', props.ocrCropTopRatio, direction, 95)
}

function stepBottom(direction) {
  stepPercent('update:ocrCropBottomRatio', props.ocrCropBottomRatio, direction, 95)
}

function stepLeft(direction) {
  stepPercent('update:ocrCropLeftRatio', props.ocrCropLeftRatio, direction)
}

function stepRight(direction) {
  stepPercent('update:ocrCropRightRatio', props.ocrCropRightRatio, direction)
}

function setRatios({ top, bottom, left, right }) {
  if (top !== undefined) emit('update:ocrCropTopRatio', Number(clamp(top, 0, 0.95).toFixed(4)))
  if (bottom !== undefined) emit('update:ocrCropBottomRatio', Number(clamp(bottom, 0, 0.95).toFixed(4)))
  if (left !== undefined) emit('update:ocrCropLeftRatio', Number(clamp(left, 0, 0.45).toFixed(4)))
  if (right !== undefined) emit('update:ocrCropRightRatio', Number(clamp(right, 0, 0.45).toFixed(4)))
}

function nudgeWindow(dx, dy) {
  const minWidth = 0.08
  const minHeight = 0.06
  const left = clamp(props.ocrCropLeftRatio, 0, 0.45)
  const rightEdge = clamp(1 - props.ocrCropRightRatio, 0.55, 1)
  const top = clamp(props.ocrCropTopRatio, 0, 0.95)
  const bottomEdge = clamp(1 - props.ocrCropBottomRatio, 0.05, 1)
  const width = Math.max(minWidth, rightEdge - left)
  const height = Math.max(minHeight, bottomEdge - top)
  const nextLeft = clamp(left + dx, 0, 1 - width)
  const nextTop = clamp(top + dy, 0, 1 - height)
  setRatios({
    left: nextLeft,
    right: 1 - (nextLeft + width),
    top: nextTop,
    bottom: 1 - (nextTop + height),
  })
}

function resizeWindow(delta) {
  const minWidth = 0.08
  const minHeight = 0.06
  const left = clamp(props.ocrCropLeftRatio, 0, 0.45)
  const rightEdge = clamp(1 - props.ocrCropRightRatio, 0.55, 1)
  const top = clamp(props.ocrCropTopRatio, 0, 0.95)
  const bottomEdge = clamp(1 - props.ocrCropBottomRatio, 0.05, 1)
  const centerX = (left + rightEdge) / 2
  const centerY = (top + bottomEdge) / 2
  const nextWidth = clamp((rightEdge - left) + delta * 2, minWidth, 1)
  const nextHeight = clamp((bottomEdge - top) + delta * 2, minHeight, 1)
  const nextLeft = clamp(centerX - nextWidth / 2, 0, 1 - nextWidth)
  const nextTop = clamp(centerY - nextHeight / 2, 0, 1 - nextHeight)
  setRatios({
    left: nextLeft,
    right: 1 - (nextLeft + nextWidth),
    top: nextTop,
    bottom: 1 - (nextTop + nextHeight),
  })
}

function nextPreviewTime() {
  const duration = Number(preview.duration_seconds || 0)
  if (!preview.image_data_url || !duration) return undefined
  if (duration <= 1) return 0
  const step = Math.max(3, duration * 0.17)
  const next = (Number(preview.time_seconds || 0) + step) % duration
  return Number(Math.min(duration - 0.1, Math.max(0, next)).toFixed(3))
}

function formatTime(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60).toString().padStart(2, '0')
  return `${minutes}:${rest}`
}

async function loadPreview() {
  if (!props.inputVideo) {
    error.value = '先下载或选择一个本地视频。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const requestedTime = nextPreviewTime()
    const payload = {
      input_video: props.inputVideo,
      ocr_scope: props.ocrScope,
      ocr_crop_top_ratio: props.ocrCropTopRatio,
      ocr_crop_bottom_ratio: props.ocrCropBottomRatio,
      ocr_crop_left_ratio: props.ocrCropLeftRatio,
      ocr_crop_right_ratio: props.ocrCropRightRatio,
    }
    if (requestedTime !== undefined) payload.time_seconds = requestedTime
    const result = await api('/api/ocr-preview-frame', payload)
    preview.image_data_url = result.image_data_url || ''
    preview.time_seconds = result.time_seconds || 0
    preview.duration_seconds = result.duration_seconds || preview.duration_seconds || 0
    preview.width = result.width || 0
    preview.height = result.height || 0
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}
</script>
