<template>
  <div class="ocr-crop-panel">
    <div class="crop-header">
      <div>
        <b>{{ title }}</b>
        <span>{{ cropStatus }}</span>
      </div>
      <div class="crop-actions">
        <button class="secondary mini" type="button" @click="toggleExclude">
          {{ ocrExcludeEnabled ? '关闭排除框' : '添加 Logo 排除框' }}
        </button>
        <button class="secondary mini" type="button" :disabled="loading || !inputVideo" @click="loadPreview">
          {{ previewButtonLabel }}
        </button>
      </div>
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

      <div v-if="ocrExcludeEnabled" class="crop-controls grid-crop exclude-controls" aria-label="Logo 排除框微调">
        <div class="crop-field exclude">
          <span>排上</span>
          <button type="button" class="crop-value-step" aria-label="减少排除框上边界" @click="stepExcludeTop(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrExcludeTopRatio)" @input="onExcludeTopInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加排除框上边界" @click="stepExcludeTop(1)">＋</button>
          <b>%</b>
        </div>
        <div class="crop-field exclude">
          <span>排下</span>
          <button type="button" class="crop-value-step" aria-label="减少排除框下边界" @click="stepExcludeBottom(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrExcludeBottomRatio)" @input="onExcludeBottomInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加排除框下边界" @click="stepExcludeBottom(1)">＋</button>
          <b>%</b>
        </div>
        <div class="crop-field exclude">
          <span>排左</span>
          <button type="button" class="crop-value-step" aria-label="减少排除框左边界" @click="stepExcludeLeft(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrExcludeLeftRatio)" @input="onExcludeLeftInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加排除框左边界" @click="stepExcludeLeft(1)">＋</button>
          <b>%</b>
        </div>
        <div class="crop-field exclude">
          <span>排右</span>
          <button type="button" class="crop-value-step" aria-label="减少排除框右边界" @click="stepExcludeRight(-1)">−</button>
          <input type="text" inputmode="decimal" :value="ratioToPercent(ocrExcludeRightRatio)" @input="onExcludeRightInput" @keydown.enter.prevent />
          <button type="button" class="crop-value-step" aria-label="增加排除框右边界" @click="stepExcludeRight(1)">＋</button>
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
      <div ref="previewEl" class="crop-preview" @pointermove="onPointerMove" @pointerup="endDrag" @pointercancel="endDrag">
        <img :src="preview.image_data_url" alt="OCR crop preview" />
        <div class="crop-shade top" :style="topShadeStyle"></div>
        <div class="crop-shade bottom" :style="bottomShadeStyle"></div>
        <div class="crop-shade left" :style="leftShadeStyle"></div>
        <div class="crop-shade right" :style="rightShadeStyle"></div>
        <div class="crop-window draggable" :style="windowStyle" title="拖动移动字幕区域；拖右下角调整大小" @pointerdown.stop.prevent="startDrag('crop', 'move', $event)">
          <span class="crop-window-label">字幕区</span>
          <span class="crop-resize-handle" @pointerdown.stop.prevent="startDrag('crop', 'resize', $event)"></span>
        </div>
        <div v-if="ocrExcludeEnabled" class="exclude-window draggable" :style="excludeWindowStyle" title="拖动移动 Logo 排除框；拖右下角调整大小" @pointerdown.stop.prevent="startDrag('exclude', 'move', $event)">
          <span class="crop-window-label">排除</span>
          <span class="crop-resize-handle" @pointerdown.stop.prevent="startDrag('exclude', 'resize', $event)"></span>
        </div>
        <svg
          v-if="preview.ocr_analyzed && preview.width && preview.height"
          class="ocr-candidate-overlay"
          :viewBox="`0 0 ${preview.width} ${preview.height}`"
          :style="{ '--ocr-candidate-font-size': `${candidateFontSize}px` }"
          preserveAspectRatio="none"
          aria-label="OCR 3.0 候选框预览"
        >
          <g v-for="(candidate, index) in preview.accepted" :key="`accepted-${index}`">
            <polygon :points="candidatePoints(candidate)" :class="acceptedCandidateBoxClass(candidate)" />
            <text :x="candidateLabelX(candidate)" :y="candidateLabelY(candidate)" :class="acceptedCandidateLabelClass(candidate)">
              {{ candidateLabel(candidate, acceptedCandidateStatus(candidate)) }}
            </text>
          </g>
          <g v-for="(candidate, index) in preview.rejected" :key="`rejected-${index}`">
            <polygon :points="candidatePoints(candidate)" class="ocr-candidate-box rejected" />
            <text :x="candidateLabelX(candidate)" :y="candidateLabelY(candidate)" class="ocr-candidate-label rejected">
              {{ candidateLabel(candidate, '硬排除') }}
            </text>
          </g>
        </svg>
      </div>
      <div class="crop-preview-meta">
        <span>预览帧 {{ previewTimeLabel }}</span>
        <span v-if="ocrExcludeEnabled">红框内 OCR 会被忽略</span>
        <span v-if="preview.ocr_analyzed" class="ocr-preview-summary">
          <b class="kept">普通候选 {{ regularCandidateCount }}</b>
          <b v-if="softCandidateCount" class="caution">待几何精修 {{ softCandidateCount }}</b>
          <b class="removed">硬排除 {{ preview.rejected.length }}</b>
        </span>
        <span v-if="preview.width && preview.height">{{ preview.width }} × {{ preview.height }}</span>
      </div>
      <div v-if="preview.ocr_analyzed" class="muted crop-note">单帧预览只显示几何预筛；最终是否进入字幕由跨帧证据和几何 LLM 精修决定。</div>
    </div>
    <div v-if="error" class="status bad">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({
  title: { type: String, default: 'OCR 裁剪区域' },
  inputVideo: { type: String, default: '' },
  ocrScope: { type: String, default: 'bottom' },
  ocrExtractionMode: { type: String, default: 'region' },
  ocrShapeMode: { type: String, default: 'horizontal_preferred' },
  sourceLanguage: { type: String, default: 'korean' },
  ocrLanguage: { type: String, default: 'auto' },
  ocrMinConfidence: { type: Number, default: 0.45 },
  ocrCropTopRatio: { type: Number, default: 0.58 },
  ocrCropBottomRatio: { type: Number, default: 0 },
  ocrCropLeftRatio: { type: Number, default: 0 },
  ocrCropRightRatio: { type: Number, default: 0 },
  ocrExcludeEnabled: { type: Boolean, default: false },
  ocrExcludeTopRatio: { type: Number, default: 0.04 },
  ocrExcludeBottomRatio: { type: Number, default: 0.82 },
  ocrExcludeLeftRatio: { type: Number, default: 0.76 },
  ocrExcludeRightRatio: { type: Number, default: 0.02 },
  autoLoadPreview: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:ocrCropTopRatio',
  'update:ocrCropBottomRatio',
  'update:ocrCropLeftRatio',
  'update:ocrCropRightRatio',
  'update:ocrExcludeEnabled',
  'update:ocrExcludeTopRatio',
  'update:ocrExcludeBottomRatio',
  'update:ocrExcludeLeftRatio',
  'update:ocrExcludeRightRatio',
])

