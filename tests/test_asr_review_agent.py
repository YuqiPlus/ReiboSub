import json
from types import SimpleNamespace

import pytest

from scripts.asr_review_agent import (
    apply_decisions, make_units, restore_qwen_spacing, speech_coverage, validate_plan,
    protect_names, restore_names,
    filter_protected_names,
    corroborated_speech, resolve_timing_duplicates,
    continuation_windows, pending_groups,
    reuse_cached_translation, LLMQuotaError,
    validate_human_questions,
    apply_name_selections,
    recognition_preferences,
)


def unit(id='w1', origin='asr22', text='첫 차량', coverage=1):
    return {'id':id,'origin':origin,'text':text,'start':5,'end':7,'speech_coverage':coverage}


def retry(text='첫 촬영', engine='whisper', ids=('w1',)):
    return {'id':'r1','start':2,'end':10,'target_ids':list(ids),'candidates':[{'engine':engine,'variant':'original','text':text,
            'words':[{'text':text,'start':5,'end':7,'probability':.8}] if engine=='whisper' and text else []}]}


def bundle(*records):
    return {**records[0],'candidates':[c for r in records for c in r['candidates']]}


def proposal(id='w1', action='replace', text='첫 촬영', **kwargs):
    return {'id':id,'action':action,'text':text,**kwargs}


def test_plan_preserves_original_offsets_and_limits_round_budget():
    units=[unit()]
    requests=[{'target_ids':['w1'],'reason':'test'}]*5
    plans=validate_plan(requests,units,90,3)
    assert len(plans)==1
    assert plans[0]['start']==2
    assert plans[0]['end']==10
    wider=validate_plan(requests,units,90,2,plans,wider=True)
    assert wider[0]['start']==0
    assert wider[0]['end']==13
    assert wider[0]['id']=='r2'


def test_plan_rejects_unknown_ids_or_overlong_span():
    with pytest.raises(ValueError,match='unknown'):
        validate_plan([{'target_ids':['w999']}],[unit()],90,3)
    far={**unit('w2'),'start':40,'end':42}
    with pytest.raises(ValueError,match='spans'):
        validate_plan([{'target_ids':['w1','w2']}],[unit(),far],90,3)


def test_plan_cannot_crop_outside_sample():
    target={**unit(),'start':88,'end':89.9}
    plan=validate_plan([{'target_ids':['w1']}],[target],90,3)[0]
    assert plan['start']==82 and plan['end']==90


def test_unsupported_language_only_rewrite_is_not_applied():
    audit=apply_decisions([unit()],[proposal(text='완전히 새로운 이야기')],[retry()])[0]
    assert audit['after']=='첫 차량'
    assert audit['rejection']=='not_supported_by_local_asr'
    assert audit['needs_review']


def test_supported_correction_keeps_timeline():
    audit=apply_decisions([unit()],[proposal()],[retry()])[0]
    assert audit['after']=='첫 촬영'
    assert audit['applied']
    assert (audit['start'],audit['end'])==(5,7)


def test_plausible_text_elsewhere_in_window_cannot_replace_target():
    r=retry()
    r['candidates'][0]['words'][0].update(start=20,end=21)
    a=apply_decisions([unit()],[proposal()],[r])[0]
    assert a['after']=='첫 차량'
    assert a['rejection']=='candidate_not_localized_to_target'


def test_unresolved_or_unreviewed_does_not_change_original():
    for p in [proposal(action='unresolved'),proposal(uncertain=True)]:
        a=apply_decisions([unit()],[p],[retry()])[0]
        assert a['after']=='첫 차량' and a['needs_review']
    a=apply_decisions([unit()],[proposal()],[])[0]
    assert a['rejection']=='not_locally_reviewed'
    assert apply_decisions([unit()],[],[retry()])[0]['needs_review']


