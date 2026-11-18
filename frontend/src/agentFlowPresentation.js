const freezeEntries = (entries) => Object.freeze(
  Object.fromEntries(
    Object.entries(entries).map(([key, value]) => [key, Object.freeze({ ...value })]),
  ),
)

export const AGENT_FLOW_STAGES = Object.freeze([
  Object.freeze({ id: 'analyze', label: '分析素材' }),
  Object.freeze({ id: 'decide', label: '确定路线' }),
  Object.freeze({ id: 'source', label: '取得原文' }),
  Object.freeze({ id: 'glossary', label: 'Glossary 审核' }),
  Object.freeze({ id: 'translate', label: '翻译字幕' }),
  Object.freeze({ id: 'deliver', label: '交付结果' }),
])

/**
 * Presentation-only grouping for Agent phases.
 *
 * Backend phases are deliberately more detailed and branch-specific. The UI
 * should not arrange those phases into one long linear pipeline, because doing
 * so marks unvisited branches as complete. Every real phase instead belongs to
 * one of six stable user-facing stages.
 */
export const AGENT_PHASE_PRESENTATIONS = freezeEntries({
  created: { stageId: 'analyze', label: '等待启动' },
  probe: { stageId: 'analyze', label: '检测视频和字幕' },
  download_video_for_project: { stageId: 'source', label: '下载工程视频' },
  download_video_for_audio_probe: { stageId: 'analyze', label: '下载视频用于音源检测' },
  probe_audio_language: { stageId: 'analyze', label: '检测音源语言' },

  confirm_subtitle: { stageId: 'decide', label: '等待确认字幕源' },
  diagnose_ocr_asr: { stageId: 'decide', label: '等待选择 OCR / ASR 路线' },
  download_video_for_preview: { stageId: 'decide', label: '下载视频用于 OCR 预览' },
  confirm_hybrid_ocr_settings: { stageId: 'decide', label: '等待确认 OCR 范围' },
  confirm_ocr_reuse: { stageId: 'decide', label: '等待确认是否复用 OCR' },

  download_subtitle: { stageId: 'source', label: '下载原文字幕' },
  download_video_for_subtitle: { stageId: 'source', label: '下载字幕路线视频' },
  download_video_for_manual: { stageId: 'source', label: '下载手动处理视频' },
  download_video_for_ocr: { stageId: 'source', label: '下载视频用于 OCR' },
  download_reference_subtitle: { stageId: 'source', label: '下载参考字幕' },
  dual_subtitle_reference: { stageId: 'source', label: '合并原声主字幕与英文参考' },
  download_anchor_subtitle: { stageId: 'source', label: '下载定轴字幕' },
  download_video_for_hybrid: { stageId: 'source', label: '下载视频用于定轴 OCR' },
  hybrid_anchor_ocr: { stageId: 'source', label: '英文定轴 + 原声 OCR' },
  ocr_full: { stageId: 'source', label: 'OCR 提取原文字幕' },
  download_video_for_asr: { stageId: 'source', label: '下载视频用于 ASR' },
  audio_asr: { stageId: 'source', label: 'ASR 提取完整台词' },
  ocr_reference: { stageId: 'source', label: '提取 OCR 参考字幕' },
  asr_ocr_refine: { stageId: 'source', label: '使用 OCR 校准 ASR 原文' },

  generate_glossary: { stageId: 'glossary', label: '生成 Glossary' },
  prepare_glossary_candidates: { stageId: 'glossary', label: '准备审核用原句参考译文' },
  review_glossary: { stageId: 'glossary', label: '等待 Glossary 审核' },
  download_video_for_translation: { stageId: 'translate', label: '下载视频用于字幕交付' },
  translate: { stageId: 'translate', label: '翻译字幕' },
  done: { stageId: 'deliver', label: '已完成' },

  // A cancelled session no longer carries the phase at which it stopped, so
  // it must not imply that any particular stage was reached.
  cancelled: { stageId: null, label: '已中断' },
})

