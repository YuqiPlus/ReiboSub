<template>
  <header class="topbar">
    <div class="topbar-leading">
      <button class="icon-button" type="button" aria-label="切换侧边栏" aria-controls="main-sidebar" :aria-expanded="sidebarOpen" @click="$emit('toggle-sidebar')"><AppIcon name="panel" /></button>
      <h1>{{ title }}</h1>
    </div>
    <span class="topbar-signature">ReiboSub <span>字幕工作空间</span></span>
  </header>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
defineProps({ title: { type: String, default: 'ReiboSub' }, sidebarOpen: Boolean })
defineEmits(['toggle-sidebar'])
</script>
