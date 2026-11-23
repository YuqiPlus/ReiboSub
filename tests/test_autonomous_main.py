import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_translate.agent import autonomous as agent
from video_translate.agent import vision
from video_translate.agent.models import AgentSession
from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import write_srt
from video_translate.asr_review_web import read_json,write_json_atomic


def basic_state():
    return {'counts':{},'events':[],'sources':{},'captions':[],'language':'korean','evidence':{},'user_confirmations':{}}


def test_only_link_probe_initially_available_and_no_arbitrary_shell():
    state=basic_state()
    assert [t.name for t in agent.ready(state)]==['probe']
    for call in ({'tool':'shell','args':{}},{'tool':'probe','args':{'url':'http://localhost'}},{'tool':'finish'}):
        with pytest.raises(ValueError):agent.validate_call(call,state)


def test_readiness_enforces_real_tools_and_budget():
    s=basic_state();s.update(probe={'duration':90},captions=[{'lang':'ko','kind':'manual'}])
    assert 'captions' in {t.name for t in agent.ready(s)} and 'asr' not in {t.name for t in agent.ready(s)}
    s['media']='/owned/video.mp4'
    assert 'asr' in {t.name for t in agent.ready(s)} and 'ocr' not in {t.name for t in agent.ready(s)}
    s['counts']['asr']=1
    assert 'asr' not in {t.name for t in agent.ready(s)}
    with pytest.raises(ValueError):agent.validate_call({'tool':'captions','args':{'index':99}},s)


def test_vision_only_accepts_small_stable_non_subtitle_logo_proposals():
    result={'subtitle_regions':[[0,.7,1,.98]],'regions':[
        {'kind':'logo','bbox':[.8,.02,.95,.1],'certainty':'high','frame_ids':[0,1]},
        {'kind':'logo','bbox':[.8,.75,.95,.85],'certainty':'high','frame_ids':[0,1]},
        {'kind':'object_text','bbox':[.1,.1,.2,.2],'certainty':'high','frame_ids':[0,1]},
        {'kind':'watermark','bbox':[0,0,1,.6],'certainty':'high','frame_ids':[0,1]},
        {'kind':'logo','bbox':[.1,.02,.2,.1],'certainty':'high','frame_ids':[0]}]}
    checked=vision.validate(result,3)
    assert len(checked['exclusion_proposals'])==1 and len(checked['rejected_proposals'])==4


@pytest.mark.parametrize('box', [[0,0,2,1],[0,0,0,1],[0,float('nan'),1,1],[True,0,1,1]])
def test_vision_bad_boxes_rejected(box):
    with pytest.raises(ValueError):vision.rect(box)


def test_mask_trial_detects_lost_subtitle_even_if_total_box_count_is_equal():
    before={'width':100,'height':100,'ocr_analysis':{'accepted':[
        {'text':'对白字幕','bbox':[10,75,90,90]},{'text':'Logo','bbox':[80,0,95,10]}]}}
    after={'width':100,'height':100,'ocr_analysis':{'accepted':[
        {'text':'Logo','bbox':[80,0,95,10]},{'text':'其他噪声','bbox':[0,0,20,10]}]}}
    result=vision.trial_comparison(before,after,[[0,.7,1,1]])
    assert not result['safe'] and result['lost_protected_text']==['对白字幕']


@pytest.fixture
def runtime(tmp_path):
    session=AgentSession(id='test',payload={'url':'https://www.youtube.com/watch?v=abcdefghijk','agent_mode':'autonomous','source_language':'korean'})
    source=tmp_path/'original.srt';write_srt([SubtitleCue(1,0,2,'안녕하세요')],source)
    calls=[]
    def ensure(path):Path(path).resolve().relative_to(tmp_path.resolve())
    def update(sid,values):session.result.update(values)
    def done(sid,values):session.result.update(values);session.status='done';session.phase='done'
    def wait(sid,phase,question):session.status='waiting';session.phase=phase;session.question=question
    def translate(payload):
        calls.append('translate');out=Path(payload['out']);write_srt([SubtitleCue(1,0,2,'你好')],out)
        return SimpleNamespace(result={'translated_srt':str(out)})
    def bind(sid,task):session.result.update(task_id=task['id'],task_dir=str(tmp_path/'task'),run_generation=1)
    app=SimpleNamespace(ROOT=tmp_path,PYTHON='/project/python',_ensure_under_root=ensure,_agent_workspace=lambda s:tmp_path/'work',
        normalize_youtube_url=lambda url:url,_agent_update_result=update,_agent_set_phase=lambda sid,phase:setattr(session,'phase',phase),
        get_agent_session=lambda sid:session,_agent_log=lambda *a:None,_agent_done=done,_agent_wait=wait,
        _wait_for_job=lambda j,**k:j.result,
        probe_video=lambda *a,**k:{'normalized_url':session.payload['url'],'title':'fixture','duration':20,'subtitles':[{'lang':'ko','kind':'manual'}]},
        _ensure_agent_task=lambda **k:{'id':'task','run_generation':1},_bind_session_to_task_run=bind,
        _update_task_stage=lambda *a,**k:True,_session_run_generation=lambda s:1,
        download_subtitle_job=lambda p:SimpleNamespace(result={'subtitle_path':str(source)}),translate_subtitle_job=translate)
    def ensure_video(item,probe,*,phase):
        video=tmp_path/'project'/'video.mp4'
        if not video.exists():
            video.parent.mkdir(exist_ok=True);video.write_bytes(b'completed-video');calls.append('video_download')
        context={'input_video':str(video),'project_dir':str(video.parent)}
        item.result.update(context)
        return context
    app._agent_ensure_project_video=ensure_video
    # Frozen v1 sessions must remain resumable without opting them into a new
    # planner protocol. Goal-controller tests below explicitly create v2 state.
    result=agent.Runtime(app,session)
    result.state['controller_version']=1
    result.state.pop('screen_source_policy_version',None)
    result.save()
    return result,session,app,calls


def test_autonomous_tools_use_bilibili_selected_part_and_caption_provenance(runtime):
    r, session, app, calls = runtime
    url = 'https://www.bilibili.com/video/BV1GJ411x7h7?p=2'
    session.payload['url'] = 'https://b23.tv/example'
    app.probe_video = lambda *a, **k: {'normalized_url': url, 'source_type': 'bilibili',
        'title': 'fixture [BV1GJ411x7h7 P2]', 'duration': 20,
        'subtitles': [{'lang': 'ai-ko', 'kind': 'auto'}]}
    r.execute('probe', {})
    assert session.payload['url'] == url and session.result['source_type'] == 'bilibili'
    received = []
    source = r.root / 'captions.srt'
    write_srt([SubtitleCue(1, 0, 2, '안녕하세요')], source)
    app.download_subtitle_job = lambda p: (received.append(p) or SimpleNamespace(result={'subtitle_path': str(source)}))
    r.state['language'] = 'auto'
    r.execute('captions', {'index': 0})
    assert received[0]['url'] == url and received[0]['kind'] == 'auto'
    assert r.state['language'] == 'korean'
    assert next(iter(r.state['sources'].values()))['language'] == 'ko'


def test_main_route_with_captions_skips_video_download_ocr_and_asr(runtime,monkeypatch):
    r,session,app,calls=runtime
    commands=iter([{'tool':'probe'},{'tool':'captions','args':{'index':0}},
        {'tool':'select_source','args':{'source_id':'captions_1'}},{'tool':'inspect'},{'tool':'glossary'}])
    path=r.root/'glossary.yaml'
    def glossary(item,source,*,defer_wait=False):
        assert defer_wait
        path.write_text("characters:\n- source: 레이\n  zh: ''\n  reviewed: false\n")
        item.result['glossary_path']=str(path)
    app._agent_generate_glossary_review=glossary
    original_wait=app._agent_wait
    def published_after_persistence(sid,phase,question):
        assert read_json(r.path)['events'][-1]['tool']=='glossary'
        original_wait(sid,phase,question)
    app._agent_wait=published_after_persistence
    from scripts import asr_review_agent
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda root,name,task,instruction,data:
        {'checks':[{'id':row['id'],'verdict':'pass'} for row in data['subtitles']]} if name.startswith('verify-') else next(commands))
    agent.run(session,app)
    assert session.status=='waiting' and session.phase=='review_glossary' and calls==[]
    saved=read_json(r.path)
    assert [e['tool'] for e in saved['events']]==['probe','captions','select_source','inspect','glossary']
    assert not agent.glossary_approved(saved)
    from video_translate import web_agent
    import hashlib
    path.write_text('characters:\n- source: 레이\n  zh: 用户指定译名\n  reviewed: true\n')
    session.result.update(translation_glossary_path=str(path),glossary_digest=hashlib.sha256(path.read_bytes()).hexdigest())
    app._glossary_review_summary=web_agent._glossary_review_summary;app._glossary_items=web_agent._glossary_items;app._load_yaml_file=web_agent._load_yaml_file
    commands=iter([{'tool':'translate'},{'tool':'verify'},{'tool':'finish'}])
    original_translate=app.translate_subtitle_job
    def with_glossary(payload):
        assert payload['glossary']==str(path)
        return original_translate(payload)
    app.translate_subtitle_job=with_glossary
    session.status='running';session.question={}
    agent.resume_after_glossary(session,app)
    assert session.status=='done' and calls==['translate']
    assert Path(session.result['translated_srt']).is_file()


def test_mixed_source_translation_preserves_screen_brackets_in_srt_and_bcc(runtime):
    import hashlib
    import json
    from video_translate.subtitle.delivery import export_bcc
    from video_translate.subtitle.srt import read_srt

    r,session,app,_=runtime
    source=r.root/'source.mixed.srt'
    write_srt([SubtitleCue(1,0,3,'[제목]'),SubtitleCue(2,1,2,'안녕하세요'),
               SubtitleCue(3,3,4,'[첫 줄][둘째 줄]'),SubtitleCue(4,4,5,'[편지]')],source)
    info=r.add_source(source,'mixed',mixed_provenance={'screen_cue_ids':[1,3,4]})
    r.state['selected']=info['source_id']
    glossary=r.root/'approved.yaml';glossary.write_text('characters: []\n',encoding='utf-8')
    r.state['glossary_review']={'human_approved':True,'snapshot_path':str(glossary),
        'source_text_sha256':agent.source_text_digest(r.state),'sha256':hashlib.sha256(glossary.read_bytes()).hexdigest()}
    r.state['counts']['translate']=1
    r.execute('inspect',{})
    model_output=r.root/'zh_1.srt'
    def translate(payload):
        assert '[内容]' in payload['extra_prompt']
        assert payload['source_srt']==str(source)
        write_srt([SubtitleCue(1,0,3,'标题'),SubtitleCue(2,1,2,'大家好'),
                   SubtitleCue(3,3,4,'[第一行][第二行]'),SubtitleCue(4,4,5,'【画面配字】手写信')],model_output)
        return SimpleNamespace(result={'translated_srt':str(model_output)})
    app.translate_subtitle_job=translate
    assert r.execute('translate',{})=={'translated':True}
    target=Path(session.result['translated_srt'])
    expected=[(0,3,'[标题]'),(1,2,'大家好'),(3,4,'[第一行][第二行]'),(4,5,'[手写信]')]
    assert target!=model_output and read_srt(model_output)[0].text=='标题'
    assert [(c.start,c.end,c.text) for c in read_srt(target)]==expected
    assert [(c['from'],c['to'],c['content']) for c in json.loads(export_bcc(target).read_text())['body']]==expected


