import test from 'node:test'
import assert from 'node:assert/strict'
import { mediaClock, questionMediaUrl, questionMediaWindow } from './questionMedia.js'

test('question media encodes non-ASCII paths and literal hashes separately from the time fragment', () => {
  const path = '/videos/[BESTie] #10 현장!.mp4'
  const url = questionMediaUrl(path, questionMediaWindow({ video_start: 183.833, video_end: 188.127 }))
  const parsed = new URL(url, 'http://localhost')
  assert.equal(parsed.searchParams.get('path'), path)
  assert.equal(parsed.hash, '#t=183.833,188.127')
  assert.equal(mediaClock(183.833), '3:03')
})

test('legacy questions without valid times never get an undefined or invalid media fragment', () => {
  for (const question of [{}, { video_start: '' }, { video_start: null }, { video_start: -1 }, { video_start: 'NaN' }]) {
    assert.equal(questionMediaWindow(question), null)
  }
  for (const end of [undefined, null, '', 1, 'invalid']) {
    const window = questionMediaWindow({ video_start: 10, video_end: end })
    assert.deepEqual(window, { start: 10, end: null })
    assert.equal(questionMediaUrl('/video.mp4', window), '/api/file?path=%2Fvideo.mp4#t=10')
  }
  assert.equal(questionMediaUrl(''), '')
  assert.equal(questionMediaUrl('/video.mp4'), '/api/file?path=%2Fvideo.mp4')
})
