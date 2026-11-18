<template>
  <section class="panel video-overlay-panel video-studio">
    <header class="studio-page-head"><div><span class="studio-kicker">视频处理</span><h2>调整画面，保留原片</h2><p>镜像、裁剪、改尺寸或加贴图，输出为新视频。</p></div><button class="secondary" type="button" @click="$emit('open-assets')"><AppIcon name="folder" :size="16" />选择素材</button></header>
    <details class="studio-disclosure video-source-details" :open="sourceOpen" @toggle="sourceOpen = $event.target.open"><summary>{{ inputVideo ? fileLabel(inputVideo) : '选择或填写视频路径' }}</summary><label for="overlayInputVideo">视频文件<input id="overlayInputVideo" :value="inputVideo" placeholder="填写本地视频路径" @input="$emit('update:inputVideo', $event.target.value)" /></label></details>
    <div class="video-workbench">
      <div class="video-preview-column">
        <div class="studio-section-head"><div><h3>画面预览</h3><p>抽取一帧查看效果；贴图可直接拖动。</p></div><button class="secondary mini" type="button" :disabled="loading || !inputVideo" @click="loadPreview()">{{ loading ? '抽帧中…' : preview.image_data_url ? '换一帧' : '加载预览' }}</button></div>
      <div class="overlay-preview-box">
        <div v-if="!inputVideo" class="overlay-empty">先从素材列表选择一个视频。</div>
        <div v-else-if="!preview.image_data_url" class="overlay-empty">抽一帧后可以预览镜像、裁剪和贴图位置。</div>
        <div v-else class="video-overlay-preview" @pointermove="onDragMove" @pointerup="endDrag" @pointercancel="endDrag" @pointerleave="endDrag">
          <img
            :src="preview.image_data_url"
            :class="{ mirrored: transformSettings.horizontal_flip }"
            alt="video preview"
            draggable="false"
          />
          <div
            ref="cropFrameRef"
            class="video-transform-crop-frame"
            :class="{ cropped: cropActive }"
            :style="cropFrameStyle"
          >
            <div
              v-for="layer in visibleLayers"
              :key="layer.kind"
              class="overlay-preview-layer"
              :class="{ active: activeLayerKind === layer.kind }"
              :style="layerPreviewStyle(layer)"
              @pointerdown.stop.prevent="startDrag(layer, $event)"
              @click.stop="activeLayerKind = layer.kind"
            >
              <img :src="layer.image_data_url" :alt="layer.label" draggable="false" />
              <span>{{ layer.label }}</span>
            </div>
          </div>
        </div>
        <div class="crop-preview-meta">
          <span v-if="preview.image_data_url">预览帧 {{ formatTime(preview.time_seconds) }}</span>
          <span v-if="preview.width && preview.height">{{ preview.width }} × {{ preview.height }}</span>
        </div>
      </div>

        <div v-if="preview.width && preview.height && !transformInspection.error" class="video-transform-summary"><span>保留 {{ transformInspection.cropped_width }} × {{ transformInspection.cropped_height }}</span><span>输出 {{ transformInspection.output_width }} × {{ transformInspection.output_height }}</span></div>
        <details class="studio-disclosure overlay-frame-time"><summary>按时间定位预览帧</summary><div class="overlay-time-row"><label for="overlayPreviewTime">预览秒数<input id="overlayPreviewTime" type="number" min="0" step="0.1" v-model="previewTimeInput" @keydown.enter.prevent="loadPreviewAtInput" /></label><button class="secondary mini" type="button" :disabled="loading || !inputVideo" @click="loadPreviewAtInput">跳到此秒</button></div></details>
      </div>
      <div class="video-controls-column">
        <div class="overlay-transform-card">
          <div class="overlay-layer-head">
            <div>
              <b>画面变换</b>
              <small>按照 镜像 → 裁剪 → 尺寸 → 贴图 的顺序处理</small>
            </div>
            <button class="ghost mini" type="button" @click="resetTransform">重置画面</button>
          </div>

          <label class="check-row">
            <input type="checkbox" v-model="transformSettings.horizontal_flip" />
            <span>水平镜像翻转</span>
          </label>
          <p class="muted compact-note">只翻转原视频，水印和遮挡图片保持正向。</p>

          <label class="check-row">
            <input type="checkbox" v-model="transformSettings.crop_enabled" />
            <span>裁掉画面边缘</span>
          </label>
          <div v-if="transformSettings.crop_enabled" class="video-crop-input-grid">
            <label v-for="side in cropSides" :key="side.key">
              <span>裁掉{{ side.label }}（%）</span>
              <input
                type="number"
                min="0"
                max="95"
                step="0.1"
                v-model.number="transformSettings[side.key]"
              />
              <small>{{ cropPixelLabel(side.side) }}</small>
            </label>
          </div>

          <label class="check-row">
            <input type="checkbox" v-model="transformSettings.resize_enabled" />
            <span>设置最终输出尺寸</span>
          </label>
          <div v-if="transformSettings.resize_enabled" class="video-output-size-row">
            <label>
              <span>宽度（px）</span>
              <input type="number" min="2" max="8192" step="2" placeholder="自动" v-model="transformSettings.output_width" />
            </label>
            <span>×</span>
            <label>
              <span>高度（px）</span>
              <input type="number" min="2" max="8192" step="2" placeholder="自动" v-model="transformSettings.output_height" />
            </label>
          </div>
          <p v-if="transformSettings.resize_enabled" class="muted compact-note">只填一边会等比例计算；两边都填时需与裁剪后的宽高比一致。奇数会向下取偶数。</p>

          <div v-if="transformInspection.error" class="status bad compact-status">{{ transformInspection.error }}</div>

        </div>


        <details class="studio-disclosure overlay-stickers"><summary>水印与 Logo 遮挡<span>{{ visibleLayers.length ? `${visibleLayers.length} 层已启用` : '可选' }}</span></summary>
        <div v-for="layer in layerList" :key="layer.kind" class="overlay-layer-card" :class="{ active: activeLayerKind === layer.kind }">
          <div class="overlay-layer-head">
            <label class="check-row">
              <input type="checkbox" v-model="layer.enabled" @change="activeLayerKind = layer.kind" />
              <span>{{ layer.label }}</span>
            </label>
            <button class="ghost mini" type="button" :disabled="!layer.enabled" @click="activeLayerKind = layer.kind">选中贴图</button>
          </div>

          <label v-if="layer.enabled" class="file-picker">
            <span>{{ layer.fileName || '选择贴图图片' }}</span>
            <input type="file" accept="image/*" @change="onLayerFile(layer, $event)" />
          </label>

          <details v-if="layer.enabled" class="studio-disclosure overlay-layer-options"><summary>大小、透明度与扣背景</summary><label class="check-row subtle">
            <input type="checkbox" v-model="layer.remove_background" />
            <span>扣背景</span>
          </label>

          <div class="range-grid">
            <label>
              <span>大小 {{ percent(layer.width) }}%</span>
              <input type="range" min="2" max="90" step="1" :value="percent(layer.width)" @input="layer.width = numberRatio($event.target.value)" />
            </label>
            <label>
              <span>透明度 {{ percent(layer.opacity) }}%</span>
              <input type="range" min="0" max="100" step="1" :value="percent(layer.opacity)" @input="layer.opacity = numberRatio($event.target.value)" />
            </label>
          </div>
          </details>
        </div>


          <button class="secondary mini" type="button" @click="resetLayers">重置贴图位置</button>
        </details>
      </div>
    </div>
    <p v-if="error" class="operation-status bad" role="alert">{{ error }}</p>
    <details class="studio-disclosure video-processing-notes"><summary>处理顺序与注意事项</summary><p>按“镜像 → 裁剪 → 尺寸 → 贴图”处理。左右裁剪以镜像后的画面为准；贴图不跟随镜像翻转。扣背景适合纯色底图片。</p></details>
    <footer class="studio-save-bar operation-run-bar"><span>原视频不会被覆盖。</span><button type="button" :disabled="!canRun" @click="runProcessing">{{ loading ? '正在加载预览…' : '生成处理后视频' }}</button></footer>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'
