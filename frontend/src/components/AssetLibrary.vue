<template>
  <section class="panel library-studio">
    <header class="studio-page-head"><div><h2>素材库</h2><p>{{ projects.length }} 个素材项目 · 视频、字幕和处理工具放在一起。</p></div><div class="toolbar"><button class="secondary" type="button" @click="$emit('refresh')"><AppIcon name="history" :size="16" />刷新</button><button type="button" :disabled="uploadBusy" :aria-expanded="showImport" @click="showImport = !showImport"><AppIcon name="plus" :size="17" />导入素材</button></div></header>

    <section v-if="showImport" class="library-import" aria-label="导入素材">
      <div class="studio-section-head"><div><h3>从本机上传</h3><p>仅保存素材，不会自动开始识别或翻译。</p></div><button class="icon-button" type="button" aria-label="收起导入" :disabled="uploadBusy" @click="showImport = false"><AppIcon name="close" :size="18" /></button></div>
      <div class="upload-grid"><label class="file-picker"><span>{{ uploadFileName || '选择视频或音频' }}</span><input type="file" accept="video/*,audio/*,.mkv,.m4v,.avi,.ts,.m2ts,.flac,.m4a,.aac,.ogg,.opus,.wma" :disabled="uploadBusy" @change="selectUploadFile" /></label><input v-model="uploadTitle" aria-label="素材名称" placeholder="素材名称（可选）" :disabled="uploadBusy" /><button type="button" :disabled="uploadBusy || !uploadFile" @click="submitUpload">{{ uploadBusy ? '正在上传…' : '上传素材' }}</button></div>
      <details class="studio-disclosure library-manual"><summary>素材已在服务器上？按路径导入</summary><label for="localVideo">媒体路径<input id="localVideo" :value="localVideo" placeholder="填写视频或音频的完整路径" @input="$emit('update:localVideo', $event.target.value)" /></label><div class="toolbar"><button class="secondary" :disabled="!localVideo" @click="$emit('register-local-project')">登记为素材项目</button><button class="secondary" :disabled="!localVideo" @click="$emit('open-asr-lab')">语音识别</button><button class="secondary" :disabled="!localVideo || selectedIsAudio" @click="$emit('local-ocr')">画面字幕识别</button></div></details>
    </section>

    <div class="studio-filter-bar"><label class="studio-search library-search"><AppIcon name="search" :size="18" /><input v-model="query" type="search" aria-label="搜索素材" placeholder="搜索标题或文件名" /></label><div class="studio-tabs" aria-label="素材类型"><button v-for="option in typeFilters" :key="option.id" type="button" :class="{ active: mediaFilter === option.id }" :aria-pressed="mediaFilter === option.id" @click="mediaFilter = option.id">{{ option.label }}</button></div><select v-model="sortBy" class="library-sort" aria-label="素材排序"><option value="recent">最近更新</option><option value="name">按名称</option></select></div>
    <p v-if="status && statusClass === 'bad'" class="status bad" role="alert">{{ status }}</p>
    <p v-else-if="actionFeedback" class="library-action-feedback" role="status">{{ actionFeedback }}</p>
    <p v-if="localVideo" class="library-current-media" :title="localVideo"><AppIcon name="check" :size="14" /><span>当前媒体：{{ fileLabel(localVideo) }}</span></p>
    <div v-if="!visibleProjects.length" class="studio-empty"><AppIcon :name="query ? 'search' : 'folder'" :size="34" /><h3>{{ query || mediaFilter !== 'all' ? '没有找到对应素材' : '从你的第一段素材开始' }}</h3><p>{{ query || mediaFilter !== 'all' ? '试试其他关键词，或切换素材类型。' : '上传本地文件，或到“下载与链接”保存视频。' }}</p><button v-if="query || mediaFilter !== 'all'" class="secondary" @click="query = ''; mediaFilter = 'all'">清除筛选</button><button v-else @click="showImport = true">导入素材</button></div>

    <div class="library-browser" :class="{ 'has-selection': selectedProject }">
      <div class="library-grid">
        <article v-for="project in visibleProjects" :key="project.path" class="library-card" :class="{ selected: selectedProjectPath === project.path }">
          <button class="library-card-open" type="button" :aria-label="`打开素材：${project.name}`" :aria-pressed="selectedProjectPath === project.path" @click="selectProject(project)">
            <span class="library-card-cover"><img v-if="projectCover(project)" :src="fileUrl(projectCover(project))" loading="lazy" alt="" /><AppIcon v-else :name="project.audios?.length && !project.videos?.length ? 'audio' : 'video'" :size="28" /></span>
          </button>
          <div class="library-card-content">
            <button class="library-card-title" type="button" @click="selectProject(project)"><h3>{{ project.name }}</h3></button>
            <div class="library-card-meta"><span class="library-source">{{ sourceLabel(project.source_type) }}</span><span>{{ projectSummary(project) }}</span><time>{{ modifiedLabel(project) }}</time></div>
            <div class="library-card-actions">
              <button type="button" @click="$emit('use-project', project)">载入项目</button>
              <button v-if="projectMedia(project)" class="secondary" type="button" @click="previewProject(project)"><AppIcon name="play" :size="14" />预览</button>
              <button v-if="preferredProjectSubtitle(project)" class="secondary" type="button" :title="preferredProjectSubtitle(project).path" @click="$emit('edit-subtitle', { path: preferredProjectSubtitle(project).path, videoPath: project.primary_video || project.videos?.[0]?.path || '' })"><AppIcon name="edit" :size="14" />精修字幕</button>
              <button v-else-if="projectMedia(project)?.kind === 'video'" class="secondary" type="button" @click="$emit('use-video-ocr', projectMedia(project).path)">提取画面字幕</button>
              <button v-else-if="projectMedia(project)?.kind === 'audio'" class="secondary" type="button" @click="$emit('use-media-asr', projectMedia(project).path)">语音识别</button>
              <button class="secondary library-more-action" type="button" :aria-expanded="selectedProjectPath === project.path" @click="selectProject(project)">文件与更多<AppIcon name="chevron" :size="13" /></button>
            </div>
          </div>
        </article>
      </div>
      <aside v-if="selectedProject" ref="projectDetail" class="library-detail" tabindex="-1" aria-label="所选素材详情">
        <header class="studio-section-head"><div><span class="studio-kicker">所选素材</span><h3>{{ selectedProject.name }}</h3></div><button class="icon-button" type="button" aria-label="关闭素材详情" @click="selectedProjectPath = ''"><AppIcon name="close" :size="18" /></button></header>
        <div class="toolbar library-primary-actions"><button type="button" @click="$emit('use-project', selectedProject)">载入项目</button><button v-if="previewMedia" class="secondary" type="button" :aria-expanded="showPreview" @click="showPreview = !showPreview"><AppIcon name="play" :size="14" />{{ showPreview ? '收起预览' : '预览素材' }}</button></div>
        <component v-if="showPreview && previewMedia" :is="previewMedia.kind" :key="previewMedia.path" class="library-media-preview" controls playsinline preload="metadata" :src="fileUrl(previewMedia.path)" :aria-label="selectedProject.name" />
        <section v-if="selectedProject.videos?.length" class="library-file-section"><h4>视频</h4><AssetList :items="selectedProject.videos"><template #actions="{ item }"><button class="secondary mini" :disabled="localVideo === item.path" @click="$emit('use-video', item.path)">{{ localVideo === item.path ? '当前媒体' : '设为当前' }}</button><button class="secondary mini" @click="$emit('use-media-asr', item.path)">语音识别</button><button class="secondary mini" @click="$emit('use-video-ocr', item.path)">提取画面字幕</button></template></AssetList></section>
        <section v-if="selectedProject.audios?.length" class="library-file-section"><h4>音频</h4><AssetList :items="selectedProject.audios"><template #actions="{ item }"><button class="secondary mini" :disabled="localVideo === item.path" @click="$emit('use-audio', item.path)">{{ localVideo === item.path ? '当前媒体' : '设为当前' }}</button><button class="secondary mini" @click="$emit('use-media-asr', item.path)">语音识别</button><button class="ghost mini" @click="copyPath(item.path)">复制路径</button></template></AssetList></section>
        <section v-if="selectedProject.subtitles?.length" class="library-file-section"><h4>字幕</h4><AssetList :items="selectedProject.subtitles"><template #actions="{ item }"><button class="mini" @click="$emit('edit-subtitle', { path: item.path, videoPath: selectedProject.primary_video || selectedProject.videos?.[0]?.path || '' })">精修字幕</button><button class="secondary mini" @click="$emit('use-subtitle', item.path)">用于翻译</button><a class="button-link" :href="fileUrl(item.path)" download>下载</a></template></AssetList></section>
        <details class="studio-disclosure library-project-info"><summary>文件位置与项目管理</summary><p class="path">{{ selectedProject.path }}</p><div class="toolbar"><button class="ghost mini" @click="copyPath(selectedProject.path)">复制目录</button><button v-if="selectedProject.source_url" class="ghost mini" @click="copyPath(selectedProject.source_url)">复制来源链接</button><button v-if="selectedProject.manifest_path" class="ghost mini" @click="copyPath(selectedProject.manifest_path)">复制配置路径</button><label class="ghost-file">更换封面<input type="file" accept="image/*" @change="selectProjectCover(selectedProject, $event)" /></label><button v-if="projectCover(selectedProject)" class="ghost mini" @click="copyPath(projectCover(selectedProject))">复制封面路径</button></div><p v-if="selectedProject.source_url" class="path">{{ selectedProject.normalized_url || selectedProject.source_url }}</p><AssetList v-if="selectedProject.others?.length" :items="selectedProject.others"><template #actions="{ item }"><button class="ghost mini" @click="copyPath(item.path)">复制路径</button></template></AssetList><button class="danger secondary mini library-delete" @click="$emit('delete-project', selectedProject)">删除素材目录…</button></details>
      </aside>
    </div>

    <details v-if="assets.ocr_jobs?.length" class="studio-disclosure library-outputs"><summary>独立处理结果 <span>{{ assets.ocr_jobs.length }}</span></summary><p class="muted">未归入项目的识别与翻译产物。</p><AssetList :items="assets.ocr_jobs"><template #actions="{ item }"><button v-if="item.source_srt" class="secondary mini" @click="$emit('use-subtitle', item.source_srt)">使用原文</button><button v-if="item.source_srt" class="secondary mini" @click="$emit('edit-subtitle', { path: item.source_srt, videoPath: item.input_video || '' })">精修原文</button><button v-if="item.translated_srt" class="mini" @click="$emit('edit-subtitle', { path: item.translated_srt, videoPath: item.input_video || '' })">精修中文</button><button v-if="item.translated_srt" class="ghost mini" @click="copyPath(item.translated_srt)">复制中文路径</button></template></AssetList></details>
    <Teleport to="body"><div v-if="copyStatus" class="copy-toast" :class="copyStatusClass" role="status">{{ copyStatus }}</div></Teleport>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AssetList from './AssetList.vue'
