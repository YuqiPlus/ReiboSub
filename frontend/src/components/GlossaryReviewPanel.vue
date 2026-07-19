<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Glossary 审核</h2>
        <p class="panel-subtitle">确认人名、昵称、作品名和固定术语，翻译时会严格使用这些译法。</p>
      </div>
      <span class="badge">{{ loading ? '加载中' : `${glossaryItems.length} 条` }}</span>
    </div>

    <div v-if="agentReview" class="agent-review-context">
      <b>这是 Agent 当前待办</b>
      <span>审核完成后点击保存，系统会自动返回 Agent 并继续翻译，不需要再手动确认一次。</span>
    </div>

    <div class="grid2">
      <div>
        <label for="glossaryPathReview">Glossary 路径</label>
        <input id="glossaryPathReview" :value="glossaryPath" :disabled="loading || continueBusy" placeholder="configs/glossaries/xxx.draft.yaml" @input="$emit('update:glossaryPath', $event.target.value)" />
      </div>
      <div class="field-actions">
        <label>操作</label>
        <div class="toolbar">
          <button class="secondary" :disabled="loading || continueBusy" @click="$emit('load-glossary')">{{ loading ? '加载中' : '加载' }}</button>
        </div>
      </div>
    </div>

    <div class="status" :class="statusClass">{{ status }}</div>
    <div class="glossary-save-state" :class="textDirty ? 'dirty' : saveState" role="status" aria-live="polite">
      <span aria-hidden="true"></span>
      <b>{{ textDirty ? 'YAML 有未保存修改' : saveStateLabel }}</b>
      <button v-if="saveState === 'error'" class="secondary mini" type="button" :disabled="continueBusy" @click="$emit('retry-glossary-save')">重试保存</button>
    </div>

    <div v-if="!loading && !reviewReady" class="empty">当前路径尚未成功加载。请点击“加载”后再编辑或保存，避免把另一份审核结果写错文件。</div>

    <div v-if="loading" class="empty loading-box">正在读取 glossary，并生成盲翻候选。完成后会一次性显示待确认列表。</div>

    <div v-if="!loading" class="review-summary">
      <button class="filter-chip" :class="{ active: filter === 'pending' }" @click="filter = 'pending'">
        待确认 <b>{{ pendingCount }}</b>
      </button>
      <button class="filter-chip" :class="{ active: filter === 'confirmed' }" @click="filter = 'confirmed'">
        已确认 <b>{{ confirmedCount }}</b>
      </button>
      <button class="filter-chip" :class="{ active: filter === 'all' }" @click="filter = 'all'">
        全部 <b>{{ glossaryItems.length }}</b>
      </button>
    </div>

    <div v-if="!loading" class="tabs">
      <button class="tab" :class="{ active: tab === 'review' }" :disabled="tab === 'yaml' && textDirty" @click="tab = 'review'">审核表</button>
      <button class="tab" :class="{ active: tab === 'yaml' }" :disabled="!reviewReady || ['dirty', 'saving', 'error'].includes(saveState)" @click="tab = 'yaml'">YAML</button>
    </div>

    <div v-if="!loading && tab === 'review'">
      <div class="toolbar review-toolbar">
        <button class="secondary" :disabled="continueBusy || !reviewReady" @click="$emit('apply-all-suggestions')">应用全部推荐</button>
        <button :disabled="continueBusy || !reviewReady || (agentReview && pendingCount > 0)" @click="$emit('save-glossary-review')">{{ primarySaveLabel }}</button>
      </div>
      <div v-if="!glossaryItems.length" class="empty">还没有加载 glossary。可以先到“字幕处理”生成草稿，或者在上方填路径后加载。</div>
      <div v-else-if="!visibleItems.length" class="empty">当前筛选下没有条目。</div>
      <div v-else class="review-list">
        <div v-for="{ item, index } in visibleItems" :key="`${item.section}-${item.index}`" class="review-item" :class="{ confirmed: item.reviewed }">
          <div class="review-head">
            <div>
              <div class="review-title">
                {{ item.source || '(空)' }}
                <span v-if="!item.suggested_zh && item.romanized" class="roman-hint">{{ item.romanized }}</span>
              </div>
              <div class="review-meta">
                {{ sectionLabel(item.section) }} · {{ item.type || '未分类' }}
                <span v-if="item.note"> · {{ item.note }}</span>
              </div>
              <div v-if="item.aliases?.length" class="review-meta">别名：{{ item.aliases.join(', ') }}</div>
            </div>
            <div class="review-badges">
              <span v-if="item.reviewed" class="badge done">已确认</span>
              <span v-else class="badge pending">待确认</span>
              <span v-if="item.always" class="badge core">强制</span>
            </div>
          </div>
          <div class="review-edit">
            <div>
              <label>中文译名</label>
              <input
                :ref="(el) => setReviewInputRef(el, index)"
                :value="item.zh"
                :disabled="continueBusy || !reviewReady"
                :placeholder="item.suggested_zh || item.romanized || '填写中文译名'"
                @input="$emit('update-glossary-zh', { index, zh: $event.target.value })"
                @compositionstart="isComposing = true"
                @compositionend="isComposing = false"
                @keydown.enter="handleReviewEnter($event, index)"
              />
            </div>
            <button class="secondary" :disabled="!item.suggested_zh || continueBusy || !reviewReady" @click="$emit('use-suggestion', index)">
              {{ item.suggested_zh ? `用推荐：${item.suggested_zh}` : '无推荐' }}
            </button>
            <button v-if="item.reviewed" class="secondary" :disabled="continueBusy || !reviewReady" @click="$emit('set-glossary-reviewed', { index, reviewed: false })">撤回</button>
            <button v-else :disabled="continueBusy || !reviewReady" @click="$emit('set-glossary-reviewed', { index, reviewed: true })">确认</button>
          </div>
          <div v-if="!item.suggested_zh && (item.context_text || item.english_reference_text || item.blind_candidate_zh)" class="context-box">
            <div v-if="item.context_text" class="context-line">
              <span>证据原句</span>
              <p><template v-for="(part, partIndex) in highlightParts(item.context_text, item.source)" :key="partIndex"><mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></p>
            </div>
            <div v-if="item.english_reference_text" class="context-line">
              <span>英文参考</span>
              <p><template v-for="(part, partIndex) in highlightParts(item.english_reference_text, item.source)" :key="partIndex"><mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></p>
            </div>
            <div v-if="item.blind_candidate_zh" class="context-line candidate-line">
              <span>盲翻候选</span>
              <p><template v-for="(part, partIndex) in highlightParts(item.blind_candidate_zh, item.zh || item.suggested_zh || item.source)" :key="partIndex"><mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></p>
              <button class="secondary mini" :disabled="continueBusy || !reviewReady" @click="$emit('update-glossary-zh', { index, zh: item.blind_candidate_zh })">填入候选</button>
            </div>
            <div v-else-if="item.blind_candidate_error" class="context-error">候选生成失败：{{ item.blind_candidate_error }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="!loading">
      <div class="toolbar review-toolbar">
        <button :disabled="continueBusy || !reviewReady" @click="$emit('save-glossary-text')">{{ continueBusy ? (agentReview ? '正在保存并继续...' : '正在保存...') : (agentReview ? '保存 YAML 并继续 Agent' : '保存 YAML') }}</button>
      </div>
      <textarea :value="glossaryEditor" :disabled="continueBusy || !reviewReady" placeholder="Glossary YAML 内容" @input="$emit('update:glossaryEditor', $event.target.value)" />
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { nextPendingReviewIndex, shouldConfirmReviewEnter } from '../glossaryReviewFocus.js'

const props = defineProps({
  glossaryPath: { type: String, default: '' },
  glossaryEditor: { type: String, default: '' },
  glossaryItems: { type: Array, default: () => [] },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  loading: { type: Boolean, default: false },
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
  'retry-glossary-save',
])

const tab = ref('review')
const filter = ref('pending')
const isComposing = ref(false)
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
  const sorted = [...indexedItems.value].sort((left, right) => {
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
  const nextIndex = nextPendingReviewIndex(props.glossaryItems, index)
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