def test_chinese_to_english_agent_waits_for_human_terms_then_translates_and_verifies(runtime, monkeypatch):
    import hashlib
    from scripts import asr_review_agent
    from video_translate import web_agent
    r, session, app, calls = runtime
    session.payload.update(url='https://www.bilibili.com/video/BV1GJ411x7h7', source_language='chinese', target_language='en')
    r.state.update(language='chinese', target_language='en'); r.save()
    source = r.root/'chinese.srt'; write_srt([SubtitleCue(1,0,2,'小王，你好！')],source)
    app.probe_video = lambda *a, **k: {'normalized_url':session.payload['url'],'source_type':'bilibili','title':'中文测试','duration':2,'subtitles':[{'lang':'zh-CN','kind':'manual'}]}
    app.download_subtitle_job = lambda p: SimpleNamespace(result={'subtitle_path':str(source)})
    glossary = r.root/'english-glossary.yaml'
    def generate(item, path, *, defer_wait=False):
        glossary.write_text("target_language: en\ncharacters:\n- source: 小王\n  zh: ''\n  reviewed: false\n")
        item.result['glossary_path']=str(glossary)
    app._agent_generate_glossary_review=generate
    actions=iter([{'tool':'probe'},{'tool':'captions','args':{'index':0}},{'tool':'select_source','args':{'source_id':'captions_1'}},{'tool':'inspect'},{'tool':'glossary'}])
    def model(root,name,task,instruction,data):
        if name.startswith('verify-'):
            assert data['target_language']=='en'
            return {'checks':[{'id':row['id'],'verdict':'pass'} for row in data['subtitles']]}
        return next(actions)
    monkeypatch.setattr(asr_review_agent,'llm_json',model)
    agent.run(session,app)
    assert session.status=='waiting' and session.phase=='review_glossary' and 'translate' not in calls
    glossary.write_text('target_language: en\ncharacters:\n- source: 小王\n  zh: Xiao Wang\n  reviewed: true\n')
    session.result.update(translation_glossary_path=str(glossary),glossary_digest=hashlib.sha256(glossary.read_bytes()).hexdigest())
    app._glossary_review_summary=web_agent._glossary_review_summary;app._glossary_items=web_agent._glossary_items;app._load_yaml_file=web_agent._load_yaml_file
    def translate(payload):
        assert payload['target_language']=='en' and Path(payload['out']).name.startswith('en_')
        calls.append('translate');write_srt([SubtitleCue(1,0,2,'Hello, Xiao Wang!')],Path(payload['out']))
        return SimpleNamespace(result={'translated_srt':payload['out']})
    app.translate_subtitle_job=translate
    actions=iter([{'tool':'translate'},{'tool':'verify'},{'tool':'finish'}])
    session.status='running';session.question={}
    agent.resume_after_glossary(session,app)
    assert session.status=='done' and calls==['translate']
    assert session.result['target_language']=='en' and Path(session.result['translated_srt']).name.startswith('en_')
    latest=read_json(r.path)
    assert latest['verification']['acceptable'] and agent.current_verification(latest)


def test_main_patch_cannot_use_unrelated_source_evidence(runtime):
    r,session,app,calls=runtime;s=r.state
    path=r.root/'source.srt';write_srt([SubtitleCue(1,0,2,'나의 김서원님')],path)
    s.update(selected='asr_1',sources={'asr_1':{'path':str(path),'kind':'asr'}},
             inspection={'cues':[{'index':1,'start':0,'end':2,'text':'나의 김서원님'}]},counts={'patch':1})
    s['evidence']={'1':[{'engine':'whisper','text':'나의 김서완님','source_id':'other'},
                        {'engine':'qwen','text':'나의 김서완님','source_id':'other'}]}
    with pytest.raises(ValueError):r.execute('patch',{'cue_id':1,'text':'나의 김서완님'})
    assert read_srt_for_test(path)=='나의 김서원님'


def read_srt_for_test(path):
    from video_translate.subtitle.srt import read_srt
    return read_srt(path)[0].text


def test_user_question_cannot_invent_candidate(runtime):
    r,_,_,_=runtime;r.state['inspection']={'cues':[{'index':1,'text':'实际字幕'}]}
    with pytest.raises(ValueError):r.ask({'message':'确认？','cue_id':1,'candidates':['凭空的新字幕']})


def test_source_question_can_use_an_obtained_unselected_source_without_confirming_guesses(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,_,_=runtime
    path=r.root/'captions.srt';write_srt([SubtitleCue(1,0,2,'안녕하세요')],path)
    r.state['sources']={'captions_1':{'path':str(path),'kind':'captions'}}
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:(_ for _ in ()).throw(RuntimeError('offline')))
    r.ask({'message':'请听这句补充线索','cue_id':1,'candidates':['안녕하세요','猜出来的韩文']})
    assert session.status=='waiting' and session.question['candidates']==['안녕하세요']
    assert session.question['unverified_suggestions']==['猜出来的韩文']
    assert r.state['pending_question']['source_id']=='captions_1' and not r.state.get('selected')
    assert read_srt_for_test(path)=='안녕하세요'


def test_translated_catalog_aliases_are_unambiguous_and_do_not_steal_external_target(runtime):
    from video_translate.agent import subtitle_catalog
    r,_,_,_=runtime
    r.state['translated']=str(r.root/'translated.srt')
    assert subtitle_catalog.normalize_id(r.state,'target:translated')=='translated'
    assert subtitle_catalog.normalize_id(r.state,'target:1')=='translated'
    r.state['target_caption_checks']={'1':{'path':'external.srt'}}
    assert subtitle_catalog.normalize_id(r.state,'target:1')=='target:1'
    assert subtitle_catalog.normalize_id(r.state,'target:99')=='target:99'
    call=agent.normalize_call({'tool':'read_subtitles','args':{'source_id':'target:translated','cue_ids':[1]}},r.state)
    assert call['args']['source_id']=='translated'
    assert 'translated' in {row['source_id'] for row in subtitle_catalog.catalog(r.state)}


def test_important_weak_words_cannot_pass_on_fluent_chinese_alone(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,_,_,_=runtime;s=r.state
    source=r.root/'source.srt';zh=r.root/'zh.srt'
    write_srt([SubtitleCue(1,0,2,'나의 김서원님')],source);write_srt([SubtitleCue(1,0,2,'某位朋友')],zh)
    s.update(selected='asr_2',sources={'asr_2':{'kind':'asr','path':str(source),'evidence_source_id':'asr_1'}},
        translated=str(zh),counts={'verify':1},alignment={'accepted':1},inspection={'cues':[], 'issues':[{'id':1,'kind':'weak_recognition','needs_evidence':True}]})
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:{'checks':[{'id':1,'verdict':'pass'}]})
    assert not r.verify()['acceptable']
    s['evidence']={'1':[{'source_id':'asr_1','engine':engine,'text':'나의 김서원님'} for engine in ('whisper','qwen')]}
    assert r.verify()['acceptable']


def test_repair_keeps_other_words_quality_flags_and_preserves_original(runtime):
    r,_,_,_=runtime;s=r.state;source=r.root/'source.srt';meta=r.root/'cues.json'
    write_srt([SubtitleCue(1,0,2,'나의 김서원님'),SubtitleCue(2,3,4,'안 먹었어요')],source)
    before=source.read_bytes()
    write_json_atomic(meta,{'cues':[{'index':1,'text':'나의 김서원님','minimum_probability':.1},
                                    {'index':2,'text':'안 먹었어요','minimum_probability':.1}]})
    s.update(selected='asr_1',sources={'asr_1':{'kind':'asr','path':str(source),'metadata':str(meta)}},
        inspection={'cues':[{'index':1,'text':'나의 김서원님','start':0,'end':2}]},counts={'patch':1})
    s['evidence']={'1':[{'source_id':'asr_1','engine':e,'text':'나의 김서완님'} for e in ('whisper','qwen')]}
    r.execute('patch',{'cue_id':1,'text':'나의 김서완님'})
    result=r.execute('inspect',{})
    assert [i['id'] for i in result['issues'] if i.get('needs_evidence')]==[2]
    assert source.read_bytes()==before


def test_autonomous_dispatch_is_opt_in_at_api_and_legacy_remains_default(monkeypatch):
    from video_translate import web_agent
    called=[]
    monkeypatch.setattr(web_agent,'_AGENT_SESSIONS',{})
    monkeypatch.setattr(web_agent,'_run_agent_async',lambda sid,fn:fn(web_agent._AGENT_SESSIONS[sid]))
    monkeypatch.setattr(web_agent,'_agent_start',lambda s:called.append('legacy'))
    monkeypatch.setattr(agent,'run',lambda *a,**k:called.append('autonomous'))
    web_agent.start_agent_session({'url':'abcdefghijk'})
    web_agent.start_agent_session({'url':'abcdefghijk','agent_mode':'autonomous'})
    assert called==['legacy','autonomous']


def test_empty_reply_does_not_clear_waiting_question(monkeypatch):
    from video_translate import web_agent
    session=AgentSession(id='test',status='waiting',payload={'agent_mode':'autonomous'},question={'kind':'autonomous_question'})
    monkeypatch.setattr(web_agent,'_AGENT_SESSIONS',{'test':session})
    with pytest.raises(ValueError):web_agent.answer_agent_session('test',{'action':'autonomous_reply','clue':''})
    assert session.status=='waiting' and session.question['kind']=='autonomous_question'


def test_asr_tool_builds_cues_from_word_outputs_without_changing_asr22(runtime,monkeypatch):
    r,_,_,_=runtime;r.state.update(media='/video.mp4',language='auto')
    def words_only(*a,**k):
        write_json_atomic(r.root/'asr22/words.json',{'info':{'language':'ko'},'words':[
            {'start':0,'end':1,'text':'안녕하세요.','probability':.95,'segment_id':1}]})
    monkeypatch.setattr(r,'command',words_only)
    result=r.execute('asr',{})
    source=r.state['sources'][result['source_id']]
    assert r.state['language']=='korean'
    assert read_srt_for_test(Path(source['path']))=='안녕하세요.'
    assert Path(source['metadata']).is_file()


