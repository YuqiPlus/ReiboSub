<template>
  <section class="issue-workbench" aria-label="处理字幕未确认项">
    <div class="toolbar">
      <b>字幕未确认项</b>
      <button v-if="session.status === 'done'" class="secondary mini" type="button" @click="expanded = !expanded">{{ expanded ? '收起处理面板' : '查看或处理未确认项' }}</button>
    </div>
    <template v-if="expanded">
      <p class="muted">BGM、听不清或不需要的条目，可以直接选择不翻译，不必填写译文。操作会另存版本，完整原文和旧字幕保留。</p>
      <p v-if="loading" role="status">正在读取原片位置和字幕…</p>
      <p v-if="error" role="alert">{{ error }}<button class="secondary mini" type="button" @click="load">重新加载</button></p>
      <template v-if="review">
        <nav class="issue-choices" aria-label="选择未确认字幕">
          <button v-for="row in review.issues" :key="row.cue_id" class="secondary" :class="{ selected: row.cue_id === selected }" :aria-pressed="row.cue_id === selected" :disabled="busy" type="button" @click="selected = row.cue_id">第 {{ row.cue_id }} 条 · {{ row.skipped ? '已跳过' : row.resolved ? '人工已处理' : '未确认' }}</button>
        </nav>
        <div v-if="active" class="issue-editor">
          <p><b>原识别：</b>{{ active.source }}</p>
          <p><b>{{ active.skipped ? '跳过前的译文（不会输出）：' : '当前译文：' }}</b>{{ active.translation }}</p>
          <details><summary>为什么需要处理</summary><p>{{ active.reason }}</p></details>
          <AgentQuestionMedia v-if="active.media" :question="active.media" />
          <p v-if="active.skipped" role="status">已选择不翻译：新的字幕输出中不显示原第 {{ active.cue_id }} 条。原文与旧版仍保留，可以恢复。</p>
          <div class="toolbar">
            <button type="button" :disabled="busy || loading || active.skipped" @click="submit('skip_translation')">{{ active.skipped ? '已选择不翻译' : '这条不翻译（输出中跳过）' }}</button>
            <button class="secondary" type="button" :disabled="busy || loading" @click="submit('set_translation', active.translation)">{{ active.skipped ? '恢复这条（使用上次译文）' : '确认保留当前译文' }}</button>
          </div>
          <details><summary>我能确定译文，手动填写</summary><div class="issue-editor">
            <label class="field"><span>指定这条的完整译文</span><textarea v-model="text" rows="3" maxlength="2000" :disabled="busy" aria-label="人工指定整条译文" /></label>
            <p v-if="active.preferred_translation && !active.resolved" class="muted">已预填你之前确认的译法；点击保存才会写入，不会自动采用。</p>
            <p class="muted">这是人工指定，不是机器已经核准原文。不会再以“风格偏好”为由退回。</p>
            <button type="button" :disabled="busy || loading || !text.trim()" @click="submit('set_translation', text)">{{ busy ? '正在保存…' : '保存这条（人工指定）' }}</button>
          </div></details>
        </div>
        <p v-for="(item, i) in review.unscoped_issues || []" :key="i">其他未决检查项：{{ item.reason_zh }}</p>
        <div class="toolbar issue-finish" v-if="session.status !== 'done'">
          <span>还有 {{ remainingCount }} 项未处理</span>
          <button class="secondary" type="button" :disabled="busy || loading" @click="submit('finish')">{{ remainingCount ? '保留未确认项并结束任务' : '结束并保存处理结果' }}</button>
        </div>
      </template>
      <p v-if="notice" role="status">{{ notice }}</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AgentQuestionMedia from './AgentQuestionMedia.vue'
const props = defineProps({ session: { type: Object, required: true } })
const emit = defineEmits(['updated'])
const expanded = ref(props.session.status !== 'done'), review = ref(null), selected = ref(props.session.question?.cue_id ?? null), text = ref('')
const busy = ref(false), loading = ref(false), error = ref(''), notice = ref('')
const active = computed(() => review.value?.issues.find(row => row.cue_id === selected.value))
const remainingCount = computed(() => (review.value?.remaining_ids.length || 0) + (review.value?.unscoped_issues?.length || 0))
let generation = 0, controller
watch(active, row => { text.value = row ? (row.resolved ? row.translation : row.preferred_translation || row.translation) : '' })
watch(() => [props.session.id, props.session.result?.translated_srt, expanded.value], (value, old) => {
  if (old && value[0] !== old[0]) { review.value = null; selected.value = props.session.question?.cue_id ?? null; notice.value = ''; text.value = '' }
  if (expanded.value) load()
  else { ++generation; controller?.abort(); loading.value = false }
}, { immediate: true })
onBeforeUnmount(() => { ++generation; controller?.abort() })
async function load() {
  controller?.abort(); controller = new AbortController(); const token = ++generation
  loading.value = true; error.value = ''
  try {
    const response = await fetch(`/api/agent/${encodeURIComponent(props.session.id)}/issue-review`, { signal: controller.signal })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || '未能读取字幕疑点')
    if (token !== generation) return
    review.value = result
    if (!result.issues.some(row => row.cue_id === selected.value)) selected.value = result.remaining_ids[0] ?? result.issues[0]?.cue_id ?? null
  } catch (e) { if (token === generation && e.name !== 'AbortError') error.value = e.message }
  finally { if (token === generation) loading.value = false }
}
async function submit(action, value) {
  if (busy.value || !review.value) return
  busy.value = true; error.value = ''; notice.value = ''
  const sid = props.session.id
  try {
    const response = await fetch(`/api/agent/${encodeURIComponent(sid)}/issue-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, cue_id: active.value?.cue_id, text: value,
        expected_translation_sha256: review.value.translation_sha256, expected_review_token: review.value.review_token }) })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || '未能保存处理结果')
    if (props.session.id !== sid) return
    review.value = result.review
    notice.value = action === 'finish' ? '任务已结束，字幕和处理记录已保存。' : action === 'skip_translation' ? '已在新输出中跳过这一条，原文和旧版保留，没有调用模型。' : '已按人工指定另存这一条，没有调用模型或重翻整片。'
    emit('updated', result.session)
  } catch (e) { if (props.session.id === sid) error.value = e.message }
  finally { busy.value = false }
}
</script>

<style scoped>
.issue-workbench { display: grid; gap: 12px; min-width: 0; }
.issue-workbench p { overflow-wrap: anywhere; margin: 0; }
.issue-choices { display: flex; flex-wrap: wrap; gap: 8px; }
.issue-choices .selected { border-color: #32765c; box-shadow: inset 0 0 0 1px #32765c; }
.issue-editor { display: grid; gap: 12px; min-width: 0; }
.issue-editor textarea { width: 100%; resize: vertical; box-sizing: border-box; font: inherit; }
.issue-finish { border-top: 1px solid #b9ccc2; padding-top: 14px; justify-content: space-between; flex-wrap: wrap; }
</style>