import AppIcon from './AppIcon.vue'
import { fileLabel } from '../studioTools.js'
import {
  buildVideoTransformPayload,
  createDefaultVideoTransform,
  hasVideoTransform,
  inspectVideoTransform,
  videoCropFrameStyle,
} from '../videoTransformTools.js'

const props = defineProps({
  inputVideo: { type: String, default: '' },
})
const emit = defineEmits(['run', 'update:inputVideo', 'open-assets'])
const sourceOpen = ref(!props.inputVideo)

const preview = reactive({ image_data_url: '', time_seconds: 0, duration_seconds: 0, width: 0, height: 0 })
const cropFrameRef = ref(null)
const previewTimeInput = ref('')
const loading = ref(false)
const error = ref('')
const activeLayerKind = ref('watermark')
const dragState = ref(null)
let previewRequestSequence = 0
const transformSettings = reactive(createDefaultVideoTransform())
const cropSides = [
  { key: 'crop_top_percent', side: 'top', label: '上边' },
  { key: 'crop_right_percent', side: 'right', label: '右边' },
  { key: 'crop_bottom_percent', side: 'bottom', label: '下边' },
  { key: 'crop_left_percent', side: 'left', label: '左边' },
]

const layers = reactive({
  watermark: makeLayer('watermark', '水印', 0.70, 0.08, 0.18, 0.90),
  logo_cover: makeLayer('logo_cover', '遮 Logo', 0.80, 0.80, 0.14, 1.00),
})