const ROUTE_LABELS = Object.freeze({
  download_target_subtitle: '直接下载中文字幕',
  translate_source_subtitle: '原声字幕翻译',
  translate_auto_subtitle: '自动字幕纠错翻译',
  translate_fallback_subtitle: '中转字幕翻译',
  dual_subtitle_reference: '原声主字幕 + 英文参考',
  hybrid_anchor_ocr: '英文定轴 + 原声 OCR',
  probe_audio_language: '先检测音源语言',
  ocr: 'OCR 复刻画面字幕',
  asr: 'ASR 完整听译',
  asr_ocr_reference: 'ASR 主导 + OCR 参考',
  diagnose_ocr_asr: '等待路线诊断',
})

const OCR_WORKBENCH_QUESTION_KINDS = new Set([
  'diagnose_ocr_asr',
  'confirm_hybrid_ocr_settings',
  'confirm_ocr_settings',
])

const RUNNING_OPERATION_PRESENTATIONS = freezeEntries({
  created: { title: 'Agent 正在启动', message: '正在准备任务环境。' },
  autonomous_download: { title: '正在保存工程视频', message: '视频保存后继续处理；已有字幕会保留，不会因此重新翻译。', download: true },
  probe: { title: '正在检测素材', message: '正在读取视频信息和可用字幕。' },
  download_video_for_project: { title: '正在下载工程视频', message: '路线已确定，视频保存后会继续当前处理。', download: true },
  download_video_for_audio_probe: { title: '正在下载视频', message: '下载完成后将继续检测音源语言。', download: true },
  probe_audio_language: { title: '正在检测音源语言', message: '正在分析音频样本。' },
  download_video_for_preview: { title: '正在下载 OCR 预览视频', message: '下载完成后会自动抽帧并打开字幕区域。', download: true },
  download_subtitle: { title: '正在下载原文字幕', message: '正在取得字幕文件。' },
  download_video_for_subtitle: { title: '正在下载工程视频', message: '字幕路线已确定，视频保存后会继续取得原文字幕。', download: true },
  download_video_for_manual: { title: '正在下载工程视频', message: '视频保存后会进入手动处理页面。', download: true },
  download_video_for_ocr: { title: '正在下载 OCR 视频', message: 'OCR 路线已确定，视频保存后会开始提取字幕。', download: true },
  download_reference_subtitle: { title: '正在下载参考字幕', message: '正在取得参考字幕文件。' },
  download_anchor_subtitle: { title: '正在下载定轴字幕', message: '正在准备 OCR 所需的时间轴。' },
  download_video_for_hybrid: { title: '正在下载视频', message: '下载完成后将运行定轴 OCR。', download: true },
  download_video_for_asr: { title: '正在下载视频', message: '下载完成后将继续 ASR 听译。', download: true },
  dual_subtitle_reference: { title: '正在整理双字幕', message: '正在以原声字幕为主、英文字幕为参考整理原文。' },
  hybrid_anchor_ocr: { title: '正在运行定轴 OCR', message: '正在按字幕时间轴识别画面原文。' },
  ocr_full: { title: '正在提取画面字幕', message: 'OCR 正在逐帧识别，耗时取决于视频长度。' },
  audio_asr: { title: '正在听译音频', message: 'ASR 正在提取完整台词。' },
  ocr_reference: { title: '正在提取 OCR 参考', message: '正在识别画面字幕以校准 ASR 原文。' },
  asr_ocr_refine: { title: '正在校准原文', message: '正在用 OCR 结果纠正 ASR 人名、术语和短语。' },
  generate_glossary: { title: '正在生成 Glossary', message: '正在整理人名、作品名和固定译法。' },
  download_video_for_translation: { title: '正在补全工程视频', message: '视频保存后会继续翻译并把字幕放回素材目录。', download: true },
  translate: { title: '正在翻译字幕', message: '正在保留时间轴生成中文字幕。' },
})

function normalizeKey(value) {
  return String(value || '').trim()
}

export function getAgentPhasePresentation(phase) {
  const key = normalizeKey(phase)
  const known = AGENT_PHASE_PRESENTATIONS[key]
  if (known) return { phase: key, ...known, known: true }
  return {
    phase: key,
    stageId: null,
    label: key || '未开始',
    known: false,
  }
}

export function sessionPhaseLabel(phase) {
  return getAgentPhasePresentation(phase).label
}

export function routeLabel(route) {
  const key = normalizeKey(route)
  return ROUTE_LABELS[key] || key || '等待检测'
}

