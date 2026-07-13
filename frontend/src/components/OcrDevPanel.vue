<template>
  <section class="panel ocr-dev-panel">
    <div class="panel-heading">
      <div>
        <h2>OCR 开发测试</h2>
        <p class="panel-subtitle">只运行区域 OCR：不翻译、不调用 LLM、不做自动 Logo/边缘噪声过滤。用于检查模型原始识别效果。</p>
      </div>
    </div>

    <div class="ocr-dev-path-row">
      <input :value="inputVideo" placeholder="选择或填写本地视频路径" @input="$emit('update:inputVideo', $event.target.value)" />
      <button class="secondary mini" type="button" @click="$emit('open-assets')">从素材库选</button>
    </div>

    <div class="ocr-dev-settings">
      <label>
        <span>原始字幕语言</span>
        <select :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)">
          <option value="korean">韩语</option>
          <option value="japanese">日语</option>
          <option value="chinese">中文</option>
          <option value="english">英语</option>
        </select>
      </label>
      <label>
        <span>采样帧率（FPS）</span>
        <input type="number" min="0.2" max="30" step="0.5" :value="sampleFps" @input="$emit('update:sampleFps', toNumber($event.target.value, 6))" />
      </label>
      <label>
        <span>最低置信度（%）</span>
        <input type="number" min="0" max="100" step="1" :value="minConfidence" @input="$emit('update:minConfidence', toNumber($event.target.value, 30))" />
      </label>
      <label>
        <span>短闪段平滑</span>
        <select :value="flickerSmoothingMaxDurationSeconds" @change="$emit('update:flickerSmoothingMaxDurationSeconds', toNumber($event.target.value, 0.55))">
          <option :value="0">关闭</option>
          <option :value="0.35">≤ 0.35 秒</option>
          <option :value="0.55">≤ 0.55 秒</option>
          <option :value="0.8">≤ 0.8 秒</option>
        </select>
      </label>
      <div class="ocr-dev-timing">
        <div>
          <b>精确时间轴</b>
          <span>仅在字幕出现或消失的边界逐帧复扫</span>
        </div>
        <button class="secondary mini" type="button" :aria-pressed="refineTimingBoundaries" @click="$emit('update:refineTimingBoundaries', !refineTimingBoundaries)">
          {{ refineTimingBoundaries ? '已开启' : '已关闭' }}
        </button>
      </div>
      <div class="ocr-dev-timing">
        <div>
          <b>LLM 去噪</b>
          <span>识别水印、角标与无关文字；保留原始 `source.srt`，另生成 cleaned 版本</span>
        </div>
        <button class="secondary mini" type="button" :aria-pressed="llmCleanup" @click="$emit('update:llmCleanup', !llmCleanup)">
          {{ llmCleanup ? '已开启' : '已关闭' }}
        </button>
      </div>
    </div>

    <div class="ocr-dev-debug-assets">
      <div class="section-title">
        <h3>调试素材库</h3>
        <span class="badge">{{ debugFolders.length }}</span>
        <button class="secondary mini" type="button" @click="$emit('refresh-debug-assets')">刷新</button>
      </div>
      <p class="panel-subtitle">选择 `debug` 下的文件夹，再将其中原始或已清洗字幕填入下方去噪工具。</p>
      <div v-if="!debugFolders.length" class="asset-list empty">暂无调试文件夹。</div>
      <div v-else class="ocr-dev-debug-list">
        <details v-for="folder in debugFolders" :key="folder.path" class="ocr-dev-debug-folder">
          <summary>
            <div>
              <b>{{ folder.name }}</b>
              <div class="muted path">{{ folder.path }}</div>
            </div>
            <span class="muted">{{ folder.modified_label }}</span>
          </summary>
          <div class="ocr-dev-debug-actions">
            <button class="secondary mini" type="button" :disabled="!folder.source_srt" @click="$emit('update:sourceSrt', folder.source_srt)">选择原始字幕</button>
            <button class="warning mini" type="button" :disabled="running || !folder.source_srt" @click="$emit('rebuild-track-refine', folder.path)">从 JSON 重建 + LLM 精修</button>
            <span v-if="folder.cleaned_srt" class="muted">已存在清洗版</span>
          </div>
        </details>
      </div>
    </div>

    <OcrCropControls
      title="区域 OCR 与 Logo 排除"
      :input-video="inputVideo"
      :ocr-scope="ocrScope"
      :ocr-crop-top-ratio="ocrCropTopRatio"
      :ocr-crop-bottom-ratio="ocrCropBottomRatio"
      :ocr-crop-left-ratio="ocrCropLeftRatio"
      :ocr-crop-right-ratio="ocrCropRightRatio"
      :ocr-exclude-enabled="ocrExcludeEnabled"
      :ocr-exclude-top-ratio="ocrExcludeTopRatio"
      :ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
      :ocr-exclude-left-ratio="ocrExcludeLeftRatio"
      :ocr-exclude-right-ratio="ocrExcludeRightRatio"
      @update:ocr-crop-top-ratio="$emit('update:ocrCropTopRatio', $event)"
      @update:ocr-crop-bottom-ratio="$emit('update:ocrCropBottomRatio', $event)"
      @update:ocr-crop-left-ratio="$emit('update:ocrCropLeftRatio', $event)"
      @update:ocr-crop-right-ratio="$emit('update:ocrCropRightRatio', $event)"
      @update:ocr-exclude-enabled="$emit('update:ocrExcludeEnabled', $event)"
      @update:ocr-exclude-top-ratio="$emit('update:ocrExcludeTopRatio', $event)"
      @update:ocr-exclude-bottom-ratio="$emit('update:ocrExcludeBottomRatio', $event)"
      @update:ocr-exclude-left-ratio="$emit('update:ocrExcludeLeftRatio', $event)"
      @update:ocr-exclude-right-ratio="$emit('update:ocrExcludeRightRatio', $event)"
    />

    <div class="ocr-dev-actions">
      <button :disabled="running || !inputVideo" @click="$emit('run')">{{ running ? 'OCR 测试运行中…' : '运行 OCR 开发测试' }}</button>
      <p>输出：`source.srt`、`source.cleaned.srt`、`ocr_boxes.json`、`ocr_sample_frames.json`（每个采样帧均保留，即使无识别结果）。</p>
    </div>
    <div class="ocr-dev-existing-cleanup">
      <div>
        <b>已有字幕直接去噪</b>
        <span>不重新 OCR；清洗结果写到同目录的 `*.cleaned.srt`。</span>
      </div>
      <input :value="sourceSrt" placeholder="填写已有 source.srt 路径" @input="$emit('update:sourceSrt', $event.target.value)" />
      <button class="secondary" :disabled="running || !sourceSrt" type="button" @click="$emit('run-cleanup')">直接 LLM 去噪</button>
    </div>
    <div v-if="status" class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
