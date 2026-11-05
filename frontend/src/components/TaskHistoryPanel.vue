<template>
  <section class="panel task-history" :aria-busy="loading ? 'true' : 'false'">
    <header class="task-history-head">
      <div class="task-history-heading">
        <span class="task-history-eyebrow">持久化工作流</span>
        <h2>任务历史</h2>
        <p>按任务恢复处理进度，或从指定阶段重新运行，不依赖素材库重新识别。</p>
      </div>
      <button class="secondary" type="button" :disabled="loading || anyBusy" @click="emit('refresh')">
        {{ loading ? '刷新中…' : '刷新任务' }}
      </button>
    </header>

    <div class="task-history-tools">
      <label class="task-history-search">
        <span>搜索任务</span>
        <div class="task-history-search-box">
          <span aria-hidden="true">⌕</span>
          <input
            v-model.trim="query"
            type="search"
            autocomplete="off"
            placeholder="标题、任务 ID、链接或阶段"
          />
          <button v-if="query" class="task-history-clear" type="button" aria-label="清除搜索" @click="query = ''">×</button>
        </div>
      </label>

      <div class="task-history-summary" aria-live="polite">
        <span><b>{{ counts.all }}</b> 个任务</span>
        <span><b>{{ counts.attention }}</b> 个待处理</span>
        <span><b>{{ counts.failed }}</b> 个失败</span>
      </div>
    </div>

    <nav class="task-history-tabs" aria-label="任务筛选">
      <button
        v-for="item in filters"
        :key="item.id"
        class="task-history-tab"
        :class="{ active: activeFilter === item.id }"
        type="button"
        :aria-pressed="activeFilter === item.id"
        @click="activeFilter = item.id"
      >
        <span>{{ item.label }}</span>
        <b>{{ counts[item.id] }}</b>
      </button>
    </nav>

    <p v-if="status" class="status task-history-status" :class="statusClass">{{ status }}</p>

    <div v-if="loading && !tasks.length" class="task-history-loading" aria-label="正在加载任务">
      <span v-for="index in 3" :key="index"></span>
    </div>

    <div v-else-if="!visibleTasks.length" class="empty task-history-empty">
      <b>{{ query ? '没有匹配的任务' : emptyTitle }}</b>
      <span>{{ query ? '换一个标题、任务 ID 或链接试试。' : emptyDescription }}</span>
    </div>

    <div v-else class="task-history-list">
      <article
        v-for="task in visibleTasks"
        :key="task.id"
        class="task-history-card"
        :class="[`state-${taskState(task)}`, { busy: isBusy(task) }]"
      >
        <header class="task-history-card-head">
          <div class="task-history-title-wrap">
            <span class="task-history-state-mark" aria-hidden="true"></span>
            <div>
              <h3>{{ task.title || task.url || task.id || '未命名任务' }}</h3>
              <p>
                <code>{{ task.id || '无任务 ID' }}</code>
                <span v-if="safeSourceUrl(task.url)" aria-hidden="true">·</span>
                <a v-if="safeSourceUrl(task.url)" :href="safeSourceUrl(task.url)" target="_blank" rel="noreferrer">查看来源</a>
              </p>
            </div>
          </div>
          <span class="task-history-state-pill" :class="taskState(task)">{{ taskStateLabel(task) }}</span>
        </header>

        <div class="task-history-facts">
          <div>
            <span>当前阶段</span>
            <b>{{ currentStageLabel(task.current_stage) }}</b>
          </div>
          <div>
            <span>最近更新</span>
            <b>{{ localTime(task.updated_at || task.completed_at || task.created_at) }}</b>
          </div>
          <div>
            <span>运行代次</span>
            <b>第 {{ runGeneration(task) }} 轮</b>
          </div>
          <div>
            <span>归档运行</span>
            <b>{{ archivedRunCount(task) }} 轮</b>
          </div>
        </div>

        <details v-if="archivedRuns(task).length" class="task-history-archives">
          <summary>
            <span>旧轮次与历史产物</span>
            <b>{{ archivedRuns(task).length }} 轮</b>
          </summary>
          <div class="task-history-archive-list">
            <article v-for="run in archivedRuns(task)" :key="run.generation" class="task-history-archive-run">
              <div>
                <b>第 {{ run.generation || '?' }} 轮</b>
                <span>{{ currentStageLabel(run.current_stage) }} · {{ localTime(run.archived_at || run.updated_at) }}</span>
              </div>
              <p v-if="run.error" class="task-history-stage-error">{{ run.error }}</p>
              <div v-if="run.artifacts?.length" class="task-history-stage-actions">
                <button
                  v-for="artifact in run.artifacts"
                  :key="`${artifact.kind}:${artifact.path}`"
                  class="ghost mini task-history-artifact"
                  type="button"
                  :title="artifact.path"
                  @click="openArchivedArtifact(task, run, artifact)"
                >
                  {{ archiveArtifactLabel(artifact) }}
                </button>
              </div>
            </article>
          </div>
        </details>

        <div class="task-history-card-actions">
          <button
            v-if="!isCompleted(task)"
            type="button"
            :disabled="anyBusy"
            @click="emit('continue-task', task.id)"
          >
            {{ isBusy(task) ? '处理中…' : (isTaskRunning(task) ? '查看运行' : '继续任务') }}
          </button>
          <button
            v-else
            class="secondary"
            type="button"
            :disabled="anyBusy"
            @click="emit('reopen-task', task)"
          >
            恢复为活动任务
          </button>
          <button v-if="task.can_restart !== false" class="secondary" type="button" :disabled="anyBusy" @click="emit('restart-task', task)">
            从头重跑
          </button>
          <button
            v-if="!isCompleted(task)"
            class="secondary"
            type="button"
            :disabled="anyBusy || isTaskRunning(task)"
            @click="emit('complete-task', task)"
          >
            标记完成
          </button>
          <button class="danger secondary" type="button" :disabled="anyBusy || isTaskRunning(task)" @click="emit('delete-task', task)">
            删除
          </button>
        </div>

        <div class="task-history-stages">
          <section
            v-for="stage in task.stage_items || []"
            :key="stage.id"
            class="task-history-stage"
            :class="`stage-${resolvedStageStatus(stage, task)}`"
          >
            <div class="task-history-stage-head">
              <div>
                <span class="task-history-stage-index">{{ stageIndex(task, stage) }}</span>
                <div>
                  <b>{{ stageDisplayLabel(stage) }}</b>
                  <small v-if="stage.updated_at">{{ localTime(stage.updated_at) }}</small>
                </div>
              </div>
              <span class="task-history-stage-status">{{ stageStatusLabel(stage, task) }}</span>
            </div>

            <p v-if="stage.error" class="task-history-stage-error">{{ stage.error }}</p>

            <div v-if="artifactItems(stage).length || canRerun(stage)" class="task-history-stage-actions">
              <button
                v-for="artifact in artifactItems(stage)"
                :key="`${artifact.kind}:${artifact.path}`"
                class="ghost mini task-history-artifact"
                type="button"
                :title="artifact.path"
                @click="openArtifact(task, stage, artifact)"
              >
                {{ artifact.label }}
              </button>
              <button
                v-if="canRerun(stage)"
                class="secondary mini"
                type="button"
                :disabled="anyBusy || isTaskRunning(task)"
                @click="emit('rerun-task', { taskId: task.id, stage: stage.id })"
              >
                {{ resolvedStageStatus(stage, task) === 'failed' ? '重试此阶段' : '重跑此阶段' }}
              </button>
            </div>
          </section>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  busyTaskId: { type: String, default: '' },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

