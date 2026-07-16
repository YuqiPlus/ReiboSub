const DEFAULT_CUE_DURATION_SECONDS = 2
const MILLISECONDS_PER_SECOND = 1000

let fallbackUidCounter = 0

/**
 * Parse a numeric second value or an SRT timestamp into seconds.
 */
export function parseSrtTime(value) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('字幕时间必须是有限数字')
    return value
  }

  const text = String(value ?? '').trim()
  if (!text) throw new TypeError('字幕时间不能为空')
  if (/^-?\d+(?:\.\d+)?$/.test(text)) {
    const seconds = Number(text)
    if (!Number.isFinite(seconds)) throw new TypeError(`无效字幕时间：${text}`)
    return seconds
  }

  const match = text.match(/^(\d+):(\d{2}):(\d{2})[,.](\d{1,3})$/)
  if (!match) throw new TypeError(`无效 SRT 时间：${text}`)

  const hours = Number(match[1])
  const minutes = Number(match[2])
  const seconds = Number(match[3])
  const milliseconds = Number(match[4].padEnd(3, '0'))
  if (minutes > 59 || seconds > 59) throw new TypeError(`无效 SRT 时间：${text}`)
  return hours * 3600 + minutes * 60 + seconds + milliseconds / MILLISECONDS_PER_SECOND
}

/**
 * Format seconds using the same millisecond rounding as the Python SRT writer.
 */
