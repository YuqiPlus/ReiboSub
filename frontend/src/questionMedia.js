export function questionMediaWindow(question = {}) {
  const start = Number(question.video_start)
  const end = Number(question.video_end)
  if (question.video_start == null || question.video_start === '' || !Number.isFinite(start) || start < 0) return null
  return { start, end: Number.isFinite(end) && end > start ? end : null }
}

export function questionMediaUrl(path, window = null) {
  if (!path) return ''
  const url = `/api/file?path=${encodeURIComponent(path)}`
  return window ? `${url}#t=${window.start}${window.end == null ? '' : `,${window.end}`}` : url
}

export function mediaClock(seconds) {
  const value = Math.max(0, Math.floor(seconds))
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`
}