@pytest.mark.parametrize('coverage', [0,.1,.24])
def test_qwen_only_candidate_cannot_be_added_from_silence(coverage):
    u=unit('q1','qwen_only','정말',coverage)
    rs=[bundle(*[retry('정말',e,('q1',)) for e in ['whisper','qwen']])]
    a=apply_decisions([u],[proposal('q1','keep','정말')],rs)[0]
    assert a['after']==''
    assert a['needs_review']


def test_new_cue_needs_both_engines_not_two_variants_of_one():
    u=unit('q1','qwen_only','정말')
    a=apply_decisions([u],[proposal('q1','keep','정말')],[retry('정말','qwen',('q1',))]*2)[0]
    assert a['after']==''
    a=apply_decisions([u],[proposal('q1','keep','정말')],[bundle(*[retry('정말',e,('q1',)) for e in ['qwen','whisper']])])[0]
    assert a['after']=='정말' and a['applied']


def test_vad_alone_cannot_delete_existing_quiet_speech():
    u=unit(coverage=0)
    a=apply_decisions([u],[proposal(action='drop',text='')],[retry('첫 차량')])[0]
    assert a['after']=='첫 차량'
    assert a['rejection']=='deletion_not_proven_by_audio_candidates'


def test_empty_retries_and_no_vad_support_can_exclude_existing_cue():
    a=apply_decisions([unit(coverage=0)],[proposal(action='drop',text='')],[retry('')])[0]
    assert a['after']=='' and a['applied']


def test_new_cue_does_not_overlap_existing_timeline():
    units=[unit(),unit('q1','qwen_only','정말')]
    rs=[bundle(*[retry('정말',e,('q1',)) for e in ['qwen','whisper']])]
    a=apply_decisions(units,[proposal('q1','keep','정말')],rs)[1]
    assert a['after']=='' and a['rejection']=='new_cue_overlaps_existing'


def test_new_cue_cannot_duplicate_a_nearby_sentence_with_shifted_alignment():
    original={**unit(),'text':'진짜 춥더라','start':8,'end':10}
    new=unit('q1','qwen_only','춥더라')
    rs=[bundle(*[retry('춥더라',e,('q1',)) for e in ['qwen','whisper']])]
    a=apply_decisions([original,new],[proposal('q1','keep','춥더라')],rs)[1]
    assert a['after']=='' and a['rejection']=='duplicate_nearby_original_content'


def test_restore_original_korean_spacing_from_aligner_tokens():
    words=[{'index':1,'text':' 첫'},{'index':2,'text':' 촬'},{'index':3,'text':' 영'},
           {'index':4,'text':' 이야'}]
    cue={'word_indexes':[1,2,3],'text':'첫 촬 영'}
    raw=[{'text':'첫 촬영이야.'}]
    assert restore_qwen_spacing([cue],words,raw)[0]['text']=='첫 촬영'
    with pytest.raises(ValueError):
        restore_qwen_spacing([cue],words,[{'text':'다른 말'}])


def test_qwen_only_candidate_is_audited_not_silently_added():
    w={'index':1,'start':1,'end':2,'text':'원문'}
    q={'index':1,'start':5,'end':6,'text':'정말'}
    units=make_units([w],[q],[{'start':1,'end':2}])
    assert units[1]['origin']=='qwen_only'
    assert units[1]['speech_coverage']==0
    assert apply_decisions(units,[],[])[1]['after']==''
    assert speech_coverage(0,10,[{'start':1,'end':2}])==.1


def test_unknown_or_duplicate_llm_ids_fail_closed():
    with pytest.raises(ValueError):
        apply_decisions([unit()],[proposal('w999')],[])
    with pytest.raises(ValueError):
        apply_decisions([unit()],[proposal(),proposal()],[])


