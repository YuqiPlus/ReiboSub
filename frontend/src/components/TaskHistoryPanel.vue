<template>
  <section class="panel task-history history-studio" :aria-busy="loading">
    <header class="studio-page-head"><div><h2>任务历史</h2><p>{{ tasks.length }} 个任务 · 查看进展、打开字幕，或继续处理。</p></div><button class="secondary" type="button" :disabled="loading || anyBusy" @click="emit('refresh')"><AppIcon name="history" :size="16" />{{ loading ? '刷新中…' : '刷新任务' }}</button></header>
    <div class="studio-filter-bar history-filter-bar"><label class="studio-search"><AppIcon name="search" :size="17" /><input v-model.trim="query" type="search" autocomplete="off" aria-label="搜索任务" placeholder="搜索标题、链接或任务编号" /><button v-if="query" class="icon-button" type="button" aria-label="清除搜索" @click="query = ''"><AppIcon name="close" :size="14" /></button></label><select v-model="sortBy" class="library-sort" aria-label="任务排序"><option value="recent">最近更新</option><option value="name">按标题</option></select></div>
    <nav class="studio-tabs history-tabs" aria-label="任务筛选"><button v-for="item in filters" :key="item.id" type="button" :class="{ active: activeFilter === item.id }" :aria-pressed="activeFilter === item.id" @click="activeFilter = item.id">{{ item.label }}<span v-if="counts[item.id]">{{ counts[item.id] }}</span></button></nav>
    <p v-if="status && statusClass !== 'ok'" class="status" :class="statusClass" role="status">{{ status }}</p>
    <div v-if="loading && !tasks.length" class="studio-empty" role="status">正在读取任务…</div>
    <div v-else-if="!visibleTasks.length" class="studio-empty"><AppIcon name="history" :size="30" /><h3>{{ query ? '没有匹配的任务' : emptyTitle }}</h3><p>{{ query ? '试试其他标题或链接。' : emptyDescription }}</p><button v-if="query" class="secondary" @click="query = ''">清除搜索</button></div>
    <div v-else class="history-task-list">
      <article v-for="task in visibleTasks" :key="task.id" class="history-task-card" :class="[taskState(task), { busy: isBusy(task) }]">
        <header class="history-task-heading"><div><h3>{{ task.title || task.url || task.id || '未命名任务' }}</h3><div class="history-card-meta"><span>{{ currentStageLabel(task.current_stage) }}</span><span>第 {{ runGeneration(task) }} 轮<span v-if="archivedRunCount(task)"> · {{ archivedRunCount(task) }} 轮归档</span></span><time>{{ localTime(task.updated_at || task.completed_at || task.created_at) }}</time><a v-if="safeSourceUrl(task.url)" :href="safeSourceUrl(task.url)" target="_blank" rel="noreferrer">原视频<AppIcon name="link" :size="12" /></a></div></div><span class="history-state" :class="taskState(task)"><span></span>{{ taskStateLabel(task) }}</span></header>
        <div v-if="task.stage_items?.length" class="history-stage-snapshot" aria-label="各阶段状态">
          <span v-for="stage in task.stage_items" :key="stage.id" :class="`snapshot-${resolvedStageStatus(stage, task)}`"><i aria-hidden="true"></i>{{ stageDisplayLabel(stage) }}<b>{{ stageStatusLabel(stage, task) }}</b></span>
        </div>
        <p v-if="taskError(task)" class="history-card-error" :title="taskError(task)"><AppIcon name="log" :size="14" /><span>{{ taskError(task) }}</span></p>
        <div class="history-card-footer">
          <div class="history-primary-actions"><button v-if="!isCompleted(task)" :disabled="anyBusy" @click="emit('continue-task', task.id)">{{ isBusy(task) ? '处理中…' : isTaskRunning(task) ? '查看运行' : '继续任务' }}</button><button v-else class="secondary" @click="toggleDetails(task.id)">查看记录</button><button v-for="entry in artifactShortcuts(task)" :key="entry.artifact.path" class="secondary" :title="entry.artifact.path" @click="openArtifact(task, entry.stage, entry.artifact)"><AppIcon :name="entry.artifact.kind === 'glossary' ? 'book' : 'log'" :size="15" />{{ entry.label }}</button></div>
          <button class="danger secondary history-delete-task" type="button" :disabled="anyBusy || isTaskRunning(task)" :title="isTaskRunning(task) ? '请先中断正在运行的任务' : '删除任务档案与任务产物，保留已下载视频'" @click="emit('delete-task', task)">删除任务…</button>
        </div>
        <details class="history-task-details" :open="expandedIds.has(task.id)" @toggle="setDetailsOpen(task.id, $event.target.open)"><summary>阶段记录、重跑与更多</summary>
          <div class="history-task-meta"><span>任务编号 <code>{{ task.id }}</code></span><span>第 {{ runGeneration(task) }} 轮 · {{ archivedRunCount(task) }} 轮归档</span><a v-if="safeSourceUrl(task.url)" :href="safeSourceUrl(task.url)" target="_blank" rel="noreferrer">查看原视频</a></div>
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

            <div v-if="artifactItems(stage, task).length || canRerun(stage)" class="task-history-stage-actions">
              <button
                v-for="artifact in artifactItems(stage, task)"
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


          <div class="history-manage-actions"><span>任务管理</span><button v-if="task.can_restart !== false" class="secondary mini" :disabled="anyBusy" @click="emit('restart-task', task)">从头重跑…</button><button v-if="!isCompleted(task)" class="secondary mini" :disabled="anyBusy || isTaskRunning(task)" @click="emit('complete-task', task)">标记完成</button><button v-else class="secondary mini" :disabled="anyBusy" @click="emit('reopen-task', task)">恢复为活动任务</button></div>
        </details>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { targetSubtitleLabel } from '../translationLanguages.js'

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
const sortBy = ref('recent')
const expandedIds = ref(new Set())
function setDetailsOpen(id, open) {
  const ids = new Set(expandedIds.value)
  if (open) ids.add(id)
  else ids.delete(id)
  expandedIds.value = ids
}
function toggleDetails(id) { setDetailsOpen(id, !expandedIds.value.has(id)) }
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
  }).sort((a, b) => sortBy.value === 'name'
    ? String(a.title || '').localeCompare(String(b.title || ''))
    : (Number(b.updated_at || b.completed_at || b.created_at) || 0) - (Number(a.updated_at || a.completed_at || a.created_at) || 0))
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

