import hashlib
from pathlib import Path

import pytest
import yaml

from video_translate import web_agent as web
from video_translate.asr_review_web import read_json,write_json_atomic


@pytest.fixture
def failed(monkeypatch,tmp_path):
    folder=tmp_path/'tasks'/'task';old=tmp_path/'jobs'/'session'/'autonomous'
    folder.mkdir(parents=True);old.mkdir(parents=True)
    source=old/'source.srt';target=old/'zh.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\n안녕\n');target.write_text('1\n00:00:00,000 --> 00:00:01,000\n你好\n')
    state={'sources':{'ocr_1':{'kind':'ocr','path':str(source)}},'selected':'ocr_1','translated':str(target),
           'counts':{'translate':1,'review_translation':2},'events':[]}
    write_json_atomic(old/'state.json',state)
    (folder/'task.yaml').write_text(yaml.safe_dump({'id':'task','run_generation':1,'stages':{}}))
    session=web.AgentSession(id='session',payload={'agent_mode':'autonomous'},status='failed',
        result={'task_id':'task','run_generation':1,'autonomous_workspace':str(old)})
    monkeypatch.setattr(web,'ROOT',tmp_path);monkeypatch.setattr(web,'TASK_DIR',folder.parent)
    monkeypatch.setattr(web,'_AGENT_SESSIONS',{session.id:session})
    starts=[];monkeypatch.setattr(web,'_run_agent_async',lambda *args:starts.append(args))
    return session,old,source,target,starts


def test_recovery_clones_records_locks_inputs_and_never_resets_successful_counts(failed):
    session,old,source,target,starts=failed
    before=[p.read_bytes() for p in (old/'state.json',source,target)]
    web.recover_existing_agent_session(session.id,'translation')
    new=Path(session.result['autonomous_workspace'])
    assert new!=old and new.is_dir() and session.status=='running' and len(starts)==1
    state=read_json(new/'state.json');policy=state['execution_policy']
    assert policy['continue_existing_translation'] and policy['preserve_existing_outputs']
    assert policy['translated_sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    assert state['counts']=={'translate':1,'review_translation':2}
    assert [p.read_bytes() for p in (old/'state.json',source,target)]==before


def test_running_task_is_never_interrupted_and_glossary_recovery_cannot_retranslate(failed):
    session,old,_,_,starts=failed
    session.status='running'
    with pytest.raises(ValueError,match='不中断'):web.recover_existing_agent_session(session.id,'translation')
    assert not starts
    session.status='failed';state=read_json(old/'state.json');state.pop('translated');write_json_atomic(old/'state.json',state)
    web.recover_existing_agent_session(session.id,'glossary')
    policy=read_json(Path(session.result['autonomous_workspace'])/'state.json')['execution_policy']
    assert policy['stop_at_glossary'] and len(starts)==1


def test_existing_clues_recovery_clones_waiting_workspace_and_targets_only_one_cue(failed):
    session,old,source,target,starts=failed
    state=read_json(old/'state.json');state.update(translation_guidance=[{'cue_id':1,'clue':'已提交的线索'}],
        verification={'issues':[{'id':1,'kind':'semantic_uncertain'}]})
    write_json_atomic(old/'state.json',state);original=(old/'state.json').read_bytes()
    session.status='waiting';session.question={'kind':'autonomous_question','cue_id':1}
    web.recover_existing_agent_session(session.id,'translation',review_existing_clue_id=1)
    updated=read_json(Path(session.result['autonomous_workspace'])/'state.json')
    assert updated['pending_reply_review']['cue_id']==1
    assert updated['translation_guidance']==state['translation_guidance']
    assert updated['execution_policy']['allowed_repair_cue_ids']==[1]
    assert updated['counts']==state['counts'] and (old/'state.json').read_bytes()==original
    assert len(starts)==1


def test_legacy_review_conclusion_can_be_closed_only_with_matching_receipt(failed):
    from video_translate.agent import reply_review
    session,old,source,target,starts=failed
    state=read_json(old/'state.json')
    state.update(translation_guidance=[{'cue_id':1,'clue':'已收到的线索'}],verification={'issues':[{'id':1}]})
    reply_review.queue(state,1)
    record=reply_review.record(state,{'target_ids':[1],'translation_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'translated_srt':str(target),'unresolved_ids':[1],
        'audit':'audit.json','decisions':[{'id':1,'source':'안녕','before':'你好','after':'你好','reason_zh':'证据不足',
            'independent_review':{'reason_zh':'无法核准'}}]})
    write_json_atomic(old/'state.json',state);before=(old/'state.json').read_bytes()
    session.status='waiting';session.question={'kind':'autonomous_review_result'}
    with pytest.raises(ValueError,match='不一致'):web.finish_agent_reply_review(session.id,'stale')
    assert session.status=='waiting' and not starts
    web.finish_agent_reply_review(session.id,record['signature'])
    assert session.status=='running' and len(starts)==1
    assert Path(session.result['autonomous_workspace'])!=old and (old/'state.json').read_bytes()==before
