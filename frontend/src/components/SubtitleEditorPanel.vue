<template>
  <section class="panel subtitle-editor editor-studio">
    <header class="studio-page-head">
      <div><span class="studio-kicker">字幕精修</span><h2>{{ cues.length ? fileLabel(subtitlePath) : '把字幕打磨得更好' }}</h2><p>{{ cues.length ? `${cues.length} 条字幕 · 选择一条，边听边改。` : '打开字幕和配套视频，从一条开始。' }}</p></div>
      <div class="toolbar editor-save-actions"><span class="editor-save-state" :class="{ dirty }" role="status">{{ dirty ? '有未保存修改' : cues.length ? '已保存' : '' }}</span><button class="secondary" type="button" :disabled="loading || !canUndo" :title="`撤回最近修改（${undoCount} 步可撤回）`" @click="$emit('undo')">↶ 撤回</button><button :disabled="loading || !saveReady || !cues.length" @click="$emit('save-subtitle-as')">另存副本</button><details class="editor-save-more"><summary aria-label="更多保存选项">•••</summary><button class="secondary" :disabled="loading || !saveReady || !cues.length" @click="$emit('save-subtitle')">覆盖原字幕</button></details></div>
    </header>

    <details class="editor-file-details studio-disclosure" :open="!saveReady">
      <summary>字幕与配套视频</summary>
      <div class="editor-file-grid"><label for="subtitleEditorPath">字幕文件<input id="subtitleEditorPath" :value="subtitlePath" placeholder="选择或填写 SRT 文件路径" @input="$emit('update:subtitlePath', $event.target.value)" @keydown.enter.prevent="$emit('load-subtitle')" /></label><button class="secondary" :disabled="loading" @click="$emit('load-subtitle')">{{ loading ? '加载中…' : '加载字幕' }}</button><label for="subtitleEditorVideoPath">配套视频<input id="subtitleEditorVideoPath" :value="videoPath" placeholder="填写配套视频路径，启用播放和校时" @input="$emit('update:videoPath', $event.target.value)" /></label></div>
      <p v-if="cues.length && !saveReady" class="status bad">路径已改变，请先加载；当前内容不会写入未加载的文件。</p>
    </details>
    <p v-if="status && !status.startsWith('已加载') && !status.startsWith('已保存')" class="editor-feedback" :class="statusClass" role="status">{{ status }}</p>

    <div v-if="!cues.length" class="studio-empty"><AppIcon name="edit" :size="32" /><h3>还没有打开字幕</h3><p>可从素材库进入精修，或在上方加载 SRT 文件。</p><button class="secondary" @click="$emit('open-assets')">去素材库选择</button></div>
    <div v-else class="editor-workbench">
      <aside class="editor-preview-column" aria-label="视频与校对工具">
        <div v-if="videoUrl" class="subtitle-video-stage">
          <video :key="videoUrl" ref="videoRef" :src="videoUrl" controls playsinline preload="metadata" @loadedmetadata="onVideoLoaded" @durationchange="onVideoLoaded" @timeupdate="onVideoTimeUpdate" @seeking="onVideoSeeking" @seeked="onVideoTimeUpdate" @emptied="resetVideoState" @error="onVideoError"></video>
          <div v-if="previewSubtitleVisible" class="subtitle-video-overlay" aria-live="polite"><span>{{ previewCue?.text }}</span></div>
        </div>
        <div v-else class="editor-no-video"><AppIcon name="video" :size="28" /><p>添加配套视频，即可试听和校准时间。</p><button class="secondary mini" @click="openVideoFile">添加视频路径</button></div>
        <div class="editor-player-toolbar"><span>{{ currentTimeLabel }}<template v-if="durationLabel"> / {{ durationLabel }}</template></span><button class="secondary mini" type="button" :disabled="!videoReady" @click="addCueAtCurrentTime"><AppIcon name="plus" :size="14" />此刻新增字幕</button></div>
        <p v-if="videoError || previewError" class="status bad" role="alert">{{ videoError || previewError }}</p>
    <details class="editor-batch studio-disclosure">
      <summary class="section-title">
        <b>检查与批量清理</b>
        <span class="editor-check-count">{{ pairIssues.length ? `${pairIssues.length} 处符号待检查` : speakerCandidates.length ? `${speakerCandidates.length} 类说话者候选` : '未发现待检查项' }}</span>
      </summary>
      <div v-if="cues.length" class="mechanical-check-summary">
        <span class="badge done">实时机械检查</span>
        <b>{{ speakerCandidates.length }} 类说话者候选 · {{ pairIssues.length }} 处符号待检查</b>
        <span class="muted">字幕文字或结构变化后会自动重新计算，不调用大模型。</span>
      </div>
      <div class="toolbar editor-tools">
        <button class="secondary mini" :disabled="!cues.length" @click="$emit('strip-all-breaks')">全部去异常换行</button>
        <button class="secondary mini" :disabled="!cues.length" @click="$emit('strip-trailing-commas')">删除结尾逗号</button>
        <button class="ghost mini" :disabled="!cues.length" @click="$emit('remove-empty')">删除空字幕</button>
      </div>
      <div class="speaker-candidate-tool">
        <div class="speaker-candidate-head">
          <div>
            <b>说话者前缀候选</b>
            <span class="muted">Glossary 已确认人物会默认勾选；重复短标签只提示，不自动选。</span>
          </div>
          <button
            class="secondary mini"
            type="button"
            :disabled="!selectedSpeakerCandidateCount"
            @click="$emit('strip-speaker-candidates')"
          >去除已选（{{ selectedSpeakerCandidateCount }} 类）</button>
        </div>
        <div v-if="speakerCandidates.length" class="speaker-candidate-list">
          <label
            v-for="candidate in speakerCandidates"
            :key="candidate.id"
            class="speaker-candidate-item"
            :class="candidate.recommended ? 'recommended' : 'review'"
          >
            <input
              type="checkbox"
              :checked="selectedSpeakerCandidateIds.includes(candidate.id)"
              @change="$emit('toggle-speaker-candidate', { id: candidate.id, selected: $event.target.checked })"
            />
            <span>
              <b>{{ candidate.name }}</b>
              <small>{{ candidate.count }} 条 · {{ candidate.reason }}</small>
            </span>
            <em>{{ candidate.recommended ? '可安全去除' : '待确认' }}</em>
          </label>
        </div>
        <p v-else class="muted">没有发现符合安全规则的“说话者 + 冒号”前缀。</p>
      </div>
      <div>
        <label for="subtitlePrefixNames">手动补充名前缀（高级）</label>
        <div class="prefix-tool-row">
          <input
            id="subtitlePrefixNames"
            :value="prefixNames"
            placeholder="朴宝英, 禧主, 小昱"
            @input="$emit('update:prefixNames', $event.target.value)"
            @keydown.enter.prevent="$emit('strip-prefixes')"
          />
          <button class="secondary mini" :disabled="!cues.length || !prefixNames.trim()" @click="$emit('strip-prefixes')">删除名前缀</button>
        </div>
        <p class="muted">手动工具仍支持“名字 + 空格 / 冒号”；自动候选只处理更安全的“人物名 + 冒号”。</p>
      </div>

    <div v-if="pairIssues.length" class="pair-issue-panel">
      <div class="pair-issue-head">
        <div>
          <b>成对符号待检查</b>
          <span>{{ pairIssues.length }} 处，已自动随字幕更新</span>
        </div>
        <button
          v-if="pairAutoRepairCount"
          class="secondary mini"
          type="button"
          @click="$emit('repair-auto-pair-issues')"
        >修复明确错配（{{ pairAutoRepairCount }}）</button>
      </div>
      <div class="pair-issue-list">
        <article
          v-for="issue in pairIssues"
          :key="issue.issueId"
          class="pair-issue-item"
          :class="{ active: focusedCueUid === issue.uid }"
        >
          <div>
            <b>#{{ issue.cueNumber }} · {{ issue.start_time || '--' }} → {{ issue.end_time || '--' }}</b>
            <span>{{ pairIssueLabel(issue) }}</span>
            <p>{{ issue.text }}</p>
          </div>
          <div class="pair-issue-actions">
            <button class="secondary mini" type="button" @click="$emit('focus-pair-issue', issue.uid)">定位</button>
            <button
              v-if="issue.suggestionAvailable"
              class="ghost mini"
              type="button"
              @click="$emit('repair-pair-issue', issue)"
            >{{ pairRepairActionLabel(issue) }}</button>
            <button v-if="issue.missingSymbol" class="ghost mini" type="button" @click="$emit('copy-pair-symbol', issue.missingSymbol)">复制 {{ issue.missingSymbol }}</button>
          </div>
        </article>
      </div>
    </div>

    </details>

      </aside>
      <div class="editor-cues-column">
        <div class="editor-list-toolbar"><label class="studio-search"><AppIcon name="search" :size="17" /><input v-model="cueQuery" type="search" aria-label="查找字幕" placeholder="查找文字、编号或时间" /></label><div class="toolbar"><button class="icon-button" type="button" aria-label="上一条字幕" :disabled="activeCueIndex <= 0" @click="selectAdjacent(-1)">↑</button><button class="icon-button" type="button" aria-label="下一条字幕" :disabled="activeCueIndex < 0 || activeCueIndex >= cues.length - 1" @click="selectAdjacent(1)">↓</button></div></div>
        <div v-if="!visibleCues.length" class="studio-empty"><p>没有匹配的字幕</p><button class="secondary mini" @click="cueQuery = ''">清除搜索</button></div>
        <div class="subtitle-edit-list">
          <article v-for="{ cue, index } in visibleCues" :key="cue.uid" class="subtitle-edit-item" :class="{ selected: activeCueUid === cue.uid, focused: focusedCueUid === cue.uid, playing: previewCueUid === cue.uid }" :data-subtitle-cue="cue.uid">
            <button class="cue-summary" type="button" :aria-expanded="activeCueUid === cue.uid" :aria-label="`选择第 ${index + 1} 条字幕`" @click="activeCueUid = cue.uid"><span class="cue-number">{{ index + 1 }}</span><span class="cue-summary-copy"><span class="cue-summary-text">{{ cue.text || '（空字幕，待填写）' }}</span><span v-if="activeCueUid !== cue.uid" class="cue-summary-time">{{ cue.start_time }} — {{ cue.end_time }}</span><span v-else class="cue-summary-time">正在编辑</span></span><AppIcon name="chevron" :size="15" /></button>
            <div v-if="activeCueUid === cue.uid" class="cue-editor">
              <label class="sr-only" :for="`cue-text-${cue.uid}`">第 {{ index + 1 }} 条字幕文字</label>
              <textarea :id="`cue-text-${cue.uid}`" rows="3" :data-subtitle-textarea="cue.uid" :value="cue.text" @focus="$emit('begin-cue-edit', { uid: cue.uid, field: 'text' })" @input="$emit('update-cue', { uid: cue.uid, patch: { text: $event.target.value } })" @blur="$emit('end-cue-edit', { uid: cue.uid, field: 'text' })" />
              <div class="cue-main-controls"><button class="mini subtitle-play-button" type="button" :disabled="!videoReady" @click="playCue(cue)"><AppIcon name="play" :size="13" />{{ previewCueUid === cue.uid ? '重新播放' : '播放本条' }}</button><button class="secondary mini" @click="$emit('insert-cue', cue.uid, 'after')"><AppIcon name="plus" :size="13" />后面新增</button><span class="cue-edit-hint">修改后需保存</span></div>
              <div class="cue-time-fields"><label>开始<input :value="cue.start_time" :aria-label="`第 ${index + 1} 条开始时间`" @focus="$emit('begin-cue-edit', { uid: cue.uid, field: 'start_time' })" @input="$emit('update-cue', { uid: cue.uid, patch: { start_time: $event.target.value } })" @blur="$emit('end-cue-edit', { uid: cue.uid, field: 'start_time' })" /></label><span>→</span><label>结束<input :value="cue.end_time" :aria-label="`第 ${index + 1} 条结束时间`" @focus="$emit('begin-cue-edit', { uid: cue.uid, field: 'end_time' })" @input="$emit('update-cue', { uid: cue.uid, patch: { end_time: $event.target.value } })" @blur="$emit('end-cue-edit', { uid: cue.uid, field: 'end_time' })" /></label></div>
              <details class="cue-timing-tools"><summary>精调时间与更多操作</summary><div class="cue-nudge-row"><span>开始</span><button class="secondary mini" aria-label="开始时间提前 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'start', -0.1)">−0.1s</button><button class="secondary mini" aria-label="开始时间延后 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'start', 0.1)">＋0.1s</button><button class="ghost mini" :disabled="!videoReady" @click="setCueBoundary(cue.uid, 'start')">用当前时间</button><button class="ghost mini" :disabled="index === 0" @click="$emit('snap-cue', cue.uid, 'start', 'prev')">接上条</button></div><div class="cue-nudge-row"><span>结束</span><button class="secondary mini" aria-label="结束时间提前 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'end', -0.1)">−0.1s</button><button class="secondary mini" aria-label="结束时间延后 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'end', 0.1)">＋0.1s</button><button class="ghost mini" :disabled="!videoReady" @click="setCueBoundary(cue.uid, 'end')">用当前时间</button><button class="ghost mini" :disabled="index === cues.length - 1" @click="$emit('snap-cue', cue.uid, 'end', 'next')">接下条</button></div><div class="toolbar cue-structure-actions"><button class="secondary mini" @click="$emit('insert-cue', cue.uid, 'before')">前面新增</button><button class="ghost mini" :disabled="index === 0" @click="$emit('merge-prev', cue.uid)">合并到上一条</button><button class="ghost mini" :disabled="index === cues.length - 1" @click="$emit('merge-next', cue.uid)">合并下一条</button><button class="ghost mini" @click="$emit('strip-breaks', cue.uid)">去除换行</button><button class="danger secondary mini" @click="$emit('delete-cue', cue.uid)">删除本条</button></div></details>
            </div>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { buildSubtitleCuePreview, formatSrtTime, getSubtitlePreviewState } from '../subtitleEditorTools.js'
