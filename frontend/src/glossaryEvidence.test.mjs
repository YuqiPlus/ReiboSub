import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceCaptions, evidenceKey, evidenceTime, evidenceWindow } from './glossaryEvidence.js'

test('default evidence clip includes three seconds before and after real cue time', () => {
  assert.deepEqual(evidenceWindow({start:105,end:106}),{start:102,end:109})
  assert.deepEqual(evidenceWindow({start:1,end:4},{duration:5}),{start:0,end:5})
  assert.deepEqual(evidenceWindow({start:105,end:106},{padding:10}),{start:95,end:116})
})
test('invalid or out-of-video cue locations are not guessed', () => {
  for (const cue of [{start:-1,end:3},{start:3,end:3},{start:NaN,end:4},{start:'3',end:4}]) {
    assert.throws(()=>evidenceWindow(cue))
  }
  assert.throws(()=>evidenceWindow({start:10,end:12},{duration:9}))
})
test('overlay is visible only during the actual source cue, not the whole clip', () => {
  const rows=[{cue_id:1,start:105,end:106,text:'철구!'}]
  assert.deepEqual(evidenceCaptions(rows,102),[])
  assert.deepEqual(evidenceCaptions(rows,105),rows)
  assert.deepEqual(evidenceCaptions(rows,106),[])
})
test('term identity does not change on edits or human confirmation', () => {
  const item={section:'characters',index:2,source:'name'}
  assert.equal(evidenceKey(item),evidenceKey({...item,zh:'译名',reviewed:true}))
  assert.notEqual(evidenceKey(item),evidenceKey({...item,index:3}))
})
test('timestamps include hours where needed', () => {
  assert.equal(evidenceTime(63.9),'01:03')
  assert.equal(evidenceTime(3661),'1:01:01')
  assert.equal(evidenceTime(NaN),'--:--')
})
