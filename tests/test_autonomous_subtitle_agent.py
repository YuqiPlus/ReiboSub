import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import autonomous_subtitle_agent as agent
from scripts.asr3_benchmark import load_json,save_json


def data():
    u={'id':'w1','origin':'asr22','index':1,'start':2,'end':4,'text':'오늘 좋아요','speech_coverage':1,
       'qwen_references':[{'text':'오늘 좋아요','start':2,'end':4}]}
    return {'units':[u],'whisper':[u],'qwen':[u],'qwen_raw':[{'text':'오늘 좋아요'}],
            'sample':{'duration':20},'asr22_quality':{}}


def state():
    d=data();d['units'][0]['qwen_references'][0]['text']='오늘 싫어요'
    s={'clip':{'sample':{'id':'clip','duration':20,'start':0},'data':d,'issues':agent.inspect_source(d),
       'plans':[],'proposals':{},'retries':[],'judged_windows':0,'translation_issues':[]}}
    agent.refresh(s);return s


def test_inspector_distinguishes_identical_text_and_missing_or_disagreeing_content():
    assert agent.inspect_source(data())==[]
    s=state();assert s['clip']['audit'][0]['needs_review']
    assert s['clip']['issues'][0]['id']=='w1'


def test_no_arbitrary_tools_unknown_targets_or_premature_finish():
    allowed=agent.available(state(),False,False,False,0)
    for action in ({'tool':'shell','command':'anything'},{'tool':'finish'},{'tool':'ask_user'},
                   {'tool':'relisten','sample_id':'clip','target_ids':['unknown'],'strategy':'context'}):
        with pytest.raises(ValueError):agent.validate_action(action,allowed)


def test_cannot_ask_before_both_contexts_and_judgment_or_budget_exhaustion():
    s=state();entry=s['clip']
    entry['plans']=[{'id':'r1','start':1.2,'end':4.8,'target_ids':['w1'],'strategy':'focus'},
                    {'id':'r2','start':0,'end':14,'target_ids':['w1'],'strategy':'context'}]
    assert 'ask_user' not in {a['tool'] for a in agent.available(s,True,True,True,1)}
    entry['judged_windows']=2
    assert 'ask_user' in {a['tool'] for a in agent.available(s,True,True,True,1)}


def test_original_window_not_requested_twice():
    s=state()['clip'];option=agent.eligible(s)[0]
    s['plans']=[option['plan']]
    assert all(p['plan']['start']!=option['plan']['start'] or p['plan']['end']!=option['plan']['end'] for p in agent.eligible(s))


def test_context_candidates_do_not_copy_neighboring_subtitle_into_the_target():
    unit={'text':'나의 영원한 김서원 님','start':2,'end':4}
    text=agent.localized_candidate(unit,{'engine':'qwen','text':'재원이 나의 영원한 김서환님 재원이 연극 보러 갔다'})
    assert text=='나의 영원한 김서환님'
    assert agent.localized_candidate(unit,{'engine':'qwen','text':'完全不同而且没有时间证据'}) is None


def test_budget_is_enforced_and_translation_qa_has_retry_limit():
    s=state();s['clip']['plans']=[{}]*6;s['clip']['judged_windows']=6
    assert agent.eligible(s['clip'])==[]
    s['clip']['translation_issues']=[{'id':1}]
    assert 'translate' in {a['tool'] for a in agent.available(s,True,True,True,1)}
    assert 'translate' not in {a['tool'] for a in agent.available(s,True,True,True,2)}


def test_finish_requires_translation_check_and_alignment():
    s=state();s['clip']['audit'][0]['needs_review']=False
    assert 'finish' not in {a['tool'] for a in agent.available(s,True,False,True,1)}
    assert 'finish' not in {a['tool'] for a in agent.available(s,True,True,False,1)}
    assert 'finish' in {a['tool'] for a in agent.available(s,True,True,True,1)}


def test_unreviewed_noops_are_ignored_but_edits_feed_back_to_agent():
    units=data()['units']+[{'id':'w2','text':'unchanged'}]
    decisions=[{'id':'w1','action':'keep','text':'오늘 좋아요'},
        {'id':'w2','action':'keep','text':'unchanged'},{'id':'w2','action':'replace','text':'invented'}]
    accepted,errors=agent.guard_decisions(decisions,units,{'w1'})
    assert [p['id'] for p in accepted]==['w1'] and errors
    assert agent.guard_decisions([{'id':'w2','action':'replace','text':'invented'}],units,{'w1'})[1]


