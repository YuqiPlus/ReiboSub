<template>
  <section class="panel primary-panel">
    <div class="panel-head">
      <h2>输入视频</h2>
      <span class="muted">先检测字幕，有原生字幕就不用 OCR 时间轴</span>
    </div>
    <div class="url-row">
      <div>
        <label for="url">YouTube 链接或视频 ID</label>
        <input id="url" :value="url" placeholder="https://www.youtube.com/watch?v=..." @input="$emit('update:url', $event.target.value)" />
      </div>
      <button :disabled="probing" @click="$emit('probe')">检测字幕</button>
    </div>
    <div class="mode-row">
      <label>画面内嵌字幕</label>
      <div class="segmented">
        <button type="button" :class="{ active: embeddedSubtitleHint === 'unknown' }" @click="$emit('update:embeddedSubtitleHint', 'unknown')">不清楚</button>
        <button type="button" :class="{ active: embeddedSubtitleHint === 'yes' }" @click="$emit('update:embeddedSubtitleHint', 'yes')">有</button>
        <button type="button" :class="{ active: embeddedSubtitleHint === 'no' }" @click="$emit('update:embeddedSubtitleHint', 'no')">没有</button>
      </div>
      <span class="muted">没有可用字幕时，Agent 会用这个判断节省 OCR/ASR 诊断时间</span>
    </div>
    <div class="mode-row">
      <label for="sourceLanguage">音源语言</label>
      <select id="sourceLanguage" :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)">
        <option value="auto">自动</option>
        <option value="korean">韩语</option>
        <option value="japanese">日语</option>
        <option value="english">英语</option>
        <option value="chinese">中文</option>
      </select>
      <span class="muted">用于 ASR 和选择视频作者上传的原声字幕。</span>
    </div>
    <div class="mode-row">
      <label for="ocrLanguage">OCR 字幕语言</label>
      <select id="ocrLanguage" :value="ocrLanguage" @change="$emit('update:ocrLanguage', $event.target.value)">
        <option value="auto">跟随音源</option>
        <option value="korean">韩语</option>
        <option value="japanese">日语</option>
        <option value="english">英语</option>
        <option value="chinese">中文：只提取</option>
      </select>
      <span class="muted">画面里烧录中文字幕时选中文，会直接 OCR 提取为 zh.srt，不翻译。</span>
    </div>
    <div class="toolbar">
      <button class="secondary" @click="$emit('download-video')">下载视频</button>
      <button class="secondary" @click="$emit('download-thumbnail')">下载封面</button>
      <button class="warning" @click="$emit('ocr-full')">下载视频并 OCR 翻译</button>
    </div>
    <div class="mode-row">
      <label for="thumbnailFormat">封面格式</label>
      <select id="thumbnailFormat" :value="thumbnailFormat" @change="$emit('update:thumbnailFormat', $event.target.value)">
        <option value="jpg">JPG</option>
        <option value="png">PNG</option>
        <option value="webp">WebP</option>
        <option value="source">原始格式</option>
      </select>
      <span class="muted">默认 JPG；选择原始格式时保留 YouTube 返回的 webp/jpg/png</span>
    </div>
    <div class="mode-row">
      <label for="videoQuality">视频画质</label>
      <select id="videoQuality" :value="videoQuality" @change="$emit('update:videoQuality', $event.target.value)">
        <option value="1080p">主流程 1080p H264</option>
        <option value="720p">主流程 720p H264</option>
        <option value="1440p">主流程最高 2K</option>
        <option value="2160p">主流程最高 4K</option>
        <option value="best">最高画质收藏版</option>
      </select>
      <span class="muted">默认下载 OCR/播放器更稳的 H264 MP4；最高画质收藏版会另存为 .best.<编码> 文件，不覆盖主流程视频</span>
    </div>
    <div class="mode-row">
      <label for="ocrTranslationMode">OCR 翻译处理模式</label>
      <select id="ocrTranslationMode" :value="ocrExtractionMode === 'region_v3' ? 'translate_only' : ocrTranslationMode" :disabled="ocrExtractionMode === 'region_v3'" @change="$emit('update:ocrTranslationMode', $event.target.value)">
        <option value="translate_only">锁定时间轴：只翻译文本</option>
        <option value="standard_cleanup">标准清理：去重复和残片</option>
        <option value="readability_retime">强力精修：优化阅读时长</option>
      </select>
      <span v-if="ocrExtractionMode === 'region_v3'" class="muted">OCR 3.0 固定锁定几何精修后的原时间轴，只翻译文本。</span>
      <span v-else class="muted">内嵌字幕稳定时选锁定时间轴；OCR 有闪字/残片时选标准或强力</span>
    </div>
    <div class="mode-row">
      <label>OCR 模式</label>
      <div class="segmented">
        <button type="button" :class="{ active: ocrScope !== 'smart_full' }" @click="setOcrMode('limited')">限定区域</button>
        <button type="button" :class="{ active: ocrScope === 'smart_full' }" @click="setOcrMode('smart_full')">全屏辅助</button>
      </div>
      <span class="muted">限定区域只扫绿色裁剪框；全屏辅助会额外扫全画面候选，适合字幕位置不固定或有花字。</span>
    </div>
    <div class="mode-row">
      <label>OCR 提取方式</label>
      <div class="segmented">
        <button type="button" :class="{ active: ocrExtractionMode === 'auto' }" @click="$emit('update:ocrExtractionMode', 'auto')">自动主字幕</button>
        <button type="button" :class="{ active: ocrExtractionMode === 'region' }" @click="$emit('update:ocrExtractionMode', 'region')">区域 OCR</button>
        <button type="button" :class="{ active: ocrExtractionMode === 'region_v3' }" @click="$emit('update:ocrExtractionMode', 'region_v3')">OCR 3.0（几何精修实验）</button>
      </div>
      <span class="muted">区域 OCR 会信任绿色裁剪框里的文字，不走原来的 logo/主字幕分类；旧自动模式不变。</span>
    </div>
    <div v-if="ocrExtractionMode === 'region_v3'" class="mode-row">
      <label for="ocrShapeMode">文字形态策略</label>
      <select id="ocrShapeMode" :value="ocrShapeMode" @change="$emit('update:ocrShapeMode', $event.target.value)">
        <option value="unrestricted">不限形态（不按角度预判）</option>
        <option value="horizontal_preferred">横向优先（推荐，软标记）</option>
        <option value="horizontal_strict">严格近水平（硬过滤）</option>
      </select>
      <span class="muted">3.0 参考文字行角度：横向优先会保留倾斜候选并交给几何 LLM，严格近水平才会在识别阶段硬过滤。</span>
    </div>
    <div class="mode-row">
      <label>裁剪预设</label>
      <div class="segmented">
        <button type="button" :class="{ active: isCropPreset(0.58) }" @click="applyCropPreset(0.58)">底部</button>
        <button type="button" :class="{ active: isCropPreset(0.38) }" @click="applyCropPreset(0.38)">中下</button>
      </div>
      <span class="muted">预设只调整下方裁剪区域；不合适时继续用抽帧预览里的上/下/左/右微调。</span>
    </div>

    <OcrCropControls
      :input-video="inputVideo"
      :ocr-scope="ocrScope"
      :ocr-extraction-mode="ocrExtractionMode"
      :ocr-shape-mode="ocrShapeMode"
      :source-language="sourceLanguage"
      :ocr-language="ocrLanguage"
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
    <div v-if="ocrExtractionMode !== 'region_v3'" class="mode-row">
      <label for="ocrRefinementMode">OCR 原文精修</label>
      <select id="ocrRefinementMode" :value="ocrRefinementMode" @change="$emit('update:ocrRefinementMode', $event.target.value)">
        <option value="none">关闭：使用当前机器分段</option>
        <option value="llm_boxes">新版：LLM 参考原始 OCR 框精修</option>
      </select>
      <span class="muted">新版会把逐帧文字框和机器分段一起交给 LLM，适合减少误换行、闪字和孤立噪声</span>
    </div>
    <div v-else class="mode-row">
      <label>OCR 3.0 原文精修</label>
      <b>专属几何 LLM（自动启用）</b>
      <span class="muted">先按轨迹计算移动、缩放、旋转和透视证据，再由独立 3.0 策略保守决定；不会再接旧版文本去噪。</span>
    </div>
    <div class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