def test_ocr_tool_uses_final_layered_output_and_does_not_replace_lab_debug(runtime):
    r,_,app,_=runtime;r.state['trial']={'params':{'input_video':'/video.mp4'}}
    layered=r.root/'layered.srt';raw=r.root/'raw.srt'
    write_srt([SubtitleCue(1,0,2,'[화면] 대사')],layered)
    write_srt([SubtitleCue(1,0,2,'대사')],raw)
    def ocr(payload):
        assert payload['materialize_debug_bundle'] is False
        return SimpleNamespace(result={'v3_layered_srt':str(layered),'v3_refined_srt':str(raw)})
    app.ocr_development_job=ocr
    result=r.execute('ocr',{})
    assert read_srt_for_test(Path(r.state['sources'][result['source_id']]['path']))=='[화면] 대사'


def test_wrong_confirmation_does_not_clear_waiting_question(monkeypatch):
    from video_translate import web_agent
    session=AgentSession(id='test',status='waiting',payload={'agent_mode':'autonomous'},
        question={'kind':'autonomous_question','candidates':['原文']})
    monkeypatch.setattr(web_agent,'_AGENT_SESSIONS',{'test':session})
    with pytest.raises(ValueError):web_agent.answer_agent_session('test',{'action':'autonomous_reply','confirmed_text':'编造'})
    assert session.status=='waiting' and session.question['candidates']==['原文']


def test_resume_restores_pending_question_without_running_the_planner(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,_=runtime;r.state['probe']={'duration':20}
    r.state['pending_question']={'message':'请给点线索','candidates':[]};r.save()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('恢复待答问题不应再次规划'))
    agent.run(session,app)
    assert session.status=='waiting' and session.question['message']=='请给点线索'


def test_isolated_ocr_job_does_not_materialize_shared_debug(monkeypatch,tmp_path):
    from video_translate import web_agent
    video=tmp_path/'fixture.mp4';video.write_bytes(b'fixture')
    monkeypatch.setattr(web_agent,'ROOT',tmp_path)
    monkeypatch.setattr(web_agent,'JOB_DIR',tmp_path/'jobs')
    monkeypatch.setattr(web_agent,'_run_command',lambda *a,**k:None)
    monkeypatch.setattr(web_agent,'_materialize_ocr_debug_bundle',lambda *a,**k:pytest.fail('实验任务不得覆盖Lab调试目录'))
    job=web_agent.ocr_development_job({'input_video':str(video),'ocr_extraction_mode':'region_v3','materialize_debug_bundle':False})
    result=web_agent._wait_for_job(job,timeout=5)
    assert Path(result['v3_layered_srt']).parent==tmp_path/'jobs'/job.id
    assert 'debug_dir' not in result


def prepared_translation(runtime):
    r,session,app,calls=runtime
    source=r.root/'source.srt';zh=r.root/'zh.srt'
    write_srt([SubtitleCue(1,0,2,'안 먹었어요')],source);write_srt([SubtitleCue(1,0,2,'没吃')],zh)
    r.state.update(probe={'duration':20,'title':'fixture'},selected='captions_1',
        sources={'captions_1':{'path':str(source),'kind':'captions'}},translated=str(zh),counts={'verify':1})
    import hashlib
    r.state['execution_policy']={'verification_only':True,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'translated_sha256':hashlib.sha256(zh.read_bytes()).hexdigest()}
    r.execute('inspect',{})
    return r,session,app,calls


def test_legacy_positive_issue_list_is_rechecked_not_accepted_or_retranslated(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime)
    r.state['verification']={'acceptable':False,'issues':[{'id':1,'reason_zh':'无明显问题'}]}
    r.state['pending_question']={'message':'是否确认通过内部错误？','cue_id':None}
    r.save();decisions=iter([{'tool':'verify'},{'tool':'finish'}])
    def llm(root,name,task,instruction,data):
        if name.startswith('verify-'):return {'checks':[{'id':1,'verdict':'pass'}]}
        return next(decisions)
    monkeypatch.setattr(asr_review_agent,'llm_json',llm)
    before=Path(r.state['translated']).read_bytes()
    agent.run(session,app)
    saved=read_json(r.path)
    assert session.status=='done' and calls==[]
    assert Path(session.result['translated_srt']).read_bytes()==before
    assert 'pending_question' not in saved
    assert [event['tool'] for event in saved['events']]==['internal_recovery','verify','finish']
    assert saved['verification_history'][0]['acceptable'] is False


def test_protocol_error_gets_one_repair_then_stops_without_asking_or_translating(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime);r.save();requested=[]
    def llm(root,name,*args):
        requested.append(name)
        return {'issues':[{'id':1,'source_quote':'안','reason_zh':'无问题'}]} if name.startswith('verify-') else {'tool':'verify'}
    monkeypatch.setattr(asr_review_agent,'llm_json',llm)
    with pytest.raises(agent.InternalAgentError):agent.run(session,app)
    saved=read_json(r.path)
    assert len([n for n in requested if n.startswith('verify-')])==2
    assert saved['verification']['status']=='internal_error' and not saved['verification']['acceptable']
    assert saved['internal_error']['code']=='verification_protocol_error'
    assert session.question=={} and calls==[]


def test_repeated_invalid_tools_fail_internally_instead_of_asking_user(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime);r.save()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:{'tool':'finish'})
    with pytest.raises(agent.InternalAgentError):agent.run(session,app)
    state=read_json(r.path)
    assert state['consecutive_tool_errors']==3 and state['internal_error']['code']=='tool_recovery_exhausted'
    assert session.question=={} and calls==[]


def test_user_cannot_override_internal_review_error_or_generic_acceptance(runtime):
    r,_,_,_=prepared_translation(runtime)
    r.state['events']=[{},{}]
    r.state['internal_error']={'code':'verification_protocol_error'}
    assert 'ask_user' not in {t.name for t in agent.ready(r.state)}
    with pytest.raises(ValueError):r.ask({'message':'确认通过？'})
    r.state.pop('internal_error')
    with pytest.raises(ValueError):r.ask({'message':'确认通过？'})


def test_verification_only_policy_blocks_all_mutating_tools_and_checks_input_hashes(runtime):
    import hashlib
    r,_,_,calls=prepared_translation(runtime)
    r.state['execution_policy']={'verification_only':True,
        'source_sha256':hashlib.sha256(Path(r.selected()['path']).read_bytes()).hexdigest(),
        'translated_sha256':hashlib.sha256(Path(r.state['translated']).read_bytes()).hexdigest()}
    assert {t.name for t in agent.ready(r.state)}<={'inspect','verify','finish','ask_user'}
    for name in ('translate','patch','asr','captions','select_source','align','download'):
        with pytest.raises(ValueError):r.execute(name,{})
    Path(r.state['translated']).write_text('unexpected edit')
    with pytest.raises(agent.InternalAgentError):r.check_locked_inputs()
    assert calls==[]


def test_locked_review_with_real_issues_pauses_without_bad_tool_retries(runtime,monkeypatch):
    import hashlib
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime)
    r.state['execution_policy']={'verification_only':True,
        'source_sha256':hashlib.sha256(Path(r.selected()['path']).read_bytes()).hexdigest(),
        'translated_sha256':hashlib.sha256(Path(r.state['translated']).read_bytes()).hexdigest()}
    r.save()
    def llm(root,name,task,instruction,data):
        if name.startswith('verify-'):
            assert 'context_before' in data['subtitles'][0]
            return {'checks':[{'id':1,'verdict':'uncertain','source_quote':'안','translation_quote':'没吃','reason_zh':'需进一步结合原音确认'}]}
        return {'tool':'verify'}
    monkeypatch.setattr(asr_review_agent,'llm_json',llm)
    agent.run(session,app)
    assert session.status=='waiting' and session.question['kind']=='autonomous_verification_review'
    assert session.question['options']==[] and calls==[]
    state=read_json(r.path)
    assert state['review_hold'] and not state.get('internal_error')
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('内容待复核不应空转重试'))
    agent.run(session,app)


def test_content_review_hold_cannot_be_confirmed_away_at_api(monkeypatch):
    from video_translate import web_agent
    session=AgentSession(id='test',status='waiting',payload={'agent_mode':'autonomous'},
        question={'kind':'autonomous_verification_review','options':[]})
    monkeypatch.setattr(web_agent,'_AGENT_SESSIONS',{'test':session})
    with pytest.raises(ValueError):web_agent.answer_agent_session('test',{'action':'autonomous_reply','clue':'确认通过'})
    assert session.status=='waiting' and session.question['kind']=='autonomous_verification_review'


def test_scoped_translation_review_isolated_from_whole_translation_and_source_edits(runtime,monkeypatch):
    import hashlib
    from video_translate.agent import translation_review
    r,session,app,calls=prepared_translation(runtime);original=Path(r.state['translated'])
    source=Path(r.selected()['path']);source_before=source.read_bytes();zh_before=original.read_bytes()
    r.state['verification']={'schema_version':agent.SCHEMA_VERSION,'status':'complete','acceptable':False,
        'issues':[{'id':1,'kind':'translation_error','source_quote':'안','reason_zh':'仅作局部测试'}],
        'checks':[{'id':1,'verdict':'issue'}]}
    r.state['execution_policy']={'targeted_translation_review':True,'allowed_cue_ids':[1],
        'original_translation_path':str(original),'source_sha256':hashlib.sha256(source_before).hexdigest(),
        'translated_sha256':hashlib.sha256(zh_before).hexdigest()}
    assert [t.name for t in agent.ready(r.state)]==['review_translation']
    for name in ('translate','patch','asr','align','download'):
        with pytest.raises(ValueError):r.execute(name,{})
    with pytest.raises(ValueError):agent.validate_call({'tool':'review_translation','args':{'cue_ids':[2]}},r.state)
    revised=r.root/'local.srt';write_srt([SubtitleCue(1,0,2,'我没吃')],revised)
    def local(source_path,zh_path,issues,ids,out):
        assert ids==[1] and Path(source_path)==source and Path(zh_path)==original
        return {'translated_srt':str(revised),'audit':str(out/'audit.json'),'output_sha256':hashlib.sha256(revised.read_bytes()).hexdigest(),
            'changed_ids':[1],'unresolved_ids':[],'decisions':[{'id':1,'source':'안 먹었어요','action':'revise'}]}
    monkeypatch.setattr(translation_review,'review_translation_cues',local)
    r.state['counts']['review_translation']=1
    r.execute('review_translation',{'cue_ids':[1]})
    assert r.state['verification']['acceptable'] and r.state['verification']['checks']==[{'id':1,'verdict':'pass'}]
    def materialize(session,path,name):
        assert name in {f'source.review_{session.id}.srt',f'zh.review_{session.id}.srt'}
        return path
    app._materialize_task_artifact=materialize
    app._copy_agent_translated_sidecar=lambda *a:pytest.fail('局部修订不得覆盖原素材旁的字幕')
    r.execute('finish',{})
    assert session.status=='done' and calls==[]
    assert source.read_bytes()==source_before and original.read_bytes()==zh_before


