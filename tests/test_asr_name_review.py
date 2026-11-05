import copy
import hashlib
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from scripts.asr3_benchmark import load_json, save_json
from scripts import asr_name_review as names
from scripts import asr_review_agent as agent


def question():
    return {'case_id': 'clip:w2', 'sample_id': 'clip', 'unit_id': 'w2',
            'start': 10, 'end': 12, 'original': '나의 김성아 님', 'candidates': [
                {'slot_zh': '人物', 'korean': '김성아', 'romanization': 'Kim Seong-a'},
                {'slot_zh': '人物', 'korean': '김서완', 'romanization': 'Kim Seo-wan'}]}


def evidence():
    return {'units': [{'id': 'w1', 'start': 7, 'end': 9, 'text': '오늘 재원이'},
                      {'id': 'w2', 'start': 10, 'end': 12, 'text': '나의 김성아 님'},
                      {'id': 'w3', 'start': 13, 'end': 16, 'text': '재원이 연극을 보러 갔다 왔어'}]}


def retries():
    return [{'target_ids': ['w2'], 'start': 5, 'end': 20, 'candidates': [
        {'engine': 'whisper', 'variant': 'original', 'text': '재원이 나의 김서완님'},
        {'engine': 'whisper', 'variant': 'gain', 'text': '증폭만 있는 이름'},
        {'engine': 'qwen', 'variant': 'original', 'text': '재원이 나의 김성아님'}]}]


def decision():
    return {'cases': [{'case_id': 'clip:w2', 'slots': [{'slot_zh': '人物', 'korean': '김서완',
        'reason_zh': '长上下文出现此读法，仍需确认。', 'citations': [
            {'source_id': 'retry:1', 'quote': '김서완님'},
            {'source_id': 'cue:w3', 'quote': '재원이 연극을 보러 갔다 왔어'}]}]}]}


def test_packet_has_wide_context_but_counts_no_gain_duplicates():
    p = names.packet(question(), evidence(), retries() * 3)
    assert len([s for s in p['sources'] if s['kind'] == 'local_asr']) == 2
    assert all('증폭만' not in s['text'] for s in p['sources'])
    assert p['sources'][0]['text'] == '오늘 재원이'


def test_grounded_context_recommendation_never_confirms_identity_or_edits():
    q = question(); before = copy.deepcopy(q)
    result = names.validate_assessment(decision(), [names.packet(q, evidence(), retries())])
    slot = result[q['case_id']]['slots']['人物']
    assert slot['korean'] == '김서완' and slot['status'] == 'recognition_only'
    assert not slot['identity_verified'] and not slot['auto_apply']
    assert slot['next_action'] == 'ask_user' and q == before


@pytest.mark.parametrize('mutation', ['new_name', 'invented_quote', 'unknown_source', 'one_citation', 'gain_only', 'wrong_slot', 'missing_case'])
def test_bad_context_claims_rejected(mutation):
    data = decision(); slot = data['cases'][0]['slots'][0]
    if mutation == 'new_name': slot['korean'] = '김상'
    if mutation == 'invented_quote': slot['citations'][0]['quote'] = '这个原句没有'
    if mutation == 'unknown_source': slot['citations'][0]['source_id'] = 'web:invented'
    if mutation == 'one_citation': slot['citations'] = slot['citations'][:1]
    if mutation == 'gain_only': slot['korean'] = '김성아'; slot['citations'][0]['source_id'] = 'cue:w2'; slot['citations'][0]['quote'] = '김성아'
    if mutation == 'wrong_slot': slot['slot_zh'] = '其他人'
    if mutation == 'missing_case': data['cases'] = []
    with pytest.raises(ValueError):
        names.validate_assessment(data, [names.packet(question(), evidence(), retries())])


def test_ambiguous_is_valid_without_forcing_a_winner():
    data = decision(); data['cases'][0]['slots'][0]['korean'] = None
    result = names.validate_assessment(data, [names.packet(question(), evidence(), retries())])
    assert result['clip:w2']['slots']['人物']['status'] == 'ambiguous'


