<template>
  <section class="panel link-tool-panel links-studio">
    <header class="studio-page-head"><div><span class="studio-kicker">下载与链接</span><h2>从一个链接开始</h2><p>直接保存视频，或按需查看它的字幕。</p></div><AppIcon class="links-page-icon" name="download" :size="28" /></header>
    <form class="links-composer" @submit.prevent="downloadVideo">
      <label class="links-url" for="url">YouTube 链接或视频 ID<input id="url" :value="url" autocomplete="off" placeholder="粘贴 YouTube 链接…" @input="$emit('update:url', $event.target.value)" /></label>
      <div class="links-download-row">
        <label class="links-quality" for="videoQuality"><AppIcon name="video" :size="17" /><span class="sr-only">视频画质</span><select id="videoQuality" aria-label="视频画质" :value="videoQuality" @change="$emit('update:videoQuality', $event.target.value)"><option value="1080p">兼容下载 · 最高 1080p · H.264 / MP4 优先</option><optgroup v-if="availableVideoFormats.length" label="当前视频实际可用格式"><option v-for="format in availableVideoFormats" :key="format.id" :value="videoFormatChoiceValue(format)">{{ format.label }}</option></optgroup></select></label>
        <button class="secondary links-refresh-formats" type="button" :disabled="!hasUrl || videoFormatsLoading" @click="$emit('load-video-formats')"><AppIcon name="history" :size="15" />{{ videoFormatsLoading ? '读取中…' : '刷新画质' }}</button>
        <button class="links-download-primary" type="submit" :disabled="!hasUrl || Boolean(actionBusy) || probing"><AppIcon name="download" :size="17" />{{ actionBusy === 'download-video' ? '正在创建任务…' : '下载视频' }}</button>
      </div>
    </form>
    <p v-if="videoFormatsLoading || videoFormatsStatus" class="links-format-feedback" :class="videoFormatsStatusClass" role="status">{{ videoFormatsLoading ? '正在读取这个视频可下载的画质…' : videoFormatsStatus }}</p>
    <p v-else class="links-format-feedback">粘贴链接后自动读取可用画质。不必先检测字幕，也可以直接下载。</p>
    <div class="links-secondary-action"><button class="secondary" type="button" :disabled="!hasUrl || probing || Boolean(actionBusy)" @click="$emit('probe')"><AppIcon name="scan" :size="16" />{{ probing ? '正在检测…' : '查看字幕与视频信息' }}</button><span>可选操作，不会自动跳转或开始翻译。</span></div>
    <p v-if="status" class="links-operation-feedback" :class="statusClass" role="status">{{ status }}</p>
    <details class="link-tool-section">
      <summary>
        <span>
          <b>封面与下载说明</b>
          <small>下载封面，或查看画质模式说明</small>
        </span>
        <span class="link-tool-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="link-tool-section-body link-tool-download-options">
        <div class="link-setting">
          <label for="thumbnailFormat">封面格式</label>
          <select id="thumbnailFormat" :value="thumbnailFormat" @change="$emit('update:thumbnailFormat', $event.target.value)">
            <option value="jpg">JPG</option>
            <option value="png">PNG</option>
            <option value="webp">WebP</option>
            <option value="source">原始格式</option>
          </select>
          <small>默认 JPG；原始格式会保留 YouTube 返回的 WebP/JPG/PNG。</small>
        </div>
        <div class="link-tool-option-action">
          <button
            class="secondary"
            type="button"
            :disabled="!hasUrl || Boolean(actionBusy) || probing"
            @click="$emit('download-thumbnail')"
          >
            {{ actionBusy === 'download-thumbnail' ? '正在创建任务…' : '下载封面' }}
          </button>
        </div>
        <p class="link-tool-help">
          “快速兼容”无需预先读取格式，会优先选择 H.264 / MP4，适合播放器与 OCR；真实格式会按当前视频列出分辨率、容器和编码，并使用 YouTube 的具体格式 ID 精确下载，不会把 4K 悄悄回落成 1080p。
        </p>
      </div>
    </details>

    <details class="link-tool-section link-tool-ocr-section">
      <summary>
        <span>
          <b>手动提取画面字幕</b>
          <small>按需使用 OCR；独立保留全部语言、裁框和精修设置</small>
        </span>
        <span class="link-tool-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="link-tool-section-body">
        <div class="link-tool-settings-grid">
          <div class="link-setting">
            <label>画面内嵌字幕</label>
            <div class="segmented">
              <button type="button" :class="{ active: embeddedSubtitleHint === 'unknown' }" @click="$emit('update:embeddedSubtitleHint', 'unknown')">不清楚</button>
              <button type="button" :class="{ active: embeddedSubtitleHint === 'yes' }" @click="$emit('update:embeddedSubtitleHint', 'yes')">有</button>
              <button type="button" :class="{ active: embeddedSubtitleHint === 'no' }" @click="$emit('update:embeddedSubtitleHint', 'no')">没有</button>
            </div>
            <small>没有可用字幕轨道时，这项可帮助判断是否适合 OCR。</small>
          </div>
          <div class="link-setting">
            <label for="sourceLanguage">音源语言</label>
            <select id="sourceLanguage" :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)">
              <option value="auto">自动</option>
              <option value="korean">韩语</option>
              <option value="japanese">日语</option>
              <option value="english">英语</option>
              <option value="chinese">中文</option>
            </select>
            <small>用于 ASR，以及选择作者上传的原声字幕。</small>
          </div>
          <div class="link-setting">
            <label for="ocrLanguage">OCR 字幕语言</label>
            <select id="ocrLanguage" :value="ocrLanguage" @change="$emit('update:ocrLanguage', $event.target.value)">
              <option value="auto">跟随音源</option>
              <option value="korean">韩语</option>
              <option value="japanese">日语</option>
              <option value="english">英语</option>
              <option value="chinese">中文：只提取</option>
            </select>
            <small>画面是烧录中文字幕时选中文，会直接提取为 zh.srt。</small>
          </div>
        </div>

        <details class="link-tool-advanced">
          <summary>OCR 高级设置</summary>
          <div class="link-tool-advanced-body">
            <div class="link-tool-settings-grid">
              <div class="link-setting">
                <label for="ocrTranslationMode">翻译处理模式</label>
                <select id="ocrTranslationMode" :value="ocrExtractionMode === 'region_v3' ? 'translate_only' : ocrTranslationMode" :disabled="ocrExtractionMode === 'region_v3'" @change="$emit('update:ocrTranslationMode', $event.target.value)">
                  <option value="translate_only">锁定时间轴：只翻译文本</option>
                  <option value="standard_cleanup">标准清理：去重复和残片</option>
                  <option value="readability_retime">强力精修：优化阅读时长</option>
                </select>
                <small v-if="ocrExtractionMode === 'region_v3'">OCR 3.0 固定锁定几何精修后的原时间轴。</small>
                <small v-else>字幕稳定时选锁定时间轴；有闪字或残片时再加强清理。</small>
              </div>

              <div class="link-setting">
                <label>OCR 扫描范围</label>
                <div class="segmented">
                  <button type="button" :class="{ active: ocrScope !== 'smart_full' }" @click="setOcrMode('limited')">限定区域</button>
                  <button type="button" :class="{ active: ocrScope === 'smart_full' }" @click="setOcrMode('smart_full')">全屏辅助</button>
                </div>
                <small>限定区域只扫裁剪框；全屏辅助还会扫描全画面候选。</small>
              </div>

              <div class="link-setting link-setting-wide">
                <label>OCR 提取方式</label>
                <div class="segmented">
                  <button type="button" :class="{ active: ocrExtractionMode === 'auto' }" @click="$emit('update:ocrExtractionMode', 'auto')">自动主字幕</button>
                  <button type="button" :class="{ active: ocrExtractionMode === 'region' }" @click="$emit('update:ocrExtractionMode', 'region')">区域 OCR 2.0</button>
                  <button type="button" :class="{ active: ocrExtractionMode === 'region_v3' }" @click="$emit('update:ocrExtractionMode', 'region_v3')">OCR 3.0 几何精修</button>
                </div>
                <small>区域模式会信任裁剪框里的文字；原来的自动主字幕模式保持不变。</small>
              </div>

              <div v-if="ocrExtractionMode === 'region_v3'" class="link-setting">
                <label for="ocrShapeMode">文字形态策略</label>
                <select id="ocrShapeMode" :value="ocrShapeMode" @change="$emit('update:ocrShapeMode', $event.target.value)">
                  <option value="unrestricted">不限形态（不按角度预判）</option>
                  <option value="horizontal_preferred">横向优先（推荐，软标记）</option>
                  <option value="horizontal_strict">严格近水平（硬过滤）</option>
                </select>
                <small>横向优先会把倾斜候选交给几何 LLM；严格近水平才会硬过滤。</small>
              </div>

              <div class="link-setting">
                <label>裁剪预设</label>
                <div class="segmented">
                  <button type="button" :class="{ active: isCropPreset(0.58) }" @click="applyCropPreset(0.58)">底部</button>
                  <button type="button" :class="{ active: isCropPreset(0.38) }" @click="applyCropPreset(0.38)">中下</button>
                </div>
                <small>预设只调整下方区域；还可在抽帧预览里拖动和微调。</small>
              </div>
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

            <div v-if="ocrExtractionMode !== 'region_v3'" class="link-setting">
              <label for="ocrRefinementMode">OCR 原文精修</label>
              <select id="ocrRefinementMode" :value="ocrRefinementMode" @change="$emit('update:ocrRefinementMode', $event.target.value)">
                <option value="none">关闭：使用当前机器分段</option>
                <option value="llm_boxes">新版：LLM 参考原始 OCR 框精修</option>
              </select>
              <small>适合减少误换行、闪字和孤立噪声。</small>
            </div>
            <div v-else class="link-setting">
              <label>OCR 3.0 原文精修</label>
              <b>专属几何 LLM（自动启用）</b>
              <small>先计算移动、缩放、旋转和透视证据，再进行独立的保守精修。</small>
            </div>
          </div>
        </details>

        <div class="link-tool-ocr-action">
          <div>
            <b>开始 OCR 全流程</b>
            <span>会先下载视频，再按上方语言和 OCR 设置提取字幕。</span>
          </div>
          <button
            class="warning"
            type="button"
            :disabled="!hasUrl || Boolean(actionBusy) || probing"
            @click="$emit('ocr-full')"
          >
            {{ actionBusy === 'ocr-full' ? '正在创建任务…' : '下载视频并运行 OCR' }}
          </button>
        </div>
      </div>
    </details>

  </section>