def test_failed_local_review_uses_new_directory_even_when_retry_count_is_reused(runtime,monkeypatch):
    from video_translate.agent import translation_review
    r,_,_,_=prepared_translation(runtime)
    r.state['execution_policy']={'targeted_translation_review':True,'allowed_cue_ids':[1],
        'original_translation_path':r.state['translated'],
        'source_sha256':__import__('hashlib').sha256(Path(r.selected()['path']).read_bytes()).hexdigest(),
        'translated_sha256':__import__('hashlib').sha256(Path(r.state['translated']).read_bytes()).hexdigest()}
    r.state['verification']={'issues':[{'id':1,'kind':'translation_error'}]}
    directories=[]
    def fail(source,target,issues,ids,folder,**kwargs):
        folder.mkdir();directories.append(folder)
        raise RuntimeError('partial attempt retained')
    monkeypatch.setattr(translation_review,'review_translation_cues',fail)
    for _ in range(2):
        r.state['counts']['review_translation']=1
        with pytest.raises(RuntimeError,match='partial attempt'):
            r.execute('review_translation',{'cue_ids':[1]})
    assert len(set(directories))==2 and all(path.is_dir() for path in directories)


def test_formal_translation_and_delivery_cannot_skip_human_glossary(runtime):
    r,_,_,calls=prepared_translation(runtime);r.state.pop('execution_policy')
    r.state['verification']={'schema_version':agent.SCHEMA_VERSION,'acceptable':True}
    names={t.name for t in agent.ready(r.state)}
    assert 'glossary' in names and not names&{'translate','finish','review_translation'}
    for name in ('translate','finish'):
        with pytest.raises(agent.EvidenceRequired,match='Glossary'):r.execute(name,{})
    assert calls==[]


def test_pending_glossary_resumes_waiting_without_model_or_translation(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime);r.state.pop('execution_policy')
    path=r.root/'draft.yaml';path.write_text("characters:\n- source: 레이\n  suggested_zh: 建议译名\n  zh: ''\n  reviewed: false\n")
    r.state.update(pending_glossary=True,glossary_review={'path':str(path),'source_text_sha256':agent.source_text_digest(r.state),'human_approved':False})
    r.save()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('等待人工审核不应调用模型'))
    agent.run(session,app)
    assert session.status=='waiting' and session.phase=='review_glossary' and calls==[]
    assert session.question['options']==[{'action':'continue_after_glossary','label':'我已审核，继续翻译'}]
    assert not agent.glossary_approved(read_json(r.path))