const emit = defineEmits([
  'refresh',
  'continue-task',
  'rerun-task',
  'restart-task',
  'complete-task',
  'reopen-task',
  'delete-task',
  'open-glossary',
  'open-artifact',
])

const query = ref('')
const activeFilter = ref('all')
const anyBusy = computed(() => Boolean(props.busyTaskId))

const filters = [
  { id: 'all', label: '全部' },
  { id: 'active', label: '进行中' },
  { id: 'attention', label: '待处理' },
  { id: 'failed', label: '失败' },
  { id: 'completed', label: '已完成' },
]

const counts = computed(() => ({
  all: props.tasks.length,
  active: props.tasks.filter((task) => taskState(task) === 'active').length,
  attention: props.tasks.filter((task) => needsAttention(task)).length,
  failed: props.tasks.filter((task) => isFailed(task)).length,
  completed: props.tasks.filter((task) => isCompleted(task)).length,
}))

const visibleTasks = computed(() => {
  const needle = query.value.toLocaleLowerCase()
  return props.tasks.filter((task) => {
    if (!matchesFilter(task, activeFilter.value)) return false
    if (!needle) return true
    const stageText = (task.stage_items || [])
      .map((stage) => `${stage.id || ''} ${stage.label || ''} ${stage.status || ''}`)
      .join(' ')
    return [task.title, task.id, task.url, task.current_stage, task.workflow_status, stageText]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase().includes(needle))
  })
})

