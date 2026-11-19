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

export function looksLikeVideoInput(value) {
  const input = normalizeLinkInput(value)
  if (/^(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]*)$/.test(input)) return true
  if (/^(?:(?:https?:\/\/)?(?:www\.|m\.)?bilibili\.com\/video\/(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]*)(?:[/?#]|$)|(?:https?:\/\/)?(?:www\.)?b23\.tv\/[A-Za-z0-9]+(?:[/?#]|$))/i.test(input)) return true
  return looksLikeYoutubeInput(input)
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
