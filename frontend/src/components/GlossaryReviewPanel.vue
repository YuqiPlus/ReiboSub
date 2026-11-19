<template>
  <section class="panel glossary-studio">
    <header class="studio-page-head">
      <div><span class="studio-kicker">术语审核</span><h2>一起确认这些名字</h2><p>听一听原声，结合语境，留下你认可的译名。</p></div>
      <div class="glossary-progress" aria-label="审核进度"><b>{{ confirmedCount }}<span> / {{ glossaryItems.length }}</span></b><span>已确认</span></div>
    </header>

    <div v-if="agentReview" class="review-agent-note"><AppIcon name="spark" :size="17" /><span>确认完成后，保存并返回 Agent 继续翻译。</span></div>

    <ReferenceTranslator ref="translator" :target-language="targetLanguage" />

    <details class="glossary-file-details studio-disclosure" :open="!reviewReady || loading">
      <summary>术语文件与高级编辑</summary>
      <div class="glossary-file-row"><label for="glossaryPathReview">术语文件<input id="glossaryPathReview" :value="glossaryPath" :disabled="loading || continueBusy" placeholder="选择或填写术语文件路径" @input="$emit('update:glossaryPath', $event.target.value)" /></label><button class="secondary" :disabled="loading || continueBusy" @click="$emit('load-glossary')">{{ loading ? '加载中…' : '加载文件' }}</button></div>
      <div class="toolbar"><button class="secondary mini" :disabled="!reviewReady || continueBusy || (tab === 'yaml' && textDirty) || ['dirty', 'saving', 'error'].includes(saveState)" @click="tab = tab === 'review' ? 'yaml' : 'review'">{{ tab === 'yaml' ? '返回审核列表' : '编辑 YAML' }}</button><button v-if="tab === 'review'" class="secondary mini" :disabled="continueBusy || !reviewReady" @click="$emit('apply-all-suggestions')">应用全部推荐</button></div>
    </details>

    <p v-if="status && (statusClass === 'bad' || !reviewReady)" class="status" :class="statusClass" role="status">{{ status }}</p>
    <div v-if="!loading && (['preparing', 'running'].includes(candidateStatus.state) || candidateStatus.failed)" class="studio-inline-notice" role="status">
      <span>{{ candidateStatus.failed ? '部分参考译文暂不可用，可以直接手动填写。' : '参考译文正在准备，不影响审核。' }}</span><button v-if="candidateStatus.failed && candidateStatus.state !== 'running'" class="secondary mini" :disabled="continueBusy" @click="$emit('retry-candidates')">重试</button>
    </div>
    <div v-if="loading" class="studio-empty" role="status">正在读取术语表…</div>
    <div v-else-if="!reviewReady" class="studio-empty"><AppIcon name="book" :size="30" /><h3>先打开一份术语表</h3><p>从 Agent 或任务历史进入，术语和原视频会自动关联。也可以在上方加载文件。</p></div>

    <template v-else-if="tab === 'review'">
      <div class="studio-filter-bar">
        <div class="studio-tabs" aria-label="术语筛选">
          <button v-for="option in reviewFilters" :key="option.id" type="button" :class="{ active: filter === option.id }" :aria-pressed="filter === option.id" @click="filter = option.id">{{ option.label }}<span v-if="option.id === 'pending'">{{ pendingCount }}</span></button>
        </div>
        <label class="studio-search"><AppIcon name="search" :size="17" /><input v-model="query" type="search" aria-label="搜索术语" placeholder="搜索名字或译名" /></label>
      </div>
      <div v-if="!glossaryItems.length" class="studio-empty"><h3>这份术语表是空的</h3><p>没有需要确认的条目。</p></div>
      <div v-else-if="!visibleItems.length" class="studio-empty"><AppIcon :name="query ? 'search' : 'check'" :size="28" /><h3>{{ query ? '没有匹配的术语' : filter === 'pending' ? '这一页已审核完成' : '没有对应条目' }}</h3><button v-if="query" class="secondary mini" @click="query = ''">清除搜索</button><button v-else-if="filter !== 'all'" class="secondary mini" @click="filter = 'all'">查看全部</button></div>
      <div v-else class="review-list">
        <article v-for="{ item, index } in visibleItems" :key="`${item.section}-${item.index}`" class="review-item" :class="{ confirmed: item.reviewed }">
          <header class="review-head">
            <div><div class="review-title">{{ item.source || '(空)' }}<span v-if="item.romanized" class="roman-hint">{{ item.romanized }}</span></div><span class="review-meta">{{ sectionLabel(item.section) }}<template v-if="item.always"> · 固定译法</template></span></div>
            <div class="term-head-actions"><span v-if="item.reviewed" class="term-confirmed"><AppIcon name="check" :size="14" />已确认</span><button class="secondary mini" type="button" :aria-expanded="activeEvidence === evidenceKey(item)" :disabled="continueBusy || !item.source" @click="activeEvidence = activeEvidence === evidenceKey(item) ? '' : evidenceKey(item)"><AppIcon name="play" :size="14" />{{ activeEvidence === evidenceKey(item) ? '收起片段' : '播放证据片段' }}</button></div>
          </header>
          <GlossaryEvidencePlayer v-if="activeEvidence === evidenceKey(item)" :key="activeEvidence" :path="glossaryPath" :item="item" @close="activeEvidence = ''" />
          <div class="term-review-body">
            <div class="term-context">
              <div v-if="item.context_text" class="term-quote"><span>原句</span><p><template v-for="(part, partIndex) in highlightParts(item.context_text, item.source)" :key="partIndex"><mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></p></div>
              <div v-if="item.blind_candidate_zh" class="term-reference"><span>参考译文 · 仅供理解语境</span><p>{{ item.blind_candidate_zh }}</p></div>
              <p v-else-if="item.blind_candidate_error" class="context-error">参考译文暂不可用</p>
              <p v-else-if="item.blind_candidate_pending" class="review-meta">参考译文准备中…</p>
              <p v-if="!item.context_text && !item.blind_candidate_zh" class="review-meta">可播放原片段来核对语境。</p>
              <button class="ghost mini" type="button" @click="translator?.setText(item.context_text || item.source)">放入翻译器</button>
              <details v-if="item.note || item.aliases?.length || item.english_reference_text || item.blind_candidate_zh" class="term-note-details"><summary>更多参考与识别说明</summary><p v-if="item.note">{{ item.note }}</p><p v-if="item.aliases?.length">别名：{{ item.aliases.join(', ') }}</p><p v-if="item.english_reference_text">英文参考：{{ item.english_reference_text }}</p><div v-if="item.blind_candidate_zh" class="term-full-reference"><p>下方操作会把整句参考填入译名，不会自动确认；人名通常只应填写名字。</p><button class="ghost mini" :disabled="continueBusy" @click="$emit('update-glossary-zh', { index, zh: item.blind_candidate_zh })">将整句填入译名</button></div></details>
            </div>
            <div class="term-answer">
              <label :for="`term-answer-${index}`">{{ targetLanguageLabel }}译名</label>
              <div class="term-answer-row"><input :id="`term-answer-${index}`" :ref="(el) => setReviewInputRef(el, index)" :value="item.zh" :disabled="continueBusy" :placeholder="item.suggested_zh || '填写译名或音译'" @input="$emit('update-glossary-zh', { index, zh: $event.target.value })" @compositionstart="isComposing = true" @compositionend="isComposing = false" @keydown.enter="handleReviewEnter($event, index)" /><button v-if="item.reviewed" class="secondary" :disabled="continueBusy" @click="$emit('set-glossary-reviewed', { index, reviewed: false })">撤回确认</button><button v-else :disabled="continueBusy" @click="$emit('set-glossary-reviewed', { index, reviewed: true })">确认</button></div>
              <button v-if="item.suggested_zh" class="term-suggestion" :disabled="continueBusy" @click="$emit('use-suggestion', index)">采用推荐：{{ item.suggested_zh }}</button>
            </div>
          </div>
        </article>
      </div>
    </template>
    <div v-else class="glossary-yaml-editor"><p class="muted">直接编辑文件内容。未保存时，请先保存 YAML 再切回审核列表。</p><textarea :value="glossaryEditor" :disabled="continueBusy" aria-label="Glossary YAML 内容" @input="$emit('update:glossaryEditor', $event.target.value)" /></div>

    <footer v-if="reviewReady && !loading" class="studio-save-bar">
      <div class="studio-save-copy" role="status" aria-live="polite"><span class="save-dot" :class="textDirty ? 'dirty' : saveState"></span><span>{{ textDirty ? 'YAML 有未保存修改' : saveStateLabel }}</span><button v-if="saveState === 'error'" class="secondary mini" :disabled="continueBusy" @click="$emit('retry-glossary-save')">重试保存</button></div>
      <span v-if="tab === 'review'" class="studio-key-hint">Enter 确认并跳到下一条</span>
      <button v-if="tab === 'review'" :disabled="continueBusy || (agentReview && pendingCount > 0)" @click="$emit('save-glossary-review')">{{ primarySaveLabel }}</button><button v-else :disabled="continueBusy" @click="$emit('save-glossary-text')">{{ continueBusy ? '正在保存…' : agentReview ? '保存 YAML 并继续 Agent' : '保存 YAML' }}</button>
    </footer>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { nextPendingReviewIndex, shouldConfirmReviewEnter } from '../glossaryReviewFocus.js'
