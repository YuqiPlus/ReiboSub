<template>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>语言</th>
          <th>类型</th>
          <th>格式</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="`${item.lang}-${item.kind}`">
          <td><span class="badge core">{{ item.lang }}</span></td>
          <td><span class="badge" :class="item.kind">{{ item.kind === 'manual' ? '人工' : '自动' }}</span></td>
          <td>{{ formatList(item.formats) }}</td>
          <td><button class="secondary mini" @click="$emit('download', item)">下载字幕</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
})
defineEmits(['download'])

function formatList(value) {
  return Array.isArray(value) && value.length ? value.join(', ') : 'srt'
}
</script>