const emptyTitle = computed(() => ({
  active: '没有进行中的任务',
  attention: '没有等待处理的任务',
  failed: '没有失败任务',
  completed: '还没有已完成任务',
}[activeFilter.value] || '还没有持久化任务'))

const emptyDescription = computed(() => ({
  active: '开始新任务后，可以随时回到这里继续。',
  attention: '当前没有需要审核、确认或恢复的阶段。',
  failed: '当前所有任务阶段均未报告失败。',
  completed: '完成的任务会保留在这里，方便再次运行。',
}[activeFilter.value] || '任务开始后，阶段和产物会显示在这里。'))

function matchesFilter(task, filter) {
  if (filter === 'active') return taskState(task) === 'active'
  if (filter === 'attention') return needsAttention(task)
  if (filter === 'failed') return isFailed(task)
  if (filter === 'completed') return isCompleted(task)
  return true
}

function isCompleted(task) {
  if (typeof task?.is_completed === 'boolean') return task.is_completed
  if (task?.workflow_status) return task.workflow_status === 'completed'
  return task?.current_stage === 'done'
}

function isFailed(task) {
  if (task?.status === 'failed' || task?.workflow_status === 'failed') return true
  if (String(task?.current_stage || '').endsWith('_failed')) return true
  return (task?.stage_items || []).some((stage) => resolvedStageStatus(stage, task) === 'failed')
}

function needsAttention(task) {
  if (isCompleted(task) || isFailed(task)) return false
  if (['waiting', 'needs_input', 'interrupted'].includes(String(task?.status || ''))) return true
  const current = String(task?.current_stage || '').toLowerCase()
  if (/(review|confirm|waiting|interrupted|attention)/.test(current)) return true
  return (task?.stage_items || []).some((stage) => (
    ['waiting', 'waiting_review', 'needs_input', 'interrupted'].includes(String(stage?.status || ''))
  ))
}

function taskState(task) {
  if (isCompleted(task)) return 'completed'
  if (isFailed(task)) return 'failed'
  if (needsAttention(task)) return 'attention'
  return 'active'
}

function taskStateLabel(task) {
  return {
    completed: '已完成',
    failed: '运行失败',
    attention: '等待处理',
    active: '进行中',
  }[taskState(task)]
}

function isBusy(task) {
  return Boolean(props.busyTaskId && String(task?.id || '') === props.busyTaskId)
}

function isTaskRunning(task) {
  const stages = [
    ...(task?.stage_items || []),
    ...Object.values(task?.stages || {}),
  ]
  return stages.some((stage) => ['running', 'queued', 'rerunning'].includes(String(stage?.status || '')))
}

function archivedRunCount(task) {
  for (const key of ['archived_run_count', 'archived_runs_count', 'archive_run_count', 'run_archive_count', 'archived_count']) {
    const value = Number(task?.[key])
    if (Number.isFinite(value) && value >= 0) return value
  }
  for (const key of ['archived_runs', 'archive_runs', 'run_history', 'runs']) {
    if (Array.isArray(task?.[key])) return task[key].length
  }
  return 0
}

function archivedRuns(task) {
  return Array.isArray(task?.archived_runs) ? task.archived_runs : []
}