def test_llm_cache_keeps_credentials_out_and_refuses_different_request(tmp_path,monkeypatch):
    from scripts.asr_review_agent import llm_json
    import video_translate.llm_config as config
    import video_translate.translate.volcengine as transport
    calls=[]
    monkeypatch.setattr(config,'load_llm_task_config',lambda _:SimpleNamespace(
        api_key='test-secret-not-for-artifacts',base_url='https://example.invalid/v1',model='doubao-seed-2-1-lite-test'))
    def request(url,key,payload,**kwargs):
        calls.append(payload)
        return '{"requests":[]}'
    monkeypatch.setattr(transport,'_request_translation',request)
    assert llm_json(tmp_path,'plan','asr_correction','instruction',{})=={'requests':[]}
    assert llm_json(tmp_path,'plan','asr_correction','instruction',{})=={'requests':[]}
    assert len(calls)==1
    assert calls[0]['thinking']=={'type':'disabled'}
    assert calls[0]['max_tokens']==4096
    assert all('test-secret-not-for-artifacts' not in p.read_text() for p in tmp_path.rglob('*.json'))
    with pytest.raises(FileExistsError):
        llm_json(tmp_path,'plan','asr_correction','different instruction',{})


def test_report_requires_translation_timeline_to_be_unchanged(tmp_path):
    from scripts.asr_review_agent import report
    from scripts.asr3_benchmark import save_json
    save_json(tmp_path/'manifest.json',{'samples':[{'id':'clip','label':'test','start':10,
        'duration':20,'audio':'/unused.wav'}],'policy':{}})
    save_json(tmp_path/'clip/audit.json',{'windows':[],'decisions':[]})
    cue={'index':1,'start':2,'end':4,'text':'한국어'}
    for branch in ['asr22','qwen','agent']:
        save_json(tmp_path/'clip'/branch/'source.json',{'cues':[cue]})
        save_json(tmp_path/'clip'/branch/'translated.json',{'cues':[{**cue,'text':'中文'}]})
    report(tmp_path)
    result=json.loads((tmp_path/'comparison.json').read_text())
    assert result['samples'][0]['branches']['agent']['cues'][0]['zh']=='中文'
    save_json(tmp_path/'clip/agent/translated.json',{'cues':[{**cue,'end':8}]})
    with pytest.raises(ValueError,match='timeline'):
        report(tmp_path)


def test_proper_name_correction_needs_two_engines_not_gain_consensus():
    r=retry('김서원님')
    r['reason']='人名误识别'
    a=apply_decisions([unit(text='김성아님')],[proposal(text='김서원님')],[r])[0]
    assert a['rejection']=='proper_name_not_agreed_between_engines'


def test_normal_sentence_does_not_inherit_name_guard_from_shared_window():
    r=retry('그리고 나 첫 촬영')
    r['reason']='和导演姓名共用复核窗口，人名误识别'
    a=apply_decisions([unit(text='그리고 나 첫 촬영 그')],[proposal(text='그리고 나 첫 촬영')],[r])[0]
    assert a['after']=='그리고 나 첫 촬영' and not a['needs_review']


def test_low_vad_can_be_overridden_by_two_engines_in_two_timed_contexts():
    u=unit('q1','qwen_only','정말',0)
    one=bundle(*[retry('정말',e,('q1',)) for e in ['whisper','qwen']])
    two={**one,'id':'r2','start':0,'end':14}
    a=apply_decisions([u],[proposal('q1','keep','정말')],[one,two])[0]
    assert a['after']=='정말' and not a['needs_review']
    assert a['speech_evidence']['vad_override']
    assert a['speech_evidence']['contexts']==2
    assert not corroborated_speech(u,'정말',[one,one])['accepted']


def test_low_vad_override_cannot_use_gain_only_or_unstable_timing():
    u=unit('q1','qwen_only','정말',0)
    one=bundle(*[retry('정말',e,('q1',)) for e in ['whisper','qwen']])
    two={**one,'id':'r2','start':0,'end':14,'candidates':[
        {**c,'variant':'gain'} for c in one['candidates']]}
    assert not corroborated_speech(u,'정말',[one,two])['accepted']
    two['candidates']=[{**c,'variant':'original','words':[
        {**w,'start':w['start']-1.1} for w in c.get('words',[])]} for c in two['candidates']]
    assert not corroborated_speech(u,'정말',[one,two])['accepted']


