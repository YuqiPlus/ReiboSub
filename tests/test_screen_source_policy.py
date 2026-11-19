from pathlib import Path
from types import SimpleNamespace

import pytest

from video_translate.agent import autonomous as agent, decisions, screen_source_policy as policy
from video_translate.agent.models import AgentSession


def state():
    return {'controller_version': 2, 'screen_source_policy_version': 1,
            'counts': {}, 'events': [], 'sources': {}, 'captions': [],
            'language': 'korean', 'evidence': {}, 'user_confirmations': {},
            'probe': {'duration': 100}, 'media': '/example/video.mp4'}


def observe(s, present=True, times=(10, 35, 65, 90), regions=None):
    frames = [{'path': f'/example/{t}.jpg', 'time_seconds': t} for t in times]
    regions = ([[.1, .6, .9, .8]] if present else []) if regions is None else regions
    policy.observe(s, frames, {'has_burned_subtitles': present,
                              'subtitle_regions': regions, 'summary_zh': '实际抽样观察'})


def names(s):
    return {t.name for t in agent.ready(s)}


def test_unknown_screen_cannot_fall_back_to_asr_or_lock_caption_source():
    s = state()
    s['sources'] = {'captions_1': {'kind': 'captions'}}
    assert 'sample_frames' in names(s)
    assert not names(s) & {'asr', 'select_source', 'glossary', 'translate', 'finish', 'ocr'}
    s['frames'] = [{'path': '/example/frame.jpg', 'time_seconds': 20}]
    s['frame_history'] = [{'time_seconds': t} for t in (10, 35, 65, 90)]
    assert 'analyze_frames' in names(s)
    assert policy.assessment(s)['status'] == 'unknown'  # Sampling != seeing.


@pytest.mark.parametrize('times', [(10,), (1, 2, 3, 4), (10, 25, 45, 65)])
def test_narrow_or_single_negative_sample_is_not_evidence_for_whole_video_asr(times):
    s = state(); observe(s, False, times)
    assert policy.assessment(s)['status'] == 'unknown'
    assert 'asr' not in names(s)


def test_diverse_negative_observations_allow_audio_but_do_not_claim_whole_video_proof():
    s = state(); observe(s, False)
    check = policy.assessment(s)
    assert check['status'] == 'not_seen_in_samples' and check['surveyed']
    assert 'asr' in names(s)
    assert '不代表整片证明' in check['notice']


def test_positive_evidence_cannot_be_erased_by_a_later_negative_batch():
    s = state(); observe(s, True, (20,))
    observe(s, False)
    assert policy.assessment(s)['status'] == 'present'
    assert 'asr' not in names(s)
    assert policy.protected_regions(s) == [[.1, .6, .9, .8]]


def test_known_hard_subtitles_cannot_select_asr_or_external_caption_as_primary():
    s = state(); observe(s)
    s['sources'] = {'asr_1': {'kind': 'asr'}, 'captions_2': {'kind': 'captions'}}
    assert 'select_source' not in names(s) and 'asr' not in names(s)
    s['sources']['ocr_3'] = {'kind': 'ocr'}
    assert 'select_source' in names(s)
    for source in ('asr_1', 'captions_2'):
        with pytest.raises(ValueError, match='只能选择本次OCR'):
            agent.validate_call({'tool': 'select_source', 'args': {'source_id': source}}, s)
    assert agent.validate_call({'tool': 'select_source', 'args': {'source_id': 'ocr_3'}}, s)[0] == 'select_source'


def test_existing_wrong_asr_selection_cannot_enter_glossary_when_hard_subtitles_found(tmp_path):
    s = state(); observe(s)
    video = tmp_path / 'video.mp4'; video.write_bytes(b'video'); s['media'] = str(video)
    s.update(selected='asr_1', sources={'asr_1': {'kind': 'asr'}}, inspection={'cues': []})
    assert 'glossary' not in names(s)
    s.update(selected='ocr_2', sources={'ocr_2': {'kind': 'ocr'}})
    assert 'glossary' in names(s)