import OcrCropControls from './OcrCropControls.vue'

defineProps({
  inputVideo: { type: String, default: '' },
  sourceLanguage: { type: String, default: 'korean' },
  sampleFps: { type: Number, default: 6 },
  minConfidence: { type: Number, default: 30 },
  refineTimingBoundaries: { type: Boolean, default: true },
  flickerSmoothingMaxDurationSeconds: { type: Number, default: 0.55 },
  llmCleanup: { type: Boolean, default: true },
  sourceSrt: { type: String, default: '' },
  debugFolders: { type: Array, default: () => [] },
  ocrScope: { type: String, default: 'bottom' },
  ocrCropTopRatio: { type: Number, default: 0.58 },
  ocrCropBottomRatio: { type: Number, default: 0 },
  ocrCropLeftRatio: { type: Number, default: 0 },
  ocrCropRightRatio: { type: Number, default: 0 },
  ocrExcludeEnabled: { type: Boolean, default: false },
  ocrExcludeTopRatio: { type: Number, default: 0.04 },
  ocrExcludeBottomRatio: { type: Number, default: 0.82 },
  ocrExcludeLeftRatio: { type: Number, default: 0.76 },
  ocrExcludeRightRatio: { type: Number, default: 0.02 },
  running: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

defineEmits([
  'update:inputVideo',
  'update:sourceLanguage',
  'update:sampleFps',
  'update:minConfidence',
  'update:refineTimingBoundaries',
  'update:flickerSmoothingMaxDurationSeconds',
  'update:llmCleanup',
  'update:sourceSrt',
  'update:ocrCropTopRatio',
  'update:ocrCropBottomRatio',
  'update:ocrCropLeftRatio',
  'update:ocrCropRightRatio',
  'update:ocrExcludeEnabled',
  'update:ocrExcludeTopRatio',
  'update:ocrExcludeBottomRatio',
  'update:ocrExcludeLeftRatio',
  'update:ocrExcludeRightRatio',
  'open-assets',
  'run',
  'run-cleanup',
  'rebuild-track-refine',
  'refresh-debug-assets',
])

function toNumber(value, fallback) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
</script>