const preview = reactive({
  image_data_url: '',
  time_seconds: 0,
  duration_seconds: 0,
  width: 0,
  height: 0,
  ocr_analyzed: false,
  ocr_stale: false,
  accepted: [],
  rejected: [],
})
const previewEl = ref(null)
const loading = ref(false)
const error = ref('')
const nudgeSteps = [0.01, 0.03, 0.05]
const nudgeStep = ref(0.03)
const cropStatus = ref('调整后会自动保存到当前 OCR 参数。')
const dragState = ref(null)
const lastAutoLoadedVideo = ref('')

const topPct = computed(() => ratioToPercent(props.ocrCropTopRatio))
const bottomPct = computed(() => ratioToPercent(props.ocrCropBottomRatio))
const leftPct = computed(() => ratioToPercent(props.ocrCropLeftRatio))
const rightPct = computed(() => ratioToPercent(props.ocrCropRightRatio))
const keepTop = computed(() => topPct.value)
const keepBottom = computed(() => 100 - bottomPct.value)
const keepLeft = computed(() => leftPct.value)
const keepRight = computed(() => 100 - rightPct.value)
const excludeTopPct = computed(() => ratioToPercent(props.ocrExcludeTopRatio))
const excludeBottomPct = computed(() => ratioToPercent(props.ocrExcludeBottomRatio))
const excludeLeftPct = computed(() => ratioToPercent(props.ocrExcludeLeftRatio))
const excludeRightPct = computed(() => ratioToPercent(props.ocrExcludeRightRatio))
const excludeKeepBottom = computed(() => 100 - excludeBottomPct.value)
const excludeKeepRight = computed(() => 100 - excludeRightPct.value)

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
const excludeWindowStyle = computed(() => ({
  left: `${excludeLeftPct.value}%`,
  top: `${excludeTopPct.value}%`,
  width: `${Math.max(0, excludeKeepRight.value - excludeLeftPct.value)}%`,
  height: `${Math.max(0, excludeKeepBottom.value - excludeTopPct.value)}%`,
}))
const previewTimeLabel = computed(() => formatTime(preview.time_seconds))
const candidateFontSize = computed(() => Math.max(18, Number(preview.width || 0) * 0.018))
const softCandidateCount = computed(() => preview.accepted.filter(isSoftGeometryCandidate).length)
const regularCandidateCount = computed(() => Math.max(0, preview.accepted.length - softCandidateCount.value))
const previewButtonLabel = computed(() => {
  const analyze = props.ocrExtractionMode === 'region_v3'
  if (loading.value) return analyze ? 'OCR 分析中' : (preview.image_data_url ? '换帧中' : '抽帧中')
  if (analyze && preview.image_data_url && preview.ocr_stale) return '按当前设置重新分析'
  if (preview.image_data_url) return analyze ? '换一帧并分析' : '换一帧'
  return analyze ? '抽一帧并分析' : '抽一帧预览'
})
const cropKey = computed(() => [
  props.ocrScope,
  props.ocrExtractionMode,
  props.ocrShapeMode,
  props.sourceLanguage,
  props.ocrLanguage,
  Number(props.ocrMinConfidence || 0).toFixed(4),
  Number(props.ocrCropTopRatio || 0).toFixed(4),
  Number(props.ocrCropBottomRatio || 0).toFixed(4),
  Number(props.ocrCropLeftRatio || 0).toFixed(4),
  Number(props.ocrCropRightRatio || 0).toFixed(4),
  props.ocrExcludeEnabled ? 'exclude-on' : 'exclude-off',
  Number(props.ocrExcludeTopRatio || 0).toFixed(4),
  Number(props.ocrExcludeBottomRatio || 0).toFixed(4),
  Number(props.ocrExcludeLeftRatio || 0).toFixed(4),
  Number(props.ocrExcludeRightRatio || 0).toFixed(4),
].join('|'))
const previewRequestKey = computed(() => [props.inputVideo, cropKey.value].join('|'))