function runGeneration(task) {
  const value = Number(task?.run_generation)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function safeSourceUrl(value) {
  const url = String(value || '').trim()
  return /^https?:\/\//i.test(url) ? url : ''
}

function localTime(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '—'
  const milliseconds = number > 1e12 ? number : number * 1000
  const date = new Date(milliseconds)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function currentStageLabel(stage) {
  const labels = {
    created: '刚创建',
    probe: '检测中',
    probe_done: '检测完成',
    ocr_done: 'OCR 完成',
    asr_done: 'ASR 完成',
    asr_ocr_done: 'ASR + OCR 完成',
    glossary_review: '等待术语审核',
    glossary_reviewed: '术语已审核',
    translate_pending: '翻译排队中',
    translate_running: '翻译中',
    done: '全部完成',
    ocr_rerun: '正在重跑 OCR',
    glossary_rerun: '正在重跑术语',
    translate_rerun: '正在重跑翻译',
    ocr_failed: 'OCR 失败',
    glossary_failed: '术语阶段失败',
    translate_failed: '翻译失败',
  }
  if (labels[stage]) return labels[stage]
  const match = String(stage || '').match(/^(probe|ocr|asr|glossary|translate)_(running|waiting|interrupted)$/)
  if (match) {
    const stageLabels = { probe: '来源检测', ocr: '原文字幕', asr: '语音识别', glossary: '术语表', translate: '中文字幕' }
    const stateLabels = { running: '运行中', waiting: '等待确认', interrupted: '已中断' }
    return `${stageLabels[match[1]]}${stateLabels[match[2]]}`
  }
  return stage || '未开始'
}

function stageDisplayLabel(stage) {
  if (stage?.source_stage === 'asr') return 'ASR 原文字幕'
  const labels = {
    probe: '来源检测',
    source: '原文字幕',
    ocr: '原文字幕',
    asr: '语音识别',
    glossary: '术语表',
    translate: '中文字幕',
  }
  return labels[stage?.id] || stage?.label || stage?.id || '未命名阶段'
}

function stageIndex(task, stage) {
  const index = (task?.stage_items || []).findIndex((item) => item.id === stage.id)
  return String(Math.max(0, index) + 1).padStart(2, '0')
}

function resolvedStageStatus(stage, task) {
  if (stage?.id === 'glossary' && stage?.status === 'waiting_review') {
    const translationDone = (task?.stage_items || []).some((item) => item.id === 'translate' && item.status === 'done')
    if (translationDone) return 'done'
  }
  if (stage?.id === 'ocr' && (!stage?.status || stage.status === 'pending')) {
    if (task?.stages?.asr?.status) return task.stages.asr.status
    if (task?.stages?.glossary?.source_srt) return 'done'
  }
  return String(stage?.status || 'pending')
}

function stageStatusLabel(stage, task) {
  const status = resolvedStageStatus(stage, task)
  const labels = {
    pending: '未开始',
    queued: '已排队',
    running: '运行中',
    rerunning: '重跑中',
    done: '完成',
    reviewed: '已审核',
    waiting: '等待确认',
    waiting_review: '待审核',
    needs_input: '等待输入',
    failed: '失败',
    invalidated: '已失效',
    interrupted: '已中断',
    cancelled: '已取消',
  }
  return labels[status] || status || '未开始'
}

function canRerun(stage) {
  if (stage?.can_rerun === false) return false
  const explicitlySupported = stage?.can_rerun === true
  const legacySupported = ['ocr', 'glossary', 'translate'].includes(stage?.id)
  return (explicitlySupported || legacySupported)
    && ['done', 'reviewed', 'waiting_review', 'failed', 'invalidated', 'interrupted', 'cancelled'].includes(String(stage?.status || ''))
}

function artifactItems(stage) {
  const nested = stage?.job_result && typeof stage.job_result === 'object' ? stage.job_result : {}
  const candidates = [
    { kind: 'glossary', label: '打开术语表', path: stage?.glossary_path || nested.glossary_path },
    { kind: 'source_srt', label: '查看原文 SRT', path: stage?.source_srt || nested.source_srt },
    { kind: 'translated_srt', label: '查看中文字幕', path: stage?.translated_srt || nested.translated_srt },
    { kind: 'translated_sidecar', label: '查看字幕副本', path: stage?.translated_sidecar || nested.translated_sidecar },
    { kind: 'subtitle', label: '查看字幕', path: stage?.subtitle_path || nested.subtitle_path },
  ]
  const seen = new Set()
  return candidates.filter((item) => {
    const path = String(item.path || '').trim()
    if (!path || seen.has(path)) return false
    item.path = path
    seen.add(path)
    return true
  })
}

function openArtifact(task, stage, artifact) {
  const payload = {
    path: artifact.path,
    taskId: task.id,
    stage: stage.id,
    kind: artifact.kind,
  }
  if (artifact.kind === 'glossary') emit('open-glossary', payload)
  else emit('open-artifact', payload)
}

function archiveArtifactLabel(artifact) {
  return {
    source_srt: '旧版原文 SRT',
    reference_srt: '旧版参考 SRT',
    glossary_path: '旧版术语表',
    translated_srt: '旧版中文字幕',
    translated_sidecar: '旧版字幕副本',
    subtitle_path: '旧版字幕',
  }[artifact?.kind] || '打开历史产物'
}

function openArchivedArtifact(task, run, artifact) {
  const payload = {
    path: artifact.path,
    taskId: task.id,
    stage: artifact.stage || '',
    generation: run.generation,
    kind: artifact.kind,
  }
  if (artifact.kind === 'glossary_path') emit('open-glossary', payload)
  else emit('open-artifact', payload)
}
</script>

<style scoped>
.task-history {
  display: grid;
  gap: 16px;
  padding: 20px;
}

.task-history-head,
.task-history-tools,
.task-history-card-head,
.task-history-stage-head,
.task-history-card-actions,
.task-history-stage-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.task-history-head,
.task-history-card-head,
.task-history-stage-head {
  justify-content: space-between;
}

.task-history-heading {
  display: grid;
  gap: 4px;
}

.task-history-heading h2 {
  font-size: 20px;
}

.task-history-heading p {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.task-history-eyebrow {
  color: var(--teal);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.task-history-tools {
  align-items: end;
  justify-content: space-between;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--soft);
}

.task-history-search {
  width: min(560px, 100%);
  margin: 0;
}

.task-history-search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.task-history-search-box > span {
  position: absolute;
  left: 11px;
  color: var(--muted);
  font-size: 18px;
  pointer-events: none;
}

.task-history-search-box input {
  padding-right: 38px;
  padding-left: 36px;
}

.task-history-clear {
  position: absolute;
  right: 7px;
  width: 26px;
  min-height: 26px;
  padding: 0;
  border-color: transparent;
  background: transparent;
  color: var(--muted);
  box-shadow: none;
  font-size: 18px;
}

.task-history-clear:hover {
  border-color: var(--line);
  background: #fff;
  color: var(--ink);
}

.task-history-summary {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 7px;
}

.task-history-summary span {
  padding: 6px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: var(--muted);
  font-size: 12px;
}

.task-history-summary b {
  color: var(--ink);
}

.task-history-tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  padding-bottom: 1px;
  border-bottom: 1px solid var(--line);
}

.task-history-tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 7px 10px;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  box-shadow: none;
}

.task-history-tab:hover {
  border-bottom-color: var(--line-strong);
  background: var(--soft);
  color: var(--ink);
}

.task-history-tab.active {
  border-bottom-color: var(--teal);
  color: var(--teal-dark);
}

.task-history-tab b {
  min-width: 21px;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--soft);
  font-size: 11px;
  text-align: center;
}

