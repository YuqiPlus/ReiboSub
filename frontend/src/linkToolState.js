export function normalizeLinkInput(value) {
  return String(value || '').trim()
}

export function resolveLinkActionUrl(inputUrl, probeUrl = '') {
  return normalizeLinkInput(inputUrl) || normalizeLinkInput(probeUrl)
}

export function isProbeResponseCurrent(requestedUrl, currentUrl) {
  return normalizeLinkInput(requestedUrl) === normalizeLinkInput(currentUrl)
}

export function shouldClearLinkProbe(probe, probedInputUrl, nextUrl) {
  if (!probe) return false
  return !isProbeResponseCurrent(probedInputUrl, nextUrl)
}

export function looksLikeYoutubeInput(value) {
  const input = normalizeLinkInput(value)
  if (/^[A-Za-z0-9_-]{11}$/.test(input)) return true
  return /(?:youtube\.com|youtu\.be)\//i.test(input)
}

export function videoFormatChoiceValue(format) {
  const id = normalizeLinkInput(format?.id)
  return id ? `format:${id}` : ''
}

export function selectedVideoFormat(formats, choice) {
  const value = normalizeLinkInput(choice)
  if (!value.startsWith('format:')) return null
  const id = value.slice('format:'.length)
  return (Array.isArray(formats) ? formats : []).find((format) => normalizeLinkInput(format?.id) === id) || null
}
