import pytest
from video_translate.agent.target_captions import assess,candidate_indexes,route
from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import write_srt


def test_only_manual_target_tracks_have_priority_not_youtube_auto_translations():
    s={'captions':[{'lang':'ko','kind':'manual'},{'lang':'zh-TW','kind':'manual'},
        {'lang':'zh-Hans','kind':'auto'},{'lang':'zh','kind':'manual'},{'lang':'zh-Hans','kind':'manual'}]}
    assert candidate_indexes(s)==[4,3,1]
    assert route(s)=={'stage':'inspect','indexes':[4,3,1]}


@pytest.mark.parametrize('policy',['verification_only','targeted_translation_review','continue_existing_translation','reuse_existing_source'])
def test_scoped_recovery_cannot_switch_to_another_subtitle(policy):
    assert route({'execution_policy':{policy:True},'captions':[{'lang':'zh','kind':'manual'}]}) is None


def test_auto_chinese_is_not_a_reason_to_skip_human_glossary():
    assert route({'captions':[{'lang':'zh','kind':'auto'},{'lang':'ko','kind':'manual'}]}) is None


def test_wrong_language_or_empty_target_is_rejected_and_other_tracks_are_tried(tmp_path):
    path=tmp_path/'caption.srt';write_srt([SubtitleCue(1,0,98,'한국어자막입니다'*30)],path)
    assert assess(path,100)['status']=='rejected'
    path.write_text('')
    assert assess(path,100)['status']=='rejected'
    s={'captions':[{'lang':'zh','kind':'manual'},{'lang':'zh-TW','kind':'manual'}],
        'target_caption_checks':{'0':{'status':'rejected'}}}
    assert route(s)=={'stage':'inspect','indexes':[1]}
    s['target_caption_checks']['1']={'status':'rejected'}
    assert route(s) is None


def test_readable_chinese_reports_time_span_without_claiming_semantic_certainty(tmp_path):
    path=tmp_path/'caption.srt';write_srt([SubtitleCue(1,0,98,'你好，今天我们来做一个测试。')],path)
    result=assess(path,100)
    assert result['status']=='passed' and result['subtitle_end_ratio']==.98
    assert '未逐句听音' in result['notice']
    assert assess(path,200)['status']=='needs_review'
    assert assess(path,50)['status']=='rejected'


def test_short_video_still_flags_an_obviously_partial_track(tmp_path):
    path=tmp_path/'short.srt';write_srt([SubtitleCue(1,0,2,'你好')],path)
    assert assess(path,20)['status']=='needs_review'
