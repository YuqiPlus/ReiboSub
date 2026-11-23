import { targetSubtitleLabel, sessionTargetLanguage } from './translationLanguages.js'

export function currentLocalReview(result) {
  const review = result?.local_translation_review
  if (!review || result.local_translation_review_current === false) return null
  if (result.local_translation_review_current === true || review.translated_srt === result.translated_srt) return review
  return null
}

export function subtitleSourceLabel(result) {
  if (result?.delivery_mode === 'existing_target_subtitle') return `字幕来源：现成${targetSubtitleLabel(result.target_language)}，未重新翻译`
  if (result?.source_kind === 'ocr') return '原文来源：画面内嵌字幕 · OCR 3.0'
  if (result?.source_kind === 'asr') return '原文来源：语音识别 · ASR 2.2'
  if (result?.source_kind === 'captions') return '原文来源：外挂字幕'
  if (result?.source_kind === 'mixed') return '原文来源：OCR 画面配字＋原声字幕（混合）'
  if (result?.screen_source_assessment?.enabled && result.screen_source_assessment.status === 'present') {
    return '已发现内嵌字幕，优先提取画面文字'
  }
  return ''
}

const publicToolNames = {
  inspect_target: '检查现成目标字幕', deliver_target: '交付现成目标字幕', review_target: '对照原文抽查目标字幕',
  read_subtitles: '查看字幕上下文', transcribe_clip: '局部音频核查', sample_frames: '抽帧观察',
  analyze_frames: '分析画面', ocr_trial: 'OCR 试跑', review_translation: '局部译文复核',
  review_audio: '局部重听', compare_sources: '对照字幕来源', select_source: '选择原文',
  detect_language: '检测音源语言', ask_target: '确认现成字幕疑点', ask_user: '询问字幕疑点',
  probe: '检查链接', download: '下载视频', captions: '获取外挂字幕', inspect: '检查原文',
  glossary: '准备术语审核', translate: '翻译字幕', align: '校准时间轴', verify: '检查译文',
  finish: '交付字幕', patch: '局部修正原文', asr: '音频识别', ocr: '画面文字识别', refine_screen_ocr: '核查画面文字候选', finalize_screen_ocr: '整理内嵌字幕',
}

export function friendlyAgentText(value) {
  if (typeof value !== 'string') return ''
  // Models sometimes return numeric HTML entities. Decode characters, never
  // interpret markup; Vue still renders the resulting string as plain text.
  return value.replace(/&#(x[\da-f]+|\d+);/gi, (entity, number) => {
    const point = number[0].toLowerCase() === 'x' ? Number.parseInt(number.slice(1), 16) : Number(number)
    return point >= 32 && point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff) ? String.fromCodePoint(point) : entity
  }).replace(/\b[a-z]+(?:_[a-z]+)*\b/g, word => publicToolNames[word] || word)
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
  if (session?.question?.kind === 'autonomous_issue_review') return '请在上方处理字幕疑点；只保存你指定的条目，可随时保留未确认项并结束。'
  if (session?.result?.completion_status === 'completed_manually') return session.result.quality_warning || '任务已结束，译文疑点已按人工指定处理；并非机器已核准原文。'
  if (session?.result?.completion_status === 'completed_with_issues') return session.result.quality_warning || '任务已结束，已保存有未确认项的字幕草稿；未标记验收通过，不再等待输入。'
  if (session?.question?.kind === 'autonomous_review_result') return '已使用保存的线索完成局部复核；草稿保留，仍有无法核准的条目，不再重复索要线索。'
  if (session?.status === 'waiting' && session?.phase === 'autonomous_verification_review') return '结构检查已完成，尚有译文疑点需要局部复核；当前为草稿，未标记完成。'
  if (session?.status === 'running' && session?.phase === 'autonomous_download') return `${targetSubtitleLabel(sessionTargetLanguage(session))}已保留，正在保存视频素材，不会重新翻译。`
  if (session?.status === 'failed') return `${targetSubtitleLabel(sessionTargetLanguage(session))}已保留，但最终检查尚未完成。工具失败详情见操作记录，不是等待检测。`
  if (session?.status === 'done') return session.result?.quality_warning || '已完成自动检查；语义检查为抽查，不代表人工逐字核准。'
  if (session?.status === 'waiting') return '字幕已保留，正在等待你补充具体疑点的线索。'
  return '正在检查当前译稿；只对具体疑点做局部复核，不重翻整片。'
}
