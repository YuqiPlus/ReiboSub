<template>
  <svg class="app-icon" :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path v-for="(path, index) in (paths[name] || paths.spark)" :key="index" :d="path" />
  </svg>
</template>

<script setup>
defineProps({ name: { type: String, default: 'spark' }, size: { type: [Number, String], default: 20 } })
const paths = {
  toolbox: ['M8 7V4h8v3', 'M3 7h18v14H3V7Z', 'M3 12h18M10 11v3h4v-3'],
  search: ['M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15Z', 'm16 16 5 5'],
  play: ['m8 4 12 8-12 8V4Z'],
  check: ['m5 12 4 4L19 6'],
  plus: ['M12 4v16M4 12h16'],
  spark: ['M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z'],
  compose: ['M13 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8', 'm16 3 5 5-10 10-5 1 1-5L17 3'],
  panel: ['M9 3v18', 'M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z'],
  folder: ['M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z'],
  history: ['M3 11a9 9 0 1 1 2.4 7', 'M3 4v7h7', 'M12 7v5l3 2'],
  download: ['M12 3v12', 'm7 10 5 5 5-5', 'M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4'],
  edit: ['m15 4 5 5-10 10-6 1 1-6L15 4Z', 'm12 7 5 5'],
  book: ['M12 5v16', 'M12 5C8 2 4 3 2 4v15c3-1 7-1 10 2 3-3 7-3 10-2V4c-2-1-6-2-10 1Z'],
  language: ['M3 5h12', 'M9 3v2c0 7-4 10-6 11', 'M5 9c1 3 4 5 7 6', 'm13 21 5-13 5 13', 'M15 17h6'],
  scan: ['M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5', 'M7 8h10M7 12h10M7 16h6'],
  audio: ['M12 3v18M8 7v10M4 10v4M16 7v10M20 10v4'],
  video: ['M3 5h13v14H3V5Z', 'm16 10 5-3v10l-5-3'],
  settings: ['M9 3h6l.6 3 2.5 1.5L21 7l2 5-2.5 2 .1 3L16 20l-2-2h-4l-2 2-4.6-3 .1-3L1 12l2-5 2.9.5L8.4 6 9 3Z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z'],
  log: ['M5 3h14v18H5V3Z', 'M9 7h6M9 11h6M9 15h4'],
  arrow: ['M12 19V5', 'm6 11 6-6 6 6'],
  chevron: ['m9 5 7 7-7 7'],
  link: ['m10 13 4-4', 'm8 16-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0', 'm16 8 1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0'],
  close: ['m6 6 12 12M6 18 18 6'],
}
</script>