def test_duplicate_candidate_closes_and_repairs_existing_end_without_mutating_baseline():
    original={**unit(text='진짜 춥더라'),'start':3.2,'end':5.08}
    new={**unit('q1','qwen_only','춥더라'),'start':7.52,'end':8.32}
    r=bundle(retry('진짜 춥더라',ids=('q1',)),retry('진짜 춥더라','qwen',('q1',)))
    r.update(start=0,end=8)
    r['candidates'][0]['words']=[{'text':'춥더라','start':6.22,'end':7.62,'probability':.87}]
    other={**r,'id':'r2','end':8.82}
    audit=resolve_timing_duplicates(apply_decisions([original,new],[],[]),[original,new],[r,other])
    assert audit[1]['resolution']=='duplicate_existing_content' and not audit[1]['needs_review']
    assert audit[0]['end']==7.62
    assert original['end']==5.08


def test_protected_name_round_trip_and_failure_if_translator_invents_name():
    text,mapping=protect_names('재원이랑 김서원님',['재원','김서원'])
    assert '재원' not in text and '김서원' not in text
    assert restore_names(text,text+' 一起',mapping)=='재원이랑 김서원님 一起'
    with pytest.raises(ValueError,match='dropped'):
        restore_names(text,'金瑞元',mapping)
    with pytest.raises(ValueError,match='invented'):
        restore_names(text,text+' ⟦N999⟧',mapping)


def test_name_extraction_cannot_lock_plain_movie_noun_or_unattested_name():
    assert filter_protected_names(['영화','영아','재원','김서원'],['우리 영화 재원'])==['재원']
    one,_=protect_names('재원',['재원'])
    two,_=protect_names('재원',['김성아','재원'])
    assert one==two


def test_keep_cannot_clear_a_real_name_disagreement():
    u=unit(text='김성아님')
    one=bundle(retry('김성아님'),retry('김서환님','qwen'))
    a=apply_decisions([u],[proposal(action='keep',text='김성아님')],[one])[0]
    assert a['needs_review'] and a['rejection']=='proper_name_still_conflicted'


def test_continuation_selects_new_context_without_touching_resolved_units():
    u=unit()
    focus=continuation_windows([{'target_ids':['w1'],'strategy':'focus'}],[u],['w1'],90,[],'focus')[0]
    assert focus['start']==4.2 and focus['end']==7.8
    context=continuation_windows([{'target_ids':['w1'],'strategy':'context'}],[u],['w1'],90,[focus],'context')[0]
    assert context['start']==0 and context['end']==17
    assert context['id']=='r2'
    with pytest.raises(ValueError,match='resolved'):
        continuation_windows([{'target_ids':['w1']}],[u],[],90,[],'focus')
    assert continuation_windows([{'target_ids':['w1'],'strategy':'focus'}],[u],['w1'],90,[focus],'focus')==[]


def test_pending_names_next_to_each_other_share_a_window():
    units=[unit('w1'),{**unit('w2'),'start':7,'end':9},{**unit('w3'),'start':30,'end':32}]
    assert pending_groups(units,['w1','w2','w3'])==[['w1','w2'],['w3']]


def test_quota_failure_is_recorded_and_does_not_switch_provider(tmp_path,monkeypatch):
    from scripts.asr_review_agent import llm_json
    import video_translate.llm_config as config
    import video_translate.translate.volcengine as transport
    monkeypatch.setattr(config,'load_llm_task_config',lambda _:SimpleNamespace(
        api_key='test-secret',base_url='https://example.invalid/v1',model='doubao-seed-2-1-lite-test'))
    def fail(*args,**kwargs):
        assert kwargs['max_attempts']==1
        raise RuntimeError('AccountQuotaExceeded reset at 2026-11-03 16:21:55 +0800 CST')
    monkeypatch.setattr(transport,'_request_translation',fail)
    with pytest.raises(LLMQuotaError): llm_json(tmp_path,'judge','asr_correction','test',{})
    status=json.loads((tmp_path/'runtime-status.json').read_text())
    assert not status['switched_provider'] and not status['audio_uploaded']
    assert status['reset_time']=='2026-11-03 16:21:55 +0800'