def test_human_glossary_binding_survives_retiming_but_not_text_or_snapshot_edits(runtime):
    import hashlib
    r,_,_,_=prepared_translation(runtime);r.state.pop('execution_policy')
    path=r.root/'snapshot.yaml';path.write_text('characters: []\n')
    r.state['glossary_review']={'human_approved':True,'source_text_sha256':agent.source_text_digest(r.state),
        'snapshot_path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    assert agent.glossary_approved(r.state)
    source=Path(r.selected()['path']);write_srt([SubtitleCue(1,1,3,'안 먹었어요')],source)
    assert agent.glossary_approved(r.state)
    write_srt([SubtitleCue(1,1,3,'새 사람')],source)
    assert not agent.glossary_approved(r.state)
    write_srt([SubtitleCue(1,1,3,'안 먹었어요')],source);path.write_text('characters: []\nterms: []\n')
    assert not agent.glossary_approved(r.state)


def test_plain_reply_or_skip_cannot_confirm_a_glossary(runtime,monkeypatch):
    from video_translate import web_agent
    r,session,app,calls=runtime
    session.status='waiting';session.phase='review_glossary'
    session.question={'kind':'review_glossary'}
    monkeypatch.setattr(web_agent,'_AGENT_SESSIONS',{session.id:session})
    for answer in ({'action':'skip_glossary'},{'action':'autonomous_reply','clue':'都确认好了'}):
        with pytest.raises(ValueError):web_agent.answer_agent_session(session.id,answer)
        assert session.status=='waiting' and session.question['kind']=='review_glossary'


def test_unreviewed_glossary_snapshot_cannot_mark_human_approval(runtime):
    import hashlib
    from video_translate import web_agent
    r,session,app,calls=prepared_translation(runtime);r.state.pop('execution_policy')
    path=r.root/'snapshot.yaml';path.write_text("characters:\n- source: 레이\n  zh: 候选\n  reviewed: false\n")
    r.state['glossary_review']={'source_text_sha256':agent.source_text_digest(r.state),'human_approved':False};r.save()
    app._glossary_review_summary=web_agent._glossary_review_summary;app._glossary_items=web_agent._glossary_items;app._load_yaml_file=web_agent._load_yaml_file
    session.result.update(translation_glossary_path=str(path),glossary_digest=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError,match='未审核'):agent.resume_after_glossary(session,app)
    assert not agent.glossary_approved(read_json(r.path)) and calls==[]


def test_source_reuse_policy_does_not_allow_reextraction_or_translation_before_glossary(runtime):
    import hashlib
    r,_,_,calls=prepared_translation(runtime)
    r.state.pop('translated');r.state['execution_policy']={'reuse_existing_source':True,'preserve_existing_outputs':True,
        'source_sha256':hashlib.sha256(Path(r.selected()['path']).read_bytes()).hexdigest()}
    assert {t.name for t in agent.ready(r.state)}<={'inspect','glossary','ask_user'}
    for name in ('download','asr','ocr','captions','patch','select_source','align'):
        with pytest.raises(ValueError):r.execute(name,{})
    with pytest.raises(agent.EvidenceRequired):r.execute('translate',{})
    assert calls==[]


def test_existing_translation_never_exposes_or_executes_whole_translation(runtime):
    r,_,_,calls=prepared_translation(runtime)
    r.state.pop('execution_policy')
    assert 'translate' not in {t.name for t in agent.ready(r.state)}
    # Even with an approved glossary the execution guard cannot be bypassed.
    import hashlib
    path=r.root/'approved.yaml';path.write_text('characters: []\n')
    r.state['glossary_review']={'human_approved':True,'source_text_sha256':agent.source_text_digest(r.state),
        'snapshot_path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    with pytest.raises(ValueError,match='禁止整片重翻'):r.execute('translate',{})
    assert 'translate' not in {t.name for t in agent.ready(r.state)} and calls==[]


def test_current_verdict_is_reused_and_new_evidence_invalidates_it(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,_,_,_=prepared_translation(runtime);requested=[]
    def llm(*args):
        requested.append(args[1]);return {'checks':[{'id':1,'verdict':'pass'}]}
    monkeypatch.setattr(asr_review_agent,'llm_json',llm)
    r.verify();r.verify()
    assert len(requested)==1 and 'verify' not in {t.name for t in agent.ready(r.state)}
    r.state['user_confirmations']['1']='안 먹었어요'
    assert not agent.current_verification(r.state)
    r.verify();assert len(requested)==2


def test_continuation_cannot_mutate_source_or_retranslate(runtime):
    r,_,_,calls=prepared_translation(runtime)
    r.state['execution_policy'].update(continue_existing_translation=True,original_translation_path=r.state['translated'])
    r.state['execution_policy'].pop('verification_only')
    for tool in ('translate','align','patch','asr','glossary','download'):
        with pytest.raises(ValueError):r.execute(tool,{})
    r.check_locked_inputs()
    assert calls==[]


def test_chinese_question_is_not_checked_as_source_evidence_or_saved_as_korean(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime)
    r.state.update(events=[{},{}],verification={'schema_version':agent.SCHEMA_VERSION,'issues':[{'id':1,'kind':'semantic_uncertain','reason_zh':'含义不确定'}]})
    question={'message':'这句指的是哪一种意思？','cue_id':1,'question_type':'translation','candidates':['还没吃','没吃过']}
    r.ask(question);r.save()
    assert session.question['question_type']=='translation'
    assert session.question['candidate_details'][0]['romanization']==''
    before=Path(r.selected()['path']).read_bytes()
    # Observe the persisted human answer without running another tool or model.
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('本测试不调用模型'))
    app.get_agent_session=lambda sid:None
    agent.run(session,app,{'confirmed_text':'还没吃'})
    saved=read_json(r.path)
    assert saved['translation_guidance']==[{'cue_id':1,'preferred_zh':'还没吃'}]
    assert saved['user_confirmations']=={} and Path(r.selected()['path']).read_bytes()==before
    assert calls==[]


def test_human_reply_forces_one_scoped_review_then_concludes_without_reasking(runtime,monkeypatch):
    import hashlib
    from scripts import asr_review_agent
    from video_translate.agent import reply_review,translation_review
    r,session,app,calls=prepared_translation(runtime)
    original=Path(r.state['translated']);source=Path(r.selected()['path'])
    old_bytes=(source.read_bytes(),original.read_bytes())
    r.state.update(controller_version=2,events=[{},{}],counts={'translate':1,'review_translation':2,'ask_user':4},
        verification={'schema_version':agent.SCHEMA_VERSION,'issues':[{'id':1,'kind':'semantic_uncertain','reason_zh':'原文不确定'}]},
        translation_guidance=[{'cue_id':1,'clue':'以前提交的线索'}])
    r.state['execution_policy'].update(continue_existing_translation=True,original_translation_path=str(original),allowed_repair_cue_ids=[1])
    r.state['execution_policy'].pop('verification_only')
    r.state['pending_question']={'cue_id':1,'question_type':'translation','candidates':[]}
    r.save();session.status='running';received=[]
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('收到线索后不能先询问planner'))
    def local(source_path,target_path,issues,ids,folder,**options):
        received.append((ids,options));folder.mkdir();output=folder/'zh.local.srt';output.write_bytes(original.read_bytes())
        row={'id':1,'source':'안 먹었어요','before':'没吃','after':'没吃','action':'uncertain','reason_zh':'原文证据不足',
             'independent_review':{'reason_zh':'用户提供的中文意思不能替代原文证据'}}
        return {'target_ids':ids,'translated_srt':str(output),'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'translation_sha256':hashlib.sha256(Path(target_path).read_bytes()).hexdigest(),'unresolved_ids':[1],
            'changed_ids':[],'decisions':[row],'audit':str(folder/'audit.json')}
    monkeypatch.setattr(translation_review,'review_translation_cues',local)
    agent.run(session,app,{'clue':'新提交的线索'})
    saved=read_json(r.path)
    assert received[0][0]==[1] and received[0][1]['user_guidance']==[{'cue_id':1,'clue':'以前提交的线索'},{'cue_id':1,'clue':'新提交的线索'}]
    assert saved['counts']['review_translation']==3 and saved['counts']['translate']==1 and saved['counts']['ask_user']==4
    assert session.status=='done' and session.question=={}
    assert session.result['completion_status']=='completed_with_issues' and session.result['review_passed'] is False
    assert saved['closed_reply_review']['result']['unresolved_cue_ids']==[1]
    assert not saved['verification']['acceptable'] and 'pending_reply_review' not in saved
    assert (source.read_bytes(),original.read_bytes())==old_bytes and calls==[]
    assert reply_review.completed(saved,1)['outcome']=='unresolved'
    agent.run(session,app)
    assert len(received)==1 and session.status=='done'
    # Even a planner trying the old question cannot reopen the same input form.
    restored=agent.Runtime(app,session)
    restored.ask({'cue_id':1,'question_type':'translation','message':'请再填一次','candidates':[]})
    assert session.status=='done' and session.question=={}
    assert len(list(r.root.glob('draft_conclusion_*')))==1


def test_pending_human_reply_disables_other_tools_and_blocks_direct_ask(runtime):
    from video_translate.agent import reply_review
    r,_,_,_=prepared_translation(runtime)
    r.state['execution_policy'].pop('verification_only')
    r.state['execution_policy']['continue_existing_translation']=True
    r.state.update(events=[{},{}],translation_guidance=[{'cue_id':1,'clue':'上下文'}],
        verification={'issues':[{'id':1,'kind':'semantic_uncertain'}]})
    reply_review.queue(r.state,1)
    assert [t.name for t in agent.ready(r.state)]==['review_translation']
    with pytest.raises(agent.EvidenceRequired,match='必须先'):
        r.ask({'cue_id':1,'question_type':'translation','message':'再问一次','candidates':[]})


def test_transient_tool_error_does_not_disable_real_content_question(runtime):
    r,session,_,_=prepared_translation(runtime)
    r.state.update(events=[{},{}],internal_error={'code':'tool_call_error'},
        verification={'issues':[{'id':1,'kind':'semantic_uncertain'}]})
    assert 'ask_user' in {t.name for t in agent.ready(r.state)}
    r.ask({'cue_id':1,'question_type':'translation','message':'这句的意思是什么？','candidates':['还没吃']})
    assert session.status=='waiting'


def test_independent_local_review_finishes_without_another_conflicting_global_review(runtime,monkeypatch):
    from scripts import asr_review_agent
    from video_translate.agent import translation_review
    import hashlib
    r,session,app,calls=prepared_translation(runtime)
    r.state['execution_policy']={'continue_existing_translation':True,'original_translation_path':r.state['translated'],
        'source_sha256':hashlib.sha256(Path(r.selected()['path']).read_bytes()).hexdigest(),
        'translated_sha256':hashlib.sha256(Path(r.state['translated']).read_bytes()).hexdigest()}
    r.state['events']=[{'tool':'reuse_source'},{'tool':'reuse_translation'}];r.save();seen=[]
    def llm(root,name,task,instruction,data):
        seen.append(name)
        if name.startswith('verify-'):
            return {'checks':[{'id':1,'verdict':'issue','source_quote':'안','translation_quote':'没吃','reason_zh':'待证实的假设'}]}
        return {'tool':'review_translation','args':{'cue_ids':[1]}} if data.get('verification') else {'tool':'verify'}
    def local(source,zh,issues,ids,out):
        assert ids==[1]
        path=Path(out)/'keep.srt';path.parent.mkdir();path.write_bytes(Path(zh).read_bytes())
        return {'translated_srt':str(path),'audit':str(Path(out)/'audit.json'),
            'output_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'changed_ids':[],'unresolved_ids':[],'decisions':[{'id':1,'action':'keep'}]}
    monkeypatch.setattr(asr_review_agent,'llm_json',llm)
    monkeypatch.setattr(translation_review,'review_translation_cues',local)
    agent.run(session,app)
    saved=read_json(r.path)
    assert session.status=='done' and saved['verification']['acceptable']
    assert len([name for name in seen if name.startswith('verify-')])==1
    assert saved['events'][-1]['tool']=='finish' and calls==[]
    assert session.result['local_translation_review_current'] is True


def test_failed_tool_actions_have_a_visible_reason(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,_=prepared_translation(runtime);r.save()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:{'tool':'translate'})
    with pytest.raises(agent.InternalAgentError):agent.run(session,app)
    assert all(event.get('reason') for event in read_json(r.path)['events'])


def test_unambiguous_scalar_repair_does_not_expand_local_authority(runtime):
    r,_,_,_=prepared_translation(runtime)
    r.state['execution_policy']={'continue_existing_translation':True}
    r.state['verification']={'issues':[{'id':1,'kind':'translation_error'}]}
    call=agent.normalize_call({'tool':'review_translation','args':{'cue_ids':'1'}})
    assert call['args']['cue_ids']==[1]
    assert agent.validate_call(call,r.state)==('review_translation',{'cue_ids':[1]})
    with pytest.raises(ValueError):agent.validate_call(agent.normalize_call({'tool':'review_translation','args':{'cue_ids':'2'}}),r.state)
    assert agent.normalize_call({'tool':'review_translation','args':{'cue_ids':'1,2'}})['args']['cue_ids']=='1,2'


def test_reviewer_glossary_does_not_reopen_old_draft_uncertainty():
    from video_translate.translate.glossary import Glossary,GlossaryEntry
    glossary=Glossary(entries=[GlossaryEntry(source='기니',zh='豚鼠',type='nickname',note='需要用户确认')])
    assert glossary.to_reviewed_context(['대장 기니다운 선택'])['glossary']==[
        {'source':'기니','zh':'豚鼠','type':'nickname','human_approved':True}]
    assert glossary.entries[0].note=='需要用户确认'


def target_fixture(runtime,monkeypatch,*,partial=False):
    from scripts import asr_review_agent
    r,session,app,calls=runtime
    r.state.update(probe={'duration':100,'title':'fixture'},captions=[{'lang':'ko','kind':'manual'},{'lang':'zh','kind':'manual'}])
    r.state['events']=[{'tool':'probe','status':'done'}]
    def download(payload):
        assert payload['lang']=='zh' and payload['kind']=='manual'
        path=Path(payload['output_dir'])/'fixture.zh.srt'
        write_srt([SubtitleCue(1,0,2 if partial else 98,'[现成中文字幕] 你好，这是测试字幕。')],path)
        calls.append('target_download')
        return SimpleNamespace(result={'subtitle_path':str(path)})
    app.download_subtitle_job=download
    app._agent_generate_glossary_review=lambda *a,**k:pytest.fail('现成目标字幕不应生成词表')
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('已知目标字幕可用时无需再调用模型规划或翻译'))
    r.save()
    return r,session,app,calls


def test_korean_audio_with_existing_chinese_delivers_without_glossary_or_translation(runtime,monkeypatch):
    r,session,app,calls=target_fixture(runtime,monkeypatch)
    assert [t.name for t in agent.ready(r.state)]==['inspect_target']
    for tool in ('glossary','translate','captions','ocr','asr'):
        with pytest.raises(ValueError):r.execute(tool,{})
    with pytest.raises(ValueError):agent.validate_call({'tool':'inspect_target','args':{'index':0}},r.state)
    agent.run(session,app)
    state=read_json(r.path)
    assert session.status=='done' and session.result['delivery_mode']=='existing_target_subtitle'
    assert calls==['target_download'] and state['language']=='korean'
    assert [e['tool'] for e in state['events']]==['probe','inspect_target','deliver_target']
    assert not state.get('glossary_review') and not state.get('translated')
    path=Path(session.result['translated_srt'])
    assert session.result['target_caption_check']['sha256']==__import__('hashlib').sha256(path.read_bytes()).hexdigest()
    # A restored completed task must not plan, redownload, or translate again.
    session.status='running';agent.run(session,app)
    assert session.status=='done' and calls==['target_download']


def test_partial_chinese_pauses_instead_of_silently_retranslating(runtime,monkeypatch):
    r,session,app,calls=target_fixture(runtime,monkeypatch,partial=True)
    agent.run(session,app)
    assert session.status=='waiting' and session.question['kind']=='autonomous_target_review'
    assert calls==['target_download'] and 'glossary' not in r.state.get('counts',{})
    session.status='running'
    agent.run(session,app,{'action':'use_target_caption'})
    assert session.status=='done' and session.result['target_caption_check']['user_accepted_warnings']
    assert calls==['target_download'] and session.result['requires_translation'] is False


def test_target_delivery_cannot_use_changed_captions_or_overwrite_existing_output(runtime,monkeypatch):
    r,session,app,_=target_fixture(runtime,monkeypatch)
    report=r.inspect_target({'index':1})
    path=Path(report['path']);original=path.read_bytes()
    path.write_bytes(original+b'changed')
    with pytest.raises(ValueError,match='发生变化'):r.deliver_target()
    path.write_bytes(original)
    task=r.root/'task';task.mkdir();session.result['task_dir']=str(task)
    target=task/f'zh.caption_{session.id}_{report["sha256"][:10]}.srt';target.write_text('previous user result')
    with pytest.raises(ValueError,match='拒绝覆盖'):r.deliver_target()
    assert target.read_text()=='previous user result'


def test_target_question_api_only_accepts_explicit_caption_choice(monkeypatch):
    from video_translate import web_agent
    session=AgentSession(id='target',status='waiting',payload={'agent_mode':'autonomous'},question={'kind':'autonomous_target_review'})
    monkeypatch.setattr(web_agent,'_AGENT_SESSIONS',{'target':session});calls=[]
    monkeypatch.setattr(web_agent,'_run_agent_async',lambda sid,fn:calls.append(sid))
    with pytest.raises(ValueError):web_agent.answer_agent_session('target',{'action':'autonomous_reply','clue':'跳过'})
    assert session.status=='waiting'
    web_agent.answer_agent_session('target',{'action':'use_target_caption'})
    assert session.status=='running' and calls==['target']


def goal_call(tool,args=None,*,refs=None,plan=None):
    return {'tool':tool,'args':args or {},'reason':'根据当前证据执行'+tool,
        'assessment':{'summary':'根据已经返回的工具结果选择下一项操作','evidence_refs':refs or ['goal'],'unknowns':[]},
        'plan':plan or ['检查现有字幕是否满足交付目标'],'next_check':'核对工具实际返回的内容与当前目标'}


def test_screen_first_agent_runs_ocr_then_waits_for_glossary_not_asr(runtime,monkeypatch):
    import base64
    from scripts import asr_review_agent
    from video_translate.agent import ocr_candidates, ocr_finalize
    r,session,app,calls=runtime
    r.state.update(controller_version=2,screen_source_policy_version=1)
    r.save()
    original=r.root/'screen.srt';write_srt([SubtitleCue(1,2,3,'화면 자막')],original)
    def preview(payload):
        return {'time_seconds':payload['time_seconds'],'width':100,'height':100,
                'image_data_url':'data:image/jpeg;base64,'+base64.b64encode(b'fake fixture frame').decode(),
                'ocr_analysis':{'accepted':[{'text':'화면 자막','bbox':[10,70,90,80]}]}}
    app.ocr_preview_frame=preview
    monkeypatch.setattr(vision,'analyze',lambda *a:{'has_burned_subtitles':True,
        'subtitle_regions':[[.1,.65,.9,.85]],'summary_zh':'抽样画面有内嵌字幕','exclusion_proposals':[]})
    def ocr(payload):
        assert payload['ocr_crop_left_ratio']==payload['ocr_crop_right_ratio']==0
        assert payload['ocr_crop_top_ratio']<=.45 and payload['ocr_crop_bottom_ratio']==0
        assert payload['ocr_pipeline_version']=='v3' and payload['materialize_debug_bundle'] is False
        assert payload['llm_cleanup'] is False
        calls.append('ocr')
        raw=r.root/'raw';raw.mkdir()
        for name,content in [('tracks.json','[]'),('ocr_boxes.json','[]'),('run.yaml','ocr: {}')]:
            (raw/name).write_text(content)
        return SimpleNamespace(result={'output_dir':str(raw)})
    app.ocr_development_job=ocr
    app._debug_rebuild_timing=lambda _:None
    monkeypatch.setattr(ocr_candidates,'prepare',lambda *a,**k:{'debug_dir':str(r.root/'raw'),'kept_tracks':1})
    def refine(payload):
        calls.append('ocr_refine')
        return SimpleNamespace(result={'v3_layered_srt':str(original)})
    monkeypatch.setattr(ocr_finalize,'launch',lambda app,candidate:refine(candidate))
    glossary=r.root/'screen.glossary.yaml'
    def prepare_glossary(item,source,*,defer_wait=False):
        assert source==str(original) and defer_wait
        glossary.write_text("characters:\n- source: 이름\n  zh: ''\n  reviewed: false\n")
        item.result['glossary_path']=str(glossary)
    app._agent_generate_glossary_review=prepare_glossary
    commands=iter([goal_call('probe'),goal_call('download'),
        goal_call('sample_frames',{'times':[1,6,12,18]}),goal_call('analyze_frames'),
        goal_call('ocr_trial',{'use_exclusion':False}),goal_call('ocr'),goal_call('refine_screen_ocr'),goal_call('finalize_screen_ocr'),
        goal_call('select_source',{'source_id':'ocr_1'}),goal_call('inspect'),goal_call('glossary')])
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:next(commands))
    agent.run(session,app)
    saved=read_json(r.path)
    assert session.status=='waiting' and session.phase=='review_glossary'
    assert session.result['source_kind']=='ocr' and saved['selected']=='ocr_1'
    assert calls==['video_download','ocr','ocr_refine'] and not agent.glossary_approved(saved)
    assert [e['tool'] for e in saved['events']]==['probe','download','sample_frames','analyze_frames',
        'ocr_trial','ocr','refine_screen_ocr','finalize_screen_ocr','select_source','inspect','glossary']
    assert 'translated_srt' not in session.result