import { evidenceKey } from '../glossaryEvidence.js'
import GlossaryEvidencePlayer from './GlossaryEvidencePlayer.vue'
import ReferenceTranslator from './ReferenceTranslator.vue'
import AppIcon from './AppIcon.vue'
import { targetLanguages } from '../translationLanguages.js'

const props = defineProps({
  targetLanguage: { type: String, default: 'zh' },
  glossaryPath: { type: String, default: '' },
  glossaryEditor: { type: String, default: '' },
  glossaryItems: { type: Array, default: () => [] },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  candidateStatus: { type: Object, default: () => ({ state: 'ready', failed: 0 }) },
  agentReview: { type: Boolean, default: false },
  reviewReady: { type: Boolean, default: false },
  saveState: { type: String, default: 'idle' },
  textDirty: { type: Boolean, default: false },
  continueBusy: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:glossaryPath', 'update:glossaryEditor', 'load-glossary',
  'apply-all-suggestions', 'save-glossary-review', 'save-glossary-text',
  'update-glossary-zh', 'set-glossary-reviewed', 'use-suggestion',
  'retry-glossary-save', 'retry-candidates',
])

const tab = ref('review')
const translator = ref(null)
const targetLanguageLabel = computed(() => targetLanguages.find((item) => item.id === props.targetLanguage)?.label || '目标语言')
const filter = ref('pending')
const query = ref('')
const reviewFilters = [{ id: 'pending', label: '待确认' }, { id: 'confirmed', label: '已确认' }, { id: 'all', label: '全部' }]
const isComposing = ref(false)
const activeEvidence = ref('')
watch(() => [props.glossaryPath, props.loading, filter.value, tab.value], () => { activeEvidence.value = '' })
const reviewInputRefs = new Map()