def test_offline_translation_uses_same_clip_exact_qwen_cache_for_added_word(tmp_path):
    from scripts.asr3_benchmark import save_json
    output=tmp_path/'new';seed=tmp_path/'old'
    old={'index':1,'start':1,'end':2,'text':'진짜 춥더라'}
    new={'index':2,'start':8,'end':9,'text':'정말'}
    for branch in ['agent','asr22','qwen']:
        ko=[old,*([new] if branch=='qwen' else [])]
        zh=[{**old,'text':'真的很冷'},*([{**new,'text':'真的'}] if branch=='qwen' else [])]
        save_json(seed/'clip'/branch/'source.json',{'cues':ko})
        save_json(seed/'clip'/branch/'translated.json',{'cues':zh})
    save_json(output/'clip/agent/source.json',{'cues':[{**old,'end':3},new]})
    reuse_cached_translation(output,seed,{'id':'clip'})
    result=json.loads((output/'clip/agent/translated.json').read_text())
    assert [c['text'] for c in result['cues']]==['真的很冷','真的']
    assert result['cues'][0]['end']==3 and result['provenance'][1]['source_branch']=='qwen'
    assert not result['llm_refreshed']


def human_case():
    return {'case_id':'clip:w7','sample_id':'clip','unit_id':'w7','start':20,'end':23,
            'original_time':110,'original':'나의 영원한 김성아 님',
            'evidence_texts':['김성아 님','나의 영원한 김서환님','나의 영원한 김서원님']}


def human_result():
    return {'questions':[{'case_id':'clip:w7','question_zh':'称呼的人是谁？','context_zh':'提到看话剧时的称呼。',
        'uncertainty_zh':'两个模型名字读法不同。','candidates':[
        {'korean':'김서환','romanization':'Kim Seo-hwan','chinese_candidates':['金瑞焕','金叙焕'],'slot_zh':'被称呼的人'},
        {'korean':'김서원','romanization':'Kim Seo-won','chinese_candidates':['金瑞元'],'slot_zh':'被称呼的人'}]}]}


def test_human_question_includes_korean_romanization_and_chinese_candidates():
    rows=validate_human_questions(human_result(),[human_case()])
    candidate=rows[0]['candidates'][0]
    assert (candidate['korean'],candidate['romanization'],candidate['chinese_candidates'][0])==('김서환','Kim Seo-hwan','金瑞焕')
    assert not candidate['verified'] and candidate['kind']=='phonetic_suggestion'


@pytest.mark.parametrize('field,value',[
    ('korean','박보영'),('romanization','金瑞焕'),('romanization',''),
    ('chinese_candidates',[]),('chinese_candidates',['Kim Seo-hwan']),
])
def test_human_question_rejects_unattested_name_or_missing_language_layer(field,value):
    result=human_result();result['questions'][0]['candidates'][0][field]=value
    with pytest.raises(ValueError): validate_human_questions(result,[human_case()])


def test_human_question_cannot_drop_or_add_pending_case():
    with pytest.raises(ValueError): validate_human_questions({'questions':[]},[human_case()])
    result=human_result();result['questions'][0]['case_id']='clip:unknown'
    with pytest.raises(ValueError): validate_human_questions(result,[human_case()])


def test_human_question_removes_duplicate_or_incomplete_chinese_suggestions():
    result=human_result()
    result['questions'][0]['candidates'][0]['chinese_candidates']=['金瑞焕','金瑞焕','焕']
    rows=validate_human_questions(result,[human_case()])
    assert rows[0]['candidates'][0]['chinese_candidates']==['金瑞焕']