def test_new_sessions_use_goal_controller_but_saved_sessions_keep_their_version(runtime):
    r,session,app,_=runtime
    assert agent.Runtime(app,session).state['controller_version']==1
    r.path.unlink()
    fresh=agent.Runtime(app,session)
    assert fresh.state['controller_version']==2
    assert session.result['autonomous_controller_version']==2


def test_goal_controller_chooses_text_context_before_delivery_instead_of_forcing_it(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=target_fixture(runtime,monkeypatch)
    r.state['controller_version']=2;r.save();observations=[]
    options={t.name for t in agent.ready(r.state)}
    assert {'download','captions','inspect_target'}<=options
    commands=iter([goal_call('inspect_target',{'index':1},refs=['metadata']),
                   goal_call('read_subtitles',{'source_id':'target:1','time_seconds':50},refs=['target:1']),
                   goal_call('download',refs=['event:3']),goal_call('deliver_target',refs=['event:4'])])
    def planner(root,name,task,prompt,data):
        observations.append(data)
        return next(commands)
    monkeypatch.setattr(asr_review_agent,'llm_json',planner)
    agent.run(session,app)
    state=read_json(r.path)
    assert session.status=='done' and calls==['target_download','video_download']
    assert [e['tool'] for e in state['events']]==['probe','inspect_target','read_subtitles','download','deliver_target']
    assert len(observations)==4  # Download timing and delivery are planner decisions.
    assert observations[2]['previous_expectation']
    assert state['events'][-1]['decision']['evidence_refs']==['event:4']
    assert Path(session.result['input_video']).is_file()
    assert session.result['autonomous_decisions'][-1]['tool']=='deliver_target'


def test_goal_controller_investigates_partial_caption_before_asking_user(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=target_fixture(runtime,monkeypatch,partial=True)
    r.state['controller_version']=2;r.save();observations=[]
    commands=iter([goal_call('inspect_target',{'index':1}),
                   goal_call('read_subtitles',{'source_id':'target:1','time_seconds':80},refs=['target:1']),
                   goal_call('ask_target',refs=['event:3'])])
    def planner(*args):observations.append(args[-1]);return next(commands)
    monkeypatch.setattr(asr_review_agent,'llm_json',planner)
    agent.run(session,app)
    saved=read_json(r.path)
    assert len(observations)==3 and saved['events'][-2]['result']['covers_queried_time'] is False
    assert session.status=='waiting' and session.question['kind']=='autonomous_target_review'
    assert saved['events'][-1]['tool']=='ask_target' and saved['pending_target']
    assert calls==['target_download']
    session.status='running'
    final_calls=iter([goal_call('download'),goal_call('deliver_target',refs=['target:1'])])
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:next(final_calls))
    agent.run(session,app,{'action':'use_target_caption'})
    assert session.status=='done' and session.result['target_caption_check']['user_accepted_warnings']
    assert calls==['target_download','video_download']


def test_goal_controller_changes_plan_after_tool_failure_without_repeating_full_job(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=runtime
    r.state.update(controller_version=2,probe={'duration':20,'title':'fixture'},media=str(r.root/'video.mp4'),
                   captions=[{'lang':'ko','kind':'manual'}],events=[{'tool':'probe','status':'done'}])
    Path(r.state['media']).write_bytes(b'completed-video')
    r.save();seen=[]
    commands=iter([goal_call('asr',plan=['从音频提取原文']),
        goal_call('captions',{'index':0},refs=['event:2'],plan=['识别工具失败，改查已有外挂字幕']),
        goal_call('select_source',{'source_id':'captions_1'},refs=['source:captions_1']),
        goal_call('inspect',refs=['source:captions_1']),goal_call('glossary',refs=['event:5'])])
    def planner(*args):seen.append(args[-1]);return next(commands)
    monkeypatch.setattr(asr_review_agent,'llm_json',planner)
    original_execute=agent.Runtime.execute
    def execute(self,name,args):
        if name=='asr':calls.append('asr_failed');raise RuntimeError('worker unavailable')
        return original_execute(self,name,args)
    monkeypatch.setattr(agent.Runtime,'execute',execute)
    glossary=r.root/'glossary.yaml'
    def generate(item,source,**kwargs):glossary.write_text('characters: []\n');item.result['glossary_path']=str(glossary)
    app._agent_generate_glossary_review=generate
    agent.run(session,app)
    saved=read_json(r.path)
    assert session.status=='waiting' and session.phase=='review_glossary'
    assert calls==['asr_failed']
    assert seen[1]['evidence_catalog'][-1]['status']=='rejected_or_failed'
    assert saved['events'][2]['decision']['plan']==['识别工具失败，改查已有外挂字幕']
    assert not saved.get('translated')


def test_goal_controller_never_executes_a_call_with_fabricated_evidence(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=runtime;r.state['controller_version']=2;r.save()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:goal_call('probe',refs=['invented_hearing']))
    app.probe_video=lambda *a,**k:pytest.fail('无有效证据引用的调用不能执行')
    with pytest.raises(agent.InternalAgentError):agent.run(session,app)
    assert not read_json(r.path)['counts'] and calls==[]


def test_goal_controller_selects_frame_times_and_invalidates_stale_masks(runtime):
    import base64
    r,_,app,_=runtime
    r.state.update(controller_version=2,probe={'duration':100},media='/owned/video.mp4',
                   vision={'subtitle_regions':[[0,.8,1,1]]},trial={'accepted':True},counts={'sample_frames':1})
    requested=[]
    def preview(payload):
        requested.append(payload['time_seconds'])
        return {'image_data_url':'data:image/jpeg;base64,'+base64.b64encode(b'test-frame').decode(),
                'time_seconds':payload['time_seconds'],'width':100,'height':100}
    app.ocr_preview_frame=preview
    call={'tool':'sample_frames','args':{'times':[18,45,47]}}
    name,args=agent.validate_call(call,r.state);r.execute(name,args)
    assert requested==[18,45,47]
    assert 'vision' not in r.state and 'trial' not in r.state
    assert r.state['trial_history']==[{'accepted':True}]
    assert 'analyze_frames' in {t.name for t in agent.ready(r.state)}
    with pytest.raises(ValueError,match='重复'):agent.validate_call(call,r.state)
    for times in ([101],[-1],[True],[float('nan')],[]):
        with pytest.raises(ValueError):agent.validate_call({'tool':'sample_frames','args':{'times':times}},r.state)


def test_explicit_retry_preserves_video_counts_and_recovers_bad_frame_arguments(runtime,monkeypatch):
    import base64
    from scripts import asr_review_agent
    class EndOfTest(Exception):pass
    r,session,app,calls=runtime
    video=Path(app._agent_ensure_project_video(session,{},phase='test')['input_video'])
    before=video.read_bytes();calls.clear()
    failures=[{'tool':'sample_frames','status':'rejected_or_failed','reason':'times必须是数组'} for _ in range(3)]
    r.state.update(controller_version=2,probe={'duration':337.27},media=str(video),
        counts={'probe':1,'download':1},consecutive_tool_errors=3,
        internal_error={'code':'tool_recovery_exhausted'},events=failures)
    r.save();seen=[];requested=[]
    app.ocr_preview_frame=lambda payload:(requested.append(payload['time_seconds']) or {
        'image_data_url':'data:image/jpeg;base64,'+base64.b64encode(b'frame').decode(),
        'time_seconds':payload['time_seconds'],'width':100,'height':100})
    def model(root,name,task,instruction,data):
        seen.append(data)
        assert not {'probe','download'} & {t['name'] for t in data['available_tools']}
        if len(seen)==1:
            assert 'times必须是数组' in data['feedback']
            return goal_call('sample_frames',{'times':[True]})
        if len(seen)==2:
            assert '有限数字' in data['feedback']
            assert data['internal_error']['argument_error']['code']=='times_number'
            return goal_call('sample_frames',{'times':'15,100,200,310'})
        raise EndOfTest()
    monkeypatch.setattr(asr_review_agent,'llm_json',model)
    with pytest.raises(EndOfTest):agent.retry(session,app)
    saved=read_json(r.path)
    assert saved['counts']=={'probe':1,'download':1,'sample_frames':1}
    assert saved['consecutive_tool_errors']==0 and not saved.get('internal_error')
    assert requested==[15,100,200,310] and video.read_bytes()==before and calls==[]
    assert saved['events'][:3]==failures
    event=saved['events'][-1]
    assert event['status']=='done' and event['argument_repair']['field']=='times'
    assert event['argument_repair']['normalized']==[15,100,200,310]


def test_goal_controller_cannot_drop_existing_translation_by_switching_source(runtime):
    r,_,_,_=prepared_translation(runtime);r.state['controller_version']=2;r.state.pop('execution_policy')
    assert not {'select_source','patch'}&{t.name for t in agent.ready(r.state)}
    with pytest.raises(ValueError,match='已有译文'):r.execute('select_source',{'source_id':r.state['selected']})


def test_subtitle_context_tool_is_bounded_and_does_not_modify_original(runtime):
    r,_,_,_=runtime
    source=r.root/'long.srt';write_srt([SubtitleCue(i,i*2,i*2+1,f'内容{i}') for i in range(1,31)],source)
    r.state.update(controller_version=2,sources={'captions_1':{'kind':'captions','path':str(source)}},probe={'duration':100})
    before=source.read_bytes()
    name,args=agent.validate_call({'tool':'read_subtitles','args':{'source_id':'captions_1','cue_ids':[14],'context':2}},r.state)
    result=r.execute(name,args)
    assert [row['id'] for row in result['cues']]==[12,13,14,15,16]
    assert source.read_bytes()==before
    with pytest.raises(ValueError):agent.validate_call({'tool':'read_subtitles','args':{'source_id':'/etc/passwd','cue_ids':[1]}},r.state)
    with pytest.raises(ValueError):r.read_subtitles({'source_id':'captions_1','cue_ids':[999]})


def test_local_audio_tool_checks_window_and_never_selects_partial_transcript_as_full_source(runtime,monkeypatch):
    r,_,_,_=runtime;r.state.update(controller_version=2,media=str(r.root/'video.mp4'),probe={'duration':100})
    commands=[]
    def command(name,args,env=None):
        commands.append(args)
        if args[0]=='ffmpeg':Path(args[-1]).write_bytes(b'isolated audio')
        else:
            folder=Path(args[args.index('--output-dir')+1])
            write_json_atomic(folder/'words.json',{'info':{'language':'ko'},'words':[
                {'start':1,'end':2,'text':'안녕하세요','probability':.9,'segment_id':1}]})
    monkeypatch.setattr(r,'command',command)
    name,args=agent.validate_call({'tool':'transcribe_clip','args':{'start':40,'end':50}},r.state)
    result=r.execute(name,args)
    assert result['window']==[40,50] and result['cues'][0]['start']==41
    assert r.state['sources']=={} and not r.state.get('selected')
    assert commands[1][commands[1].index('--language')+1]=='korean'
    assert r.state['audio_observations'][0]['id']=='clip:1'
    for start,end in ((-1,10),(1,3),(0,31),(90,101),(float('nan'),10),(True,10)):
        with pytest.raises(ValueError):agent.validate_call({'tool':'transcribe_clip','args':{'start':start,'end':end}},r.state)


def test_independent_target_review_preserves_text_and_blocks_unqualified_delivery_on_real_dispute(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=target_fixture(runtime,monkeypatch)
    r.state['controller_version']=2
    report=r.inspect_target({'index':1});path=Path(report['path']);before=path.read_bytes()
    source=r.root/'ko.srt';write_srt([SubtitleCue(1,0,98,'안 먹었어요')],source)
    r.state['sources']={'captions_1':{'path':str(source),'kind':'captions'}}
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:{'checks':[{'id':1,'verdict':'issue',
        'source_quote':'안','translation_quote':'你好','reason_zh':'原文是否定吃过，中文变成问候，需核查是否时轴错位'}]})
    name,args=agent.validate_call({'tool':'review_target','args':{'index':1,'source_id':'captions_1','cue_ids':[1]}},r.state)
    result=r.execute(name,args)
    assert result['issues'] and report['status']=='needs_review'
    assert path.read_bytes()==before and not r.state.get('translated')
    assert 'deliver_target' not in {t.name for t in agent.ready(r.state)}
    assert 'ask_target' in {t.name for t in agent.ready(r.state)}
    assert calls==['target_download']


def test_goal_delivery_requires_real_video_even_when_chinese_is_ready(runtime,monkeypatch):
    r,session,app,calls=target_fixture(runtime,monkeypatch);r.state['controller_version']=2
    r.inspect_target({'index':1})
    assert 'deliver_target' not in {t.name for t in agent.ready(r.state)}
    with pytest.raises(agent.EvidenceRequired,match='本地视频'):r.deliver_target()
    assert session.status!='done' and not r.state.get('target_delivery')
    r.execute('download',{})
    assert 'deliver_target' in {t.name for t in agent.ready(r.state)}
    r.deliver_target()
    assert session.status=='done' and Path(session.result['input_video']).stat().st_size>0
    assert calls==['target_download','video_download']


def test_failed_video_download_does_not_deliver_or_lose_ready_chinese(runtime,monkeypatch):
    r,session,app,calls=target_fixture(runtime,monkeypatch);r.state['controller_version']=2
    report=r.inspect_target({'index':1});before=Path(report['path']).read_bytes()
    def failed(*a,**k):raise RuntimeError('download unavailable')
    app._agent_ensure_project_video=failed
    with pytest.raises(RuntimeError):r.execute('download',{})
    assert Path(report['path']).read_bytes()==before
    assert session.status!='done' and 'deliver_target' not in {t.name for t in agent.ready(r.state)}
    assert calls==['target_download']


def test_completed_goal_caption_task_backfills_only_missing_video(runtime,monkeypatch):
    from scripts import asr_review_agent
    r,session,app,calls=target_fixture(runtime,monkeypatch);r.state['controller_version']=2
    report=r.inspect_target({'index':1});before=Path(report['path']).read_bytes()
    r.state['target_delivery']={'translated_srt':report['path'],'sha256':report['sha256'],
        'delivery_mode':'existing_target_subtitle','requires_translation':False}
    r.save()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('只补视频，不能重新规划字幕或翻译'))
    agent.run(session,app)
    assert session.status=='done' and Path(session.result['input_video']).is_file()
    assert Path(report['path']).read_bytes()==before and calls==['target_download','video_download']
    assert read_json(r.path)['events'][-1]['tool']=='download'
    session.status='running';agent.run(session,app)
    assert session.status=='done' and calls==['target_download','video_download']


def test_download_tool_reuses_existing_project_video(runtime):
    r,session,app,calls=runtime;r.state.update(controller_version=2,probe={'duration':20})
    first=r.execute('download',{});second=r.execute('download',{})
    assert first['input_video']==second['input_video'] and calls==['video_download']


def test_new_translation_route_prepares_video_before_human_glossary_review(runtime):
    r,_,_,_=prepared_translation(runtime)
    r.state.pop('translated');r.state.pop('execution_policy');r.state['controller_version']=2
    assert 'glossary' not in {t.name for t in agent.ready(r.state)}
    with pytest.raises(agent.EvidenceRequired,match='术语审核需要播放'):r.execute('glossary',{})
    r.execute('download',{})
    assert 'glossary' in {t.name for t in agent.ready(r.state)}


def test_empty_translation_has_local_repair_tool_not_unrelated_caption_alignment(runtime,monkeypatch):
    import hashlib
    from scripts import asr_review_agent
    r,_,_,_=prepared_translation(runtime)
    write_srt([SubtitleCue(1,0,2,'')],Path(r.state['translated']))
    r.state['execution_policy']['translated_sha256']=hashlib.sha256(Path(r.state['translated']).read_bytes()).hexdigest()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('结构错误不应先请求语义检查'))
    result=r.verify()
    assert result['issues'][0]['id']==1 and result['issues'][0]['kind']=='empty_translation'
    assert 'align' not in {t.name for t in agent.ready(r.state)}
    r.state['execution_policy'].pop('verification_only');r.state['execution_policy']['continue_existing_translation']=True
    assert 'review_translation' in {t.name for t in agent.ready(r.state)}
    with pytest.raises(ValueError,match='结构错误'):r.align()


