<template>
  <section class="panel ocr-dev-panel">
    <div class="panel-heading">
      <div>
        <h2>OCR 开发测试</h2>
        <p class="panel-subtitle">只运行 OCR 提取：2.0 保留原区域逻辑；3.0 保存文字框四边形和文字行角度，横向优先只做软标记，严格近水平才会硬过滤。</p>
      </div>
    </div>

    <div class="ocr-dev-path-row">
      <input :value="inputVideo" placeholder="选择或填写本地视频路径" @input="$emit('update:inputVideo', $event.target.value)" />
      <button class="secondary mini" type="button" @click="$emit('open-assets')">从素材库选</button>
    </div>

    <div class="ocr-dev-settings">
      <label>
        <span>OCR 提取方式</span>
        <select :value="ocrExtractionMode" @change="$emit('update:ocrExtractionMode', $event.target.value)">
          <option value="region">OCR 2.0（区域增强）</option>
          <option value="region_v3">OCR 3.0（稳定版）</option>
        </select>
      </label>
      <label v-if="ocrExtractionMode === 'region_v3'">
        <span>文字形态策略</span>
        <select :value="ocrShapeMode" @change="$emit('update:ocrShapeMode', $event.target.value)">
          <option value="unrestricted">不限形态（不按角度预判）</option>
          <option value="horizontal_preferred">横向优先（推荐，软标记）</option>
          <option value="horizontal_strict">严格近水平（硬过滤）</option>
        </select>
        <small class="muted">横向优先会保留倾斜文字行并交给几何 LLM；严格近水平会在生成轨迹前直接排除超出角度限制的候选。</small>
      </label>
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
          <b>{{ ocrExtractionMode === 'region_v3' ? '3.0 完整成品精修' : '2.0 专属轨迹 LLM 精修' }}</b>
          <span v-if="ocrExtractionMode === 'region_v3'">几何判断只作软提示，随后执行文字纠错、变体合并和画面字/对白分层；诊断版与成品版分别保存</span>
          <span v-else>结合逐帧文字框和轨迹精修；保留 `source.machine.srt`，另生成 `source.refined.srt`</span>
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
      <p class="panel-subtitle">2.0 与 3.0 使用独立调试目录和精修按钮；运行 3.0 不会覆盖已有 2.0 素材。</p>
      <div v-if="!debugFolders.length" class="asset-list empty">暂无调试文件夹。</div>
      <div v-else class="ocr-dev-debug-list">
        <details v-for="folder in debugFolders" :key="folder.path" class="ocr-dev-debug-folder">
          <summary>
            <div>
              <b>{{ folder.name }}</b>
              <div class="muted path">{{ folder.path }}</div>
            </div>
            <span><b class="badge">{{ folder.ocr_version_label || 'OCR 2.0' }}</b> <span class="muted">{{ folder.modified_label }}</span></span>
          </summary>
          <div class="ocr-dev-debug-actions">
            <button class="secondary mini" type="button" :disabled="!folder.source_srt" @click="$emit('update:sourceSrt', folder.source_srt)">选择原始字幕</button>
            <button v-if="folder.ocr_lab_version !== 'v3'" class="warning mini" type="button" :disabled="running || !folder.has_ocr_boxes || !folder.has_tracks" @click="$emit('rebuild-track-refine', folder.path)">2.0 从 JSON 重建 + 轨迹精修</button>
            <button v-if="folder.ocr_lab_version === 'v3'" class="warning mini" type="button" :disabled="running || !folder.has_ocr_boxes || !folder.has_tracks" title="复用已有 tracks.json 和 ocr_boxes.json，不重新运行 OCR" @click="$emit('geometry-refine', folder.path)">3.0 几何精修（不重跑 OCR）</button>
            <button v-if="folder.ocr_lab_version === 'v3'" class="warning mini" type="button" :disabled="running || !folder.has_machine_source || !folder.has_ocr_boxes || !folder.has_tracks" title="复用当前目录已有的机器字幕、OCR、轨迹和几何结果，只运行 3.0 成品精修" @click="$emit('v3-refine', folder.path)">3.0 文字 + 分层精修（不重跑 OCR）</button>
            <button v-if="folder.ocr_lab_version === 'v3'" class="secondary mini" type="button" :disabled="running || !folder.v3_refined_srt || !folder.has_machine_source || !folder.has_ocr_boxes" title="复用 source.v3.refined.srt、机器字幕、OCR boxes 和已有几何提示；跳过 OCR 与文字精修" @click="$emit('layered-refine', folder.path)">3.0 仅重跑分层（最快）</button>
            <button v-if="folder.ocr_lab_version !== 'v3'" class="secondary mini" type="button" :disabled="running || !folder.source_srt || !folder.has_ocr_boxes" title="2.0 专用：需要原始字幕和 ocr_boxes.json" @click="$emit('layered-refine', folder.path)">2.0 分层精修（画面字 + 对白）</button>
            <span v-if="folder.cleaned_srt" class="muted">已存在清洗版</span>
            <span v-if="folder.track_refined_srt" class="muted">已有 2.0 轨迹精修版</span>
            <span v-if="folder.geometry_srt" class="muted">已有几何精修版</span>
            <span v-if="folder.layered_srt" class="muted">已有分层版</span>
            <span v-if="folder.v3_refined_srt" class="muted">已有 3.0 文字精修版</span>
            <span v-if="folder.v3_layered_srt" class="muted">已有 3.0 分层精修版</span>
          </div>
        </details>
      </div>
    </div>

    <OcrCropControls
      title="区域 OCR 与 Logo 排除"
      :input-video="inputVideo"
      :ocr-scope="ocrScope"
      :ocr-extraction-mode="ocrExtractionMode"
      :ocr-shape-mode="ocrShapeMode"
      :source-language="sourceLanguage"
      :ocr-language="sourceLanguage"
      :ocr-min-confidence="minConfidence / 100"
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
      <p v-if="ocrExtractionMode === 'region_v3'">输出：`source.srt`、`ocr_boxes.json`、`ocr_sample_frames.json`、`ocr_rejected_boxes.json`；`source.geometry_refined.srt` 和 `ocr_geometry.json` 仅供几何诊断，成品精修另生成 `source.v3.refined.srt`、`source.v3.layered.srt` 和 `ocr_v3_layers.json`。</p>
      <p v-else>输出：`source.srt`、`source.machine.srt`、`source.refined.srt`、`ocr_boxes.json`、`ocr_sample_frames.json`。</p>
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
  ocrExtractionMode: { type: String, default: 'region' },
  ocrShapeMode: { type: String, default: 'horizontal_preferred' },
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
  'update:ocrExtractionMode',
  'update:ocrShapeMode',
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
  'geometry-refine',
  'v3-refine',
  'layered-refine',
  'refresh-debug-assets',
])

function toNumber(value, fallback) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
</script>
