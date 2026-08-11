<template>
  <section class="panel subtitle-editor">
    <div class="panel-head">
      <div>
        <h2>字幕精修</h2>
        <p class="panel-subtitle">修改文字、删除条目、合并碎片，保存为新的 edited.srt 或覆盖原字幕。</p>
      </div>
      <span class="badge" :class="dirty ? 'pending' : 'done'">{{ dirty ? '未保存' : '已同步' }}</span>
    </div>

    <div class="prefix-tool">
      <div class="section-title">
        <h3>字幕文件与保存</h3>
        <span class="muted">{{ cues.length }} 条字幕</span>
      </div>
      <div class="path-row subtitle-editor-path-row">
        <div>
          <label for="subtitleEditorPath">字幕文件</label>
          <input
            id="subtitleEditorPath"
            :value="subtitlePath"
            placeholder="YoutubeDownloads/example/example.zh.srt"
            @input="$emit('update:subtitlePath', $event.target.value)"
            @keydown.enter.prevent="$emit('load-subtitle')"
          />
        </div>
        <div class="toolbar editor-toolbar">
          <button class="secondary" :disabled="loading" @click="$emit('load-subtitle')">加载</button>
          <button
            class="secondary subtitle-undo-button"
            type="button"
            :disabled="loading || !canUndo"
            title="撤回最近一次文字、时间或结构修改"
            @click="$emit('undo')"
          >↶ 撤回上一步<template v-if="undoCount">（{{ undoCount }}）</template></button>
          <button class="warning" :disabled="loading || !saveReady || !cues.length" @click="$emit('save-subtitle')">覆盖保存</button>
          <button :disabled="loading || !saveReady || !cues.length" @click="$emit('save-subtitle-as')">另存 edited</button>
        </div>
      </div>
    </div>

    <div class="prefix-tool">
      <div class="section-title">
        <h3>视频定位</h3>
        <span class="badge" :class="videoReady ? 'done' : 'pending'">{{ videoReady ? '可以定位' : '等待视频' }}</span>
      </div>
      <div class="path-row subtitle-editor-path-row">
        <div>
          <label for="subtitleEditorVideoPath">配套视频</label>
          <input
            id="subtitleEditorVideoPath"
            :value="videoPath"
            placeholder="选择或填写与字幕对应的视频路径"
            @input="$emit('update:videoPath', $event.target.value)"
          />
        </div>
        <div class="toolbar editor-toolbar">
          <button class="warning" type="button" :disabled="!videoReady" @click="addCueAtCurrentTime">当前时间新增</button>
          <span class="muted">当前 {{ currentTimeLabel }}<template v-if="durationLabel"> / {{ durationLabel }}</template></span>
        </div>
      </div>
      <div v-if="videoUrl" class="subtitle-video-stage">
        <video
          :key="videoUrl"
          ref="videoRef"
          :src="videoUrl"
          controls
          playsinline
          preload="metadata"
          @loadedmetadata="onVideoLoaded"
          @durationchange="onVideoLoaded"
          @timeupdate="onVideoTimeUpdate"
          @seeking="onVideoSeeking"
          @seeked="onVideoTimeUpdate"
          @emptied="resetVideoState"
          @error="onVideoError"
        ></video>
        <div v-if="previewSubtitleVisible" class="subtitle-video-overlay" aria-live="polite">
          <span>{{ previewCue?.text }}</span>
        </div>
      </div>
      <p v-else class="muted">填写配套视频后，可以边播放边新增字幕并用当前时间校准起止点。</p>
      <div v-if="videoError" class="status bad">{{ videoError }}</div>
      <div v-if="previewError" class="status bad">{{ previewError }}</div>
    </div>

    <details class="prefix-tool" :open="Boolean(speakerCandidates.length || pairIssues.length)">
      <summary class="section-title">
        <b>批量工具</b>
        <span class="muted">加载即自动检查说话者和成对符号</span>
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
    </details>

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

    <div v-if="!cues.length" class="asset-list empty">还没有加载字幕。</div>
    <div v-else class="subtitle-edit-list">
      <article
        v-for="(cue, index) in cues"
        :key="cue.uid"
        class="subtitle-edit-item"
        :class="{ focused: focusedCueUid === cue.uid, playing: previewCueUid === cue.uid }"
        :data-subtitle-cue="cue.uid"
      >
        <div class="subtitle-edit-index">
          <b>{{ index + 1 }}</b>
          <span>{{ cue.start_time }} → {{ cue.end_time }}</span>
        </div>
        <div class="subtitle-edit-fields">
          <div class="time-grid">
            <div>
              <label>开始</label>
              <input
                :value="cue.start_time"
                @focus="$emit('begin-cue-edit', { uid: cue.uid, field: 'start_time' })"
                @input="$emit('update-cue', { uid: cue.uid, patch: { start_time: $event.target.value } })"
                @blur="$emit('end-cue-edit', { uid: cue.uid, field: 'start_time' })"
              />
              <div class="toolbar">
                <button class="ghost mini" type="button" aria-label="开始时间提前 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'start', -0.1)">−0.1s</button>
                <button class="ghost mini" type="button" aria-label="开始时间延后 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'start', 0.1)">＋0.1s</button>
                <button class="secondary mini" type="button" :disabled="!videoReady" @click="setCueBoundary(cue.uid, 'start')">当前=开始</button>
                <button class="ghost mini" type="button" :disabled="index === 0" @click="$emit('snap-cue', cue.uid, 'start', 'prev')">接上条</button>
              </div>
            </div>
            <div>
              <label>结束</label>
              <input
                :value="cue.end_time"
                @focus="$emit('begin-cue-edit', { uid: cue.uid, field: 'end_time' })"
                @input="$emit('update-cue', { uid: cue.uid, patch: { end_time: $event.target.value } })"
                @blur="$emit('end-cue-edit', { uid: cue.uid, field: 'end_time' })"
              />
              <div class="toolbar">
                <button class="ghost mini" type="button" aria-label="结束时间提前 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'end', -0.1)">−0.1s</button>
                <button class="ghost mini" type="button" aria-label="结束时间延后 0.1 秒" @click="$emit('nudge-cue', cue.uid, 'end', 0.1)">＋0.1s</button>
                <button class="secondary mini" type="button" :disabled="!videoReady" @click="setCueBoundary(cue.uid, 'end')">当前=结束</button>
                <button class="ghost mini" type="button" :disabled="index === cues.length - 1" @click="$emit('snap-cue', cue.uid, 'end', 'next')">接下条</button>
              </div>
            </div>
          </div>
          <textarea
            rows="3"
            :data-subtitle-textarea="cue.uid"
            :value="cue.text"
            @focus="$emit('begin-cue-edit', { uid: cue.uid, field: 'text' })"
            @input="$emit('update-cue', { uid: cue.uid, patch: { text: $event.target.value } })"
            @blur="$emit('end-cue-edit', { uid: cue.uid, field: 'text' })"
          />
        </div>
        <div class="subtitle-edit-actions">
          <button class="secondary mini" type="button" @click="$emit('insert-cue', cue.uid, 'before')">前插</button>
          <button class="secondary mini" type="button" @click="$emit('insert-cue', cue.uid, 'after')">后插</button>
          <button
            class="warning mini subtitle-play-button"
            type="button"
            :disabled="!videoReady"
            :title="videoReady ? '从本条开始播放，到结束时间自动暂停并显示字幕' : '先加载配套视频'"
            @click="playCue(cue)"
          >{{ previewCueUid === cue.uid ? '重新播放' : '播放本条' }}</button>
          <button class="ghost mini" :disabled="index === 0" @click="$emit('merge-prev', cue.uid)">并上</button>
          <button class="ghost mini" :disabled="index === cues.length - 1" @click="$emit('merge-next', cue.uid)">并下</button>
          <button class="secondary mini" @click="$emit('strip-breaks', cue.uid)">去换行</button>
          <button class="danger secondary mini" @click="$emit('delete-cue', cue.uid)">删除</button>
        </div>
      </article>
    </div>

    <div class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { buildSubtitleCuePreview, formatSrtTime, getSubtitlePreviewState } from '../subtitleEditorTools.js'

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
])

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