import AppIcon from './AppIcon.vue'
import { fileLabel, visibleSubtitleRows } from '../studioTools.js'

const props = defineProps({
  subtitlePath: { type: String, default: '' },
  videoPath: { type: String, default: '' },
  cues: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  dirty: { type: Boolean, default: false },
  saveReady: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  prefixNames: { type: String, default: '' },
  speakerCandidates: { type: Array, default: () => [] },
  selectedSpeakerCandidateIds: { type: Array, default: () => [] },
  canUndo: { type: Boolean, default: false },
  undoCount: { type: Number, default: 0 },
  pairIssues: { type: Array, default: () => [] },
  focusedCueUid: { type: String, default: '' },
})

const emit = defineEmits([
  'update:subtitlePath',
  'update:videoPath',
  'update:prefixNames',
  'toggle-speaker-candidate',
  'strip-speaker-candidates',
  'load-subtitle',
  'save-subtitle',
  'save-subtitle-as',
  'begin-cue-edit',
  'end-cue-edit',
  'update-cue',
  'delete-cue',
  'merge-prev',
  'merge-next',
  'strip-breaks',
  'strip-all-breaks',
  'strip-trailing-commas',
  'focus-pair-issue',
  'copy-pair-symbol',
  'repair-pair-issue',
  'repair-auto-pair-issues',
  'remove-empty',
  'strip-prefixes',
  'undo',
  'add-cue-at-time',
  'insert-cue',
  'set-cue-boundary',
  'nudge-cue',
  'snap-cue',
  'open-assets',
])

