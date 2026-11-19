export function fileLabel(value) {
  return String(value || '').split(/[\\/]/).filter(Boolean).at(-1) || '未选择文件'
}

export function localModifiedLabel(item) {
  const seconds = Number(item?.modified_at || 0)
  if (!Number.isFinite(seconds) || seconds <= 0 || !Number.isFinite(new Date(seconds * 1000).getTime())) return item?.modified_label || ''
  return new Intl.DateTimeFormat(undefined, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(seconds * 1000))
}

export function projectMediaSummary(project) {
  return [['videos', '视频'], ['audios', '音频'], ['subtitles', '字幕']].flatMap(([key, label]) => {
    const count = project[key]?.length ?? project.counts?.[key] ?? 0
    return count ? [`${count} ${label}`] : []
  }).join(' · ') || '暂无媒体文件'
}

export function projectMedia(project) {
  const video = project?.primary_video || project?.videos?.find(file => file.path)?.path
  if (video) return { kind: 'video', path: video }
  const audio = project?.primary_audio || project?.audios?.find(file => file.path)?.path
  return audio ? { kind: 'audio', path: audio } : null
}

export function preferredProjectSubtitle(project) {
  const files = (project?.subtitles || []).filter(file => file.path)
  // Prefer an explicitly labelled translation; never infer a language from the
  // project title. Recent files win only within the same role.
  const rank = file => file.role === 'translated' ? 0 : file.role === 'source' ? 1 : 2
  return [...files].sort((a, b) => rank(a) - rank(b) || Number(!!a.is_archived) - Number(!!b.is_archived) || (Number(b.delivered_at || b.modified_at) || 0) - (Number(a.delivered_at || a.modified_at) || 0))[0] || null
}

export function assetRoleLabel(item) {
  const language = { zh: '中文', en: '英文', ja: '日文', ko: '韩文' }[item.language] || ''
  if (item.role === 'translated') return `${language}译文`
  if (item.role === 'source') return `${language}原文字幕`
  const role = item.role || item.kind
  return { downloaded: '外挂字幕', video: '视频', audio: '音频', subtitle: '字幕' }[role] || role || ''
}

export function filterLibraryProjects(projects, { query = '', kind = 'all', sort = 'recent' } = {}) {
  const key = { video: 'videos', audio: 'audios', subtitle: 'subtitles' }[kind]
  const needle = String(query).trim().toLocaleLowerCase()
  return projects.filter(project => {
    if (key && !(project[key]?.length ?? project.counts?.[key] ?? 0)) return false
    const fields = [project.name, project.source_url, project.path, ...['videos', 'audios', 'subtitles'].flatMap(key => (project[key] || []).map(file => file.name || fileLabel(file.path)))]
    return !needle || fields.some(value => String(value || '').toLocaleLowerCase().includes(needle))
  }).sort((a, b) => sort === 'name' ? String(a.name || '').localeCompare(String(b.name || '')) : (Number(b.modified_at) || 0) - (Number(a.modified_at) || 0))
}

export function visibleSubtitleRows(cues, query = '') {
  const needle = String(query).trim().toLocaleLowerCase()
  return cues.map((cue, index) => ({ cue, index })).filter(({ cue, index }) => !needle || [String(index + 1), cue.text, cue.start_time, cue.end_time].some(value => String(value || '').toLocaleLowerCase().includes(needle)))
}
