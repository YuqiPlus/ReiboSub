import json
from pathlib import Path

import pytest
import yaml

from video_translate import web_agent as web
from video_translate.asr_review_web import write_json_atomic
from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt,write_srt


@pytest.fixture
def manual(monkeypatch,tmp_path):
    old=tmp_path/'jobs'/'session'/'autonomous';old.mkdir(parents=True)
    source=old/'source.srt';target=old/'zh.srt'
    write_srt([SubtitleCue(i,i*3+7,i*3+8,f'원문{i}') for i in range(1,56)],source)
    write_srt([SubtitleCue(i,i*3+7,i*3+8,f'旧译{i}') for i in range(1,56)],target)
    issues=[{'id':i,'kind':'semantic_uncertain','reason_zh':f'原文{i}无法核准'} for i in (17,19,55)]
    state={'sources':{'mixed_1':{'path':str(source),'kind':'mixed'}},'selected':'mixed_1','translated':str(target),
        'counts':{'translate':1,'review_translation':2},'verification':{'status':'complete','acceptable':False,'issues':issues},
        'translation_guidance':[{'cue_id':17,'preferred_zh':'请多多谅解'}],'probe':{'duration':190}}
    write_json_atomic(old/'state.json',state)
    task=tmp_path/'tasks'/'task';task.mkdir(parents=True)
    project=tmp_path/'downloads'/'video';project.mkdir(parents=True);video=project/'video.mp4';video.write_bytes(b'video')
    (task/'task.yaml').write_text(yaml.safe_dump({'id':'task','run_generation':1,'workflow_status':'active',
        'payload':{'agent_mode':'autonomous','source_language':'korean','target_language':'zh'},'stages':{}}))
    session=web.AgentSession(id='session',status='waiting',phase='autonomous_review_result',payload={'agent_mode':'autonomous','target_language':'zh'},
        result={'task_id':'task','run_generation':1,'autonomous_workspace':str(old),'source_srt':str(source),'translated_srt':str(target),'input_video':str(video)},
        question={'kind':'autonomous_review_result','cue_id':17})
    monkeypatch.setattr(web,'ROOT',tmp_path);monkeypatch.setattr(web,'TASK_DIR',task.parent);monkeypatch.setattr(web,'DOWNLOAD_DIR',project.parent)
    monkeypatch.setattr(web,'_AGENT_SESSIONS',{'session':session});monkeypatch.setattr(web,'_JOBS',{})
    monkeypatch.setattr(web,'_ensure_delivery_thumbnail',lambda *a:{})
    for name in ('_run_command','_run_agent_async','translate_subtitle_job','start_job'):
        monkeypatch.setattr(web,name,lambda *a,**k:pytest.fail('Manual processing must not invoke jobs, models or a full translation'))
    return session,old,source,target


def action(session,operation,**fields):
    review=web.agent_issue_review(session.id)
    return web.apply_agent_issue_action(session.id,{'action':operation,'expected_translation_sha256':review['translation_sha256'],
        'expected_review_token':review['review_token'],**fields})


def test_reading_issues_is_read_only_and_prefills_prior_choice_without_auto_applying(manual):
    session,old,source,target=manual;before=(source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())
    review=web.agent_issue_review(session.id)
    assert [r['cue_id'] for r in review['issues']]==[17,19,55] and review['remaining_ids']==[17,19,55]
    assert review['issues'][0]['preferred_translation']=='请多多谅解'
    assert review['issues'][0]['translation']=='旧译17' and review['issues'][0]['media']['video_start']==56
    assert (source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())==before and session.status=='waiting'


def test_user_specified_translation_is_applied_exactly_once_without_model_veto_and_keeps_versions(manual):
    session,old,source,target=manual;before=(source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())
    old_review=web.agent_issue_review(session.id)
    response=action(session,'set_translation',cue_id=17,text='请多多谅解')
    assert session.status=='waiting' and session.question['kind']=='autonomous_issue_review'
    assert response['review']['remaining_ids']==[19,55] and response['review']['manual_reviewed_ids']==[17]
    actual=read_srt(Path(session.result['translated_srt']));original=read_srt(target)
    assert {c.index:c.text for c in actual if c.index in (17,19,55)}=={17:'请多多谅解',19:'旧译19',55:'旧译55'}
    assert all(c.text==('请多多谅解' if c.index==17 else old.text) for c,old in zip(actual,original))
    assert [(c.index,c.start,c.end) for c in actual]==[(c.index,c.start,c.end) for c in original]
    assert (source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())==before
    assert session.result['manual_issue_review']['resolutions']['17']['machine_verified'] is False
    assert json.loads((Path(session.result['autonomous_workspace'])/'state.json').read_text())['counts']=={'translate':1,'review_translation':2}
    with pytest.raises(ValueError,match='版本|记录'):
        web.apply_agent_issue_action(session.id,{'action':'set_translation','cue_id':19,'text':'过期页面的输入',
            'expected_translation_sha256':old_review['translation_sha256'],'expected_review_token':old_review['review_token']})