</template>

<script setup>
import { computed } from 'vue'
import OcrCropControls from './OcrCropControls.vue'
import AppIcon from './AppIcon.vue'

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
  availableVideoFormats: { type: Array, default: () => [] },
  videoFormatsLoading: { type: Boolean, default: false },
  videoFormatsStatus: { type: String, default: '' },
  videoFormatsStatusClass: { type: String, default: '' },
  embeddedSubtitleHint: { type: String, default: 'unknown' },
  sourceLanguage: { type: String, default: 'auto' },
  ocrLanguage: { type: String, default: 'auto' },
  probing: { type: Boolean, default: false },
  actionBusy: { type: String, default: '' },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

const emit = defineEmits(['update:url', 'update:ocrTranslationMode', 'update:ocrScope', 'update:ocrExtractionMode', 'update:ocrShapeMode', 'update:ocrCropTopRatio', 'update:ocrCropBottomRatio', 'update:ocrCropLeftRatio', 'update:ocrCropRightRatio', 'update:ocrExcludeEnabled', 'update:ocrExcludeTopRatio', 'update:ocrExcludeBottomRatio', 'update:ocrExcludeLeftRatio', 'update:ocrExcludeRightRatio', 'update:ocrRefinementMode', 'update:embeddedSubtitleHint', 'update:sourceLanguage', 'update:ocrLanguage', 'update:thumbnailFormat', 'update:videoQuality', 'probe', 'load-video-formats', 'download-video', 'download-thumbnail', 'ocr-full'])

