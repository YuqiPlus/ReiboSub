<template>
  <nav id="main-sidebar" class="side-nav" aria-label="主导航">
    <div class="side-brand">
      <div class="brand-mark"><AppIcon name="language" :size="23" /></div>
      <div>
        <strong>ReiboSub</strong>
        <span>让语言不再是距离</span>
      </div>
      <button class="icon-button sidebar-close" type="button" aria-label="收起侧边栏" @click="$emit('close')"><AppIcon name="panel" :size="18" /></button>
    </div>

    <button class="nav-new-task" type="button" @click="$emit('new-task')"><AppIcon name="compose" />新建字幕任务</button>
    <div class="nav-groups">
      <component
        v-for="(group, groupIndex) in groupedItems"
        :is="group.key === '日常流程' ? 'div' : 'details'"
        :open="group.key !== '日常流程' && group.items.some(item => item.id === activeView)"
        :key="group.key"
        class="nav-section"
        role="group"
        :aria-labelledby="group.label ? groupHeadingId(groupIndex) : undefined"
        :aria-label="group.label ? undefined : '主导航项'"
      >
        <component :is="group.key === '日常流程' ? 'h2' : 'summary'" v-if="group.label" :id="groupHeadingId(groupIndex)" class="nav-group-title">
          {{ group.key === '日常流程' ? '工作空间' : group.label }}<AppIcon v-if="group.key !== '日常流程'" name="chevron" :size="14" />
        </component>
        <div class="nav-group">
          <button
            v-for="item in group.items"
            :key="item.id"
            type="button"
            class="nav-item"
            :class="{ active: item.id === activeView }"
            :aria-current="item.id === activeView ? 'page' : undefined"
            @click="$emit('select', item.id)"
          >
            <AppIcon :name="icons[item.id]" :size="19" />
            <span class="nav-text">
              <strong>{{ item.label }}</strong>
            </span>
            <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
          </button>
        </div>
      </component>

      <section v-if="sessions.length" class="nav-recents" aria-label="最近任务">
        <h2 class="nav-group-title">最近任务</h2>
        <button v-for="item in sessions.slice(0, 10)" :key="item.id" type="button" class="nav-recent" :class="{ active: item.id === selectedSessionId && activeView === 'agent' }" :title="sessionTitle(item)" :aria-label="`${sessionTitle(item)} · ${statusLabel(item.status)}`" @click="$emit('select-session', item.id)">
          <span class="session-dot" :class="item.status"></span><span>{{ sessionTitle(item) }}</span>
        </button>
        <button class="nav-all-tasks" type="button" @click="$emit('select', 'task-history')">查看全部任务<AppIcon name="chevron" :size="14" /></button>
      </section>
    </div>

    <div class="nav-footer">
      <button v-for="item in footerItems" :key="item.id" class="nav-item" :class="{ active: activeView === item.id }" :aria-current="activeView === item.id ? 'page' : undefined" type="button" @click="$emit('select', item.id)"><AppIcon :name="icons[item.id]" :size="19" /><span class="nav-text"><strong>{{ item.label }}</strong></span><span v-if="item.badge" class="nav-badge">{{ item.badge }}</span></button>
    </div>
  </nav>
</template>

<script setup>
import { computed, useId } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  activeView: { type: String, required: true },
  items: { type: Array, default: () => [] },
  sessions: { type: Array, default: () => [] },
  selectedSessionId: { type: String, default: '' },
})
defineEmits(['select', 'new-task', 'select-session', 'close'])

const icons = { agent: 'spark', 'task-history': 'history', assets: 'folder', 'new-task': 'download', 'subtitle-edit': 'edit', glossary: 'book', subtitles: 'language', 'ocr-dev': 'scan', 'asr-dev': 'audio', 'video-overlay': 'video', settings: 'settings', jobs: 'log' }
const footerItems = computed(() => props.items.filter(item => ['settings', 'jobs'].includes(item.id)))
function sessionTitle(item) { return String(item.result?.probe?.title || item.payload?.url || '字幕任务') }
function statusLabel(value) { return { running: '进行中', waiting: '待你确认', failed: '需要重试', done: '已完成', cancelled: '已中断' }[value] || '已保存' }

const headingIdPrefix = useId()

const groupedItems = computed(() => {
  const groups = []
  const byKey = new Map()

  for (const item of props.items || []) {
    if (['settings', 'jobs'].includes(item.id)) continue
    const descriptor = groupDescriptor(item?.group)
    let group = byKey.get(descriptor.key)
    if (!group) {
      group = { ...descriptor, items: [] }
      byKey.set(descriptor.key, group)
      groups.push(group)
    }
    group.items.push(item)
  }

  return groups
})

function groupDescriptor(value) {
  if (value && typeof value === 'object') {
    const label = String(value.label || value.name || '').trim()
    const key = String(value.id || label || '__ungrouped__').trim()
    return { key, label }
  }
  const label = String(value || '').trim()
  return { key: label || '__ungrouped__', label }
}

function groupHeadingId(index) {
  return `${headingIdPrefix}-group-${index}`
}
</script>