def test_clean_case_skips_audio_tools_and_runs_selected_quality_actions(tmp_path,monkeypatch):
    out=tmp_path/'experiment';d=data();sample={'id':'clip','start':0,'duration':20,'audio_sha256':'test'}
    def prepare(manifest,output):
        save_json(output/'manifest.json',{'samples':[sample],'policy':{}})
        save_json(output/'clip/evidence.json',d);return [sample]
    monkeypatch.setattr(agent.tools,'prepare',prepare)
    choices=iter(['translate','check_translation','align','finish'])
    monkeypatch.setattr(agent.tools,'llm_json',lambda *a:{'tool':next(choices),'reason':'bounded smoke test'})
    def translate(output,sample,*a,**k):
        p=output/'clip/agent';source=load_json(p/'source.json');save_json(p/'translated.json',source)
    monkeypatch.setattr(agent,'translate',translate);monkeypatch.setattr(agent,'check_translation',lambda *a:[])
    monkeypatch.setattr(agent.tools,'translate_branch',lambda *a:None)
    def align(output,*a):
        save_json(output/'timing-summary.json',{'samples':[{'sample_id':'clip','total':1,'aligned':1,'timing_needs_review':0}]})
    monkeypatch.setattr(agent,'align',align);monkeypatch.setattr(agent.tools,'report',lambda *a:None)
    agent.run(SimpleNamespace(output=out,manifest=tmp_path/'baseline.json'))
    trace=load_json(out/'autonomous-trace.json')
    assert [a['tool'] for a in trace['actions']]==['translate','check_translation','align','finish']
    assert not trace['quality']['ground_truth_verified']
    assert trace['status']=='draft_ready'
    with pytest.raises(FileExistsError):agent.run(SimpleNamespace(output=out,manifest=None))