const layerList = computed(() => [layers.watermark, layers.logo_cover])
const visibleLayers = computed(() => layerList.value.filter((layer) => layer.enabled && layer.image_data_url))
const transformInspection = computed(() => inspectVideoTransform(transformSettings, preview.width, preview.height))
const cropFrameStyle = computed(() => videoCropFrameStyle(transformSettings))
const cropActive = computed(() => Boolean(
  transformSettings.crop_enabled
  && (
    Number(transformSettings.crop_top_percent)
    || Number(transformSettings.crop_right_percent)
    || Number(transformSettings.crop_bottom_percent)
    || Number(transformSettings.crop_left_percent)
  )
))
const canRun = computed(() => Boolean(
  String(props.inputVideo || '').trim()
  && !loading.value
  && !transformInspection.value.error
  && (visibleLayers.value.length > 0 || hasVideoTransform(transformSettings))
))

watch(() => props.inputVideo, () => {
  previewRequestSequence += 1
  preview.image_data_url = ''
  preview.time_seconds = 0
  preview.duration_seconds = 0
  preview.width = 0
  preview.height = 0
  previewTimeInput.value = ''
  error.value = ''
  loading.value = false
  dragState.value = null
  resetTransform()
})

function makeLayer(kind, label, x, y, width, opacity) {
  return {
    kind,
    label,
    enabled: false,
    fileName: '',
    image_data_url: '',
    remove_background: false,
    x,
    y,
    width,
    opacity,
  }
}

function resetLayers() {
  Object.assign(layers.watermark, makeLayer('watermark', '水印', 0.70, 0.08, 0.18, 0.90), {
    enabled: layers.watermark.enabled,
    fileName: layers.watermark.fileName,
    image_data_url: layers.watermark.image_data_url,
    remove_background: layers.watermark.remove_background,
  })
  Object.assign(layers.logo_cover, makeLayer('logo_cover', '遮 Logo', 0.80, 0.80, 0.14, 1.00), {
    enabled: layers.logo_cover.enabled,
    fileName: layers.logo_cover.fileName,
    image_data_url: layers.logo_cover.image_data_url,
    remove_background: layers.logo_cover.remove_background,
  })
}

function resetTransform() {
  Object.assign(transformSettings, createDefaultVideoTransform())
}

function cropPixelLabel(side) {
  if (!preview.width || !preview.height) return '抽帧后显示像素'
  return `${transformInspection.value.crop_pixels[side]} px`
}

function percent(value) {
  return Math.round(Number(value || 0) * 100)
}

function numberRatio(value) {
  return clamp(Number(value || 0) / 100, 0, 1)
}

function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min))
}

function onLayerFile(layer, event) {
  const file = event.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    layer.image_data_url = String(reader.result || '')
    layer.fileName = file.name
    layer.enabled = true
    activeLayerKind.value = layer.kind
    error.value = ''
  }
  reader.onerror = () => {
    error.value = '图片读取失败。'
  }
  reader.readAsDataURL(file)
  event.target.value = ''
}