def test_finish_can_keep_unresolved_issues_without_mutating_translations_or_claiming_success(manual):
    session,old,source,target=manual;before=target.read_bytes()
    response=action(session,'finish')
    assert session.status=='done' and session.question=={}
    assert session.result['completion_status']=='completed_with_issues' and session.result['review_passed'] is False
    assert response['review']['remaining_ids']==[17,19,55]
    assert Path(session.result['translated_srt']).read_bytes()==before and target.read_bytes()==before
    assert web._read_task('task')['workflow_status']=='completed'


def test_all_manually_handled_items_can_finish_but_never_become_machine_approved(manual):
    session,_,_,_=manual
    for cue in (17,19,55):action(session,'set_translation',cue_id=cue,text=f'人工译文{cue}')
    action(session,'finish')
    assert session.status=='done' and session.result['completion_status']=='completed_manually'
    assert session.result['human_review_completed'] is True and session.result['review_passed'] is False
    assert session.result['unresolved_cue_ids']==[] and session.result['manual_reviewed_cue_ids']==[17,19,55]
    assert web._read_task('task')['completion_status']=='completed_manually'
    # A closed version remains editable only through a new explicit user action.
    action(session,'set_translation',cue_id=17,text='人工再次调整17')
    assert session.status=='waiting' and session.result['completion_status']=='manual_review_in_progress'


def test_invalid_or_running_requests_never_change_session_or_originals(manual):
    session,old,source,target=manual;before=(source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())
    for cue,text in [(True,'文字'),(99,'文字'),(17,''),(17,'正文\n\n新字幕块')]:
        with pytest.raises(ValueError):action(session,'set_translation',cue_id=cue,text=text)
    assert session.status=='waiting' and not list(old.parent.glob('autonomous_manual_*'))
    session.status='running'
    with pytest.raises(ValueError,match='状态'):web.agent_issue_review(session.id)
    assert (source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())==before


def test_confirming_unchanged_text_still_invalidates_old_review_token(manual):
    session,_,_,_=manual;old=web.agent_issue_review(session.id)
    action(session,'set_translation',cue_id=17,text='旧译17')
    assert web.agent_issue_review(session.id)['translation_sha256']==old['translation_sha256']
    with pytest.raises(ValueError,match='记录'):
        web.apply_agent_issue_action(session.id,{'action':'finish','expected_translation_sha256':old['translation_sha256'],'expected_review_token':old['review_token']})


def test_unscoped_checks_cannot_be_silently_marked_manually_complete(manual):
    session,old,_,_=manual;state=json.loads((old/'state.json').read_text())
    state['verification']['issues'].append({'kind':'alignment_needed','reason_zh':'时间仍需核查'})
    write_json_atomic(old/'state.json',state)
    for cue in (17,19,55):action(session,'set_translation',cue_id=cue,text=f'人工{cue}')
    action(session,'finish')
    assert session.result['completion_status']=='completed_with_issues'
    assert session.result['human_review_completed'] is False and session.result['unresolved_issues'][0]['kind']=='alignment_needed'


