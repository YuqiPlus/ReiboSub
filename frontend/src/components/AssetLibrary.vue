<template>
  <section class="panel">
    <div class="panel-head">
      <h2>本地素材库</h2>
      <button class="secondary mini" @click="$emit('refresh')">刷新</button>
    </div>
    <div class="upload-card">
      <div>
        <div class="eyebrow">Mobile Upload</div>
        <h3>上传视频后直接 ASR 翻译</h3>
        <p class="panel-subtitle">视频会保存为本地项目，完成后自动生成 source.srt 和 zh.srt 到视频同目录。</p>
      </div>
      <div class="upload-grid">
        <label class="file-picker">
          <span>{{ uploadFileName || '选择视频' }}</span>
          <input type="file" accept="video/*" @change="selectUploadFile" />
        </label>
        <input v-model="uploadTitle" placeholder="项目名，可不填" />
        <button class="warning" :disabled="uploadBusy || !uploadFile" @click="submitUploadAsrTranslate">{{ uploadBusy ? '处理中' : '上传并 ASR 翻译' }}</button>
      </div>
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
          <button class="secondary" @click="$emit('register-local-project')">登记为视频项目</button>
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
        <details v-for="project in projects" :key="project.path" class="project-card">
          <summary>
            <div>
              <div class="project-title">{{ project.name }}</div>
              <div class="project-meta">
                <span class="badge">{{ sourceLabel(project.source_type) }}</span>
                <button v-if="project.source_url" class="ghost mini" type="button" @click.prevent="copyPath(project.source_url)">复制链接</button>
                <button v-if="project.manifest_path" class="ghost mini" type="button" @click.prevent="copyPath(project.manifest_path)">复制配置</button>
                <label class="ghost-file mini" @click.stop>上传封面<input type="file" accept="image/*" @change="selectProjectCover(project, $event)" /></label>
              </div>
              <div v-if="project.source_url" class="muted path">{{ project.normalized_url || project.source_url }}</div>
              <div class="muted path">{{ project.path }}</div>
            </div>
            <div class="project-counts">
              <span>{{ project.counts?.videos || 0 }} 视频</span>
              <span>{{ project.counts?.subtitles || 0 }} 字幕</span>
              <span v-if="project.counts?.images">{{ project.counts.images }} 封面</span>
              <button class="secondary mini" type="button" @click.prevent="$emit('use-project', project)">继续处理</button>
              <button class="danger secondary mini" type="button" @click.prevent="$emit('delete-project', project)">删除目录</button>
            </div>
          </summary>
          <div class="project-body">
            <div v-if="projectCover(project)" class="project-cover">
              <img :src="fileUrl(projectCover(project))" alt="" />
              <button class="ghost mini" @click="copyPath(projectCover(project))">复制封面路径</button>
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
                  <button class="warning mini" @click="$emit('edit-subtitle', { path: item.path, videoPath: project.primary_video || project.videos?.[0]?.path || '' })">精修</button>
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
          <button v-if="item.source_srt" class="warning mini" @click="$emit('edit-subtitle', { path: item.source_srt, videoPath: item.input_video || '' })">精修 source</button>
          <button v-if="item.translated_srt" class="warning mini" @click="$emit('edit-subtitle', { path: item.translated_srt, videoPath: item.input_video || '' })">精修 zh</button>
          <button v-if="item.translated_srt" class="ghost mini" @click="copyPath(item.translated_srt)">复制 zh.srt</button>
        </template>
      </AssetList>
    </div>
    <Teleport to="body">
      <div v-if="copyStatus" class="copy-toast" :class="copyStatusClass">{{ copyStatus }}</div>
    </Teleport>
    <div class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
import AssetList from './AssetList.vue'
import { computed, ref } from 'vue'
import { copyText } from '../clipboard.js'

const props = defineProps({
  localVideo: { type: String, default: '' },
  audioLanguage: { type: String, default: 'auto' },
  audioModelSize: { type: String, default: 'large-v3' },
  assets: { type: Object, required: true },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  uploadBusy: { type: Boolean, default: false },
})
const copyStatus = ref('')
const uploadFile = ref(null)
const uploadTitle = ref('')
const uploadFileName = computed(() => uploadFile.value?.name || '')

const emit = defineEmits([
  'update:localVideo', 'update:audioLanguage', 'update:audioModelSize',
  'refresh', 'local-ocr', 'local-audio', 'register-local-project', 'use-project', 'use-video', 'use-video-ocr', 'use-subtitle',
  'edit-subtitle', 'delete-project', 'upload-asr-translate', 'upload-cover',
])



function selectProjectCover(project, event) {
  const file = event.target.files?.[0] || null
  event.target.value = ''
  if (!file || !project?.path) return
  emit('upload-cover', { project, file })
}

function selectUploadFile(event) {
  const file = event.target.files?.[0] || null
  uploadFile.value = file
  if (file && !uploadTitle.value.trim()) {
    uploadTitle.value = file.name.replace(/\.[^.]+$/, '')
  }
}

function submitUploadAsrTranslate() {
  if (!uploadFile.value) return
  emitUploadAsrTranslate(uploadFile.value, uploadTitle.value.trim())
}

function emitUploadAsrTranslate(file, title) {
  emit('upload-asr-translate', { file, title })
}

async function copyPath(path) {
  const ok = await copyText(path)
  copyStatus.value = ok ? '已复制。' : '复制失败，请手动选择文本。'
  window.setTimeout(() => {
    copyStatus.value = ''
  }, 1600)
}

function sourceLabel(sourceType) {
  if (sourceType === 'youtube') return 'YouTube'
  if (sourceType === 'local') return '本地视频'
  return '未登记来源'
}

const projects = computed(() => props.assets.projects || [])

function projectCover(project) {
  return project?.thumbnail || project?.images?.[0]?.path || ''
}

function fileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path)}`
}
</script>
