import pytest

from video_translate.agent import decisions


def receipt(**updates):
    value={'tool':'probe','args':{},'reason':'检查视频信息',
           'assessment':{'summary':'目前只有用户提供的链接','evidence_refs':['goal'],'unknowns':['有哪些字幕']},
           'plan':['寻找可复用字幕'],'next_check':'得到字幕列表和时长'}
    value.update(updates)
    return value


def test_public_receipt_requires_real_evidence_not_invented_observations():
    catalog=decisions.evidence_catalog({})
    assert decisions.validate_decision(receipt(),catalog)['plan']==['寻找可复用字幕']
    with pytest.raises(ValueError,match='不存在的证据'):
        decisions.validate_decision(receipt(assessment={'summary':'声称听过了','evidence_refs':['audio:invented']}),catalog)


@pytest.mark.parametrize('field,value', [('plan',[]),('plan',['a']*6),('next_check',''),('assessment',None),('reason','')])
def test_invalid_receipts_do_not_authorize_tools(field,value):
    with pytest.raises(ValueError):decisions.validate_decision(receipt(**{field:value}),decisions.evidence_catalog({}))


def test_failed_observations_are_evidence_not_silently_dropped():
    state={'events':[{'tool':'asr','status':'rejected_or_failed','reason':'识别工具不可用'}]}
    row=decisions.evidence_catalog(state)[-1]
    assert row['id']=='event:1' and row['status']=='rejected_or_failed'
    assert row['facts']['message']=='识别工具不可用'
    assert not decisions.goal_status(state)['conditions']['current_translation_check_passed']


def test_goal_is_conditions_not_a_prescribed_tool_sequence():
    status=decisions.goal_status({'target_caption_checks':{'1':{'status':'passed'}}})
    assert status['conditions']['usable_target_caption']
    assert not status['conditions']['translation_exists']
    assert 'steps' not in status


def test_video_is_a_goal_requirement_but_scoped_reviews_do_not_redownload():
    assert decisions.video_required({'controller_version':2})
    for scope in ('verification_only','targeted_translation_review','continue_existing_translation','reuse_existing_source'):
        assert not decisions.video_required({'controller_version':2,'execution_policy':{scope:True}})
    assert not decisions.video_required({'controller_version':1})


def test_video_ready_rejects_missing_empty_or_partial_downloads(tmp_path):
    video=tmp_path/'video.mp4'
    assert not decisions.video_ready({'media':str(video)})
    video.touch();assert not decisions.video_ready({'media':str(video)})
    video.write_bytes(b'finished video');assert decisions.video_ready({'media':str(video)})
    partial=tmp_path/'video.mp4.part';partial.write_bytes(b'partial')
    assert not decisions.video_ready({'media':str(partial)})


def test_nine_or_more_real_citations_are_not_reported_as_fabricated_evidence():
    catalog=decisions.evidence_catalog({'events':[{'tool':'inspect','status':'done'} for _ in range(25)]})
    refs=['goal']+[f'event:{i}' for i in range(1,26)]
    parsed=decisions.validate_decision(receipt(assessment={'summary':'引用实际存在的检查记录','evidence_refs':refs,'unknowns':[]}),catalog)
    assert parsed['evidence_refs']==refs
    assert 'event:1' in {r['id'] for r in catalog}  # Not evicted after 16 steps.


def test_duplicate_real_citations_are_deduplicated_without_spending_tool_budget():
    parsed=decisions.validate_decision(receipt(assessment={'summary':'当前目标','evidence_refs':['goal']*20,'unknowns':[]}),decisions.evidence_catalog({}))
    assert parsed['evidence_refs']==['goal']
