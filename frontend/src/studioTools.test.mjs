import test from 'node:test'
import assert from 'node:assert/strict'
import { fileLabel, localModifiedLabel, filterLibraryProjects, projectMediaSummary, visibleSubtitleRows } from './studioTools.js'

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
test('subtitle search retains original row indices and UIDs', () => {
  const cues = [{ uid: 'one', text: '你好', start_time: '00:00:01,000' }, { uid: 'two', text: 'Second line', start_time: '00:00:02,000' }]
  assert.equal(visibleSubtitleRows(cues, 'second')[0].index, 1)
  assert.equal(visibleSubtitleRows(cues, '2')[0].cue.uid, 'two')
  assert.equal(visibleSubtitleRows(cues, '00:00:01')[0].cue.uid, 'one')
  assert.equal(visibleSubtitleRows(cues, 'missing').length, 0)
  assert.equal(cues.length, 2)
})