def test_approved_local_fill_requires_new_semantic_check_and_preserves_originals(runtime,monkeypatch):
    import hashlib
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime)
    source=Path(r.selected()['path']);target=Path(r.state['translated'])
    write_srt([SubtitleCue(1,0,4,'감사합니다.'),SubtitleCue(2,2,4,'니다.')],source)
    write_srt([SubtitleCue(1,0,4,'谢谢大家'),SubtitleCue(2,2,4,'')],target)
    original_source=source.read_bytes();original_target=target.read_bytes()
    r.state['execution_policy']={'continue_existing_translation':True,'original_translation_path':str(target),
        'source_sha256':hashlib.sha256(original_source).hexdigest(),'translated_sha256':hashlib.sha256(original_target).hexdigest()}
    r.execute('inspect',{});r.verify()
    actions=iter([{'tool':'read_context','args':{'cue_ids':[2],'radius':1}},
        {'tool':'propose','args':{'decisions':[{'id':2,'action':'revise','replacement':'谢谢',
            'reason_zh':'重叠句尾属于前条感谢句，恢复上下文支持的短译文',
            'evidence':[{'id':2,'quote':'니다.'},{'id':1,'quote':'감사합니다.'}]}]}},
        {'tool':'check'},{'tool':'finish'}])
    checked=[]
    def llm(root,name,task,instruction,data):
        if name.startswith('proposal-check'):
            return {'checks':[{'id':2,'verdict':'approve','reason_zh':'前条原文明确是感谢，短译文没有新增事实',
                'evidence':[{'id':2,'quote':'니다.'},{'id':1,'quote':'감사합니다.'}],
                'change_basis':{'kind':'omission','context_supports_disputed_meaning':True}}]}
        if name.startswith('verify-'):
            checked.extend(row['id'] for row in data['subtitles'])
            return {'checks':[{'id':row['id'],'verdict':'pass'} for row in data['subtitles']]}
        return next(actions)
    monkeypatch.setattr(asr_review_agent,'llm_json',llm)
    r.state['counts']['review_translation']=1
    result=r.execute('review_translation',{'cue_ids':[2]})
    assert result['changed_ids']==[2] and result['needs_semantic_verification']
    assert not agent.current_verification(r.state)
    assert 'finish' not in {t.name for t in agent.ready(r.state)}
    assert session.result['translated_srt']==r.state['translated'] and r.state['translated']!=str(target)
    assert r.verify()['acceptable'] and 2 in checked
    assert source.read_bytes()==original_source and target.read_bytes()==original_target
    assert calls==[]