.task-history-tab.active b {
  background: var(--teal-soft);
}

.task-history-status {
  margin: -4px 0 0;
}

.task-history-list {
  display: grid;
  gap: 13px;
}

.task-history-card {
  position: relative;
  display: grid;
  gap: 14px;
  overflow: hidden;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(45, 94, 68, .05);
}

.task-history-card::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--blue);
  content: '';
}

.task-history-card.state-attention::before { background: var(--amber); }
.task-history-card.state-failed::before { background: var(--red); }
.task-history-card.state-completed::before { background: var(--green); }
.task-history-card.busy { border-color: var(--teal); }

.task-history-title-wrap,
.task-history-title-wrap > div,
.task-history-stage-head > div {
  display: flex;
  align-items: center;
  min-width: 0;
}

.task-history-title-wrap {
  gap: 10px;
}

.task-history-title-wrap > div {
  display: grid;
  gap: 5px;
}

.task-history-title-wrap h3 {
  overflow: hidden;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-history-title-wrap p {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--muted);
  font-size: 11px;
}

.task-history-title-wrap code {
  color: var(--muted);
  font-size: 11px;
}

.task-history-title-wrap a {
  color: var(--teal);
  text-decoration: none;
}

.task-history-title-wrap a:hover { text-decoration: underline; }

.task-history-state-mark {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--blue);
  box-shadow: 0 0 0 4px var(--blue-soft);
}

.state-attention .task-history-state-mark { background: var(--amber); box-shadow: 0 0 0 4px var(--amber-soft); }
.state-failed .task-history-state-mark { background: var(--red); box-shadow: 0 0 0 4px var(--red-soft); }
.state-completed .task-history-state-mark { background: var(--green); box-shadow: 0 0 0 4px var(--green-soft); }

.task-history-state-pill,
.task-history-stage-status {
  flex: 0 0 auto;
  padding: 4px 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--soft);
  color: var(--muted);
  font-size: 11px;
  font-weight: 750;
}