function taskError(task) {
  if (!isFailed(task) || isCompleted(task)) return ''
  const stage = (task.stage_items || []).find(item => resolvedStageStatus(item, task) === 'failed' && item.error)
  return String(stage?.error || task.error || '')
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
  if (isCompleted(task) || ['failed', 'cancelled', 'interrupted'].includes(String(task?.status || '')) || task?.workflow_status === 'failed' || String(task?.current_stage || '').endsWith('_failed')) return false
  if (needsAttention(task)) return false
  if (task?.status === 'running') return true
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
    autonomous_running: 'Agent 正在处理',
    autonomous_failed: 'Agent 处理失败',
    autonomous_waiting: '等待确认',
    autonomous_verification_review: '字幕疑点待复核',
    autonomous_review_required: '字幕疑点待复核',
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
    const stageLabels = { probe: '来源检测', ocr: '原文字幕', asr: '语音识别', glossary: '术语表', translate: '译文字幕' }
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
    translate: '译文字幕',
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

function artifactItems(stage, task = {}) {
  const nested = stage?.job_result && typeof stage.job_result === 'object' ? stage.job_result : {}
  const candidates = [
    { kind: 'glossary', label: '打开术语表', path: stage?.glossary_path || nested.glossary_path },
    { kind: 'source_srt', label: '查看原文 SRT', path: stage?.source_srt || nested.source_srt },
    { kind: 'translated_srt', label: `查看${targetSubtitleLabel(task.payload?.target_language || task.target_language)}`, path: stage?.translated_srt || nested.translated_srt },
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

function artifactShortcuts(task) {
  const entries = (task.stage_items || []).flatMap(stage => artifactItems(stage, task).map(artifact => ({ stage, artifact })))
  const choose = kinds => entries.find(entry => kinds.includes(entry.artifact.kind))
  const target = choose(['translated_srt']) || choose(['translated_sidecar', 'subtitle'])
  const source = choose(['source_srt'])
  const glossary = choose(['glossary'])
  const seen = new Set()
  return [[target, target?.artifact.kind === 'subtitle' ? '打开字幕' : `打开${targetSubtitleLabel(task.payload?.target_language || task.target_language)}`], [source, '打开原文字幕'], [glossary, '查看术语表']].flatMap(([entry, label]) => {
    if (!entry || seen.has(entry.artifact.path)) return []
    seen.add(entry.artifact.path)
    return [{ ...entry, label }]
  })
}

function archiveArtifactLabel(artifact) {
  const language = String(artifact?.path || '').match(/(?:^|[/.])(en|ja|ko)(?:[._]|$)/)?.[1] || 'zh'
  return {
    source_srt: '旧版原文 SRT',
    reference_srt: '旧版参考 SRT',
    glossary_path: '旧版术语表',
    translated_srt: `旧版${targetSubtitleLabel(language)}`,
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
