<template>
  <section class="panel">
    <div class="panel-head">
      <h2>本地素材库</h2>
      <button class="secondary mini" type="button" @click="$emit('refresh')">刷新</button>
    </div>

    <div class="upload-card">
      <div>
        <div class="eyebrow">Local Media</div>
        <h3>上传视频或音频素材</h3>
        <p class="panel-subtitle">这里只负责保存素材，不会自动运行 ASR、OCR 或翻译。上传完成后再选择需要的处理工具。</p>
      </div>
      <div class="upload-grid">
        <label class="file-picker">
          <span>{{ uploadFileName || '选择视频或音频' }}</span>
          <input
            type="file"
            accept="video/*,audio/*,.mkv,.m4v,.avi,.ts,.m2ts,.flac,.m4a,.aac,.ogg,.opus,.wma"
            @change="selectUploadFile"
          />
        </label>
        <input v-model="uploadTitle" placeholder="素材项目名，可不填" />
        <button class="warning" type="button" :disabled="uploadBusy || !uploadFile" @click="submitUpload">
          {{ uploadBusy ? '正在上传…' : '仅上传素材' }}
        </button>
      </div>
    </div>

    <div class="grid2">
      <div>
        <label for="localVideo">当前媒体路径</label>
        <input
          id="localVideo"
          :value="localVideo"
          placeholder="从下方选择视频或音频，也可以手动填写路径"
          @input="$emit('update:localVideo', $event.target.value)"
        />
      </div>
      <div>
        <label>素材处理</label>
        <div class="toolbar">
          <button class="warning" type="button" :disabled="!localVideo || selectedIsAudio" @click="$emit('local-ocr')">视频 OCR</button>
          <button class="secondary" type="button" :disabled="!localVideo" @click="$emit('open-asr-lab')">打开 ASR Lab</button>
          <button class="secondary" type="button" :disabled="!localVideo" @click="$emit('register-local-project')">登记为素材项目</button>
        </div>
      </div>
    </div>

    <div style="margin-top:12px">
      <div class="section-title">
        <h3>素材项目</h3>
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
              <span v-if="project.counts?.audios">{{ project.counts.audios }} 音频</span>
              <span>{{ project.counts?.subtitles || 0 }} 字幕</span>
              <span v-if="project.counts?.images">{{ project.counts.images }} 封面</span>
              <button class="secondary mini" type="button" @click.prevent="$emit('use-project', project)">载入项目</button>
              <button class="danger secondary mini" type="button" @click.prevent="$emit('delete-project', project)">删除目录</button>
            </div>
          </summary>

          <div class="project-body">
            <div v-if="projectCover(project)" class="project-cover">
              <img :src="fileUrl(projectCover(project))" alt="" />
              <button class="ghost mini" type="button" @click="copyPath(projectCover(project))">复制封面路径</button>
            </div>

            <div v-if="project.videos?.length" class="project-column">
              <div class="asset-subtitle">视频</div>
              <AssetList :items="project.videos || []" empty-text="无视频。">
                <template #actions="{ item }">
                  <button class="secondary mini" type="button" @click="$emit('use-video', item.path)">设为当前</button>
                  <button class="secondary mini" type="button" @click="$emit('use-media-asr', item.path)">ASR Lab</button>
                  <button class="warning mini" type="button" @click="$emit('use-video-ocr', item.path)">OCR</button>
                </template>
              </AssetList>
            </div>

            <div v-if="project.audios?.length" class="project-column">
              <div class="asset-subtitle">音频</div>
              <AssetList :items="project.audios || []" empty-text="无音频。">
                <template #actions="{ item }">
                  <button class="secondary mini" type="button" @click="$emit('use-audio', item.path)">设为当前</button>
                  <button class="warning mini" type="button" @click="$emit('use-media-asr', item.path)">ASR Lab</button>
                  <button class="ghost mini" type="button" @click="copyPath(item.path)">复制路径</button>
                </template>
              </AssetList>
            </div>

            <div v-if="project.subtitles?.length" class="project-column">
              <div class="asset-subtitle">字幕</div>
              <AssetList :items="project.subtitles || []" empty-text="无字幕。">
                <template #actions="{ item }">
                  <button class="secondary mini" type="button" @click="$emit('use-subtitle', item.path)">设为源字幕</button>
                  <button class="warning mini" type="button" @click="$emit('edit-subtitle', { path: item.path, videoPath: project.primary_video || project.videos?.[0]?.path || '' })">精修</button>
                  <button class="ghost mini" type="button" @click="copyPath(item.path)">复制路径</button>
                </template>
              </AssetList>
            </div>

            <div v-if="project.others?.length" class="project-column">
              <div class="asset-subtitle">其他文件</div>
              <AssetList :items="project.others" empty-text="无其他文件。">
                <template #actions="{ item }">
                  <button class="ghost mini" type="button" @click="copyPath(item.path)">复制路径</button>
                </template>
              </AssetList>
            </div>
          </div>
        </details>
      </div>
    </div>

    <div style="margin-top:12px">
      <div class="section-title"><h3>处理任务输出</h3><span class="badge">{{ assets.ocr_jobs.length }}</span></div>
      <AssetList :items="assets.ocr_jobs" empty-text="暂无文件。">
        <template #actions="{ item }">
          <button v-if="item.source_srt" class="secondary mini" type="button" @click="$emit('use-subtitle', item.source_srt)">使用 source.srt</button>
          <button v-if="item.source_srt" class="warning mini" type="button" @click="$emit('edit-subtitle', { path: item.source_srt, videoPath: item.input_video || '' })">精修 source</button>
          <button v-if="item.translated_srt" class="warning mini" type="button" @click="$emit('edit-subtitle', { path: item.translated_srt, videoPath: item.input_video || '' })">精修 zh</button>
          <button v-if="item.translated_srt" class="ghost mini" type="button" @click="copyPath(item.translated_srt)">复制 zh.srt</button>
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
import { computed, ref } from 'vue'
import AssetList from './AssetList.vue'
import { copyText } from '../clipboard.js'

