<template>
  <section class="panel ocr-dev-panel ocr-studio">
    <header class="studio-page-head"><div><span class="studio-kicker">OCR Lab</span><h2>把画面里的字提取出来</h2><p>选择版本、框定字幕区域，再开始测试。2.0 与 3.0 的结果独立保留。</p></div></header>
    <nav class="studio-tabs operation-tabs" aria-label="OCR 测试方式"><button :class="{ active: labTab === 'extract' }" :aria-pressed="labTab === 'extract'" @click="labTab = 'extract'">新建识别测试</button><button :class="{ active: labTab === 'reuse' }" :aria-pressed="labTab === 'reuse'" @click="labTab = 'reuse'">复用已有结果<span>{{ debugFolders.length }}</span></button></nav>
    <div v-show="labTab === 'extract'">
      <div class="lab-version-grid ocr-version-grid" role="group" aria-label="OCR 版本"><button v-for="version in OCR_LAB_VERSIONS" :key="version.id" class="lab-version-card" :class="{ selected: ocrExtractionMode === version.id }" :aria-pressed="ocrExtractionMode === version.id" :disabled="running" @click="$emit('update:ocrExtractionMode', version.id)"><span><b>{{ version.label }}</b><small>{{ version.badge }}</small></span><p>{{ version.description }}</p></button></div>
      <p class="lab-version-detail">{{ currentVersion?.detail }}</p>
      <div class="studio-source-picker"><label for="ocrLabInput">视频文件<input id="ocrLabInput" :value="inputVideo" :disabled="running" placeholder="选择或填写本地视频路径" @input="$emit('update:inputVideo', $event.target.value)" /></label><button class="secondary" :disabled="running" @click="$emit('open-assets')"><AppIcon name="folder" :size="16" />从素材库选择</button></div>
      <div class="lab-basic-row"><label for="ocrLabLanguage">字幕语言<select id="ocrLabLanguage" :value="sourceLanguage" :disabled="running" @change="$emit('update:sourceLanguage', $event.target.value)"><option value="korean">韩语</option><option value="japanese">日语</option><option value="chinese">中文</option><option value="english">英语</option></select></label><p><template v-if="ocrExtractionMode === 'region_v3'">{{ shapeSummary }} · </template>{{ sampleFps }} 帧 / 秒 · {{ refineTimingBoundaries ? '边界复扫开启' : '边界复扫关闭' }} · {{ llmCleanup ? '成品精修开启' : '仅机器识别' }}</p></div>
    <OcrCropControls compact
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


      <details class="studio-disclosure lab-advanced"><summary>采样、时间轴与精修参数</summary><fieldset :disabled="running" class="lab-advanced-grid">
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

      </fieldset></details>
      <details class="studio-disclosure lab-artifact-notes"><summary>产物与保存说明</summary>
      <p v-if="ocrExtractionMode === 'region_v3'">输出：`source.srt`、`ocr_boxes.json`、`ocr_sample_frames.json`、`ocr_rejected_boxes.json`；`source.geometry_refined.srt` 和 `ocr_geometry.json` 仅供几何诊断，成品精修另生成 `source.v3.refined.srt`、`source.v3.layered.srt` 和 `ocr_v3_layers.json`。</p>
      <p v-else>输出：`source.srt`、`source.machine.srt`、`source.refined.srt`、`ocr_boxes.json`、`ocr_sample_frames.json`。</p>

      </details>
      <footer class="studio-save-bar operation-run-bar"><span>{{ llmCleanup ? '开启精修会调用模型服务；机器识别结果仍会保留。' : '只运行本机 OCR，保留原始识别结果。' }}</span><button :disabled="running || !inputVideo.trim()" @click="$emit('run')">{{ running ? 'OCR 测试运行中…' : `运行 ${currentVersion?.label || 'OCR'} 测试` }}</button></footer>
    </div>
    <div v-show="labTab === 'reuse'" class="lab-reuse-results">
      <div class="studio-filter-bar"><div class="studio-tabs" aria-label="调试结果版本"><button v-for="option in folderFilters" :key="option.id" :class="{ active: folderVersion === option.id }" :aria-pressed="folderVersion === option.id" @click="folderVersion = option.id">{{ option.label }}</button></div><label class="studio-search"><AppIcon name="search" :size="17" /><input v-model="folderQuery" type="search" aria-label="搜索 OCR 调试结果" placeholder="搜索素材或目录" /></label><button class="secondary mini" @click="$emit('refresh-debug-assets')">刷新结果</button></div>
      <p class="operation-notice">按目录所属版本使用对应精修工具。复用轨迹和原始框时，不必重新运行 OCR。</p>
      <div v-if="!filteredFolders.length" class="asset-list empty">暂无调试文件夹。</div>
      <div v-else class="ocr-dev-debug-list">
        <details v-for="folder in filteredFolders" :key="folder.path" class="ocr-dev-debug-folder">
          <summary>
            <div>
              <b>{{ folder.name }}</b>

            </div>
            <span><b class="badge">{{ folder.ocr_version_label || 'OCR 2.0' }}</b> <span class="muted">{{ localModifiedLabel(folder) }}</span></span>
          </summary>
          <div class="ocr-dev-debug-actions"><p class="path">{{ folder.path }}</p>
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

      <details class="studio-disclosure lab-legacy-cleanup"><summary>兼容工具：仅清理已有字幕</summary>
    <div class="ocr-dev-existing-cleanup">
      <div>
        <b>已有字幕直接去噪</b>
        <span>不重新 OCR；清洗结果写到同目录的 `*.cleaned.srt`。</span>
      </div>
      <input :value="sourceSrt" placeholder="填写已有 source.srt 路径" @input="$emit('update:sourceSrt', $event.target.value)" />
      <button class="secondary" :disabled="running || !sourceSrt" type="button" @click="$emit('run-cleanup')">直接 LLM 去噪</button>
    </div>

      </details>
    </div>
    <p v-if="status" class="operation-status" :class="statusClass" role="status">{{ status }}</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import OcrCropControls from './OcrCropControls.vue'
import AppIcon from './AppIcon.vue'
import { OCR_LAB_VERSIONS } from '../labVersions.js'
import { localModifiedLabel } from '../studioTools.js'

const props = defineProps({
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

const labTab = ref('extract'), folderVersion = ref('all'), folderQuery = ref('')
const currentVersion = computed(() => OCR_LAB_VERSIONS.find(version => version.id === props.ocrExtractionMode))
const shapeSummary = computed(() => ({ unrestricted: '不限形态', horizontal_preferred: '横向优先 · 软提示', horizontal_strict: '严格近水平 · 硬过滤' }[props.ocrShapeMode] || props.ocrShapeMode))
const folderFilters = [{ id: 'all', label: '全部版本' }, { id: 'v3', label: 'OCR 3.0' }, { id: 'v2', label: 'OCR 2.0' }]
const filteredFolders = computed(() => props.debugFolders.filter(folder => {
  const version = folder.ocr_lab_version === 'v3' ? 'v3' : 'v2'
  return (folderVersion.value === 'all' || folderVersion.value === version) && (!folderQuery.value.trim() || `${folder.name} ${folder.path}`.toLocaleLowerCase().includes(folderQuery.value.trim().toLocaleLowerCase()))
}))

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
