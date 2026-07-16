import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildSubtitleCuePreview,
  createSubtitleCueUid,
  formatSrtTime,
  getSubtitlePreviewState,
  insertSubtitleCueAtTime,
  insertSubtitleCueRelative,
  isSubtitlePreviewActive,
  normalizeSubtitleCue,
  parseSrtTime,
  renumberSubtitleCues,
  setSubtitleCueBoundary,
} from './subtitleEditorTools.js'

function cue(uid, start, end, text = uid) {
  return { uid, index: 99, start, end, text }
}

test('parses numeric seconds and SRT timestamps and formats millisecond rounding', () => {
  assert.equal(parseSrtTime(62.345), 62.345)
  assert.equal(parseSrtTime('62.345'), 62.345)
  assert.equal(parseSrtTime('01:02:03,045'), 3723.045)
  assert.equal(parseSrtTime('01:02:03.45'), 3723.45)
  assert.equal(formatSrtTime(62.3456), '00:01:02,346')
  assert.equal(formatSrtTime(-0.2), '00:00:00,000')
  assert.throws(() => parseSrtTime('00:61:00,000'), /无效 SRT 时间/)
})

test('normalizes both numeric and formatted cue time fields', () => {
  const result = normalizeSubtitleCue({
    uid: 'one',
    index: 7,
    start: 99,
    end: 100,
    start_time: '00:00:01,234',
    end_time: '00:00:02,345',
    text: '字幕',
  })

  assert.deepEqual(result, {
    uid: 'one',
    index: 7,
    start: 1.234,
    end: 2.345,
    start_time: '00:00:01,234',
    end_time: '00:00:02,345',
    text: '字幕',
  })
})

test('renumbers cues by array order while preserving stable UIDs', () => {
  const result = renumberSubtitleCues([
    cue('later', 5, 6),
    cue('earlier', 1, 2),
  ])

  assert.deepEqual(result.map((item) => [item.index, item.uid]), [[1, 'later'], [2, 'earlier']])
  assert.equal(result[0].start_time, '00:00:05,000')
})

test('renumbering repairs missing or duplicate UIDs', () => {
  const result = renumberSubtitleCues([
    cue('duplicate', 0, 1),
    cue('duplicate', 1, 2),
    { start: 2, end: 3, text: 'missing uid' },
  ])

  assert.equal(new Set(result.map((item) => item.uid)).size, 3)
  assert.equal(result[0].uid, 'duplicate')
  assert.ok(result[1].uid)
  assert.ok(result[2].uid)
})

test('adds the first cue to an empty subtitle list', () => {
  const result = insertSubtitleCueAtTime([], 1.25, { uid: 'first-cue' })

  assert.deepEqual(result.cues.map((item) => item.index), [1])
  assert.deepEqual([result.cue.start_time, result.cue.end_time], ['00:00:01,250', '00:00:03,250'])
})

test('adds at the current time, sorts by start time, and retains overlaps', () => {
  const result = insertSubtitleCueAtTime([
    cue('late', 8, 10),
    cue('wide', 0, 7),
  ], 3, { uid: 'new', durationSeconds: 2, text: '补充字幕' })

  assert.deepEqual(result.cues.map((item) => item.uid), ['wide', 'new', 'late'])
  assert.deepEqual(result.cues.map((item) => item.index), [1, 2, 3])
  assert.deepEqual([result.cue.start, result.cue.end, result.cue.text], [3, 5, '补充字幕'])
  assert.equal(result.index, 1)
  assert.equal(result.cues[0].end, 7, 'the existing overlapping cue must not be trimmed')
})

test('does not reuse an existing UID when inserting a cue', () => {
  const result = insertSubtitleCueAtTime([cue('same', 0, 1)], 2, { uid: 'same' })

  assert.equal(new Set(result.cues.map((item) => item.uid)).size, 2)
  assert.notEqual(result.cue.uid, 'same')
})

test('inserts immediately before and after an anchor without sorting away placement', () => {
  const original = [cue('first', 0, 1), cue('anchor', 5, 6), cue('last', 7, 8)]
  const before = insertSubtitleCueRelative(original, 'anchor', 'before', { uid: 'before' })
  assert.deepEqual(before.cues.map((item) => item.uid), ['first', 'before', 'anchor', 'last'])
  assert.deepEqual([before.cue.start, before.cue.end], [3, 5])

  const after = insertSubtitleCueRelative(original, 'anchor', 'after', { uid: 'after' })
  assert.deepEqual(after.cues.map((item) => item.uid), ['first', 'anchor', 'after', 'last'])
  assert.deepEqual([after.cue.start, after.cue.end], [6, 8])
  assert.equal(after.cues.at(-1).start, 7, 'overlap with the following cue remains valid')
})

test('inserting before a zero-time anchor still creates a valid editable interval', () => {
  const result = insertSubtitleCueRelative([cue('anchor', 0, 1)], 'anchor', 'before', {
    uid: 'before-zero',
    durationSeconds: 1.5,
  })

  assert.deepEqual(result.cues.map((item) => item.uid), ['before-zero', 'anchor'])
  assert.deepEqual([result.cue.start, result.cue.end], [0, 1.5])
})