def reference():
    return {'case_id': 'clip:w2', 'slot_zh': '人物', 'korean': '김서완',
            'url': 'https://example.org/interview', 'title': '测试采访', 'text': '演员与角色的关系线索',
            'checked_at': '2026-11-03', 'provenance': 'operator_checked_public_source'}


def test_context_preference_requires_an_additional_name_link_not_repeated_votes():
    q = question(); ref = reference(); ref['text'] = '演员对应角色김서완'
    refs = names.checked_references([ref], [q]); data = decision()
    data['cases'][0]['slots'][0]['citations'].append({'source_id': 'reference:1', 'quote': '角色김서완'})
    result = names.validate_assessment(data, [names.packet(q, evidence(), retries(), refs)])
    assert result[q['case_id']]['slots']['人物']['status'] == 'context_supported'


def test_target_baseline_plus_retry_is_still_not_contextual_identity_evidence():
    data = decision(); data['cases'][0]['slots'][0].update(korean='김성아', citations=[
        {'source_id': 'retry:2', 'quote': '김성아님'}, {'source_id': 'cue:w2', 'quote': '김성아'}])
    result = names.validate_assessment(data, [names.packet(question(), evidence(), retries())])
    slot = result['clip:w2']['slots']['人物']
    assert slot['status'] == 'recognition_only' and '缺少' in slot['summary_zh']


def test_multiple_person_slots_cannot_use_each_others_reference():
    q = question(); q['candidates'].append({'slot_zh':'第二位','korean':'지연','romanization':'Ji-yeon'})
    ref = reference(); ref['text'] = '김서완 与 지연 的资料'
    p = names.packet(q, evidence(), retries(), names.checked_references([ref],[q]))
    data = decision(); data['cases'][0]['slots'].append({'slot_zh':'第二位','korean':None,
        'reason_zh':'待审','citations':[{'source_id':'reference:1','quote':'지연'}]})
    with pytest.raises(ValueError, match='另一个人'):
        names.validate_assessment(data,[p])


@pytest.mark.parametrize('key,value', [('url', 'javascript:alert(1)'), ('url', 'https://key@example.org'),
                                     ('provenance', 'llm_said_verified'), ('korean', '김상'), ('text', '')])
def test_external_reference_is_not_a_model_claim_or_executable_link(key, value):
    ref = reference(); ref[key] = value
    with pytest.raises(ValueError): names.checked_references([ref], [question()])


def test_changed_candidates_invalidate_an_old_recommendation():
    q = question(); result = names.validate_assessment(decision(), [names.packet(q, evidence(), retries())])
    artifact = {'cases': result}
    assert names.current_review(q, artifact)
    q['candidates'].reverse()
    assert not names.current_review(q, artifact)


