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