import { copyText } from '../clipboard.js'
import AppIcon from './AppIcon.vue'
import { fileLabel, filterLibraryProjects, projectMediaSummary, localModifiedLabel, preferredProjectSubtitle, projectMedia } from '../studioTools.js'

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
const query = ref(''), mediaFilter = ref('all'), sortBy = ref('recent'), selectedProjectPath = ref('')
const showImport = ref(false), showPreview = ref(false)
const projectDetail = ref(null)
const typeFilters = [{ id: 'all', label: '全部' }, { id: 'video', label: '视频' }, { id: 'audio', label: '音频' }, { id: 'subtitle', label: '字幕' }]
const visibleProjects = computed(() => filterLibraryProjects(projects.value, { query: query.value, kind: mediaFilter.value, sort: sortBy.value }))
const selectedProject = computed(() => visibleProjects.value.find(project => project.path === selectedProjectPath.value) || null)
const previewMedia = computed(() => projectMedia(selectedProject.value))
const projectSummary = projectMediaSummary
const actionFeedback = computed(() => {
  if (props.statusClass !== 'ok' || /^(已扫描|已选择当前)/.test(props.status)) return ''
  if (props.status.startsWith('封面已更新')) return '封面已更新。'
  return props.status
})
const modifiedLabel = localModifiedLabel
watch(() => selectedProject.value?.path, () => { showPreview.value = false })
async function selectProject(project) {
  selectedProjectPath.value = project.path
  await nextTick()
  projectDetail.value?.focus({ preventScroll: true })
  if (window.innerWidth <= 760) projectDetail.value?.scrollIntoView({ block: 'start' })
}
async function previewProject(project) {
  await selectProject(project)
  showPreview.value = true
}
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