@pytest.fixture
def experiment(tmp_path):
    seed = tmp_path / 'seed'; seed.mkdir()
    audio = seed / 'audio.wav'; audio.write_bytes(b'frozen-test-audio')
    manifest = {'source_manifest': 'test', 'policy': {}, 'samples': [
        {'id': 'clip', 'start': 0, 'duration': 20, 'audio': str(audio),
         'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest()}]}
    save_json(seed / 'manifest.json', manifest)
    save_json(seed / 'human-review-questions.json', {'questions': [question()]})
    save_json(seed / 'clip/evidence.json', evidence())
    save_json(seed / 'clip/audit.json', {'windows': []})
    save_json(seed / 'protected-names.json', {'terms': []})
    return seed


def test_same_evidence_reuses_context_review_without_more_calls(experiment, monkeypatch):
    monkeypatch.setattr(agent, 'load_retries', lambda *args: retries())
    calls = []
    def llm(*args): calls.append(args[1]); return decision()
    first = names.assess(experiment, llm)
    second = names.assess(experiment, lambda *args: pytest.fail('no duplicate adjudication'))
    assert first == second and len(calls) == 1


def test_context_failure_preserves_original_artifact_and_reports_fallback(experiment, monkeypatch):
    monkeypatch.setattr(agent, 'load_retries', lambda *args: retries())
    before = (experiment / 'human-review-questions.json').read_bytes()
    def fail(*args): raise agent.LLMQuotaError('do not switch vendor')
    artifact = names.assess(experiment, fail)
    assert artifact['status'] == 'unavailable' and not artifact['cases']
    assert (experiment / 'human-review-questions.json').read_bytes() == before


def test_optional_references_still_require_actual_asr_support():
    q = question(); refs = names.checked_references([reference()], [q])
    p = names.packet(q, evidence(), [], refs)
    data = decision(); slot = data['cases'][0]['slots'][0]
    slot['citations'][0] = {'source_id': 'reference:1', 'quote': refs[0]['text']}
    with pytest.raises(ValueError, match='局部原音'):
        names.validate_assessment(data, [p])


def test_fork_never_copies_live_human_submission_state(experiment, monkeypatch):
    save_json(experiment / '.human-review-state.json', {'status': 'running'})
    save_json(experiment / 'human-answers.json', {'answers': ['private draft']})
    for branch in ('asr22', 'qwen', 'agent'):
        folder = experiment / 'clip' / branch; folder.mkdir()
        (folder / 'source.ko.srt').write_text('unchanged subtitle')
    monkeypatch.setattr(names, 'assess', lambda *args: {})
    monkeypatch.setattr(agent, 'report', lambda *args: None)
    args = SimpleNamespace(seed_experiment=experiment, output=experiment.parent / 'new', name_references=None)
    names.fork_review(args)
    assert not (args.output / '.human-review-state.json').exists()
    assert not (args.output / 'human-answers.json').exists()
    assert (args.output / 'clip/agent/source.ko.srt').read_bytes() == (experiment / 'clip/agent/source.ko.srt').read_bytes()
    with pytest.raises(ValueError): names.fork_review(args)


def test_review_ui_separates_context_and_recognition_and_never_preselects():
    assert '结合上下文更倾向' in agent.HTML
    assert '识别较稳定' in agent.HTML
    assert '上下文推荐 ≠ 身份确认' in agent.HTML
    assert 'contextIndex>=0?\'结合上下文更倾向\'' in agent.HTML
    assert 'current.choices[slot]=contextIndex' not in agent.HTML


def test_relative_report_path_keeps_web_submission_enabled(experiment, monkeypatch):
    root=experiment.parent; output=root/'outputs/asr3_experiments/test'
    shutil.copytree(experiment,output)
    save_json(output/'human-review-questions.json',{'experiment_id':'test','questions':[]})
    save_json(output/'clip/audit.json',{'windows':[],'decisions':[]})
    for branch in ('asr22','qwen','agent'):
        for name in ('source.json','translated.json'):
            save_json(output/'clip'/branch/name,{'cues':[]})
    monkeypatch.setattr(agent,'ROOT',root);monkeypatch.chdir(root)
    agent.report(Path('outputs/asr3_experiments/test'))
    assert load_json(output/'comparison.json')['web_review']['experiment_path']=='outputs/asr3_experiments/test'


@pytest.mark.parametrize('error',[ValueError('bad phonetic candidate'),agent.LLMQuotaError('quota exhausted')])
def test_optional_human_cards_never_discard_translated_experiment(experiment,monkeypatch,error):
    save_json(experiment/'clip/audit.json',{'decisions':[{'needs_review':True}]})
    def fail(*args):raise error
    monkeypatch.setattr(agent,'generate_human_questions',fail)
    result=agent.safe_human_questions(experiment)
    assert result['status']=='unavailable' and result['pending_case_count']==1
    assert result['questions']==[] and '不表示疑点已解决' in result['notice']
