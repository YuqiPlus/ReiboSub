import test from 'node:test'
import assert from 'node:assert/strict'
import { TOOLBOX_TOOLS, dialoguePayload, mediaChoices, subtitleTranscript, toolJobBusy } from './toolboxTools.js'

test('toolbox offers standalone file and text tools with unique keys', () => {
  assert.deepEqual(TOOLBOX_TOOLS.map(tool => tool.id), ['translate', 'subtitles', 'dialogue', 'transcript'])
})
test('media choices include both audio and video, deduplicated without mutation', () => {
  const assets = { videos: [{ path: '/v.mp4' }], audios: [{ path: '/v.mp4' }, { path: '/a.wav' }, {}] }
  assert.deepEqual(mediaChoices(assets).map(item => item.path), ['/v.mp4', '/a.wav'])
  assert.equal(assets.audios.length, 3)
  assert.deepEqual(mediaChoices(), [])
})
test('dialogue tool uses stable ASR 2.2 without translation or experimental Agent', () => {
  const payload = dialoguePayload({ input: ' /media/한글.mp4 ' })
  assert.equal(payload.input_video, '/media/한글.mp4')
  assert.equal(payload.asr_version, '2.0') // API 2.0 selects the stable 2.2 implementation.
  assert.equal(payload.high_recall, true)
  assert.equal(payload.source_language, 'auto')
  assert.equal(payload.chinese_script, 'simplified')
  assert.equal(payload.speaker_diarization, false)
  assert.equal(payload.device, 'cuda')
  assert.equal(payload.compute_type, 'float16')
  assert(!('target_language' in payload))
  assert(!('test_ranges' in payload))
})
test('CPU mode explicitly uses int8 and speaker separation stays opt-in', () => {
  const payload = dialoguePayload({ input: '/media/a.wav', device: 'cpu', model: 'small', language: 'english', speakers: true, hotwords: ' ReiboSub ' })
  assert.equal(payload.compute_type, 'int8')
  assert.equal(payload.diarization_device, 'cpu')
  assert.equal(payload.speaker_diarization, true)
  assert.equal(payload.hotwords, 'ReiboSub')
  assert.equal(payload.model_size, 'small')
})
test('dialogue extraction passes explicit traditional/original output choices', () => {
  for (const chineseScript of ['traditional', 'original']) {
    assert.equal(dialoguePayload({ input: '/a.wav', chineseScript }).chinese_script, chineseScript)
  }
  assert.throws(() => dialoguePayload({ input: '/a.wav', chineseScript: 'unknown' }), /中文输出/)
})
test('speaker count supports automatic or 1–20 and only applies with diarization enabled', () => {
  assert.equal(dialoguePayload({ input: '/a.wav', speakers: true }).known_speaker_count, 'auto')
  for (const count of [1, '2', 6, '20']) {
    assert.equal(dialoguePayload({ input: '/a.wav', speakers: true, knownSpeakerCount: count }).known_speaker_count, Number(count))
  }
  assert.equal(dialoguePayload({ input: '/a.wav', speakers: false, knownSpeakerCount: 2 }).known_speaker_count, 'auto')
  for (const count of [0, 21, 1.5, 'invalid']) {
    assert.throws(() => dialoguePayload({ input: '/a.wav', speakers: true, knownSpeakerCount: count }), /说话人数/)
  }
})
test('invalid dialogue settings fail before a request', () => {
  assert.throws(() => dialoguePayload({ input: ' ' }), /选择或上传/)
  for (const [key, value] of [['device', 'auto'], ['model', 'unknown'], ['language', 'invalid']]) {
    assert.throws(() => dialoguePayload({ input: '/a.wav', [key]: value }), /不支持/)
  }
})
test('running, queued and cancellation keep duplicate starts disabled', () => {
  for (const status of ['running', 'queued', 'cancel_requested']) assert(toolJobBusy({ status }))
  for (const status of ['done', 'failed', 'cancelled']) assert(!toolJobBusy({ status }))
  assert(!toolJobBusy(null))
})
test('subtitle text preserves repeated speech, multiline cues and speaker names', () => {
  const srt = '\uFEFF1\r\n00:00:01,000 --> 00:00:03,000\r\n<b>甲：</b>你好\r\n第二行\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\n甲：你好'
  assert.deepEqual(subtitleTranscript(srt), { count: 2, text: '甲：你好\n第二行\n\n甲：你好' })
  assert.match(subtitleTranscript(srt, { timestamps: true }).text, /^\[00:00:01,000 → 00:00:03,000\]/)
})
test('WebVTT strips cue settings, styling and inline times, not literal comparisons', () => {
  const vtt = 'WEBVTT\n\nNOTE a comment\nnot speech\n\nSTYLE\n::cue { color: red }\n\ncue-a\n00:01.000 --> 00:03.500 align:start\n<v Speaker><c.green>Hello</c></v> <00:02.000>there\n\n00:04.000 --> 00:06.000\n2 < 3 and <name>'
  assert.deepEqual(subtitleTranscript(vtt), { count: 2, text: 'Hello there\n\n2 < 3 and <name>' })
})
test('subtitle parser rejects unrelated text and retains long-hour timing', () => {
  assert.throws(() => subtitleTranscript('ordinary text'), /没有找到有效字幕/)
  assert.throws(() => subtitleTranscript(''), /没有找到有效字幕/)
  assert.equal(subtitleTranscript('1\n101:00:00,000 --> 101:00:03,000\n{\\an8}正文').text, '正文')
})