def test_http_controls_really_save_a_scoped_new_version(manual):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    session,_,_,target=manual;original=target.read_bytes()
    server=ThreadingHTTPServer(('127.0.0.1',0),web.AgentHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_address[1]}/api/agent/{session.id}/issue-review'
    try:
        with urllib.request.urlopen(url,timeout=5) as response:review=json.load(response)
        payload={'action':'set_translation','cue_id':17,'text':'请多多谅解','expected_translation_sha256':review['translation_sha256'],'expected_review_token':review['review_token']}
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=5) as response:result=json.load(response)
        assert result['review']['remaining_ids']==[19,55]
        assert result['review']['issues'][0]['translation']=='请多多谅解' and target.read_bytes()==original
        updated=result['review']
        payload={'action':'skip_translation','cue_id':19,'expected_translation_sha256':updated['translation_sha256'],'expected_review_token':updated['review_token']}
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=5) as response:result=json.load(response)
        assert result['review']['skipped_ids']==[19] and result['session']['result']['delivery_cue_count']==54
        assert target.read_bytes()==original
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_skip_omits_only_selected_output_and_keeps_original_ids_for_remaining_controls(manual):
    session,old,source,target=manual;before=(source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())
    response=action(session,'skip_translation',cue_id=17)
    review=response['review']
    assert review['remaining_ids']==[19,55] and review['skipped_ids']==[17] and review['manual_reviewed_ids']==[]
    assert review['issues'][0]['skipped'] and review['issues'][0]['manual_resolution']['action']=='skip_translation'
    output=read_srt(Path(session.result['translated_srt']))
    assert len(output)==54 and '旧译17' not in [c.text for c in output]
    assert len(read_srt(Path(session.result['original_source_srt'])))==55
    assert (source.read_bytes(),target.read_bytes(),(old/'state.json').read_bytes())==before
    # Original cue 19 remains cue 19 in the controls, even though output cue 18
    # now displays it. Do not accidentally edit original cue 20 instead.
    action(session,'set_translation',cue_id=19,text='只修改原第19条')
    output=read_srt(Path(session.result['translated_srt']))
    assert output[17].text=='只修改原第19条' and output[18].text=='旧译20'
    assert output[17].start==read_srt(target)[18].start
    assert session.result['manual_issue_review']['exports']['index_map'][17]=={'original_id':19,'output_id':18}


def test_skip_can_be_restored_without_losing_prior_versions_or_other_decisions(manual):
    session,_,_,_=manual
    action(session,'skip_translation',cue_id=17)
    skipped=Path(session.result['translated_srt']);saved=skipped.read_bytes()
    action(session,'skip_translation',cue_id=19)
    response=action(session,'set_translation',cue_id=17,text='恢复原第17条')
    assert response['review']['skipped_ids']==[19]
    assert len(read_srt(Path(session.result['translated_srt'])))==54
    assert any(c.text=='恢复原第17条' for c in read_srt(Path(session.result['translated_srt'])))
    assert skipped.read_bytes()==saved


def test_skipped_items_do_not_block_finish_and_are_not_reported_as_translated_or_machine_approved(manual):
    session,_,_,target=manual;before=target.read_bytes()
    for cue in (17,19,55):action(session,'skip_translation',cue_id=cue)
    action(session,'finish')
    assert session.status=='done' and session.result['completion_status']=='completed_manually'
    assert session.result['review_passed'] is False and session.result['human_review_completed'] is True
    assert session.result['skipped_cue_ids']==[17,19,55] and session.result['manual_reviewed_cue_ids']==[]
    assert session.result['delivery_cue_count']==52 and len(read_srt(Path(session.result['translated_srt'])))==52
    assert '跳过3条' in session.result['quality_warning'] and target.read_bytes()==before
    assert web._read_task('task')['skipped_cue_ids']==[17,19,55]


def test_all_skipped_output_can_be_empty_and_still_be_restored_from_complete_working_copy(manual,monkeypatch):
    session,old,source,target=manual
    write_srt([SubtitleCue(1,0,1,'음악')],source);write_srt([SubtitleCue(1,0,1,'音乐')],target)
    state=json.loads((old/'state.json').read_text());state['verification']['issues']=[{'id':1,'kind':'semantic_uncertain'}]
    write_json_atomic(old/'state.json',state)
    action(session,'skip_translation',cue_id=1)
    assert Path(session.result['translated_srt']).read_bytes()==b''
    action(session,'finish')
    assert session.status=='done' and session.result['delivery_cue_count']==0
    assert web.agent_issue_review(session.id)['issues'][0]['skipped']
    monkeypatch.setattr(web,'_AGENT_SESSIONS',{})
    session=web.continue_agent_task('task')
    assert session.status=='done' and web.agent_issue_review(session.id)['skipped_ids']==[1]
    action(session,'set_translation',cue_id=1,text='恢复后的译文')
    assert read_srt(Path(session.result['translated_srt']))[0].text=='恢复后的译文'


def test_task_history_and_missing_session_restore_skips_without_running_agent(manual,monkeypatch):
    session,_,_,_=manual
    action(session,'skip_translation',cue_id=17)
    target=Path(session.result['translated_srt']);before=target.read_bytes()
    assert web.continue_agent_task('task') is session
    monkeypatch.setattr(web,'_AGENT_SESSIONS',{})
    restored=web.continue_agent_task('task')
    assert restored.status=='waiting' and restored.question['kind']=='autonomous_issue_review'
    assert web.agent_issue_review(restored.id)['skipped_ids']==[17]
    assert Path(restored.result['translated_srt']).read_bytes()==before
