<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Glossary 审核</h2>
        <p class="panel-subtitle">确认人名、昵称、作品名和固定术语，翻译时会严格使用这些译法。</p>
      </div>
      <span class="badge">{{ loading ? '加载中' : `${glossaryItems.length} 条` }}</span>
    </div>

    <div class="grid2">
      <div>
        <label for="glossaryPathReview">Glossary 路径</label>
        <input id="glossaryPathReview" :value="glossaryPath" placeholder="configs/glossaries/xxx.draft.yaml" @input="$emit('update:glossaryPath', $event.target.value)" />
      </div>
      <div class="field-actions">
        <label>操作</label>
        <div class="toolbar">
          <button class="secondary" :disabled="loading" @click="$emit('load-glossary')">{{ loading ? '加载中' : '加载' }}</button>
          <button :disabled="loading" @click="$emit('save-glossary-review')">保存审核</button>
        </div>
      </div>
    </div>

    <div class="status" :class="statusClass">{{ status }}</div>

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
      <button class="tab" :class="{ active: tab === 'review' }" @click="tab = 'review'">审核表</button>
      <button class="tab" :class="{ active: tab === 'yaml' }" @click="tab = 'yaml'">YAML</button>
    </div>

    <div v-if="!loading && tab === 'review'">
      <div class="toolbar review-toolbar">
        <button class="secondary" @click="$emit('apply-all-suggestions')">应用全部推荐</button>
        <button @click="$emit('save-glossary-review')">保存审核结果</button>
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
                :placeholder="item.suggested_zh || item.romanized || '填写中文译名'"
                @input="$emit('update-glossary-zh', { index, zh: $event.target.value })"
                @compositionstart="isComposing = true"
                @compositionend="isComposing = false"
                @keydown.enter="handleReviewEnter($event, index)"
              />
            </div>
            <button class="secondary" :disabled="!item.suggested_zh" @click="$emit('use-suggestion', index)">
              {{ item.suggested_zh ? `用推荐：${item.suggested_zh}` : '无推荐' }}
            </button>
            <button v-if="item.reviewed" class="secondary" @click="$emit('set-glossary-reviewed', { index, reviewed: false })">撤回</button>
            <button v-else @click="$emit('set-glossary-reviewed', { index, reviewed: true })">确认</button>
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
              <button class="secondary mini" @click="$emit('update-glossary-zh', { index, zh: item.blind_candidate_zh })">填入候选</button>
            </div>
            <div v-else-if="item.blind_candidate_error" class="context-error">候选生成失败：{{ item.blind_candidate_error }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="!loading">
      <div class="toolbar review-toolbar">
        <button @click="$emit('save-glossary-text')">保存 YAML</button>
      </div>
      <textarea :value="glossaryEditor" placeholder="Glossary YAML 内容" @input="$emit('update:glossaryEditor', $event.target.value)" />
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
})

const emit = defineEmits([
  'update:glossaryPath', 'update:glossaryEditor', 'load-glossary',
  'apply-all-suggestions', 'save-glossary-review', 'save-glossary-text',
  'update-glossary-zh', 'set-glossary-reviewed', 'use-suggestion',
])

const tab = ref('review')
const filter = ref('pending')
const isComposing = ref(false)
const reviewInputRefs = new Map()

const indexedItems = computed(() => props.glossaryItems.map((item, index) => ({ item, index })))
const pendingCount = computed(() => props.glossaryItems.filter((item) => !item.reviewed).length)
const confirmedCount = computed(() => props.glossaryItems.length - pendingCount.value)
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
