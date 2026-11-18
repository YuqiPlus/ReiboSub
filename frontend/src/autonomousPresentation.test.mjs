import test from 'node:test'
import assert from 'node:assert/strict'
import { currentLocalReview, autonomousDraftMessage, publicAgentDecision, friendlyAgentText, evidenceRefLabel } from './autonomousPresentation.js'

test('old review is not shown against a newer downloaded translation', () => {
  assert.equal(currentLocalReview({translated_srt:'zh_2.srt',local_translation_review:{translated_srt:'local_1.srt'}}), null)
  assert.equal(currentLocalReview({local_translation_review_current:false,local_translation_review:{translated_srt:'zh_2.srt'},translated_srt:'zh_2.srt'}), null)
})
test('verified current review remains visible after materialized delivery', () => {
  const review={translated_srt:'work/local.srt'}
  assert.equal(currentLocalReview({translated_srt:'delivery.srt',local_translation_review:review,local_translation_review_current:true}),review)
})
test('failed task is not presented as waiting for detection', () => {
  assert.match(autonomousDraftMessage({status:'failed'}),/最终检查尚未完成/)
  assert.match(autonomousDraftMessage({status:'running'}),/不重翻整片/)
  assert.match(autonomousDraftMessage({status:'done',result:{}}),/抽查/)
})

test('goal-driven decision shows evidence and revisable plan, not a fixed stage rail', () => {
  assert.equal(publicAgentDecision({}), null)
  assert.equal(publicAgentDecision({autonomous_controller_version:1,autonomous_decision:{summary:'legacy'}}), null)
  const decision=publicAgentDecision({autonomous_controller_version:2,autonomous_decision:{
    summary:'发现有现成中文字幕',reason:'检查正文',next_check:'确认正文和时间范围',
    plan:['判断能否直接交付'],unknowns:['是否只覆盖片头'],evidence_refs:['metadata'],
  }})
  assert.equal(decision.summary,'发现有现成中文字幕')
  assert.deepEqual(decision.plan,['判断能否直接交付'])
  assert.deepEqual(decision.unknowns,['是否只覆盖片头'])
})

test('public decisions use readable tool and evidence names', () => {
  assert.equal(friendlyAgentText('调用 deliver_target，并用 read_subtitles 查上下文'), '调用 交付现成中文字幕，并用 查看字幕上下文 查上下文')
  assert.equal(evidenceRefLabel('event:12'), '操作记录 #12')
  assert.equal(evidenceRefLabel('metadata'), '视频信息')
  assert.equal(evidenceRefLabel('source:captions_2'), '原文来源 #2')
})

test('video backfill does not claim to be rechecking or retranslating ready captions', () => {
  assert.match(autonomousDraftMessage({status:'running',phase:'autonomous_download'}),/正在保存视频素材/)
  assert.match(autonomousDraftMessage({status:'running',phase:'autonomous_download'}),/不会重新翻译/)
})
