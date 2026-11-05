import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import asr_review_agent as agent
from scripts.asr3_benchmark import load_json,save_json


@pytest.fixture
def fixture(tmp_path):
    seed=tmp_path/'seed';seed.mkdir();audio=seed/'audio.wav';audio.write_bytes(b'test audio checksum')
    sample={'id':'clip','label':'test','start':0,'duration':3,'audio':str(audio),
            'audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest()}
    manifest={'version':1,'source_manifest':'fixture','samples':[sample],'policy':{}}
    save_json(seed/'manifest.json',manifest)
    cue={'index':1,'start':.2,'end':1.8,'text':'김서환님 안녕하세요'}
    q={'case_id':'clip:w1','sample_id':'clip','unit_id':'w1','start':.2,'end':1.8,'original_time':.2,
       'original':cue['text'],'question_zh':'谁？','context_zh':'test','uncertainty_zh':'test','candidates':[
         {'slot_zh':'人物','korean':'김서환','romanization':'Kim Seo-hwan','chinese_candidates':['金瑞焕']},
         {'slot_zh':'人物','korean':'김서원','romanization':'Kim Seo-won','chinese_candidates':['金瑞元']}]}
    save_json(seed/'human-review-questions.json',{'version':1,'experiment_id':'fingerprint','questions':[q]})
    save_json(seed/'protected-names.json',{'terms':['김서환','김서원']})
    save_json(seed/'clip/evidence.json',{'units':[{'id':'w1','text':cue['text']}]})
    save_json(seed/'clip/audit.json',{'version':1,'windows':[],'decisions':[
      {'id':'w1','start':.2,'end':1.8,'origin':'asr22','before':cue['text'],'after':cue['text'],
       'applied':False,'needs_review':True,'rejection':None,'proposal':{'action':'unresolved'},'review_window_ids':[]}]})
    for branch in ['asr22','qwen','agent']:
        save_json(seed/'clip'/branch/'source.json',{'cues':[cue]})
        save_json(seed/'clip'/branch/'translated.json',{'cues':[{**cue,'text':'김서환，你好'}]})
    request=seed/'answers.json'
    save_json(request,{'experiment_id':'fingerprint','answers':[{'case_id':'clip:w1','mode':'hint','hint':'应该叫金瑞元'}]})
    args=SimpleNamespace(seed_experiment=seed,output=tmp_path/'new',answers=request)
    return args,seed,q


def test_hint_resolves_candidate_and_updates_chinese_without_touching_parent(fixture,monkeypatch):
    args,seed,q=fixture
    before=(seed/'clip/agent/source.json').read_bytes()
    calls=[]
    def llm(*values):
        calls.append(values[1]);return {'decisions':[{'case_id':'clip:w1','state':'resolved','reason_zh':'线索与候选对应',
            'selections':[{'slot_zh':'人物','korean':'김서원','chinese':'金瑞元'}]}]}
    monkeypatch.setattr(agent,'llm_json',llm)
    agent.human_continue(args)
    assert calls==['clip-user-hints']
    assert load_json(args.output/'clip/agent/source.json')['cues'][0]['text']=='김서원님 안녕하세요'
    assert load_json(args.output/'clip/agent/translated.json')['cues'][0]['text']=='金瑞元，你好'
    assert load_json(args.output/'human-submission-result.json')['remaining_questions']==0
    assert (seed/'clip/agent/source.json').read_bytes()==before
    assert load_json(args.output/'clip/asr22/source.json')['cues'][0]['text']=='김서환님 안녕하세요'


def test_insufficient_hint_keeps_question_and_original(fixture,monkeypatch):
    args,seed,q=fixture
    monkeypatch.setattr(agent,'llm_json',lambda *args:{'decisions':[{'case_id':'clip:w1','state':'needs_more_info',
        'selections':[],'reason_zh':'请补充角色或作品'}]})
    agent.human_continue(args)
    questions=load_json(args.output/'human-review-questions.json')['questions']
    assert len(questions)==1 and questions[0]['uncertainty_zh']=='请补充角色或作品'
    assert all(c.get('romanization') and c.get('chinese_candidates') for c in questions[0]['candidates'])
    assert load_json(args.output/'clip/agent/source.json')==load_json(seed/'clip/agent/source.json')


def test_confirmed_transliteration_does_not_need_llm(fixture,monkeypatch):
    args,seed,q=fixture
    save_json(args.answers,{'experiment_id':'fingerprint','answers':[{'case_id':'clip:w1','mode':'transliteration',
        'selections':[{'slot_zh':'人物','korean':'김서환','romanization':'Kim Seo-hwan','chinese':'金瑞焕'}]}]})
    monkeypatch.setattr(agent,'llm_json',lambda *args:pytest.fail('Confirmed name-only rendering must not need LLM'))
    agent.human_continue(args)
    assert load_json(args.output/'clip/agent/translated.json')['cues'][0]['text']=='金瑞焕，你好'
    assert not load_json(args.output/'human-name-renderings.json')['renderings'][0]['identity_verified']


def test_hint_cannot_invent_a_korean_name(fixture,monkeypatch):
    args,_,_=fixture
    monkeypatch.setattr(agent,'llm_json',lambda *args:{'decisions':[{'case_id':'clip:w1','state':'resolved',
        'selections':[{'slot_zh':'人物','korean':'박보영','chinese':'朴宝英'}]}]})
    with pytest.raises(ValueError,match='未经支持'): agent.human_continue(args)
    assert not (args.output/'human-submission-result.json').exists()


def test_calibrated_parent_realigns_after_human_edit_before_publishing(fixture,monkeypatch):
    from scripts import asr_agent_timing
    args,seed,q=fixture
    manifest=load_json(seed/'manifest.json');manifest['policy']['final_text_audio_alignment']=True
    save_json(seed/'manifest.json',manifest)
    save_json(args.answers,{'experiment_id':'fingerprint','answers':[{'case_id':'clip:w1','mode':'transliteration',
        'selections':[{'slot_zh':'人物','korean':'김서환','romanization':'Kim Seo-hwan','chinese':'金瑞焕'}]}]})
    calls=[]
    def align(output):
        assert not (output/'human-submission-result.json').exists()
        assert load_json(output/'clip/agent/translated.json')['cues'][0]['text']=='金瑞焕，你好'
        calls.append(output);agent.report(output)
    monkeypatch.setattr(asr_agent_timing,'align_current',align)
    agent.human_continue(args)
    assert calls==[args.output.resolve()]
    assert (args.output/'human-submission-result.json').exists()