const activeCueUid = ref(props.cues[0]?.uid || '')
const cueQuery = ref('')
const matchingUids = ref(new Set())
const activeCueIndex = computed(() => props.cues.findIndex(cue => cue.uid === activeCueUid.value))
// Keep search membership stable while the user types in an editor, so an edit
// cannot remove its own focused textarea from the page.
watch([cueQuery, () => props.cues.map(cue => cue.uid).join('|')], () => {
  matchingUids.value = new Set(visibleSubtitleRows(props.cues, cueQuery.value).map(row => row.cue.uid))
}, { immediate: true })
const visibleCues = computed(() => props.cues.map((cue, index) => ({ cue, index })).filter(row => matchingUids.value.has(row.cue.uid)))
watch(() => props.cues, (cues, previous = []) => {
  if (!cues.some(cue => cue.uid === activeCueUid.value)) {
    const previousIndex = previous.findIndex(cue => cue.uid === activeCueUid.value)
    activeCueUid.value = cues[Math.max(0, Math.min(previousIndex, cues.length - 1))]?.uid || ''
  }
})
watch(() => props.focusedCueUid, uid => {
  if (!uid || !props.cues.some(cue => cue.uid === uid)) return
  if (!matchingUids.value.has(uid)) cueQuery.value = ''
  activeCueUid.value = uid
}, { immediate: true })
async function selectAdjacent(delta) {
  const cue = props.cues[activeCueIndex.value + delta]
  if (!cue) return
  if (!matchingUids.value.has(cue.uid)) cueQuery.value = ''
  activeCueUid.value = cue.uid
  await nextTick()
  document.querySelector(`[data-subtitle-cue="${CSS.escape(cue.uid)}"]`)?.scrollIntoView({ block: 'nearest' })
}
async function openVideoFile() {
  const input = document.getElementById('subtitleEditorVideoPath')
  input?.closest('details')?.setAttribute('open', '')
  await nextTick()
  input?.focus()
}
async function revealCue(uid) {
  if (!props.cues.some(cue => cue.uid === uid)) return
  if (!matchingUids.value.has(uid)) cueQuery.value = ''
  activeCueUid.value = uid
  await nextTick()
}
defineExpose({ revealCue })

