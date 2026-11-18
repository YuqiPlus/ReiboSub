import test from 'node:test'
import assert from 'node:assert/strict'
import { ASR_LAB_VERSIONS, OCR_LAB_VERSIONS } from './labVersions.js'

test('OCR Lab retains independent V2 and V3 IDs', () => {
  assert.deepEqual(OCR_LAB_VERSIONS.map(v => v.id).sort(), ['region', 'region_v3'])
  assert(OCR_LAB_VERSIONS.every(v => v.label && v.description && v.detail))
})
test('ASR 2.2 keeps the backend 2.0 ID and both experimental modes remain distinct', () => {
  assert.equal(ASR_LAB_VERSIONS.find(v => v.id === '2.0').label, 'ASR 2.2')
  assert.deepEqual(ASR_LAB_VERSIONS.filter(v => v.experimental).map(v => v.id).sort(), ['agent-experimental', 'autonomous-experimental'])
  assert(ASR_LAB_VERSIONS.some(v => v.id === '1.0'))
  assert(ASR_LAB_VERSIONS.filter(v => v.experimental).every(v => v.badge.includes('韩语')))
})