const indexedItems = computed(() => props.glossaryItems.map((item, index) => ({ item, index })))
const pendingCount = computed(() => props.glossaryItems.filter((item) => !item.reviewed).length)
const confirmedCount = computed(() => props.glossaryItems.length - pendingCount.value)
const primarySaveLabel = computed(() => {
  if (props.continueBusy) return props.agentReview ? '正在保存并继续...' : '正在保存...'
  if (props.agentReview && pendingCount.value > 0) return `还有 ${pendingCount.value} 条待确认`
  return props.agentReview ? '全部已确认，保存并开始翻译' : '保存审核结果'
})
const saveStateLabel = computed(() => ({
  idle: '审核表中的逐条修改会自动保存',
  dirty: '审核表有未保存修改',
  saving: '正在自动保存审核表进度…',
  saved: '审核表进度已保存',
  error: '审核表自动保存失败，修改仍保留在当前页面',
}[props.saveState] || '审核表中的逐条修改会自动保存'))
const visibleItems = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  const sorted = indexedItems.value.filter(({ item }) => !needle || [item.source, item.zh, item.romanized, ...(item.aliases || [])].some(value => String(value || '').toLocaleLowerCase().includes(needle))).sort((left, right) => {
    const leftDone = left.item.reviewed ? 1 : 0
    const rightDone = right.item.reviewed ? 1 : 0
    return leftDone - rightDone
  })
  if (filter.value === 'pending') {
    return sorted.filter(({ item }) => !item.reviewed)
  }
  if (filter.value === 'confirmed') {
    return sorted.filter(({ item }) => item.reviewed)
  }
  return sorted
})

function sectionLabel(section) {
  if (section === 'program') return '节目'
  if (section === 'characters') return '人物'
  if (section === 'terms') return '术语'
  return section || '未知'
}

function setReviewInputRef(el, index) {
  if (el) {
    reviewInputRefs.set(index, el)
  } else {
    reviewInputRefs.delete(index)
  }
}

async function confirmAndFocusNext(index) {
  const visible = new Set(visibleItems.value.map(row => row.index))
  const nextIndex = nextPendingReviewIndex(props.glossaryItems.map((item, i) => ({ ...item, reviewed: item.reviewed || !visible.has(i) })), index)
  emit('set-glossary-reviewed', { index, reviewed: true })
  if (nextIndex === -1) return
  await nextTick()
  reviewInputRefs.get(nextIndex)?.focus()
}

function handleReviewEnter(event, index) {
  if (!shouldConfirmReviewEnter(event, isComposing.value)) return
  event.preventDefault()
  confirmAndFocusNext(index)
}

function highlightParts(text, keyword) {
  const source = String(text || '')
  const key = String(keyword || '').trim()
  if (!source || !key) return [{ text: source, hit: false }]
  const lowerSource = source.toLowerCase()
  const lowerKey = key.toLowerCase()
  const parts = []
  let cursor = 0
  while (cursor < source.length) {
    const index = lowerSource.indexOf(lowerKey, cursor)
    if (index < 0) {
      parts.push({ text: source.slice(cursor), hit: false })
      break
    }
    if (index > cursor) {
      parts.push({ text: source.slice(cursor, index), hit: false })
    }
    parts.push({ text: source.slice(index, index + key.length), hit: true })
    cursor = index + key.length
  }
  return parts.length ? parts : [{ text: source, hit: false }]
}
</script>
