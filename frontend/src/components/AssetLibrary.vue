<template>
  <section class="panel">
    <div class="panel-head">
      <h2>本地素材库</h2>
      <button class="secondary mini" @click="$emit('refresh')">刷新</button>
    </div>
    <div class="grid2">
      <div>
        <label for="localVideo">本地视频路径</label>
        <input id="localVideo" :value="localVideo" placeholder="从下方视频列表选择，或手填项目内视频路径" @input="$emit('update:localVideo', $event.target.value)" />
      </div>
      <div>
        <label>本地处理</label>
        <div class="toolbar">
          <button class="warning" @click="$emit('local-ocr')">用本地视频 OCR 翻译</button>
          <button class="secondary" @click="$emit('local-audio')">音频识别字幕</button>
        </div>
      </div>
    </div>
    <div class="mode-row" style="margin-top:12px">
      <label for="audioLanguage">音频语言</label>
      <select id="audioLanguage" :value="audioLanguage" @change="$emit('update:audioLanguage', $event.target.value)">
        <option value="auto">自动识别</option>
        <option value="korean">韩语</option>
        <option value="english">英语</option>
        <option value="japanese">日语</option>
        <option value="chinese">中文</option>
      </select>
      <label for="audioModelSize">ASR 模型</label>
      <select id="audioModelSize" :value="audioModelSize" @change="$emit('update:audioModelSize', $event.target.value)">
        <option value="large-v3">large-v3</option>
        <option value="medium">medium</option>
        <option value="small">small</option>
      </select>
      <span class="muted">识别人声生成 source.srt，之后可用下方字幕翻译模式继续翻译</span>
    </div>
    <div style="margin-top:12px">
      <div class="section-title">
        <h3>视频项目</h3>
        <span class="badge">{{ projects.length }}</span>
      </div>
      <div v-if="!projects.length" class="asset-list empty">暂无文件。</div>
      <div v-else class="project-list">
        <details v-for="project in projects" :key="project.path" class="project-card" open>
          <summary>
            <div>
              <div class="project-title">{{ project.name }}</div>
              <div class="muted path">{{ project.path }}</div>
            </div>
            <div class="project-counts">
              <span>{{ project.counts?.videos || 0 }} 视频</span>
              <span>{{ project.counts?.subtitles || 0 }} 字幕</span>
              <span v-if="project.counts?.images">{{ project.counts.images }} 封面</span>
            </div>
          </summary>
          <div class="project-body">
            <div v-if="project.images?.length" class="project-cover">
              <img :src="fileUrl(project.images[0].path)" alt="" />
              <button class="ghost mini" @click="copyPath(project.images[0].path)">复制封面路径</button>
            </div>
            <div class="project-column">
              <div class="asset-subtitle">视频</div>
              <AssetList :items="project.videos || []" empty-text="无视频。">
                <template #actions="{ item }">
                  <button class="secondary mini" @click="$emit('use-video', item.path)">选为视频</button>
                  <button class="warning mini" @click="$emit('use-video-ocr', item.path)">OCR</button>
                </template>
              </AssetList>
            </div>
            <div class="project-column">
              <div class="asset-subtitle">字幕</div>
              <AssetList :items="project.subtitles || []" empty-text="无字幕。">
                <template #actions="{ item }">
                  <button class="secondary mini" @click="$emit('use-subtitle', item.path)">设为源字幕</button>
                  <button class="ghost mini" @click="copyPath(item.path)">复制路径</button>
                </template>
              </AssetList>
            </div>
            <div v-if="project.others?.length" class="project-column">
              <div class="asset-subtitle">其他文件</div>
              <AssetList :items="project.others" empty-text="无其他文件。">
                <template #actions="{ item }">
                  <button class="ghost mini" @click="copyPath(item.path)">复制路径</button>
                </template>
              </AssetList>
            </div>
          </div>
        </details>
      </div>
    </div>
    <div style="margin-top:12px">
      <div class="section-title"><h3>OCR 任务输出</h3><span class="badge">{{ assets.ocr_jobs.length }}</span></div>
      <AssetList :items="assets.ocr_jobs" empty-text="暂无文件。">
        <template #actions="{ item }">
          <button v-if="item.source_srt" class="secondary mini" @click="$emit('use-subtitle', item.source_srt)">使用 source.srt</button>
          <button v-if="item.translated_srt" class="ghost mini" @click="copyPath(item.translated_srt)">复制 zh.srt</button>
        </template>
      </AssetList>
    </div>
    <div class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
import AssetList from './AssetList.vue'
import { computed } from 'vue'

const props = defineProps({
  localVideo: { type: String, default: '' },
  audioLanguage: { type: String, default: 'auto' },
  audioModelSize: { type: String, default: 'large-v3' },
  assets: { type: Object, required: true },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})
defineEmits([
  'update:localVideo', 'update:audioLanguage', 'update:audioModelSize',
  'refresh', 'local-ocr', 'local-audio', 'use-video', 'use-video-ocr', 'use-subtitle',
])

function copyPath(path) {
  navigator.clipboard?.writeText(path)
}

const projects = computed(() => props.assets.projects || [])

function fileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path)}`
}
</script>
