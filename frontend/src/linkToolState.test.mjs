import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isProbeResponseCurrent,
  looksLikeYoutubeInput,
  looksLikeVideoInput,
  normalizeLinkInput,
  resolveLinkActionUrl,
  selectedVideoFormat,
  shouldClearLinkProbe,
  videoFormatChoiceValue,
} from './linkToolState.js'

test('normalizes a pasted link without requiring a probe', () => {
  assert.equal(normalizeLinkInput('  https://youtu.be/video-b  '), 'https://youtu.be/video-b')
  assert.equal(resolveLinkActionUrl('https://youtu.be/video-b'), 'https://youtu.be/video-b')
})

test('always prefers the current input over a stale probe URL', () => {
  assert.equal(
    resolveLinkActionUrl('https://youtu.be/video-b', 'https://youtu.be/video-a'),
    'https://youtu.be/video-b',
  )
})

test('uses the current probe URL only when the input is blank', () => {
  assert.equal(
    resolveLinkActionUrl('   ', ' https://youtu.be/video-a '),
    'https://youtu.be/video-a',
  )
})

test('clears displayed probe data when its input link changes', () => {
  const probe = { webpage_url: 'https://youtu.be/video-a' }
  assert.equal(shouldClearLinkProbe(probe, 'https://youtu.be/video-a', 'https://youtu.be/video-b'), true)
  assert.equal(shouldClearLinkProbe(probe, ' https://youtu.be/video-a ', 'https://youtu.be/video-a'), false)
  assert.equal(shouldClearLinkProbe(null, 'https://youtu.be/video-a', 'https://youtu.be/video-b'), false)
})

test('rejects a probe response when the user has switched links', () => {
  assert.equal(isProbeResponseCurrent('https://youtu.be/video-a', 'https://youtu.be/video-a'), true)
  assert.equal(isProbeResponseCurrent('https://youtu.be/video-a', 'https://youtu.be/video-b'), false)
})

test('starts automatic format detection only for a YouTube URL or video id', () => {
  assert.equal(looksLikeYoutubeInput('AbCdEf12345'), true)
  assert.equal(looksLikeYoutubeInput('https://www.youtube.com/watch?v=AbCdEf12345'), true)
  assert.equal(looksLikeYoutubeInput('https://youtu.be/AbCdEf12345'), true)
  assert.equal(looksLikeYoutubeInput('typing'), false)
})

test('maps a format choice back to its sanitized probe entry', () => {
  const formats = [
    { id: '401+140', label: '2160p · MP4 · AV1' },
    { id: '137+140', label: '1080p · MP4 · H.264' },
  ]

  assert.equal(videoFormatChoiceValue(formats[0]), 'format:401+140')
  assert.equal(selectedVideoFormat(formats, 'format:401+140'), formats[0])
  assert.equal(selectedVideoFormat(formats, '1080p'), null)
  assert.equal(selectedVideoFormat(formats, 'format:missing'), null)
})

test('detects Bilibili ordinary links and parts without changing YouTube detection', () => {
  for (const input of ['BV1GJ411x7h7', 'av170001', 'https://www.bilibili.com/video/BV1GJ411x7h7?p=2', 'https://b23.tv/aBc12', 'b23.tv/aBc12', 'https://youtu.be/AbCdEf12345', 'AbCdEf12345']) {
    assert.equal(looksLikeVideoInput(input), true, input)
  }
  for (const input of ['typing', 'https://example.com/video/BV1GJ411x7h7', 'https://bilibili.com.evil.test/video/BV1GJ411x7h7', 'https://www.bilibili.com/bangumi/play/ep123']) {
    assert.equal(looksLikeVideoInput(input), false, input)
  }
})