def test_existing_chinese_cannot_bypass_picture_check_or_ocr_comparison(tmp_path):
    s = state()
    video = tmp_path / 'video.mp4'; video.write_bytes(b'video'); s['media'] = str(video)
    s.update(captions=[{'lang': 'zh', 'kind': 'manual'}],
             target_caption_checks={'0': {'status': 'passed', 'sha256': 'target'}})
    assert 'deliver_target' not in names(s)
    observe(s)
    assert 'deliver_target' not in names(s)
    source = tmp_path / 'ocr.srt'; source.write_text('screen source')
    s['sources'] = {'ocr_1': {'kind': 'ocr', 'path': str(source)}}
    import hashlib
    review = {'source_kind': 'ocr', 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'target_sha256': 'target', 'checked_ids': [1], 'unmatched_ids': [], 'issues': []}
    s['target_caption_checks']['0']['semantic_reviews'] = [review]
    assert 'deliver_target' in names(s)
    source.write_text('edited screen source')
    assert 'deliver_target' not in names(s)  # Do not trust stale correspondence.


@pytest.mark.parametrize('scope', policy.SCOPED)
def test_explicit_recovery_scope_is_never_expanded(scope):
    s = state(); s['execution_policy'] = {scope: True}
    assert not policy.enabled(s)
    assert policy.block_reason(s, 'glossary') is None


def test_old_sessions_and_classic_workflow_keep_their_original_protocol():
    s = state(); s.pop('screen_source_policy_version')
    assert not policy.enabled(s) and 'asr' in names(s)
    s['screen_source_policy_version'] = 1; s['controller_version'] = 1
    assert not policy.enabled(s) and 'asr' in names(s)


def test_fresh_runtime_opts_in_but_saved_state_is_not_silently_migrated(tmp_path):
    session = AgentSession(id='screen-test', payload={'url': 'https://www.youtube.com/watch?v=abcdefghijk', 'source_language': 'korean'})
    app = SimpleNamespace(_agent_workspace=lambda _: tmp_path,
                          _ensure_under_root=lambda _: None, _agent_update_result=lambda *a: None)
    runtime = agent.Runtime(app, session)
    assert policy.enabled(runtime.state)
    runtime.state.pop('screen_source_policy_version'); runtime.save()
    assert not policy.enabled(agent.Runtime(app, session).state)


def test_execute_guard_cannot_be_bypassed_by_direct_dispatch(tmp_path):
    session = AgentSession(id='test', payload={'source_language': 'korean'})
    app = SimpleNamespace(_agent_workspace=lambda _: tmp_path,
                          _ensure_under_root=lambda _: None, _agent_update_result=lambda *a: None)
    runtime = agent.Runtime(app, session); runtime.state.update(state())
    with pytest.raises(agent.EvidenceRequired, match='尚未完成画面字幕核查'):
        runtime.execute('asr', {})
    observe(runtime.state)
    with pytest.raises(agent.EvidenceRequired, match='不能改走整片ASR'):
        runtime.execute('asr', {})


def test_regions_from_earlier_batches_remain_protected(tmp_path):
    session = AgentSession(id='test', payload={'source_language': 'korean'})
    app = SimpleNamespace(_agent_workspace=lambda _: tmp_path,
                          _ensure_under_root=lambda _: None, _agent_update_result=lambda *a: None)
    runtime = agent.Runtime(app, session); runtime.state.update(state())
    observe(runtime.state, True, regions=[[.1, .2, .8, .3]])
    observe(runtime.state, True, regions=[[.1, .65, .9, .8]])
    runtime.state['vision'] = {'subtitle_regions': [[.1, .65, .9, .8]]}
    params = runtime.ocr_params()
    assert params['ocr_crop_top_ratio'] < .2
    assert params['ocr_crop_bottom_ratio'] < .2


def test_samples_do_not_justify_cropping_off_edge_names_or_later_double_lines(tmp_path):
    session = AgentSession(id='test', payload={'source_language': 'korean'})
    app = SimpleNamespace(_agent_workspace=lambda _: tmp_path,
                          _ensure_under_root=lambda _: None, _agent_update_result=lambda *a: None)
    runtime = agent.Runtime(app, session); runtime.state.update(state())
    observe(runtime.state, True, regions=[[.38, .76, .61, .83]])
    params = runtime.ocr_params()
    assert params['ocr_crop_left_ratio'] == params['ocr_crop_right_ratio'] == 0
    assert params['ocr_crop_top_ratio'] <= .45
    assert params['ocr_crop_bottom_ratio'] == 0


def test_goal_exposes_screen_conditions_without_dictating_every_tool():
    s = state()
    checks = decisions.goal_status(s)['conditions']
    assert not checks['screen_source_checked'] and not checks['screen_primary_source_selected']
    observe(s); s.update(selected='ocr_1', sources={'ocr_1': {'kind': 'ocr'}})
    checks = decisions.goal_status(s)['conditions']
    assert checks['screen_source_checked'] and checks['screen_primary_source_selected']