/**
 * Returns question actions tailored to the current Agent state without
 * mutating the backend snapshot retained by Vue.
 */
export function presentAgentQuestionOptions(session) {
  const question = session?.question && typeof session.question === 'object' ? session.question : {}
  const options = Array.isArray(question.options) ? question.options : []
  const isGlossaryQuestion = normalizeKey(session?.phase) === 'review_glossary'
    || normalizeKey(question.kind) === 'review_glossary'
  const hasInputVideo = Boolean(normalizeKey(session?.result?.input_video))

  return options.flatMap((rawOption) => {
    const option = rawOption && typeof rawOption === 'object' ? { ...rawOption } : {}
    const action = normalizeKey(option.action)
    if (isGlossaryQuestion && action === 'continue_after_glossary') return []
    if (action === 'download_video_for_preview') {
      if (hasInputVideo) return []
      return [{ ...option, label: '下载视频并打开裁框预览' }]
    }
    if (hasInputVideo && action === 'run_ocr') {
      return [{ ...option, label: '按当前字幕区域开始 OCR' }]
    }
    return [option]
  })
}

export function shouldShowAgentOcrWorkbench(session, inputVideo) {
  const kind = normalizeKey(session?.question?.kind)
  const video = normalizeKey(inputVideo) || normalizeKey(session?.result?.input_video)
  return Boolean(
    video
    && normalizeKey(session?.status).toLowerCase() === 'waiting'
    && OCR_WORKBENCH_QUESTION_KINDS.has(kind),
  )
}

function safeDownloadLogProgress(logs) {
  const lines = Array.isArray(logs) ? logs : []
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = String(lines[index] || '')
    if (/already\s+(?:been\s+)?downloaded/i.test(line)) return { alreadyDownloaded: true }
    const match = line.match(/\[download\][^\r\n]*?\b(\d{1,3}(?:\.\d+)?)%/i)
    if (!match) continue
    const value = Number(match[1])
    if (!Number.isFinite(value) || value < 0 || value > 100) continue
    return { percent: Number(value.toFixed(1)) }
  }
  return {}
}

function downloadOperationMessage(session, fallback) {
  const result = session?.result && typeof session.result === 'object' ? session.result : {}
  const jobStatus = normalizeKey(result.current_job_status).toLowerCase()
  if (jobStatus === 'cancel_requested') return '正在停止视频下载。'
  if (jobStatus === 'done') return '视频下载完成，正在整理本地文件。'

  const progress = safeDownloadLogProgress(result.current_job_logs)
  if (progress.alreadyDownloaded) return '检测到视频已在本地，正在直接使用。'
  if (progress.percent !== undefined) return `视频下载进度 ${progress.percent}%。${fallback}`
  return `正在下载视频。${fallback}`
}

/**
 * Builds a safe, user-facing description of a currently running Agent step.
 * Raw job logs, shell commands and file paths are intentionally never copied.
 */
export function agentOperationPresentation(session) {
  if (normalizeKey(session?.status).toLowerCase() !== 'running') return null
  const phase = normalizeKey(session?.phase)
  const presentation = RUNNING_OPERATION_PRESENTATIONS[phase]
  if (!presentation) {
    return {
      title: 'Agent 正在处理',
      message: '正在执行当前任务，请稍候。',
    }
  }
  return {
    title: presentation.title,
    message: presentation.download
      ? downloadOperationMessage(session, presentation.message)
      : presentation.message,
  }
}

export function buildAgentFlowSteps(phase, sessionStatus = '') {
  const presentation = getAgentPhasePresentation(phase)
  const activeIndex = AGENT_FLOW_STAGES.findIndex((stage) => stage.id === presentation.stageId)
  const status = normalizeKey(sessionStatus).toLowerCase()
  const isComplete = presentation.phase === 'done' || status === 'done'

  return AGENT_FLOW_STAGES.map((stage, index) => {
    let state = 'upcoming'
    if (isComplete) state = 'done'
    else if (activeIndex >= 0 && index < activeIndex) state = 'done'
    else if (activeIndex >= 0 && index === activeIndex) {
      state = status === 'failed' || status === 'cancelled' ? 'failed' : 'active'
    }
    return {
      ...stage,
      index: index + 1,
      state,
    }
  })
}
