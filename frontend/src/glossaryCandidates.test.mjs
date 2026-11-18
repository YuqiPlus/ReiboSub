import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeGlossaryCandidates } from './glossaryCandidates.js'

test('late candidates preserve current human text and review flags', () => {
  const item={section:'characters',index:0,source:'레이',context_text:'原句',zh:'我已填写',reviewed:true,note:'已编辑',suggested_zh:'旧建议'}
  const incoming={...item,zh:'',reviewed:false,note:'旧备注',suggested_zh:'新建议',blind_candidate_zh:'参考句'}
  assert.deepEqual(mergeGlossaryCandidates([item],[incoming]),[{...item,blind_candidate_zh:'参考句'}])
})

test('different sources and changed evidence never receive stale candidates', () => {
  const item={section:'characters',index:0,source:'A',context_text:'新原句',zh:'手填',reviewed:false}
  assert.deepEqual(mergeGlossaryCandidates([item],[{...item,context_text:'旧原句',blind_candidate_zh:'旧候选'}]),[item])
  assert.deepEqual(mergeGlossaryCandidates([item],[{...item,source:'B',blind_candidate_zh:'别人的候选'}]),[item])
})

test('cached completion removes stale pending/error markers only', () => {
  const item={section:'terms',index:0,source:'x',zh:'已填',reviewed:false,blind_candidate_pending:true,blind_candidate_error:'旧错误'}
  const [result]=mergeGlossaryCandidates([item],[{...item,blind_candidate_zh:'参考',blind_candidate_pending:undefined}])
  assert.equal(result.zh,'已填')
  assert.equal(result.blind_candidate_zh,'参考')
})