function nextPreviewTime() {
  const duration = Number(preview.duration_seconds || 0)
  if (!preview.image_data_url || !duration) return undefined
  if (duration <= 1) return 0
  const step = Math.max(3, duration * 0.17)
  const next = (Number(preview.time_seconds || 0) + step) % duration
  return Number(Math.min(duration - 0.1, Math.max(0, next)).toFixed(3))
}

async function loadPreview(timeSeconds = nextPreviewTime()) {
  const requestVideo = String(props.inputVideo || '').trim()
  if (!requestVideo) {
    error.value = '先选择一个本地视频。'
    return
  }
  const requestId = ++previewRequestSequence
  loading.value = true
  error.value = ''
  try {
    const payload = { input_video: requestVideo }
    if (timeSeconds !== undefined && timeSeconds !== '') payload.time_seconds = Number(timeSeconds)
    const result = await api('/api/ocr-preview-frame', payload)
    if (requestId !== previewRequestSequence || requestVideo !== String(props.inputVideo || '').trim()) return
    preview.image_data_url = result.image_data_url || ''
    preview.time_seconds = result.time_seconds || 0
    preview.duration_seconds = result.duration_seconds || preview.duration_seconds || 0
    preview.width = result.width || 0
    preview.height = result.height || 0
    previewTimeInput.value = String(Number(preview.time_seconds || 0).toFixed(1))
  } catch (err) {
    if (requestId !== previewRequestSequence || requestVideo !== String(props.inputVideo || '').trim()) return
    error.value = err.message || String(err)
  } finally {
    if (requestId === previewRequestSequence) loading.value = false
  }
}

function loadPreviewAtInput() {
  const seconds = Number(previewTimeInput.value || 0)
  loadPreview(Number.isFinite(seconds) ? Math.max(0, seconds) : 0)
}

function layerPreviewStyle(layer) {
  return {
    left: `${(Number(layer.x || 0) * 100).toFixed(2)}%`,
    top: `${(Number(layer.y || 0) * 100).toFixed(2)}%`,
    width: `${(Number(layer.width || 0) * 100).toFixed(2)}%`,
    opacity: layer.opacity,
  }
}

function startDrag(layer, event) {
  activeLayerKind.value = layer.kind
  const rect = cropFrameRef.value?.getBoundingClientRect()
  if (!rect) return
  dragState.value = {
    kind: layer.kind,
    startX: event.clientX,
    startY: event.clientY,
    startLayerX: layer.x,
    startLayerY: layer.y,
    rectWidth: rect.width,
    rectHeight: rect.height,
  }
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function onDragMove(event) {
  const state = dragState.value
  if (!state) return
  const layer = layers[state.kind]
  if (!layer) return
  const dx = (event.clientX - state.startX) / Math.max(1, state.rectWidth)
  const dy = (event.clientY - state.startY) / Math.max(1, state.rectHeight)
  layer.x = Number(clamp(state.startLayerX + dx, 0, 0.98).toFixed(4))
  layer.y = Number(clamp(state.startLayerY + dy, 0, 0.98).toFixed(4))
}

function endDrag() {
  dragState.value = null
}

function runProcessing() {
  const inputVideo = String(props.inputVideo || '').trim()
  if (!inputVideo) {
    error.value = '先选择一个本地视频。'
    return
  }
  const payloadLayers = visibleLayers.value.map((layer) => ({
    enabled: true,
    kind: layer.kind,
    image_data_url: layer.image_data_url,
    remove_background: layer.remove_background,
    x: layer.x,
    y: layer.y,
    width: layer.width,
    opacity: layer.opacity,
  }))
  if (transformInspection.value.error) {
    error.value = transformInspection.value.error
    return
  }
  if (!payloadLayers.length && !hasVideoTransform(transformSettings)) {
    error.value = '至少启用一种画面变换，或添加一层贴图。'
    return
  }
  error.value = ''
  emit('run', {
    input_video: inputVideo,
    layers: payloadLayers,
    transform: buildVideoTransformPayload(transformSettings),
  })
}

function formatTime(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60).toString().padStart(2, '0')
  return `${minutes}:${rest}`
}
</script>
