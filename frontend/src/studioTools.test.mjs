import test from 'node:test'
import assert from 'node:assert/strict'
import { assetRoleLabel, fileLabel, localModifiedLabel, filterLibraryProjects, projectMediaSummary, visibleSubtitleRows, projectMedia, preferredProjectSubtitle } from './studioTools.js'

test('BCC delivery copies never replace SRT as the subtitle-editing shortcut', () => {
  const srt = { path: '/task/zh.srt', role: 'translated', delivered_at: 1 }
  const bcc = { path: '/task/zh.bcc', role: 'translated', delivered_at: 2 }
  assert.equal(preferredProjectSubtitle({ subtitles: [bcc, srt] }), srt)
})

test('file labels handle both path styles without changing the original', () => {
  assert.equal(fileLabel('/example/한글 中文.srt'), '한글 中文.srt')
  assert.equal(fileLabel('C:\\example\\zh.srt'), 'zh.srt')
  assert.equal(fileLabel(''), '未选择文件')
})
test('library searches file names, filters media kind and sorts a copy', () => {
  const projects = [{ name: 'B', modified_at: 1, videos: [{ name: 'Clip.MP4' }] }, { name: 'A', modified_at: 2, audios: [{ name: 'sound.wav' }], counts: { audios: 1 } }]
  assert.equal(filterLibraryProjects(projects)[0].name, 'A')
  assert.equal(filterLibraryProjects(projects, { query: 'clip', kind: 'video' })[0].name, 'B')
  assert.equal(filterLibraryProjects(projects, { query: 'clip', kind: 'audio' }).length, 0)
  assert.deepEqual(projects.map(p => p.name), ['B', 'A'])
  assert.equal(projectMediaSummary(projects[0]), '1 视频')
  assert.equal(projectMediaSummary({ counts: { subtitles: 2 } }), '2 字幕')
  assert.equal(projectMediaSummary({ videos: [], counts: { videos: 5 } }), '暂无媒体文件')
  assert.equal(filterLibraryProjects([{ videos: [], counts: { videos: 5 } }], { kind: 'video' }).length, 0)
})
test('invalid media timestamps use the provided label safely', () => {
  assert.equal(localModifiedLabel({ modified_at: 'NaN', modified_label: '旧记录' }), '旧记录')
  assert.equal(localModifiedLabel({ modified_at: 1e100 }), '')
  assert(localModifiedLabel({ modified_at: 1795003351 }))
})
test('project shortcuts use actual media and prefer labelled translations without mutating files', () => {
  assert.equal(projectMedia(null), null)
  assert.deepEqual(projectMedia({ audios: [{ path: '/a.wav' }] }), { kind: 'audio', path: '/a.wav' })
  assert.deepEqual(projectMedia({ primary_video: '/main.mp4', videos: [{ path: '/other.mp4' }], primary_audio: '/a.wav' }), { kind: 'video', path: '/main.mp4' })
  const files = [{ path: '/source.srt', role: 'source', modified_at: 9 }, { path: '/zh.srt', role: 'translated', modified_at: 1 }, { path: '/other.srt', modified_at: 10 }]
  assert.equal(preferredProjectSubtitle({ subtitles: files }).path, '/zh.srt')
  assert.equal(files[0].path, '/source.srt')
  assert.equal(preferredProjectSubtitle({ subtitles: [{ name: 'missing path' }] }), null)
  assert.equal(preferredProjectSubtitle({ subtitles: [{ path: '/older.srt', role: 'translated', modified_at: 1 }, { path: '/newer.srt', role: 'translated', modified_at: 2 }] }).path, '/newer.srt')
})
test('subtitle search retains original row indices and UIDs', () => {
  const cues = [{ uid: 'one', text: '你好', start_time: '00:00:01,000' }, { uid: 'two', text: 'Second line', start_time: '00:00:02,000' }]
  assert.equal(visibleSubtitleRows(cues, 'second')[0].index, 1)
  assert.equal(visibleSubtitleRows(cues, '2')[0].cue.uid, 'two')
  assert.equal(visibleSubtitleRows(cues, '00:00:01')[0].cue.uid, 'one')
  assert.equal(visibleSubtitleRows(cues, 'missing').length, 0)
  assert.equal(cues.length, 2)
})

test('current delivered translation wins over freshly copied archives', () => {
  const files = [
    { path: '/archive/en.srt', role: 'translated', is_archived: true, modified_at: 100 },
    { path: '/current/en.srt', role: 'translated', delivered_at: 20, modified_at: 10 },
    { path: '/older/en.srt', role: 'translated', delivered_at: 15, modified_at: 50 },
  ]
  assert.equal(preferredProjectSubtitle({ subtitles: files }).path, '/current/en.srt')
  assert.equal(assetRoleLabel({ role: 'translated', language: 'en' }), '英文译文')
  assert.equal(assetRoleLabel({ role: 'source', language: 'zh' }), '中文原文字幕')
  assert.equal(assetRoleLabel({ role: 'translated' }), '译文')
})
