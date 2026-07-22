import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DEFAULT_AGENT_OCR_PIPELINE_VERSION,
  buildAgentOcrPipelinePayload,
  getAgentOcrPipeline,
  inferAgentOcrPipelineVersion,
  normalizeAgentOcrPipelineVersion,
} from './agentOcrPipeline.js'

test('normalizes the public OCR pipeline version names', () => {
  assert.equal(DEFAULT_AGENT_OCR_PIPELINE_VERSION, 'v3')
  assert.equal(normalizeAgentOcrPipelineVersion('v2'), 'v2')
  assert.equal(normalizeAgentOcrPipelineVersion('OCR 2.0'), 'v2')
  assert.equal(normalizeAgentOcrPipelineVersion('OCR 3.0'), 'v3')
  assert.equal(normalizeAgentOcrPipelineVersion('unknown'), 'v1')
})

test('maps OCR 1.0 to the complete legacy Agent route', () => {
  assert.deepEqual(buildAgentOcrPipelinePayload('v1', { ocrScope: 'smart_full' }), {
    ocr_pipeline_version: 'v1',
    ocr_scope: 'smart_full',
    ocr_extraction_mode: 'auto',
    ocr_shape_mode: 'unrestricted',
    ocr_refinement_mode: 'none',
    ocr_translation_mode: 'standard_cleanup',
  })
})

test('maps OCR 2.0 to region extraction, dedicated refinement, and locked timing', () => {
  assert.deepEqual(buildAgentOcrPipelinePayload('v2', { ocrScope: 'smart_full' }), {
    ocr_pipeline_version: 'v2',
    ocr_scope: 'bottom',
    ocr_extraction_mode: 'region',
    ocr_shape_mode: 'unrestricted',
    ocr_refinement_mode: 'llm_boxes',
    ocr_translation_mode: 'translate_only',
  })
  assert.match(getAgentOcrPipeline('v2').description, /锁定原时间轴/)
})

test('restores old task payloads without requiring the new version field', () => {
  assert.equal(inferAgentOcrPipelineVersion({ ocr_pipeline_version: 'v2' }), 'v2')
  assert.equal(inferAgentOcrPipelineVersion({ ocr_extraction_mode: 'region' }), 'v2')
  assert.equal(inferAgentOcrPipelineVersion({ ocr_extraction_mode: 'region_v3' }), 'v3')
  assert.equal(inferAgentOcrPipelineVersion({ ocr_extraction_mode: 'auto' }), 'v1')
  assert.equal(inferAgentOcrPipelineVersion({}), 'v1')
})

test('maps the stable OCR 3.0 release and preserves restored task settings', () => {
  assert.match(getAgentOcrPipeline('v3').label, /稳定版/)
  assert.match(getAgentOcrPipeline('v3').description, /分层/)
  assert.equal(buildAgentOcrPipelinePayload('v3', { ocrScope: 'smart_full' }).ocr_scope, 'bottom')
  assert.deepEqual(buildAgentOcrPipelinePayload('v3', {
    ocrScope: 'bottom',
    restoredSettings: {
      ocr_scope: 'smart_full',
      ocr_shape_mode: 'horizontal_strict',
      ocr_refinement_mode: 'llm_boxes',
      ocr_translation_mode: 'translate_only',
    },
  }), {
    ocr_pipeline_version: 'v3',
    ocr_scope: 'smart_full',
    ocr_extraction_mode: 'region_v3',
    ocr_shape_mode: 'horizontal_strict',
    ocr_refinement_mode: 'llm_boxes',
    ocr_translation_mode: 'translate_only',
  })
})