const videoRef = ref(null)
const currentTime = ref(0)
const videoDuration = ref(0)
const videoReady = ref(false)
const videoError = ref('')
const previewCueUid = ref('')
const previewWindow = ref(null)
const previewError = ref('')
let previewPlayToken = 0

const videoUrl = computed(() => {
  const path = String(props.videoPath || '').trim()
  return path ? `/api/file?path=${encodeURIComponent(path)}` : ''
})
const selectedSpeakerCandidateCount = computed(() => props.selectedSpeakerCandidateIds.length)
const pairAutoRepairCount = computed(() => props.pairIssues.filter((issue) => issue.autoRepairable).length)

function pairIssueLabel(issue) {
  if (issue.type === 'mismatched_close') {
    return `全/半角错配：${issue.actualSymbol} 应为 ${issue.replacementSymbol} · ${issue.pairName}`
  }
  if (issue.type === 'distant_pair') {
    return `配对跨度异常：#${issue.relatedCueNumber} → #${issue.cueNumber}，跨 ${issue.cueSpan} 条 · ${issue.pairName}`
  }
  if (issue.type === 'crossed_pair') return `符号嵌套顺序交叉 · ${issue.pairName}`
  if (issue.type === 'missing_close') return `缺右符号：${issue.missingSymbol} · ${issue.pairName}`
  return `缺左符号：${issue.missingSymbol} · ${issue.pairName}`
}

