<template>
  <nav class="side-nav" aria-label="主导航">
    <div class="side-brand">
      <div class="brand-mark">VT</div>
      <div>
        <strong>Video Translate</strong>
        <span>Agent Studio</span>
      </div>
    </div>

    <div class="nav-group">
      <button
        v-for="item in items"
        :key="item.id"
        class="nav-item"
        :class="{ active: item.id === activeView }"
        @click="$emit('select', item.id)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-text">
          <strong>{{ item.label }}</strong>
          <small>{{ item.hint }}</small>
        </span>
        <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
      </button>
    </div>
  </nav>
</template>

<script setup>
defineProps({
  activeView: { type: String, required: true },
  items: { type: Array, default: () => [] },
})
defineEmits(['select'])
</script>