const props = defineProps({
  localVideo: { type: String, default: '' },
  assets: { type: Object, required: true },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  uploadBusy: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:localVideo',
  'refresh',
  'local-ocr',
  'open-asr-lab',
  'register-local-project',
  'use-project',
  'use-video',
  'use-audio',
  'use-media-asr',
  'use-video-ocr',
  'use-subtitle',
  'edit-subtitle',
  'delete-project',
  'upload-media',
  'upload-cover',
])

const copyStatus = ref('')
const copyStatusClass = ref('')
const uploadFile = ref(null)
const uploadTitle = ref('')
const uploadFileName = computed(() => uploadFile.value?.name || '')
const projects = computed(() => props.assets.projects || [])
const selectedIsAudio = computed(() => /\.(mp3|wav|flac|m4a|aac|ogg|opus|wma)$/i.test(props.localVideo || ''))

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

function submitUpload() {
  if (!uploadFile.value) return
  emit('upload-media', { file: uploadFile.value, title: uploadTitle.value.trim() })
}

async function copyPath(path) {
  const ok = await copyText(path)
  copyStatus.value = ok ? '已复制。' : '复制失败，请手动选择文本。'
  copyStatusClass.value = ok ? 'ok' : 'bad'
  window.setTimeout(() => {
    copyStatus.value = ''
    copyStatusClass.value = ''
  }, 1600)
}

function sourceLabel(sourceType) {
  if (sourceType === 'youtube') return 'YouTube'
  if (sourceType === 'local') return '本地素材'
  return '未登记来源'
}

function projectCover(project) {
  return project?.thumbnail || project?.images?.[0]?.path || ''
}

function fileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path)}`
}
</script>