function pairRepairActionLabel(issue) {
  if (issue.type === 'mismatched_close') return `替换为 ${issue.replacementSymbol}`
  if (issue.type === 'missing_close') return `补到本条末尾 ${issue.missingSymbol}`
  return `补到本条开头 ${issue.missingSymbol}`
}
const currentTimeLabel = computed(() => formatSrtTime(currentTime.value))
const durationLabel = computed(() => videoDuration.value > 0 ? formatSrtTime(videoDuration.value) : '')
const previewCue = computed(() => props.cues.find((cue) => cue.uid === previewCueUid.value) || null)
const previewSubtitleVisible = computed(() => (
  Boolean(previewWindow.value)
  && Boolean(previewCue.value)
  && Boolean(String(previewCue.value?.text || '').trim())
  && getSubtitlePreviewState(previewWindow.value, currentTime.value).active
))

watch(() => props.videoPath, () => resetVideoState({ pause: true }))
watch(previewCue, (cue) => {
  if (!cue && previewCueUid.value) clearCuePreview()
})

onBeforeUnmount(() => clearCuePreview({ pause: true }))

function resetVideoState({ pause = false } = {}) {
  clearCuePreview({ pause })
  currentTime.value = 0
  videoDuration.value = 0
  videoReady.value = false
  videoError.value = ''
  previewError.value = ''
}

