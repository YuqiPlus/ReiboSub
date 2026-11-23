import copy
import hashlib

import pytest

from video_translate.agent import reply_review


@pytest.fixture
def state(tmp_path):
    source=tmp_path/'source.srt';target=tmp_path/'zh.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\n안녕\n')
    target.write_text('1\n00:00:00,000 --> 00:00:01,000\n你好\n')
    return {'sources':{'ocr_1':{'path':str(source)}},'selected':'ocr_1','translated':str(target),
            'translation_guidance':[{'cue_id':1,'clue':'上下文线索'}],
            'verification':{'issues':[{'id':1}]},'counts':{'review_translation':7,'translate':1}}


def test_queue_preserves_all_tool_counts_and_grants_exactly_one_scoped_attempt(state):
    before=copy.deepcopy(state['counts'])
    reply_review.queue(state,1)
    assert state['counts']==before
    assert state['recovery_allowances']['review_translation']==6
    reply_review.queue(state,1)
    assert state['recovery_allowances']['review_translation']==6
    assert reply_review.assert_pending(state)['cue_id']==1


def test_pending_review_cannot_silently_use_changed_guidance_or_files(state):
    reply_review.queue(state,1)
    state['translation_guidance'].append({'cue_id':1,'clue':'新的线索'})
    with pytest.raises(ValueError,match='发生变化'):reply_review.assert_pending(state)


def test_queue_requires_existing_clue_current_issue_and_permission(state):
    for cue in [True,2,'1']:
        with pytest.raises(ValueError):reply_review.queue(state,cue)
    state['execution_policy']={'allowed_repair_cue_ids':[2]}
    with pytest.raises(ValueError,match='范围'):reply_review.queue(state,1)


def test_receipt_is_reused_for_identical_guidance_but_not_new_clues_or_changed_output(state,tmp_path):
    reply_review.queue(state,1)
    output=tmp_path/'new.srt';output.write_bytes(open(state['translated'],'rb').read())
    result={'target_ids':[1],'translation_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'unresolved_ids':[1],'audit':'audit.json','output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'translated_srt':str(output),'decisions':[{'id':1,'source':'안녕','before':'你好','after':'你好',
                'reason_zh':'证据不足','independent_review':{'reason_zh':'不应猜测'}}]}
    receipt=reply_review.record(state,result)
    state['translated']=str(output)
    assert reply_review.completed(state,1)==receipt
    assert reply_review.queue(state,1)==receipt and 'pending_reply_review' not in state
    state['translation_guidance'].append({'cue_id':1,'clue':'新增证据'})
    assert reply_review.completed(state,1) is None


def test_result_must_match_the_single_received_question(state):
    reply_review.queue(state,1)
    with pytest.raises(ValueError,match='这一条'):
        reply_review.record(state,{'target_ids':[1,2]})