const hasUrl = computed(() => Boolean(String(props.url || '').trim()))
function downloadVideo() {
  if (hasUrl.value && !props.actionBusy && !props.probing) emit('download-video')
}

function videoFormatChoiceValue(format) {
  return format?.id ? `format:${format.id}` : ''
}

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

<style scoped>
.link-tool-panel {
  display: grid;
  gap: 14px;
  padding: 20px;
}
.link-tool-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
}
.link-tool-hero h2 { font-size: 18px; }
.link-tool-hero p {
  max-width: 680px;
  margin-top: 6px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}
.link-tool-direct-badge {
  flex: 0 0 auto;
  padding: 6px 10px;
  border: 1px solid rgba(45, 143, 112, .2);
  border-radius: 999px;
  background: var(--teal-soft);
  color: var(--teal-dark);
  font-size: 12px;
  font-weight: 720;
}
.link-tool-quick-grid {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(250px, .72fr) auto;
  gap: 10px;
  align-items: start;
  padding: 14px;
  border: 1px solid rgba(45, 143, 112, .2);
  border-radius: 12px;
  background: linear-gradient(145deg, rgba(232, 247, 238, .72), rgba(255, 255, 255, .94));
}
.link-tool-download-button { min-height: 40px; margin-top: 24px; font-weight: 740; }
.link-tool-format-state {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  margin-top: 5px;
}
.link-tool-format-state span {
  color: inherit;
  font-size: 11px;
  line-height: 1.35;
}
.link-tool-format-state:not(.ok):not(.bad) { color: var(--muted); }
.link-tool-format-state button { flex: 0 0 auto; }
.link-tool-detect-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.link-tool-detect-row span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}
.link-tool-status {
  min-height: 0;
  margin: -2px 0 0;
  padding: 9px 11px;
  border-radius: 8px;
  background: var(--soft);
}
.link-tool-section {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(255, 255, 255, .72);
  overflow: hidden;
}
.link-tool-section > summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 13px 14px;
  cursor: pointer;
  list-style: none;
}
.link-tool-section > summary::-webkit-details-marker,
.link-tool-advanced > summary::-webkit-details-marker { display: none; }
.link-tool-section > summary > span:first-child { display: grid; gap: 3px; }
.link-tool-section summary small {
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
}
.link-tool-chevron {
  color: var(--muted);
  font-size: 18px;
  transition: transform .18s ease;
}
.link-tool-section[open] > summary .link-tool-chevron { transform: rotate(180deg); }
.link-tool-section-body {
  display: grid;
  gap: 14px;
  padding: 14px;
  border-top: 1px solid var(--line);
  background: var(--soft);
}
.link-tool-download-options {
  grid-template-columns: minmax(220px, 320px) auto;
  align-items: end;
}
.link-tool-help {
  grid-column: 1 / -1;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.link-tool-settings-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.link-setting {
  display: grid;
  align-content: start;
  gap: 8px;
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}
.link-setting label { margin: 0; font-weight: 700; }
.link-setting small {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
}
.link-setting-wide { grid-column: span 2; }
.link-tool-advanced {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}
.link-tool-advanced > summary {
  padding: 11px 12px;
  cursor: pointer;
  color: var(--ink);
  font-size: 13px;
  font-weight: 720;
  list-style: none;
}
.link-tool-advanced > summary::after {
  content: '展开';
  float: right;
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
}
.link-tool-advanced[open] > summary::after { content: '收起'; }
.link-tool-advanced-body {
  display: grid;
  gap: 12px;
  padding: 12px;
  border-top: 1px solid var(--line);
}
.link-tool-ocr-action {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 12px;
  border: 1px solid rgba(176, 106, 40, .22);
  border-radius: 10px;
  background: var(--amber-soft);
}
.link-tool-ocr-action > div { display: grid; gap: 3px; }
.link-tool-ocr-action span { color: var(--muted); font-size: 12px; }

@media (max-width: 900px) {
  .link-tool-quick-grid { grid-template-columns: minmax(0, 1fr) minmax(190px, 240px); }
  .link-tool-download-button { grid-column: 1 / -1; margin-top: 0; }
  .link-tool-settings-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .link-tool-panel { padding: 14px; }
  .link-tool-hero,
  .link-tool-detect-row,
  .link-tool-ocr-action { align-items: stretch; flex-direction: column; }
  .link-tool-direct-badge { align-self: flex-start; }
  .link-tool-quick-grid,
  .link-tool-download-options,
  .link-tool-settings-grid { grid-template-columns: 1fr; }
  .link-setting-wide,
  .link-tool-download-button,
  .link-tool-help { grid-column: auto; }
  .link-tool-detect-row button,
  .link-tool-ocr-action button { width: 100%; }
  .link-tool-format-state { align-items: flex-start; flex-direction: column; }
}
</style>