function onVideoLoaded() {
  const player = videoRef.value
  if (!player) return
  const duration = Number(player.duration)
  videoDuration.value = Number.isFinite(duration) && duration > 0 ? duration : 0
  videoReady.value = true
  videoError.value = ''
  syncVideoTime()
}

function syncVideoTime() {
  const seconds = Number(videoRef.value?.currentTime)
  if (Number.isFinite(seconds) && seconds >= 0) currentTime.value = seconds
}

function onVideoTimeUpdate() {
  syncVideoTime()
  const preview = previewWindow.value
  if (!preview) return
  const seconds = currentTime.value
  if (seconds + 0.02 < preview.seekTime) {
    clearCuePreview()
    return
  }
  if (getSubtitlePreviewState(preview, seconds, { tolerance: 0.02 }).shouldStop) {
    const player = videoRef.value
    clearCuePreview({ pause: true })
    if (!player) return
    player.currentTime = preview.stopTime
    currentTime.value = preview.stopTime
  }
}

function onVideoSeeking() {
  syncVideoTime()
  const preview = previewWindow.value
  if (!preview) return
  if (currentTime.value < preview.seekTime || currentTime.value >= preview.stopTime) {
    clearCuePreview()
  }
}

function onVideoError() {
  clearCuePreview()
  videoReady.value = false
  previewError.value = ''
  videoError.value = '视频加载失败，请检查路径或视频格式。'
}

function playerTime() {
  syncVideoTime()
  return currentTime.value
}

function addCueAtCurrentTime() {
  emit('add-cue-at-time', playerTime())
}

function setCueBoundary(uid, boundary) {
  emit('set-cue-boundary', uid, boundary, playerTime())
}

function playCue(cue) {
  const player = videoRef.value
  if (!player || !videoReady.value) return
  let preview
  try {
    preview = buildSubtitleCuePreview(cue, { videoDuration: videoDuration.value })
  } catch (error) {
    clearCuePreview()
    previewError.value = error.message || '这条字幕的时间无效，无法播放。'
    return
  }
  previewPlayToken += 1
  const token = previewPlayToken
  previewError.value = ''
  previewCueUid.value = preview.cueUid
  previewWindow.value = preview
  player.pause()
  player.currentTime = preview.seekTime
  currentTime.value = preview.seekTime
  const playResult = player.play()
  if (playResult?.catch) {
    playResult.catch(() => {
      if (token !== previewPlayToken) return
      clearCuePreview()
      previewError.value = '浏览器未能开始播放，请点击视频后再试。'
    })
  }
}

function clearCuePreview({ pause = false } = {}) {
  previewPlayToken += 1
  if (pause) videoRef.value?.pause()
  previewCueUid.value = ''
  previewWindow.value = null
}
</script>
