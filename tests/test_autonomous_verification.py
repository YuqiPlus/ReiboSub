import copy

import pytest

from video_translate.agent.verification import validate_review,review_semantics,VerificationProtocolError


PAIRS=[{'id':1,'source':'안 먹었어요','zh':'吃了'}, {'id':2,'source':'안녕하세요','zh':'你好'}]


def passed():return {'checks':[{'id':row['id'],'verdict':'pass'} for row in PAIRS]}


def test_positive_notes_in_old_issues_cannot_be_silently_treated_as_pass():
    with pytest.raises(ValueError):validate_review({'issues':[{'id':1,'reason_zh':'无明显问题'}]},PAIRS)


@pytest.mark.parametrize('change',[
    lambda r:r['checks'].pop(),
    lambda r:r['checks'][1].update(id=1),
    lambda r:r['checks'][1].update(id=99),
    lambda r:r['checks'][0].update(id=True),
    lambda r:r['checks'][0].update(verdict='good'),
    lambda r:r['checks'][0].update(verdict=[]),
    lambda r:r['checks'][0].update(reason_zh='有错但标记pass'),
])
def test_bad_coverage_ids_and_verdicts_are_protocol_failures(change):
    result=passed();change(result)
    with pytest.raises(ValueError):validate_review(result,PAIRS)


@pytest.mark.parametrize('verdict,kind',[('issue','translation_error'),('uncertain','semantic_uncertain')])
def test_real_errors_and_uncertainty_are_preserved(verdict,kind):
    result=passed();result['checks'][0]={'id':1,'verdict':verdict,'source_quote':'안','translation_quote':'吃了','reason_zh':'否定含义未体现'}
    parsed=validate_review(result,PAIRS)
    assert parsed['issues'][0]['kind']==kind
    result['checks'][0]['source_quote']='凭空引用'
    with pytest.raises(ValueError):validate_review(result,PAIRS)


def test_schema_repair_uses_same_pairs_and_keeps_repaired_real_issue(tmp_path):
    calls=[]
    def llm(root,name,task,instruction,data):
        calls.append((name,copy.deepcopy(data)))
        if len(calls)==1:return {'issues':[{'id':1,'reason_zh':'无问题'}]}
        result=passed();result['checks'][0]={'id':1,'verdict':'issue','source_quote':'안','translation_quote':'吃了','reason_zh':'缺少否定'}
        return result
    result=review_semantics(tmp_path,'attempt',PAIRS,llm)
    assert len(calls)==2 and calls[1][0]=='attempt-schema-repair'
    assert calls[0][1]['subtitles']==calls[1][1]['subtitles']==PAIRS
    assert result['issues'][0]['kind']=='translation_error'
    assert result['protocol_attempts'][0]['status']=='protocol_error'


def test_repair_is_bounded_and_transport_errors_are_not_schema_retried(tmp_path):
    calls=[]
    def malformed(*args):calls.append(1);return {'issues':[]}
    with pytest.raises(VerificationProtocolError):review_semantics(tmp_path,'attempt',PAIRS,malformed)
    assert len(calls)==2
    def unavailable(*args):calls.append(1);raise RuntimeError('service unavailable')
    calls.clear()
    with pytest.raises(RuntimeError):review_semantics(tmp_path,'attempt',PAIRS,unavailable)
    assert len(calls)==1


def test_neighbor_issue_cannot_be_attached_to_sampled_cue_but_can_be_reported_separately(tmp_path):
    pairs=[{'id':400,'source':'나의 사랑이 많이 담긴','zh':'饱含我满满爱意的',
        'context_after':[{'id':401,'source':'이 젤리 슈즈 많이 신었으면 좋겠다','zh':'希望大家能多穿这双果冻鞋'}]}]
    finding={'id':400,'verdict':'issue','source_quote':'이 젤리 슈즈 많이 신었으면 좋겠다',
        'translation_quote':'希望大家能多穿这双果冻鞋','reason_zh':'礼物对象可能不是大家，需结合上下文'}
    with pytest.raises(ValueError,match='401'):validate_review({'checks':[finding]},pairs)
    corrected={**finding,'id':401,'verdict':'uncertain'}
    result=validate_review({'checks':[{'id':400,'verdict':'pass'}],'context_findings':[corrected]},pairs)
    assert result['issues'][0]['id']==401 and result['issues'][0]['from_context']
    assert result['issues'][0]['kind']=='semantic_uncertain'
    corrected['id']=999
    with pytest.raises(ValueError):validate_review({'checks':[{'id':400,'verdict':'pass'}],'context_findings':[corrected]},pairs)