@pytest.fixture
def human_case(tmp_path,monkeypatch):
    seed=tmp_path/'seed';audio=tmp_path/'audio.wav';audio.write_bytes(b'local-only-test')
    sample={'id':'clip','label':'fixture','audio':str(audio),'audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),'duration':5,'start':0}
    save_json(seed/'manifest.json',{'samples':[sample],'policy':{'autonomous_subtitle_agent':True}})
    q={'case_id':'clip:w1','sample_id':'clip','unit_id':'w1','kind':'subtitle','original':'반가워요','start':0,'end':2,
       'original_time':0,'question_zh':'哪一种？','context_zh':'测试','uncertainty_zh':'测试','candidates':[
           {'slot_zh':'这句字幕','korean':'반가워요','romanization':'Bangawoyo','chinese_candidates':['很高兴见到你']},
           {'slot_zh':'这句字幕','korean':'반가웠어요','romanization':'Bangawosseoyo','chinese_candidates':['见到你很高兴']} ]}
    save_json(seed/'human-review-questions.json',{'experiment_id':'fixture','questions':[q]})
    save_json(seed/'protected-names.json',{'terms':[]});save_json(seed/'autonomous-trace.json',{'actions':[]})
    row={'id':'w1','start':0,'end':2,'origin':'asr22','before':'반가워요','after':'반가워요','needs_review':True,'applied':False,'proposal':None}
    save_json(seed/'clip/audit.json',{'windows':[],'decisions':[row]});save_json(seed/'clip/evidence.json',{'units':[]})
    for branch in ('asr22','qwen','agent'):
        agent.tools.write_source(seed/'clip'/branch,[{'start':0,'end':2,'text':'반가워요'}])
        save_json(seed/'clip'/branch/'translated.json',{'cues':[{'index':1,'start':0,'end':2,'text':'很高兴见到你'}]})
    request=tmp_path/'answer.json'
    save_json(request,{'experiment_id':'fixture','answers':[{'case_id':'clip:w1','mode':'transliteration','selections':[
        {'slot_zh':'这句字幕','korean':'반가웠어요','romanization':'Bangawosseoyo','chinese':'见到你很高兴'}]}]})
    def translate(output,sample,*a,**k):save_json(output/'clip/agent/translated.json',load_json(output/'clip/agent/source.json'))
    monkeypatch.setattr(agent,'translate',translate);monkeypatch.setattr(agent,'check_translation',lambda *a:[])
    monkeypatch.setattr(agent,'align',lambda *a:None);monkeypatch.setattr(agent.tools,'report',lambda *a:None)
    return SimpleNamespace(seed_experiment=seed,output=tmp_path/'child',answers=request),seed


def test_user_choice_continues_without_overwriting_parent(human_case):
    args,seed=human_case;before=(seed/'clip/agent/source.json').read_bytes()
    agent.respond(args)
    assert load_json(args.output/'clip/agent/source.json')['cues'][0]['text']=='반가웠어요'
    assert load_json(args.output/'human-submission-result.json')['remaining_questions']==0
    assert (seed/'clip/agent/source.json').read_bytes()==before
    agent.respond(args)  # A completed identical request is idempotent.


def test_insufficient_user_hint_stays_unresolved(human_case,monkeypatch):
    args,_=human_case
    save_json(args.answers,{'experiment_id':'fixture','answers':[{'case_id':'clip:w1','mode':'hint','hint':'我也只听到个大概'}]})
    monkeypatch.setattr(agent.tools,'llm_json',lambda *a:{'korean':None,'reason_zh':'还缺上下文线索'})
    agent.respond(args)
    assert load_json(args.output/'human-submission-result.json')['remaining_questions']==1


def test_user_cannot_inject_unlisted_transcript(human_case):
    args,_=human_case;request=load_json(args.answers)
    request['answers'][0]['selections'][0]['korean']='invented Korean'
    save_json(args.answers,request)
    with pytest.raises(ValueError):agent.respond(args)
    assert not (args.output/'human-submission-result.json').exists()


def test_completed_identical_alignment_is_reused(tmp_path,monkeypatch):
    from scripts import asr_agent_timing
    out=tmp_path/'result';sample={'id':'clip','audio_sha256':'frozen'}
    save_json(out/'manifest.json',{'samples':[sample]})
    save_json(out/'clip/agent/source.json',{'cues':[]})
    save_json(out/'human-review-questions.json',{'questions':[]});calls=[]
    def calibrate(args):
        calls.append(args.output)
        for name in ('audit.json','timing-alignment.json'):save_json(args.output/'clip'/name,{})
        for name in ('source.json','translated.json'):save_json(args.output/'clip/agent'/name,{'cues':[]})
        for name in ('source.ko.srt','translated.zh.srt'):(args.output/'clip/agent'/name).write_text('')
        save_json(args.output/'timing-summary.json',{'samples':[]})
        save_json(args.output/'human-review-questions.json',{'questions':[]})
    monkeypatch.setattr(asr_agent_timing,'calibrate',calibrate)
    agent.align(out,1,SimpleNamespace(qwen_python=Path('/local/qwen')))
    agent.align(out,1,SimpleNamespace(qwen_python=Path('/local/qwen')))
    assert len(calls)==1


def test_new_user_grounded_reading_needs_another_confirmation(human_case,monkeypatch):
    args,seed=human_case
    save_json(args.answers,{'experiment_id':'fixture','answers':[{'case_id':'clip:w1','mode':'hint','hint':'我明确听到 반갑습니다'}]})
    monkeypatch.setattr(agent.tools,'llm_json',lambda *a:{'korean':None,'reason_zh':'新线索',
        'proposed_candidate':{'korean':'반갑습니다','romanization':'Bangapseumnida','meaning_zh':'很高兴见面'}})
    agent.respond(args)
    artifact=load_json(args.output/'human-review-questions.json')
    assert len(artifact['questions'])==1 and artifact['questions'][0]['candidates'][-1]['kind']=='user_hint_proposal'
    assert load_json(args.output/'clip/agent/source.json')['cues'][0]['text']=='반가워요'


def test_chinese_only_clue_cannot_create_unattested_korean():
    q={'original':'나의 김서환님'}
    proposal={'korean':'나의 김서완님','romanization':'Na-ui Kim Seo-wan nim','meaning_zh':'新的读法'}
    assert agent.user_proposal(q,'好像是金书完',proposal) is None
    assert agent.user_proposal(q,'韩文名字是 김서완',proposal)['kind']=='user_hint_proposal'