test('sets a boundary, synchronizes both time representations, and allows neighbor overlap', () => {
  const cues = [cue('one', 0, 3), cue('two', 4, 6)]
  const result = setSubtitleCueBoundary(cues, 'two', 'start', 2.25)

  assert.equal(result.cue.start, 2.25)
  assert.equal(result.cue.start_time, '00:00:02,250')
  assert.equal(result.cue.end, 6)
  assert.equal(result.cues[0].end, 3, 'overlapping adjacent cues must be retained')
})

test('builds a cue preview from formatted fields before stale numeric fields', () => {
  const result = buildSubtitleCuePreview({
    uid: 'preview-cue',
    start: 99,
    end: 100,
    start_time: '00:00:01,250',
    end_time: '00:00:03,500',
    text: '当前\n字幕',
  })

  assert.deepEqual(result, {
    cueUid: 'preview-cue',
    seekTime: 1.25,
    stopTime: 3.5,
    subtitleStart: 1.25,
    subtitleEnd: 3.5,
    text: '当前\n字幕',
  })
})

test('clips a cue preview to a finite video duration without mutating the cue', () => {
  const original = cue('clipped', 8.25, 12, '超出结尾')
  const result = buildSubtitleCuePreview(original, { videoDuration: 10 })

  assert.deepEqual(result, {
    cueUid: 'clipped',
    seekTime: 8.25,
    stopTime: 10,
    subtitleStart: 8.25,
    subtitleEnd: 10,
    text: '超出结尾',
  })
  assert.deepEqual(original, cue('clipped', 8.25, 12, '超出结尾'))
  assert.equal(buildSubtitleCuePreview(original, { videoDuration: Number.NaN }).stopTime, 12)
  assert.equal(buildSubtitleCuePreview(original, { videoDuration: Number.POSITIVE_INFINITY }).stopTime, 12)
})

test('rejects invalid cue preview intervals and unplayable video bounds', () => {
  assert.throws(() => buildSubtitleCuePreview(null), /字幕条目必须是对象/)
  assert.throws(() => buildSubtitleCuePreview({ uid: 'missing', start: 1, text: '' }), /缺少结束时间/)
  assert.throws(() => buildSubtitleCuePreview(cue('zero', 2, 2)), /结束时间必须大于开始时间/)
  assert.throws(() => buildSubtitleCuePreview(cue('reverse', 3, 2)), /结束时间必须大于开始时间/)
  assert.throws(() => buildSubtitleCuePreview(cue('negative', -1, 2)), /字幕时间不能为负数/)
  assert.throws(() => buildSubtitleCuePreview({
    ...cue('invalid-formatted', 1, 2),
    start_time: 'not-a-time',
    end_time: '00:00:02,000',
  }), /无效 SRT 时间/)
  assert.throws(() => buildSubtitleCuePreview(cue('past-video', 10, 12), { videoDuration: 8 }), /超出视频可播放范围/)
  assert.throws(() => buildSubtitleCuePreview(cue('zero-video', 0, 1), { videoDuration: 0 }), /视频时长必须大于 0/)
  assert.throws(() => buildSubtitleCuePreview(cue('negative-video', 0, 1), { videoDuration: -2 }), /视频时长必须大于 0/)
})

test('reports preview visibility using an inclusive start and exclusive end', () => {
  const preview = buildSubtitleCuePreview(cue('active', 1.25, 2.5))

  assert.deepEqual(getSubtitlePreviewState(preview, 1.249), { active: false, shouldStop: false })
  assert.deepEqual(getSubtitlePreviewState(preview, 1.25), { active: true, shouldStop: false })
  assert.deepEqual(getSubtitlePreviewState(preview, 2.499), { active: true, shouldStop: false })
  assert.deepEqual(getSubtitlePreviewState(preview, 2.5), { active: false, shouldStop: true })
  assert.equal(isSubtitlePreviewActive(preview, 1.5), true)
  assert.equal(isSubtitlePreviewActive(preview, 2.5), false)
})

test('uses tolerance consistently for visibility and the playback stop boundary', () => {
  const preview = buildSubtitleCuePreview(cue('tolerant', 1, 2))

  assert.deepEqual(getSubtitlePreviewState(preview, 0.98, { tolerance: 0.02 }), { active: true, shouldStop: false })
  assert.deepEqual(getSubtitlePreviewState(preview, 1.98, { tolerance: 0.02 }), { active: false, shouldStop: true })
  assert.throws(() => getSubtitlePreviewState(preview, 1.5, { tolerance: -0.01 }), /容差不能为负数/)
  assert.throws(() => getSubtitlePreviewState(preview, 1.5, { tolerance: Number.NaN }), /容差必须是有限数字/)
})

test('rejects invalid own intervals and invalid operation arguments', () => {
  const cues = [cue('one', 1, 3)]

  assert.throws(() => setSubtitleCueBoundary(cues, 'one', 'end', 1), /结束时间必须大于开始时间/)
  assert.throws(() => setSubtitleCueBoundary(cues, 'one', 'start', 3), /结束时间必须大于开始时间/)
  assert.throws(() => setSubtitleCueBoundary(cues, 'missing', 'start', 0), /找不到字幕条目/)
  assert.throws(() => insertSubtitleCueRelative(cues, 'one', 'middle'), /插入位置/)
  assert.throws(() => normalizeSubtitleCue(cue('bad', 2, 2)), /结束时间必须大于开始时间/)
})

test('creates unique UIDs in the current Node or browser runtime', () => {
  const ids = Array.from({ length: 500 }, () => createSubtitleCueUid())
  assert.equal(new Set(ids).size, ids.length)
  assert.ok(ids.every(Boolean))
})
