<template>
  <section class="reference-translator" aria-label="随手翻译">
    <header class="reference-translator-head"><div><h3><AppIcon name="language" :size="17" />随手翻译</h3><span>仅供参考，不会改动术语表 · 使用已配置的翻译模型</span></div><button type="button" class="ghost mini" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起' : '展开' }}</button></header>
    <form v-if="expanded" @submit.prevent="translate">
      <div class="reference-translator-grid">
        <div class="reference-translator-pane">
          <label>原文语言<select v-model="source" aria-label="翻译器原文语言"><option value="auto">自动识别</option><option v-for="language in targetLanguages" :key="language.id" :value="language.id">{{ language.label }}</option></select></label>
          <textarea ref="input" v-model="text" aria-label="翻译器原文" placeholder="输入文字，或从下方术语放入原句" maxlength="4000" @keydown.ctrl.enter.prevent="translate" @keydown.meta.enter.prevent="translate" />
          <span class="reference-translator-count">{{ text.length }} / 4000</span>
        </div>
        <button class="secondary reference-translator-swap" type="button" aria-label="交换翻译语言与文本" :disabled="source === 'auto' || busy" @click="swap">⇄</button>
        <div class="reference-translator-pane">
          <label>译文语言<select v-model="target" aria-label="翻译器译文语言"><option v-for="language in targetLanguages" :key="language.id" :value="language.id">{{ language.label }}</option></select></label>
          <textarea :value="translation" readonly aria-label="翻译器译文" :aria-busy="busy" :placeholder="busy ? '正在翻译…' : '译文会显示在这里'" />
          <span class="reference-translator-count">{{ translation && stale ? '输入或语种已更改，请重新翻译' : '' }}</span>
        </div>
      </div>
      <footer class="reference-translator-actions"><span role="status" :class="{ 'context-error': error }">{{ error || copyStatus }}</span><button type="button" class="ghost mini" :disabled="!text && !translation" @click="clear">清空</button><button type="button" class="secondary mini" :disabled="!translation || busy || stale" @click="copy">复制译文</button><button class="mini" type="submit" :disabled="!text.trim() || busy">{{ busy ? '正在翻译…' : '翻译' }}</button></footer>
    </form>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { targetLanguages } from '../translationLanguages.js'
import { copyText } from '../clipboard.js'
import AppIcon from './AppIcon.vue'

const props = defineProps({ targetLanguage: { type: String, default: 'zh' } })
const source = ref('auto'), target = ref(props.targetLanguage), text = ref(''), translation = ref('')
const expanded = ref(true), busy = ref(false), error = ref(''), copyStatus = ref(''), input = ref(null)
const resultKey = ref('')
const requestKey = computed(() => JSON.stringify([source.value, target.value, text.value]))
const stale = computed(() => resultKey.value !== requestKey.value)
let controller, generation = 0
function cancel() { ++generation; controller?.abort(); busy.value = false }
watch(requestKey, () => { cancel(); error.value = ''; copyStatus.value = '' }, { flush: 'sync' })
watch(() => props.targetLanguage, value => { target.value = value })
onBeforeUnmount(cancel)

async function translate() {
  if (!text.value.trim() || busy.value) return
  cancel(); controller = new AbortController()
  const requestController = controller
  const token = generation, key = requestKey.value
  busy.value = true; error.value = ''; copyStatus.value = ''; translation.value = ''
  const timeout = setTimeout(() => requestController.abort(), 50000)
  try {
    const response = await fetch('/api/translate-text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: requestController.signal,
      body: JSON.stringify({ text: text.value, source_language: source.value, target_language: target.value }) })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || '翻译失败，请重试')
    if (typeof result.translation !== 'string' || !result.translation.trim()) throw new Error('翻译结果为空，请重试')
    if (token === generation && key === requestKey.value) { translation.value = result.translation; resultKey.value = key }
  } catch (e) {
    if (token === generation) error.value = e.name === 'AbortError' ? '翻译超时，请重试' : e.message || '翻译失败，请重试'
  } finally {
    clearTimeout(timeout)
    if (token === generation) busy.value = false
  }
}
function clear() { cancel(); text.value = ''; translation.value = ''; resultKey.value = ''; error.value = ''; copyStatus.value = '' }
function swap() {
  if (source.value === 'auto' || busy.value) return
  const oldSource = source.value, oldText = text.value
  const usable = !!translation.value && !stale.value
  source.value = target.value; target.value = oldSource
  text.value = usable ? translation.value : oldText
  translation.value = ''; resultKey.value = ''
}
async function copy() {
  const key = requestKey.value
  const ok = await copyText(translation.value)
  if (key === requestKey.value) copyStatus.value = ok ? '已复制译文' : '复制失败，请手动选择译文'
}
async function setText(value) {
  clear(); source.value = 'auto'; text.value = String(value || '').slice(0, 4000); expanded.value = true
  await nextTick(); input.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }); input.value?.focus({ preventScroll: true })
}
defineExpose({ setText })
</script>

<style scoped>
.reference-translator { border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; background: var(--surface); margin: 16px 0; }
.reference-translator-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.reference-translator-head h3 { display: flex; align-items: center; gap: 7px; margin: 0 0 3px; font-size: 14px; }
.reference-translator-head span { color: var(--muted); font-size: 12px; }
.reference-translator-grid { display: grid; grid-template-columns: minmax(0, 1fr) 34px minmax(0, 1fr); gap: 10px; margin-top: 14px; align-items: center; }
.reference-translator-pane { min-width: 0; }
.reference-translator-pane label { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; color: var(--muted); font-size: 12px; }
.reference-translator-pane select { width: auto; min-width: 110px; padding: 5px 25px 5px 10px; color: var(--ink); }
.reference-translator-pane textarea { width: 100%; min-height: 120px; resize: vertical; padding: 12px; box-sizing: border-box; font-size: 14px; line-height: 1.6; }
.reference-translator-pane textarea[readonly] { background: var(--soft); }
.reference-translator-swap { padding: 7px; font-size: 20px; }
.reference-translator-count { display: block; min-height: 18px; font-size: 11px; color: var(--muted); margin-top: 4px; }
.reference-translator-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-top: 8px; }
.reference-translator-actions > span { margin-right: auto; font-size: 12px; }
@media (max-width: 640px) { .reference-translator-grid { grid-template-columns: minmax(0, 1fr); gap: 6px; } .reference-translator-swap { justify-self: center; padding: 0 12px; } .reference-translator-head span { display: block; max-width: 240px; } }
</style>