export function formatSrtTime(value) {
  const seconds = parseSrtTime(value)
  const totalMilliseconds = Math.max(0, Math.round(seconds * MILLISECONDS_PER_SECOND))
  const hours = Math.floor(totalMilliseconds / 3_600_000)
  const afterHours = totalMilliseconds % 3_600_000
  const minutes = Math.floor(afterHours / 60_000)
  const afterMinutes = afterHours % 60_000
  const wholeSeconds = Math.floor(afterMinutes / MILLISECONDS_PER_SECOND)
  const milliseconds = afterMinutes % MILLISECONDS_PER_SECOND
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(wholeSeconds).padStart(2, '0')},${String(milliseconds).padStart(3, '0')}`
}

/**
 * Create a cue UID in browsers and Node without importing a platform module.
 */
export function createSubtitleCueUid() {
  const randomUuid = globalThis.crypto?.randomUUID
  if (typeof randomUuid === 'function') return randomUuid.call(globalThis.crypto)
  fallbackUidCounter += 1
  return `cue-${Date.now().toString(36)}-${fallbackUidCounter.toString(36)}`
}

/**
 * Return a cloned cue with canonical numeric and SRT-formatted time fields.
 */
export function normalizeSubtitleCue(cue, { index, uid } = {}) {
  if (!cue || typeof cue !== 'object' || Array.isArray(cue)) {
    throw new TypeError('字幕条目必须是对象')
  }

  const start = canonicalSeconds(timeSource(cue, 'start'))
  const end = canonicalSeconds(timeSource(cue, 'end'))
  assertValidInterval(start, end)

  return {
    ...cue,
    uid: normalizedUid(uid ?? cue.uid),
    index: normalizeCueIndex(index ?? cue.index),
    start,
    end,
    start_time: formatSrtTime(start),
    end_time: formatSrtTime(end),
    text: String(cue.text ?? ''),
  }
}

/**
 * Normalize every cue and number it according to its current array order.
 */
export function renumberSubtitleCues(cues) {
  assertCueArray(cues)
  const seenUids = new Set()
  return cues.map((cue, cueIndex) => {
    const existingUid = String(cue?.uid ?? '').trim()
    const uid = existingUid && !seenUids.has(existingUid)
      ? existingUid
      : nextAvailableUid(seenUids)
    seenUids.add(uid)
    return normalizeSubtitleCue(cue, { index: cueIndex + 1, uid })
  })
}

/**
 * Add a cue at the current player time and sort all cues by start time.
 * Existing and newly-created overlapping intervals are intentionally retained.
 */
export function insertSubtitleCueAtTime(cues, currentSeconds, options = {}) {
  const normalized = renumberSubtitleCues(cues)
  const start = canonicalSeconds(currentSeconds)
  const duration = normalizeDuration(options.durationSeconds)
  const uid = uniqueUidForCues(normalized, options.uid)
  const insertedCue = normalizeSubtitleCue({
    uid,
    index: normalized.length + 1,
    start,
    end: canonicalSeconds(start + duration),
    text: options.text ?? '',
  })

  const sorted = [...normalized, insertedCue]
    .map((cue, order) => ({ cue, order }))
    .sort((left, right) => left.cue.start - right.cue.start || left.order - right.order)
    .map((item) => item.cue)
  return insertionResult(renumberSubtitleCues(sorted), insertedCue.uid)
}

/**
 * Insert a cue immediately before or after an existing cue in array order.
 * The default interval is adjacent to the anchor when possible; overlap remains allowed.
 */
export function insertSubtitleCueRelative(cues, anchorUid, position, options = {}) {
  const normalized = renumberSubtitleCues(cues)
  const anchorIndex = normalized.findIndex((cue) => cue.uid === anchorUid)
  if (anchorIndex < 0) throw new RangeError(`找不到字幕条目：${anchorUid}`)
  if (position !== 'before' && position !== 'after') {
    throw new TypeError("插入位置必须是 'before' 或 'after'")
  }

  const anchor = normalized[anchorIndex]
  const duration = normalizeDuration(options.durationSeconds)
  const uid = uniqueUidForCues(normalized, options.uid)
  let start
  let end
  if (position === 'before' && anchor.start > 0) {
    end = anchor.start
    start = Math.max(0, end - duration)
  } else if (position === 'before') {
    start = 0
    end = duration
  } else {
    start = anchor.end
    end = start + duration
  }

  const insertedCue = normalizeSubtitleCue({
    uid,
    index: 0,
    start: canonicalSeconds(start),
    end: canonicalSeconds(end),
    text: options.text ?? '',
  })
  const insertIndex = position === 'before' ? anchorIndex : anchorIndex + 1
  const next = [...normalized]
  next.splice(insertIndex, 0, insertedCue)
  return insertionResult(renumberSubtitleCues(next), insertedCue.uid)
}

/**
 * Set one cue boundary from the current player time.
 * Only the cue's own interval is validated; overlaps with adjacent cues are valid.
 */
export function setSubtitleCueBoundary(cues, uid, boundary, currentSeconds) {
  if (boundary !== 'start' && boundary !== 'end') {
    throw new TypeError("字幕边界必须是 'start' 或 'end'")
  }

  const normalized = renumberSubtitleCues(cues)
  const cueIndex = normalized.findIndex((cue) => cue.uid === uid)
  if (cueIndex < 0) throw new RangeError(`找不到字幕条目：${uid}`)

  const cue = normalized[cueIndex]
  const seconds = canonicalSeconds(currentSeconds)
  const start = boundary === 'start' ? seconds : cue.start
  const end = boundary === 'end' ? seconds : cue.end
  assertValidInterval(start, end)

  const updatedCue = normalizeSubtitleCue({
    ...cue,
    start,
    end,
    start_time: formatSrtTime(start),
    end_time: formatSrtTime(end),
  }, { index: cueIndex + 1 })
  const next = [...normalized]
  next[cueIndex] = updatedCue
  return { cues: next, cue: updatedCue, cueUid: updatedCue.uid, index: cueIndex }
}

/**
 * Build the exact playable window for one cue.
 * Formatted SRT fields intentionally take precedence over stale numeric fields.
 */
export function buildSubtitleCuePreview(cue, { videoDuration } = {}) {
  if (!cue || typeof cue !== 'object' || Array.isArray(cue)) {
    throw new TypeError('字幕条目必须是对象')
  }

  const start = canonicalSeconds(timeSource(cue, 'start'))
  const end = canonicalSeconds(timeSource(cue, 'end'))
  assertValidInterval(start, end)

  const duration = normalizeVideoDuration(videoDuration)
  const seekTime = duration === null ? start : Math.min(start, duration)
  const stopTime = duration === null ? end : Math.min(end, duration)
  if (stopTime <= seekTime) {
    throw new RangeError('字幕时间超出视频可播放范围')
  }

  return {
    cueUid: String(cue.uid ?? '').trim(),
    seekTime,
    stopTime,
    subtitleStart: seekTime,
    subtitleEnd: stopTime,
    text: String(cue.text ?? ''),
  }
}

/**
 * Describe whether a cue should be visible and whether bounded playback should stop.
 * Both intervals use an inclusive start and exclusive end.
 */
export function getSubtitlePreviewState(preview, currentTime, { tolerance = 0 } = {}) {
  if (!preview || typeof preview !== 'object' || Array.isArray(preview)) {
    throw new TypeError('字幕预览窗口必须是对象')
  }

  const subtitleStart = canonicalSeconds(preview.subtitleStart)
  const subtitleEnd = canonicalSeconds(preview.subtitleEnd)
  const stopTime = canonicalSeconds(preview.stopTime)
  assertValidInterval(subtitleStart, subtitleEnd)
  if (stopTime < subtitleEnd) {
    throw new RangeError('字幕预览停止时间不能早于字幕结束时间')
  }

  const seconds = canonicalSeconds(currentTime)
  const toleranceSeconds = normalizeTolerance(tolerance)
  const reachedSubtitleStart = seconds + toleranceSeconds >= subtitleStart
  const reachedSubtitleEnd = seconds + toleranceSeconds >= subtitleEnd
  return {
    active: reachedSubtitleStart && !reachedSubtitleEnd,
    shouldStop: seconds + toleranceSeconds >= stopTime,
  }
}

export function isSubtitlePreviewActive(preview, currentTime, options = {}) {
  return getSubtitlePreviewState(preview, currentTime, options).active
}

function timeSource(cue, boundary) {
  const formattedKey = `${boundary}_time`
  if (Object.prototype.hasOwnProperty.call(cue, formattedKey)) return cue[formattedKey]
  if (Object.prototype.hasOwnProperty.call(cue, boundary)) return cue[boundary]
  throw new TypeError(`字幕缺少${boundary === 'start' ? '开始' : '结束'}时间`)
}

function canonicalSeconds(value) {
  const seconds = parseSrtTime(value)
  if (seconds < 0) throw new RangeError('字幕时间不能为负数')
  return Math.round(seconds * MILLISECONDS_PER_SECOND) / MILLISECONDS_PER_SECOND
}

function normalizeDuration(value) {
  const duration = canonicalSeconds(value ?? DEFAULT_CUE_DURATION_SECONDS)
  if (duration <= 0) throw new RangeError('字幕时长必须大于 0')
  return duration
}

function normalizeVideoDuration(value) {
  if (value === undefined || value === null || value === '') return null
  if (typeof value === 'number' && !Number.isFinite(value)) return null
  const parsedDuration = parseSrtTime(value)
  if (parsedDuration <= 0) throw new RangeError('视频时长必须大于 0')
  const duration = canonicalSeconds(parsedDuration)
  if (duration <= 0) throw new RangeError('视频时长必须大于 0')
  return duration
}

function normalizeTolerance(value) {
  const tolerance = Number(value ?? 0)
  if (!Number.isFinite(tolerance)) throw new TypeError('字幕预览容差必须是有限数字')
  if (tolerance < 0) throw new RangeError('字幕预览容差不能为负数')
  return Math.round(tolerance * MILLISECONDS_PER_SECOND) / MILLISECONDS_PER_SECOND
}

function assertValidInterval(start, end) {
  if (end <= start) throw new RangeError('字幕结束时间必须大于开始时间')
}

function normalizedUid(value) {
  const uid = String(value ?? '').trim()
  return uid || createSubtitleCueUid()
}

function uniqueUidForCues(cues, preferredUid) {
  const seenUids = new Set(cues.map((cue) => cue.uid))
  const preferred = String(preferredUid ?? '').trim()
  return preferred && !seenUids.has(preferred) ? preferred : nextAvailableUid(seenUids)
}

function nextAvailableUid(seenUids) {
  let uid = createSubtitleCueUid()
  while (seenUids.has(uid)) uid = createSubtitleCueUid()
  return uid
}

function normalizeCueIndex(value) {
  const index = Number(value)
  return Number.isInteger(index) && index > 0 ? index : 1
}

function assertCueArray(cues) {
  if (!Array.isArray(cues)) throw new TypeError('字幕列表必须是数组')
}

function insertionResult(cues, cueUid) {
  const index = cues.findIndex((cue) => cue.uid === cueUid)
  return { cues, cue: cues[index], cueUid, index }
}