watch(cropKey, (_next, previous) => {
  if (!previous) return
  cropStatus.value = '已自动保存当前裁剪设置，下一次 OCR 会使用。'
  preview.ocr_analyzed = false
  preview.ocr_stale = props.ocrExtractionMode === 'region_v3' && Boolean(preview.image_data_url)
  preview.accepted = []
  preview.rejected = []
})

watch(
  () => props.inputVideo,
  (inputVideo, previousVideo) => {
    const nextVideo = String(inputVideo || '').trim()
    const previous = String(previousVideo || '').trim()
    if (nextVideo !== previous) resetPreview()
    if (!nextVideo) {
      lastAutoLoadedVideo.value = ''
      return
    }
    if (!props.autoLoadPreview || lastAutoLoadedVideo.value === nextVideo) return
    lastAutoLoadedVideo.value = nextVideo
    void loadPreview()
  },
  { immediate: true },
)

onUnmounted(() => {
  window.removeEventListener('pointerup', endDrag)
})

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

function emitExcludeRatio(eventName, value) {
  const percent = clamp(parsePercent(value), 0, 98)
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

function stepExcludePercent(eventName, currentRatio, direction) {
  const current = ratioToPercent(currentRatio)
  const step = Math.max(1, ratioToPercent(nudgeStep.value))
  emitExcludeRatio(eventName, current + direction * step)
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

function onExcludeTopInput(event) {
  emitExcludeRatio('update:ocrExcludeTopRatio', event.target.value)
}

function onExcludeBottomInput(event) {
  emitExcludeRatio('update:ocrExcludeBottomRatio', event.target.value)
}

function onExcludeLeftInput(event) {
  emitExcludeRatio('update:ocrExcludeLeftRatio', event.target.value)
}

function onExcludeRightInput(event) {
  emitExcludeRatio('update:ocrExcludeRightRatio', event.target.value)
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

function stepExcludeTop(direction) {
  stepExcludePercent('update:ocrExcludeTopRatio', props.ocrExcludeTopRatio, direction)
}

function stepExcludeBottom(direction) {
  stepExcludePercent('update:ocrExcludeBottomRatio', props.ocrExcludeBottomRatio, direction)
}

function stepExcludeLeft(direction) {
  stepExcludePercent('update:ocrExcludeLeftRatio', props.ocrExcludeLeftRatio, direction)
}

function stepExcludeRight(direction) {
  stepExcludePercent('update:ocrExcludeRightRatio', props.ocrExcludeRightRatio, direction)
}

function setRatios({ top, bottom, left, right }) {
  if (top !== undefined) emit('update:ocrCropTopRatio', Number(clamp(top, 0, 0.95).toFixed(4)))
  if (bottom !== undefined) emit('update:ocrCropBottomRatio', Number(clamp(bottom, 0, 0.95).toFixed(4)))
  if (left !== undefined) emit('update:ocrCropLeftRatio', Number(clamp(left, 0, 0.45).toFixed(4)))
  if (right !== undefined) emit('update:ocrCropRightRatio', Number(clamp(right, 0, 0.45).toFixed(4)))
}

function setExcludeRatios({ top, bottom, left, right }) {
  if (top !== undefined) emit('update:ocrExcludeTopRatio', Number(clamp(top, 0, 0.98).toFixed(4)))
  if (bottom !== undefined) emit('update:ocrExcludeBottomRatio', Number(clamp(bottom, 0, 0.98).toFixed(4)))
  if (left !== undefined) emit('update:ocrExcludeLeftRatio', Number(clamp(left, 0, 0.98).toFixed(4)))
  if (right !== undefined) emit('update:ocrExcludeRightRatio', Number(clamp(right, 0, 0.98).toFixed(4)))
}

function toggleExclude() {
  if (!props.ocrExcludeEnabled) {
    if ((1 - props.ocrExcludeRightRatio) <= props.ocrExcludeLeftRatio || (1 - props.ocrExcludeBottomRatio) <= props.ocrExcludeTopRatio) {
      setExcludeRatios({ top: 0.04, bottom: 0.82, left: 0.76, right: 0.02 })
    }
    emit('update:ocrExcludeEnabled', true)
  } else {
    emit('update:ocrExcludeEnabled', false)
  }
}

function startDrag(kind, action, event) {
  const box = kind === 'exclude'
    ? edgesFromRatios(props.ocrExcludeTopRatio, props.ocrExcludeBottomRatio, props.ocrExcludeLeftRatio, props.ocrExcludeRightRatio, true)
    : edgesFromRatios(props.ocrCropTopRatio, props.ocrCropBottomRatio, props.ocrCropLeftRatio, props.ocrCropRightRatio, false)
  const point = previewPointerPoint(event)
  if (!point) return
  dragState.value = { kind, action, startX: point.x, startY: point.y, box }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointerup', endDrag, { once: true })
}

function onPointerMove(event) {
  if (!dragState.value) return
  const point = previewPointerPoint(event)
  if (!point) return
  const state = dragState.value
  const dx = point.x - state.startX
  const dy = point.y - state.startY
  if (state.action === 'resize') {
    applyDragResize(state.kind, state.box, dx, dy)
  } else {
    applyDragMove(state.kind, state.box, dx, dy)
  }
}

function endDrag() {
  dragState.value = null
}

function previewPointerPoint(event) {
  const el = previewEl.value
  if (!el) return null
  const rect = el.getBoundingClientRect()
  if (!rect.width || !rect.height) return null
  return {
    x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
    y: clamp((event.clientY - rect.top) / rect.height, 0, 1),
  }
}

function edgesFromRatios(top, bottom, left, right, exclude) {
  const maxEdge = exclude ? 0.98 : 0.95
  const maxHorizontal = exclude ? 0.98 : 0.45
  const safeTop = clamp(top, 0, maxEdge)
  const safeBottom = clamp(1 - Number(bottom || 0), 0.02, 1)
  const safeLeft = clamp(left, 0, maxHorizontal)
  const safeRight = clamp(1 - Number(right || 0), 0.02, 1)
  return { left: safeLeft, top: safeTop, right: Math.max(safeLeft + 0.01, safeRight), bottom: Math.max(safeTop + 0.01, safeBottom) }
}

function applyDragMove(kind, box, dx, dy) {
  const width = box.right - box.left
  const height = box.bottom - box.top
  const nextLeft = clamp(box.left + dx, 0, 1 - width)
  const nextTop = clamp(box.top + dy, 0, 1 - height)
  applyBox(kind, { left: nextLeft, top: nextTop, right: nextLeft + width, bottom: nextTop + height })
}

function applyDragResize(kind, box, dx, dy) {
  const minWidth = kind === 'exclude' ? 0.04 : 0.08
  const minHeight = kind === 'exclude' ? 0.04 : 0.06
  const nextRight = clamp(box.right + dx, box.left + minWidth, 1)
  const nextBottom = clamp(box.bottom + dy, box.top + minHeight, 1)
  applyBox(kind, { ...box, right: nextRight, bottom: nextBottom })
}

function applyBox(kind, box) {
  const ratios = { left: box.left, top: box.top, right: 1 - box.right, bottom: 1 - box.bottom }
  if (kind === 'exclude') {
    setExcludeRatios(ratios)
  } else {
    setRatios(ratios)
  }
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

function candidatePolygon(candidate) {
  if (Array.isArray(candidate?.polygon) && candidate.polygon.length >= 3) return candidate.polygon
  const bbox = Array.isArray(candidate?.bbox) ? candidate.bbox : [0, 0, 0, 0]
  return [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]]
}

function candidatePoints(candidate) {
  return candidatePolygon(candidate).map(point => `${Number(point[0] || 0)},${Number(point[1] || 0)}`).join(' ')
}

function candidateLabelX(candidate) {
  return Math.max(4, Math.min(...candidatePolygon(candidate).map(point => Number(point[0] || 0))))
}

function candidateLabelY(candidate) {
  const top = Math.min(...candidatePolygon(candidate).map(point => Number(point[1] || 0)))
  return Math.max(candidateFontSize.value, top - candidateFontSize.value * 0.22)
}

function candidateLabel(candidate, status) {
  const rawAngle = candidate?.angle_degrees
  const angle = rawAngle === null || rawAngle === undefined ? Number.NaN : Number(rawAngle)
  const angleLabel = Number.isFinite(angle) ? ` ${angle.toFixed(1)}°` : ''
  const text = String(candidate?.text || '').trim()
  return `${status}${angleLabel}${text ? ` · ${text}` : ''}`
}

function isSoftGeometryCandidate(candidate) {
  return String(candidate?.shape_hint || '').trim() === 'tilted_soft_candidate'
}

function acceptedCandidateStatus(candidate) {
  return isSoftGeometryCandidate(candidate) ? '待几何精修' : '普通候选'
}

function acceptedCandidateBoxClass(candidate) {
  return isSoftGeometryCandidate(candidate) ? 'ocr-candidate-box caution' : 'ocr-candidate-box accepted'
}

function acceptedCandidateLabelClass(candidate) {
  return isSoftGeometryCandidate(candidate) ? 'ocr-candidate-label caution' : 'ocr-candidate-label accepted'
}

function resetPreview() {
  preview.image_data_url = ''
  preview.time_seconds = 0
  preview.duration_seconds = 0
  preview.width = 0
  preview.height = 0
  preview.ocr_analyzed = false
  preview.ocr_stale = false
  preview.accepted = []
  preview.rejected = []
  error.value = ''
  cropStatus.value = props.inputVideo
    ? '视频已就绪，正在自动抽取预览帧…'
    : '调整后会自动保存到当前 OCR 参数。'
}

async function loadPreview() {
  if (!props.inputVideo) {
    error.value = '先下载或选择一个本地视频。'
    return
  }
  loading.value = true
  error.value = ''
  cropStatus.value = props.ocrExtractionMode === 'region_v3'
    ? '正在抽帧并分析 OCR 候选…'
    : '正在抽取预览帧…'
  try {
    const requestKey = previewRequestKey.value
    const requestedTime = props.ocrExtractionMode === 'region_v3' && preview.ocr_stale
      ? Number(preview.time_seconds || 0)
      : nextPreviewTime()
    const payload = {
      input_video: props.inputVideo,
      ocr_scope: props.ocrScope,
      ocr_extraction_mode: props.ocrExtractionMode,
      ocr_shape_mode: props.ocrShapeMode,
      source_language: props.sourceLanguage,
      ocr_language: props.ocrLanguage,
      ocr_min_confidence: props.ocrMinConfidence,
      analyze_ocr: props.ocrExtractionMode === 'region_v3',
      ocr_crop_top_ratio: props.ocrCropTopRatio,
      ocr_crop_bottom_ratio: props.ocrCropBottomRatio,
      ocr_crop_left_ratio: props.ocrCropLeftRatio,
      ocr_crop_right_ratio: props.ocrCropRightRatio,
      ocr_exclude_enabled: props.ocrExcludeEnabled,
      ocr_exclude_top_ratio: props.ocrExcludeTopRatio,
      ocr_exclude_bottom_ratio: props.ocrExcludeBottomRatio,
      ocr_exclude_left_ratio: props.ocrExcludeLeftRatio,
      ocr_exclude_right_ratio: props.ocrExcludeRightRatio,
    }
    if (requestedTime !== undefined) payload.time_seconds = requestedTime
    const result = await api('/api/ocr-preview-frame', payload)
    if (requestKey !== previewRequestKey.value) return
    preview.image_data_url = result.image_data_url || ''
    preview.time_seconds = result.time_seconds || 0
    preview.duration_seconds = result.duration_seconds || preview.duration_seconds || 0
    preview.width = result.width || 0
    preview.height = result.height || 0
    const analysis = result.ocr_analysis
    preview.ocr_analyzed = Boolean(analysis)
    preview.ocr_stale = false
    preview.accepted = Array.isArray(analysis?.accepted) ? analysis.accepted : []
    preview.rejected = Array.isArray(analysis?.rejected) ? analysis.rejected : []
    cropStatus.value = '预览已就绪，拖动绿色框即可调整；修改会自动保存。'
  } catch (err) {
    error.value = err.message || String(err)
    cropStatus.value = '视频已就绪，但抽帧失败；可以点击按钮重试。'
  } finally {
    loading.value = false
  }
}
</script>
