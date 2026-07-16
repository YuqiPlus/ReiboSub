<template>
  <aside>
    <section class="panel">
      <div class="panel-head">
        <h2>任务</h2>
        <button class="secondary mini" @click="$emit('clear-log')">清空显示</button>
      </div>
      <div v-if="!jobList.length" class="empty">还没有任务。</div>
      <div v-else>
        <div v-for="job in jobList" :key="job.id" class="job" :class="{ active: job.id === activeJobId }" @click="$emit('select-job', job.id)">
          <div class="job-title">
            <span>{{ job.name }}</span>
            <span class="pill" :class="job.status">{{ statusLabel(job.status) }}</span>
          </div>
          <div class="muted">{{ job.id }}</div>
          <div class="job-actions">
            <button v-if="job.cancellable" class="ghost mini" @click.stop="$emit('cancel-job', job.id)">终止</button>
          </div>
          <details class="job-log-detail" :open="job.id === activeJobId">
            <summary>任务日志</summary>
            <pre class="job-log-mini">{{ (job.logs || []).join('\n') }}</pre>
          </details>
        </div>
      </div>
    </section>

    <section class="panel" style="margin-top:14px">
      <div class="panel-head">
        <h2>当前任务日志</h2>
        <span v-if="activeJob" class="pill" :class="activeJob.status">{{ statusLabel(activeJob.status) }}</span>
      </div>
      <div v-if="activeJob?.error" class="job-error">{{ activeJob.error }}</div>
      <pre class="log">{{ activeLog }}</pre>
    </section>

    <section class="panel" style="margin-top:14px">
      <div class="panel-head"><h2>输出</h2></div>
      <div v-if="!outputRows.length" class="empty">暂无输出。</div>
      <div v-else class="outputs">
        <div v-for="row in outputRows" :key="row.key" class="output-line">
          <b>{{ row.key }}</b>
          <div class="path">{{ row.value }}</div>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  jobs: { type: Object, default: () => ({}) },
  activeJobId: { type: String, default: '' },
})

defineEmits(['select-job', 'cancel-job', 'clear-log'])

const jobList = computed(() => Object.values(props.jobs).sort((a, b) => (b.created_at || 0) - (a.created_at || 0)))
const activeJob = computed(() => props.activeJobId ? props.jobs[props.activeJobId] || null : null)
const activeLog = computed(() => activeJob.value ? (activeJob.value.logs || []).join('\n') : '')
const outputRows = computed(() => {
  const result = activeJob.value?.result || {}
  return Object.entries(result).map(([key, value]) => ({
    key,
    value: Array.isArray(value) ? value.join('\n') : String(value ?? ''),
  }))
})

function statusLabel(status) {
  const labels = {
    running: '运行中',
    cancel_requested: '终止中',
    cancelled: '已终止',
    done: '完成',
    failed: '失败',
  }
  return labels[status] || status || '未知'
}
</script>
