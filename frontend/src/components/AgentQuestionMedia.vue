<template>
  <section v-if="question.video_path || question.audio_path" class="question-media" aria-label="疑点原片与原音">
    <template v-if="question.video_path">
      <div class="toolbar question-media-actions">
        <button type="button" @click="playSegment">{{ played ? '重播疑点片段' : '播放疑点片段' }}</button>
        <span v-if="window" class="muted">{{ mediaClock(window.start) }}<template v-if="window.end != null">–{{ mediaClock(window.end) }}</template></span>
        <a :href="videoSrc" target="_blank" rel="noopener noreferrer">单独打开原片</a>
      </div>
      <video ref="video" :key="videoSrc" class="library-media-preview question-media-video" controls playsinline preload="auto"
        :src="videoSrc" aria-label="疑句原画面" @loadedmetadata="seekStart" @error="mediaFailed"
        @waiting="buffering = true" @canplay="buffering = false" @playing="buffering = false; played = true"
        @timeupdate="stopAtEnd" />
      <p v-if="error" class="question-media-error" role="alert">{{ error }}可重试，或点击“单独打开原片”；也可以听下方原音。</p>
      <p v-else-if="buffering" class="muted" role="status">原片缓冲中；加载较慢时可单独打开原片。</p>
    </template>
    <div v-if="question.audio_path" class="question-media-audio">
      <span>只听这一段原音</span>
      <audio :key="question.audio_path" controls preload="metadata" :src="questionMediaUrl(question.audio_path)" aria-label="疑句原音" />
      <a :href="questionMediaUrl(question.audio_path)" target="_blank" rel="noopener noreferrer">单独打开原音</a>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { mediaClock, questionMediaUrl, questionMediaWindow } from '../questionMedia.js'

const props = defineProps({ question: { type: Object, default: () => ({}) } })
const video = ref(null)
const played = ref(false)
const buffering = ref(false)
const error = ref('')
const window = computed(() => questionMediaWindow(props.question))
const videoSrc = computed(() => questionMediaUrl(props.question.video_path, window.value))
watch(videoSrc, () => { played.value = false; buffering.value = false; error.value = '' })

function seekStart() {
  if (video.value && window.value) video.value.currentTime = window.value.start
}

function stopAtEnd() {
  if (video.value && window.value?.end != null && video.value.currentTime >= window.value.end) video.value.pause()
}

function mediaFailed() {
  buffering.value = false
  error.value = '当前浏览器未能播放此视频。'
}

function playSegment() {
  const player = video.value
  if (!player) return
  error.value = ''
  buffering.value = true
  if (player.error) player.load()
  try {
    if (player.readyState >= 1) seekStart()
    // Call play within the click, so mobile browsers retain the user gesture.
    const pending = player.play()
    pending?.catch(() => { if (video.value === player) mediaFailed() })
  } catch {
    mediaFailed()
  }
}
</script>

<style scoped>
.question-media { min-width: 0; display: grid; gap: 10px; }
.question-media-actions { flex-wrap: wrap; gap: 12px; }
.question-media a { font-size: 13px; text-decoration: underline; text-underline-offset: 3px; }
.question-media-video { margin-bottom: 0; max-height: 360px; aspect-ratio: 16 / 9; object-fit: contain; }
.question-media-audio { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.question-media-audio audio { max-width: 100%; }
.question-media-error { color: #8a3d21; font-size: 13px; }
</style>
