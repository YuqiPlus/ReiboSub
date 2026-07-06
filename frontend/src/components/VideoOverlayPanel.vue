<template>
  <section class="video-overlay-panel">
    <div class="overlay-head">
      <div>
        <h3>视频贴图处理</h3>
        <p class="panel-subtitle">水印和遮 Logo 可以同时启用，输出新视频，不覆盖原文件。</p>
      </div>
      <button class="secondary mini" type="button" :disabled="loading || !inputVideo" @click="loadPreview()">
        {{ preview.image_data_url ? (loading ? '换帧中' : '换一帧') : (loading ? '抽帧中' : '抽一帧') }}
      </button>
    </div>

    <div class="overlay-layout">
      <div class="overlay-configs">
        <div v-for="layer in layerList" :key="layer.kind" class="overlay-layer-card" :class="{ active: activeLayerKind === layer.kind }">
          <div class="overlay-layer-head">
            <label class="check-row">
              <input type="checkbox" v-model="layer.enabled" @change="activeLayerKind = layer.kind" />
              <span>{{ layer.label }}</span>
            </label>
            <button class="ghost mini" type="button" @click="activeLayerKind = layer.kind">调整</button>
          </div>

          <label class="file-picker">
            <span>{{ layer.fileName || '选择贴图图片' }}</span>
            <input type="file" accept="image/*" @change="onLayerFile(layer, $event)" />
          </label>

          <label class="check-row subtle">
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
        </div>

        <div class="overlay-time-row">
          <label>
            <span>预览秒数</span>
            <input type="number" min="0" step="0.1" v-model="previewTimeInput" @keydown.enter.prevent="loadPreviewAtInput" />
          </label>
          <button class="secondary mini" type="button" :disabled="loading || !inputVideo" @click="loadPreviewAtInput">跳到此秒</button>
        </div>

        <div class="toolbar overlay-actions">
          <button class="warning" type="button" :disabled="!canRun" @click="runOverlay">生成新视频</button>
          <button class="secondary" type="button" @click="resetLayers">重置位置</button>
        </div>
      </div>

      <div class="overlay-preview-box">
        <div v-if="!inputVideo" class="overlay-empty">先从素材列表选择一个视频。</div>
        <div v-else-if="!preview.image_data_url" class="overlay-empty">抽一帧后可以拖动贴图看位置。</div>
        <div v-else ref="previewRef" class="video-overlay-preview" @pointermove="onDragMove" @pointerup="endDrag" @pointercancel="endDrag" @pointerleave="endDrag">
          <img :src="preview.image_data_url" alt="video preview" draggable="false" />
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
        <div class="crop-preview-meta">
          <span v-if="preview.image_data_url">预览帧 {{ formatTime(preview.time_seconds) }}</span>
          <span v-if="preview.width && preview.height">{{ preview.width }} × {{ preview.height }}</span>
        </div>
      </div>
    </div>

    <div v-if="error" class="status bad">{{ error }}</div>
    <div v-else class="muted overlay-note">扣背景使用图片边缘颜色做简易透明处理，适合白底/纯色底水印图。</div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({
  inputVideo: { type: String, default: '' },
})
const emit = defineEmits(['run'])

const preview = reactive({ image_data_url: '', time_seconds: 0, duration_seconds: 0, width: 0, height: 0 })
const previewRef = ref(null)
const previewTimeInput = ref('')
const loading = ref(false)
const error = ref('')
const activeLayerKind = ref('watermark')
const dragState = ref(null)

const layers = reactive({
  watermark: makeLayer('watermark', '水印', 0.70, 0.08, 0.18, 0.90),
  logo_cover: makeLayer('logo_cover', '遮 Logo', 0.80, 0.80, 0.14, 1.00),
})

const layerList = computed(() => [layers.watermark, layers.logo_cover])
const visibleLayers = computed(() => layerList.value.filter((layer) => layer.enabled && layer.image_data_url))
const canRun = computed(() => Boolean(props.inputVideo) && visibleLayers.value.length > 0)

watch(() => props.inputVideo, () => {
  preview.image_data_url = ''
  preview.time_seconds = 0
  preview.duration_seconds = 0
  preview.width = 0
  preview.height = 0
  previewTimeInput.value = ''
  error.value = ''
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
  if (!props.inputVideo) {
    error.value = '先选择一个本地视频。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const payload = { input_video: props.inputVideo }
    if (timeSeconds !== undefined && timeSeconds !== '') payload.time_seconds = Number(timeSeconds)
    const result = await api('/api/ocr-preview-frame', payload)
    preview.image_data_url = result.image_data_url || ''
    preview.time_seconds = result.time_seconds || 0
    preview.duration_seconds = result.duration_seconds || preview.duration_seconds || 0
    preview.width = result.width || 0
    preview.height = result.height || 0
    previewTimeInput.value = String(Number(preview.time_seconds || 0).toFixed(1))
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
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
  const rect = previewRef.value?.getBoundingClientRect()
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

function runOverlay() {
  if (!props.inputVideo) {
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
  if (!payloadLayers.length) {
    error.value = '至少启用一层贴图并选择图片。'
    return
  }
  emit('run', { input_video: props.inputVideo, layers: payloadLayers })
}

function formatTime(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60).toString().padStart(2, '0')
  return `${minutes}:${rest}`
}
</script>