def test_legacy_generic_structure_failure_is_migrated_once_with_fresh_bounded_verification(runtime):
    r,_,_,_=prepared_translation(runtime)
    r.state['verification']={'schema_version':agent.SCHEMA_VERSION,'status':'complete','issues':[{'kind':'structural_error'}]}
    r.state['counts']['verify']=3
    r.prepare_recovery()
    assert r.state['counts']['verify']==0 and r.state['verification_required']
    assert not r.state.get('verification')
    count=len(r.state['events']);r.prepare_recovery()
    assert len(r.state['events'])==count


def test_alignment_immediately_publishes_both_new_download_paths(runtime,monkeypatch):
    r,session,app,_=prepared_translation(runtime);r.state.pop('execution_policy')
    r.selected()['kind']='asr';r.state['counts']['align']=1;r.state['media']=str(r.root/'video.mp4')
    old_source=r.selected()['path'];old_zh=r.state['translated']
    fake_prefix=r.root/'envs'/'video-translate'
    qwen=fake_prefix.parent/'reibosub-asr3/bin/python';qwen.parent.mkdir(parents=True);qwen.write_text('test interpreter')
    monkeypatch.setattr(agent.sys,'prefix',str(fake_prefix))
    def command(name,args,env=None):
        if args[0]=='ffmpeg':Path(args[-1]).write_bytes(b'audio')
        else:write_json_atomic(r.root/'alignment_1/whole/timing-alignment.json',
            {'cues':[{'index':1,'start':.1,'end':2.1,'text':'안 먹었어요'}],
             'audit':[{'index':1,'accepted':True,'needs_review':False}]})
    monkeypatch.setattr(r,'command',command)
    r.align()
    assert session.result['source_srt']==r.selected()['path']!=old_source
    assert session.result['translated_srt']==r.state['translated']!=old_zh
    assert session.result['autonomous_verification'] is None
    assert read_json(r.path)['translated']==session.result['translated_srt']


def test_recovery_does_not_allow_local_edits_outside_explicit_repair_ids(runtime):
    r,_,_,_=prepared_translation(runtime)
    r.state['execution_policy'].pop('verification_only')
    r.state['execution_policy'].update(continue_existing_translation=True,allowed_repair_cue_ids=[2])
    r.state['verification']={'issues':[{'id':1,'kind':'translation_error'},{'id':2,'kind':'empty_translation'}]}
    assert agent.local_review_ids(r.state)=={2}
    with pytest.raises(ValueError):agent.validate_call({'tool':'review_translation','args':{'cue_ids':[1]}},r.state)


def test_covered_empty_fragment_exports_clean_pair_and_mapping_without_editing_inputs(runtime,monkeypatch):
    import hashlib
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime)
    source=Path(r.selected()['path']);target=Path(r.state['translated'])
    write_srt([SubtitleCue(1,0,4,'감사합니다.'),SubtitleCue(2,2,4,'니다.')],source)
    write_srt([SubtitleCue(1,0,4,'谢谢大家'),SubtitleCue(2,2,4,'')],target)
    before_source=source.read_bytes();before_target=target.read_bytes()
    r.state['execution_policy']={'continue_existing_translation':True,'original_translation_path':str(target),
        'source_sha256':hashlib.sha256(before_source).hexdigest(),'translated_sha256':hashlib.sha256(before_target).hexdigest(),
        'allowed_repair_cue_ids':[2]}
    r.execute('inspect',{});r.verify()
    evidence=[{'id':1,'quote':'감사합니다.'},{'id':2,'quote':'니다.'}]
    steps=iter([{'tool':'read_context','args':{'cue_ids':[2],'radius':1}},
        {'tool':'propose','args':{'decisions':[{'id':2,'action':'keep','replacement':None,'reason_zh':'重叠词尾已被前句覆盖','evidence':evidence}]}},
        {'tool':'check'},{'tool':'finish'}])
    semantic_ids=[]
    def llm(root,name,task,prompt,data):
        if name.startswith('proposal-check'):return {'checks':[{'id':2,'verdict':'approve','reason_zh':'前句已完整覆盖该重复词尾','evidence':evidence}]}
        if name.startswith('verify-'):
            semantic_ids.extend(row['id'] for row in data['subtitles'])
            return {'checks':[{'id':row['id'],'verdict':'pass'} for row in data['subtitles']]}
        return next(steps)
    monkeypatch.setattr(asr_review_agent,'llm_json',llm)
    r.state['counts']['review_translation']=1
    result=r.execute('review_translation',{'cue_ids':[2]})
    assert result['unresolved_ids']==[] and r.state['approved_suppressions'][0]['id']==2
    assert r.verify()['acceptable'] and semantic_ids==[1]
    r.execute('finish',{})
    assert session.status=='done' and session.result['suppressed_cue_ids']==[2]
    assert session.result['delivery_cue_count']==1
    assert len(agent.read_srt(Path(session.result['source_srt'])))==len(agent.read_srt(Path(session.result['translated_srt'])))==1
    manifest=read_json(Path(session.result['delivery_manifest']))
    assert manifest['mapping']==[{'delivery_id':1,'original_id':1}]
    assert manifest['all_kept_text_and_timing_unchanged']
    assert source.read_bytes()==before_source and target.read_bytes()==before_target and calls==[]
    final_path=session.result['translated_srt']
    session.status='running'
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('已验收交付不能重跑模型或覆盖文件'))
    agent.run(session,app)
    assert session.status=='done' and session.result['translated_srt']==final_path


def test_old_approved_keep_of_covered_empty_can_resolve_only_its_format_question(runtime):
    import hashlib
    r,_,_,_=prepared_translation(runtime);source=Path(r.selected()['path']);target=Path(r.state['translated'])
    write_srt([SubtitleCue(1,0,4,'감사합니다.'),SubtitleCue(2,2,4,'니다.')],source)
    write_srt([SubtitleCue(1,0,4,'谢谢'),SubtitleCue(2,2,4,'')],target)
    r.state['execution_policy']={'continue_existing_translation':True,'allowed_repair_cue_ids':[2]}
    evidence=[{'id':1,'quote':'감사합니다.'},{'id':2,'quote':'니다.'}]
    audit=r.root/'approved-audit.json'
    write_json_atomic(audit,{'proposals':{'2':{'action':'keep','replacement':None,'evidence':evidence}},
        'reviews':{'2':{'verdict':'approve','evidence':evidence}}})
    r.state['local_translation_review']={'audit':str(audit),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'target_ids':[2],'unresolved_ids':[2],
        'decisions':[{'id':2,'action':'uncertain'}]}
    r.state['pending_question']={'cue_id':2,'message':'空条怎么办'}
    r.prepare_recovery()
    assert not r.state.get('pending_question') and r.state['verification_required']
    assert r.state['local_translation_review']['unresolved_ids']==[]
    assert r.state['local_translation_review']['decisions'][0]['suppressed_in_delivery']


def test_new_out_of_scope_findings_pause_as_review_not_fake_permission_candidates(runtime,monkeypatch):
    import hashlib
    from scripts import asr_review_agent
    r,session,app,calls=prepared_translation(runtime)
    r.state['execution_policy'].pop('verification_only')
    r.state['execution_policy'].update(continue_existing_translation=True,allowed_repair_cue_ids=[2],
        original_translation_path=r.state['translated'])
    def reviewer(*a):return {'checks':[{'id':1,'verdict':'issue','source_quote':'안','translation_quote':'没吃','reason_zh':'需要结合语境复核'}]}
    monkeypatch.setattr(asr_review_agent,'llm_json',reviewer)
    r.verify();r.state['pending_question']={'cue_id':1,'question_type':'translation','message':'是否跳过验收交付'};r.save()
    monkeypatch.setattr(asr_review_agent,'llm_json',lambda *a:pytest.fail('边界外的复核需要明确授权，不能用普通候选回复绕过'))
    agent.run(session,app)
    assert session.status=='waiting' and session.phase=='autonomous_verification_review'
    assert session.question['options']==[] and not read_json(r.path).get('pending_question')
    assert '不代表都是真错误' in session.question['message'] and calls==[]


def test_approved_fragment_proof_survives_unrelated_local_edits_but_not_changed_context(runtime):
    import hashlib
    r,_,_,_=prepared_translation(runtime);source=Path(r.selected()['path']);target=Path(r.state['translated'])
    write_srt([SubtitleCue(1,0,1,'첫째'),SubtitleCue(2,2,6,'감사합니다.'),SubtitleCue(3,4,6,'니다.'),SubtitleCue(4,7,8,'끝')],source)
    write_srt([SubtitleCue(1,0,1,'第一'),SubtitleCue(2,2,6,'谢谢'),SubtitleCue(3,4,6,''),SubtitleCue(4,7,8,'结束')],target)
    r.state['execution_policy']={'continue_existing_translation':True,'allowed_repair_cue_ids':[3]}
    rows=[{'id':a.index,'start':a.start,'end':a.end,'source':a.text,'zh':b.text} for a,b in zip(agent.read_srt(source),agent.read_srt(target))]
    evidence=[{'id':2,'quote':'감사합니다.'},{'id':3,'quote':'니다.'}]
    audit=r.root/'proof.json';write_json_atomic(audit,{'views':{'3':rows[1:]},
        'proposals':{'3':{'action':'keep','replacement':None,'evidence':evidence}},'reviews':{'3':{'verdict':'approve','evidence':evidence}}})
    r.state['local_translation_review']={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'target_ids':[3],'audit':str(audit)}
    assert r.approved_coverage()[0]['id']==3
    newer=r.root/'other-review.srt';write_srt([SubtitleCue(c.index,c.start,c.end,'首条修订' if c.index==1 else c.text) for c in agent.read_srt(target)],newer)
    r.state['translated']=str(newer);r.state['local_translation_review']={}
    r.state['execution_policy']['allowed_repair_cue_ids']=[1]
    assert r.approved_coverage()[0]['id']==3
    changed=r.root/'changed-context.srt';write_srt([SubtitleCue(c.index,c.start,c.end,'相邻译文改变' if c.index==2 else c.text) for c in agent.read_srt(newer)],changed)
    r.state['translated']=str(changed)
    assert r.approved_coverage()==[]
