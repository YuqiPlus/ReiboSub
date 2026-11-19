import test from 'node:test'
import assert from 'node:assert/strict'
import { translationDefaults, sessionTargetLanguage, targetSubtitleLabel } from './translationLanguages.js'

test('Bilibili defaults to Chinese to English, YouTube keeps the configured source', () => {
  for (const link of ['BV1GJ411x7h7', 'https://www.bilibili.com/video/BV1GJ411x7h7?p=2', 'https://b23.tv/example']) {
    assert.deepEqual(translationDefaults(link, 'japanese'), { source: 'chinese', target: 'en' })
  }
  assert.deepEqual(translationDefaults('https://youtu.be/abcdefghijk', 'japanese'), { source: 'japanese', target: 'zh' })
  assert.equal(translationDefaults('https://bilibili.com.evil.test/video/id').target, 'zh')
})

test('saved tasks keep their language rather than inheriting new platform defaults', () => {
  assert.equal(sessionTargetLanguage({ payload: { url: 'https://b23.tv/old' } }), 'zh')
  assert.equal(sessionTargetLanguage({ payload: { target_language: 'en' } }), 'en')
  assert.equal(targetSubtitleLabel('en'), '英文字幕')
})
