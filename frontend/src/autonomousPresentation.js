export function currentLocalReview(result) {
  const review = result?.local_translation_review
  if (!review || result.local_translation_review_current === false) return null
  if (result.local_translation_review_current === true || review.translated_srt === result.translated_srt) return review
  return null
}

const publicToolNames = {
  inspect_target: '检查现成中文字幕', deliver_target: '交付现成中文字幕', review_target: '对照原文抽查中文',
  read_subtitles: '查看字幕上下文', transcribe_clip: '局部音频核查', sample_frames: '抽帧观察',
  analyze_frames: '分析画面', ocr_trial: 'OCR 试跑', review_translation: '局部译文复核',
  review_audio: '局部重听', compare_sources: '对照字幕来源', select_source: '选择原文',
  detect_language: '检测音源语言', ask_target: '确认现成字幕疑点', ask_user: '询问字幕疑点',
  probe: '检查链接', download: '下载视频', captions: '获取外挂字幕', inspect: '检查原文',
  glossary: '准备术语审核', translate: '翻译字幕', align: '校准时间轴', verify: '检查译文',
  finish: '交付字幕', patch: '局部修正原文', asr: '音频识别', ocr: '画面文字识别',
}

export function friendlyAgentText(value) {
  if (typeof value !== 'string') return ''
  return value.replace(/\b[a-z]+(?:_[a-z]+)*\b/g, word => publicToolNames[word] || word)
}

export function evidenceRefLabel(value) {
  if (value === 'goal') return '任务目标'
  if (value === 'metadata') return '视频信息'
  if (typeof value !== 'string') return ''
  if (value.startsWith('event:')) return `操作记录 #${value.slice(6)}`
  if (value.startsWith('target:')) return `中文字幕检查 #${value.slice(7)}`
  if (value.startsWith('clip:')) return `局部音频 #${value.slice(5)}`
  if (value.startsWith('source:')) return `原文来源 #${value.match(/\d+$/)?.[0] || ''}`
  return value
}

export function publicAgentDecision(result) {
  const decision = result?.autonomous_decision
  if (result?.autonomous_controller_version < 2 || !decision || typeof decision.summary !== 'string') return null
  return {
    summary: friendlyAgentText(decision.summary),
    reason: friendlyAgentText(decision.reason),
    nextCheck: friendlyAgentText(decision.next_check),
    plan: Array.isArray(decision.plan) ? decision.plan.filter(v => typeof v === 'string').map(friendlyAgentText) : [],
    unknowns: Array.isArray(decision.unknowns) ? decision.unknowns.filter(v => typeof v === 'string').map(friendlyAgentText) : [],
    evidenceRefs: Array.isArray(decision.evidence_refs) ? decision.evidence_refs.filter(v => typeof v === 'string').map(evidenceRefLabel) : [],
  }
}

export function autonomousDraftMessage(session) {
  if (session?.status === 'waiting' && session?.phase === 'autonomous_verification_review') return '结构检查已完成，尚有译文疑点需要局部复核；当前为草稿，未标记完成。'
  if (session?.status === 'running' && session?.phase === 'autonomous_download') return '中文字幕已保留，正在保存视频素材，不会重新翻译。'
  if (session?.status === 'failed') return '中文字幕已保留，但最终检查尚未完成。工具失败详情见操作记录，不是等待检测。'
  if (session?.status === 'done') return session.result?.quality_warning || '已完成自动检查；语义检查为抽查，不代表人工逐字核准。'
  if (session?.status === 'waiting') return '字幕已保留，正在等待你补充具体疑点的线索。'
  return '正在检查当前译稿；只对具体疑点做局部复核，不重翻整片。'
}
