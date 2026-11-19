export const targetLanguages = [
  { id: 'zh', label: '中文', subtitle: '中文字幕' },
  { id: 'en', label: '英语', subtitle: '英文字幕' },
  { id: 'ja', label: '日语', subtitle: '日文字幕' },
  { id: 'ko', label: '韩语', subtitle: '韩文字幕' },
]

export function translationDefaults(value, youtubeSource = 'korean') {
  const input = String(value || '').trim()
  const bili = /^(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]*)$/.test(input)
    || /^(?:https?:\/\/)?(?:(?:www\.|m\.)?bilibili\.com\/|(?:www\.)?b23\.tv\/)/i.test(input)
  return bili ? { source: 'chinese', target: 'en' } : { source: youtubeSource, target: 'zh' }
}

export function targetSubtitleLabel(language = 'zh') {
  return targetLanguages.find((item) => item.id === language)?.subtitle || '译文字幕'
}

export function sessionTargetLanguage(session) {
  // Old saved sessions were Chinese, irrespective of their video platform.
  return session?.payload?.target_language || session?.result?.target_language || 'zh'
}