.task-history-state-pill.active { color: var(--blue); background: var(--blue-soft); border-color: #ccdeed; }
.task-history-state-pill.attention { color: var(--amber); background: var(--amber-soft); border-color: #ead9bd; }
.task-history-state-pill.failed { color: var(--red); background: var(--red-soft); border-color: #efcbc7; }
.task-history-state-pill.completed { color: var(--green); background: var(--green-soft); border-color: #c6e6d1; }

.task-history-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.task-history-facts > div {
  display: grid;
  gap: 3px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--soft);
}

.task-history-facts span {
  color: var(--muted);
  font-size: 10px;
}

.task-history-facts b {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-history-archives {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}

.task-history-archives > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}

.task-history-archives > summary b {
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--soft);
  color: var(--ink);
  font-size: 10px;
}

.task-history-archive-list {
  display: grid;
  gap: 7px;
  padding: 0 10px 10px;
}

.task-history-archive-run {
  display: grid;
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--soft);
}

.task-history-archive-run > div:first-child {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}

.task-history-archive-run > div:first-child b { font-size: 12px; }
.task-history-archive-run > div:first-child span { color: var(--muted); font-size: 10px; }

.task-history-card-actions,
.task-history-stage-actions {
  flex-wrap: wrap;
}

.task-history-card-actions {
  padding-bottom: 2px;
}

.task-history-card-actions .danger.secondary {
  margin-left: auto;
  border-color: #e8b8b3;
  background: #fff;
  color: var(--red);
}

.task-history-card-actions .danger.secondary:hover {
  background: var(--red-soft);
}

.task-history-stages {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 9px;
}

.task-history-stage {
  display: grid;
  align-content: start;
  gap: 10px;
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--soft);
}

.task-history-stage-head > div {
  gap: 8px;
}

.task-history-stage-head > div > div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.task-history-stage-head b {
  font-size: 12px;
}

.task-history-stage-head small {
  color: var(--muted);
  font-size: 10px;
}

.task-history-stage-index {
  display: grid;
  flex: 0 0 auto;
  width: 27px;
  height: 27px;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
}

.stage-done .task-history-stage-status,
.stage-reviewed .task-history-stage-status { color: var(--green); background: var(--green-soft); border-color: #c6e6d1; }
.stage-failed .task-history-stage-status { color: var(--red); background: var(--red-soft); border-color: #efcbc7; }
.stage-waiting .task-history-stage-status,
.stage-waiting_review .task-history-stage-status,
.stage-needs_input .task-history-stage-status { color: var(--amber); background: var(--amber-soft); border-color: #ead9bd; }
.stage-running .task-history-stage-status,
.stage-rerunning .task-history-stage-status,
.stage-queued .task-history-stage-status { color: var(--blue); background: var(--blue-soft); border-color: #ccdeed; }

.task-history-stage-error {
  padding: 8px;
  border-radius: 7px;
  background: var(--red-soft);
  color: var(--red);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.task-history-stage-actions {
  margin-top: auto;
  gap: 6px;
}

.task-history-artifact {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-history-loading {
  display: grid;
  gap: 10px;
}

.task-history-loading span {
  height: 154px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: linear-gradient(100deg, var(--soft) 20%, #eef6f0 38%, var(--soft) 55%);
  background-size: 200% 100%;
  animation: task-history-shimmer 1.25s ease-in-out infinite;
}

.task-history-empty {
  display: grid;
  gap: 5px;
  min-height: 130px;
  align-content: center;
  justify-items: center;
  text-align: center;
}

.task-history-empty b { color: var(--ink); }
.task-history-empty span { font-size: 12px; }

@keyframes task-history-shimmer {
  to { background-position-x: -200%; }
}

@media (max-width: 860px) {
  .task-history-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .task-history-tools { align-items: stretch; flex-direction: column; }
  .task-history-search { width: 100%; }
  .task-history-summary { justify-content: flex-start; }
}

@media (max-width: 620px) {
  .task-history { padding: 14px; }
  .task-history-head, .task-history-card-head { align-items: stretch; flex-direction: column; }
  .task-history-head > button { align-self: flex-start; }
  .task-history-state-pill { align-self: flex-start; }
  .task-history-facts { grid-template-columns: 1fr; }
  .task-history-card-actions .danger.secondary { margin-left: 0; }
  .task-history-stages { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .task-history-loading span { animation: none; }
}
</style>