def test_user_name_selection_changes_only_named_span():
    q={'candidates':[{'slot_zh':'人物','korean':'김성아'},{'slot_zh':'人物','korean':'김서환'}]}
    text,edits=apply_name_selections('나의 영원한 김성아 님',q,[{'slot_zh':'人物','korean':'김서환','chinese':'金瑞焕'}])
    assert text=='나의 영원한 김서환 님'
    assert edits[0]['previous_korean']=='김성아'
    with pytest.raises(ValueError,match='唯一'):
        apply_name_selections('김성아 김성아',q,[{'slot_zh':'人物','korean':'김서환'}])


def test_review_page_defaults_to_one_focused_question_not_a_survey():
    from scripts.asr_review_agent import HTML
    assert '<body data-view="review">' in HTML
    assert 'id="lab-view"' in HTML and 'class="lab-only"' in HTML
    assert 'name-zh' in HTML and 'name-ko' in HTML and 'name-roman' in HTML
    assert 'if(q.case_id!==active?.case_id)continue' in HTML
    assert 'className=\'answer-mode\'' not in HTML
    assert 'createElement(\'textarea\')' not in HTML
    assert 'reviewStopAt' in HTML


def ranking_question():
    return {'unit_id':'w1','original':'김성아 님','candidates':[
        {'slot_zh':'人物','korean':'김성아','romanization':'Kim Seong-a'},
        {'slot_zh':'人物','korean':'김서환','romanization':'Kim Seo-hwan'},
        {'slot_zh':'人物','korean':'김서원','romanization':'Kim Seo-won'}]}


def ranking_retry(engine,text,start,variant='original'):
    return {'target_ids':['w1'],'start':start,'end':start+10,
            'candidates':[{'engine':engine,'text':text,'variant':variant}]}


def test_display_preference_balances_engines_not_number_of_retries():
    q=ranking_question()
    retries=[ranking_retry('whisper','김성아 님',i) for i in range(10)]
    retries += [ranking_retry('qwen','김서환님',i) for i in range(2)]
    pref=recognition_preferences(q,{},retries)['人物']
    assert pref['status']=='close'
    assert {r['score'] for r in pref['observations'][:2]}=={.5}
    assert not pref['verified']


def test_display_preference_ignores_gain_and_duplicate_original_contexts():
    q=ranking_question()
    original=[ranking_retry('whisper','김성아',i) for i in range(2)]+[ranking_retry('qwen','김서환',i) for i in range(2)]
    extras=[ranking_retry('whisper','김성아',i,'gain') for i in range(30)]+original*5
    assert recognition_preferences(q,{},original)==recognition_preferences(q,{},original+extras)


def test_stable_engine_can_lead_while_other_engine_disagrees_visibly():
    q=ranking_question()
    retries=[ranking_retry('qwen','김서환',i) for i in range(4)]
    retries += [ranking_retry('whisper','김성아' if i<2 else '김서원',i) for i in range(4)]
    pref=recognition_preferences(q,{},retries)['人物']
    assert pref['candidate_index']==1 and pref['status']=='tentative'
    assert '另一模型仍有分歧' in pref['reason_zh']
    assert pref['ranked_candidate_indexes'][0]==1


def test_insufficient_recognition_does_not_invent_confidence():
    q=ranking_question()
    pref=recognition_preferences(q,{'units':[{'id':'w1','origin':'asr22','text':'김성아 님'}]},[])['人物']
    assert pref['status']=='limited_evidence' and pref['candidate_index']==0
    assert 'probability' in pref['method'] and 'confidence' not in pref


def test_preference_keeps_different_people_separate():
    q=ranking_question();q['candidates'].append({'slot_zh':'第二位','korean':'지현','romanization':'Ji-hyeon'})
    prefs=recognition_preferences(q,{},[ranking_retry('qwen','김서환 지현',0),ranking_retry('whisper','김성아 지현',0)])
    assert prefs['第二位']['candidate_index']==3
    assert 3 not in prefs['人物']['ranked_candidate_indexes']