import OcrCropControls from './OcrCropControls.vue'
const props = defineProps({
  url: { type: String, default: '' },
  ocrTranslationMode: { type: String, default: 'standard_cleanup' },
  ocrScope: { type: String, default: 'bottom' },
  ocrExtractionMode: { type: String, default: 'auto' },
  ocrShapeMode: { type: String, default: 'horizontal_preferred' },
  inputVideo: { type: String, default: '' },
  ocrCropTopRatio: { type: Number, default: 0.58 },
  ocrCropBottomRatio: { type: Number, default: 0 },
  ocrCropLeftRatio: { type: Number, default: 0 },
  ocrCropRightRatio: { type: Number, default: 0 },
  ocrExcludeEnabled: { type: Boolean, default: false },
  ocrExcludeTopRatio: { type: Number, default: 0.04 },
  ocrExcludeBottomRatio: { type: Number, default: 0.82 },
  ocrExcludeLeftRatio: { type: Number, default: 0.76 },
  ocrExcludeRightRatio: { type: Number, default: 0.02 },
  ocrRefinementMode: { type: String, default: 'none' },
  thumbnailFormat: { type: String, default: 'jpg' },
  videoQuality: { type: String, default: '1080p' },
  embeddedSubtitleHint: { type: String, default: 'unknown' },
  sourceLanguage: { type: String, default: 'auto' },
  ocrLanguage: { type: String, default: 'auto' },
  probing: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})
const emit = defineEmits(['update:url', 'update:ocrTranslationMode', 'update:ocrScope', 'update:ocrExtractionMode', 'update:ocrShapeMode', 'update:ocrCropTopRatio', 'update:ocrCropBottomRatio', 'update:ocrCropLeftRatio', 'update:ocrCropRightRatio', 'update:ocrExcludeEnabled', 'update:ocrExcludeTopRatio', 'update:ocrExcludeBottomRatio', 'update:ocrExcludeLeftRatio', 'update:ocrExcludeRightRatio', 'update:ocrRefinementMode', 'update:embeddedSubtitleHint', 'update:sourceLanguage', 'update:ocrLanguage', 'update:thumbnailFormat', 'update:videoQuality', 'probe', 'download-video', 'download-thumbnail', 'ocr-full'])

function setOcrMode(mode) {
  emit('update:ocrScope', mode === 'smart_full' ? 'smart_full' : 'bottom')
}

function applyCropPreset(topRatio) {
  emit('update:ocrCropTopRatio', topRatio)
  emit('update:ocrCropBottomRatio', 0)
}

function isCropPreset(topRatio) {
  return Math.abs(Number(props.ocrCropTopRatio || 0) - topRatio) < 0.005
}

</script>
