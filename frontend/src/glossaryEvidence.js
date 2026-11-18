export function evidenceKey(item) {
  return JSON.stringify([item?.section, item?.index, item?.source])
}

export function evidenceWindow(evidence, { padding = 3, duration } = {}) {
  const start = evidence?.start, end = evidence?.end
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) throw new Error('原句时间无效，无法定位片段。')
  if (![3, 10].includes(padding)) throw new Error('片段上下文范围无效。')
  const knownDuration = Number.isFinite(duration) && duration > 0 ? duration : Infinity
  if (start >= knownDuration) throw new Error('原句时间超出视频时长，请检查字幕和素材是否对应。')
  return { start: Math.max(0, start - padding), end: Math.min(end + padding, knownDuration) }
}

export function evidenceTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '--:--'
  const whole = Math.floor(seconds)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  return `${hours ? `${hours}:` : ''}${String(minutes).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
}

export function evidenceCaptions(rows, time) {
  return (rows || []).filter(c => Number.isFinite(c.start) && Number.isFinite(c.end) && c.start <= time && time < c.end)
}
