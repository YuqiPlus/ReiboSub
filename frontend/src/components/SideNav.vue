<template>
  <nav class="side-nav" aria-label="主导航">
    <div class="side-brand">
      <div class="brand-mark">VT</div>
      <div>
        <strong>Video Translate</strong>
        <span>Agent Studio</span>
      </div>
    </div>

    <div class="nav-groups">
      <div
        v-for="(group, groupIndex) in groupedItems"
        :key="group.key"
        class="nav-section"
        role="group"
        :aria-labelledby="group.label ? groupHeadingId(groupIndex) : undefined"
        :aria-label="group.label ? undefined : '主导航项'"
      >
        <h2 v-if="group.label" :id="groupHeadingId(groupIndex)" class="nav-group-title">
          {{ group.label }}
        </h2>
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
            <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
            <span class="nav-text">
              <strong>{{ item.label }}</strong>
              <small>{{ item.hint }}</small>
            </span>
            <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
          </button>
        </div>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { computed, useId } from 'vue'

const props = defineProps({
  activeView: { type: String, required: true },
  items: { type: Array, default: () => [] },
})
defineEmits(['select'])

const headingIdPrefix = useId()

const groupedItems = computed(() => {
  const groups = []
  const byKey = new Map()

  for (const item of props.items || []) {
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
