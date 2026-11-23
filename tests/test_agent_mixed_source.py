import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from video_translate.agent import vision
from video_translate.agent.mixed_source import assemble,format_screen_text,format_translated_file,valid
from video_translate.agent.screen_source_policy import source_allowed,observe,role_review_possible
from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt,write_srt


def test_mixed_source_retains_written_letters_and_spoken_captions_without_weakening_dialogue_priority(tmp_path):
    screen=tmp_path/'screen.srt';voice=tmp_path/'voice.srt'
    write_srt([SubtitleCue(1,10,20,'1000일 고마워요'),SubtitleCue(2,12,18,'[첫 줄][둘째 줄]')],screen)
    write_srt([SubtitleCue(1,0,12,'안녕하세요'),SubtitleCue(2,12,25,'[혜연] 감사해요')],voice)
    originals=screen.read_bytes(),voice.read_bytes()
    state={'controller_version':2,'screen_source_policy_version':1,'probe':{'duration':30},
           'frames':[{'path':str(tmp_path/f'{i}.jpg'),'time_seconds':t} for i,t in enumerate([0,10,20,29])],
           'sources':{'ocr_1':{'path':str(screen),'kind':'ocr'},'captions_2':{'path':str(voice),'kind':'captions'}},
           'screen_role_review':{'screen_text_role':'supplementary_only','reviewed_frame_times':[0,10,20,29]}}
    observe(state,state['frames'],{'has_burned_subtitles':True,'subtitle_regions':[[0,0,1,1]]})
    assert role_review_possible(state)
    path,proof=assemble(state,'ocr_1','captions_2',tmp_path)
    source={'path':path,'kind':'mixed','mixed_provenance':proof}
    cues=read_srt(Path(path))
    assert [(c.index,c.start,c.end,c.text) for c in cues]==[
        (1,0,12,'안녕하세요'),(2,10,20,'[1000일 고마워요]'),(3,12,18,'[첫 줄][둘째 줄]'),(4,12,25,'[혜연] 감사해요')]
    assert proof['screen_cue_ids']==[2,3]
    assert (screen.read_bytes(),voice.read_bytes())==originals
    assert valid(state,source) and source_allowed(state,source)
    assert not source_allowed(state,state['sources']['captions_2'])
    assert not source_allowed(state,state['sources']['ocr_1'])
    state['screen_role_review']['screen_text_role']='dialogue'
    assert not source_allowed(state,source) and source_allowed(state,state['sources']['ocr_1'])
    with pytest.raises(ValueError):assemble(state,'ocr_1','captions_2',tmp_path)


def test_screen_translation_does_not_guess_provenance_or_remap_misaligned_cues(tmp_path):
    source=tmp_path/'mixed.srt';target=tmp_path/'translated.srt'
    write_srt([SubtitleCue(1,0,2,'[제목]')],source)
    write_srt([SubtitleCue(1,0,1,'标题')],target)
    mixed={'kind':'mixed','path':str(source),'mixed_provenance':{'screen_cue_ids':[1]}}
    assert format_translated_file(mixed,str(target))==str(target)
    write_srt([SubtitleCue(1,0,2,'标题')],target)
    assert format_translated_file({**mixed,'mixed_provenance':{}},str(target))==str(target)
    assert format_translated_file({**mixed,'kind':'ocr'},str(target))==str(target)


@pytest.mark.parametrize(('original','expected'),[
    ('첫 줄\n둘째 줄','[첫 줄\n둘째 줄]'),('[첫 줄][둘째 줄]','[첫 줄][둘째 줄]'),
    ('［첫 줄］【둘째 줄】','[첫 줄][둘째 줄]'),('제목 [부제]','[제목 [부제]]'),
])
def test_screen_format_preserves_content_and_does_not_double_bracket(original,expected):
    assert format_screen_text(original)==expected
    assert format_screen_text(expected)==expected


def test_vision_role_review_requires_all_sampled_frames(monkeypatch,tmp_path):
    from video_translate import llm_config
    from video_translate.translate import volcengine
    monkeypatch.setattr(llm_config,'load_llm_task_config',
                        lambda *_:SimpleNamespace(api_key='test-key',model='test-model',base_url='https://example.invalid'))
    frames=[{'time_seconds':t,'image_data_url':'data:image/jpeg;base64,AA=='} for t in (0,10,20,29)]
    frame_ids=[0,1,2]
    def request(endpoint,key,payload,**kwargs):
        assert 'screen_text_role' in payload['messages'][0]['content'][0]['text']
        return json.dumps({'has_burned_subtitles':True,'summary_zh':'标题卡','subtitle_regions':[[0,0,1,1]],
                           'regions':[],'screen_text_role':'supplementary_only','role_frame_ids':frame_ids})
    monkeypatch.setattr(volcengine,'_request_translation',request)
    with pytest.raises(ValueError,match='完整帧依据'):
        vision.analyze(frames,tmp_path,review_roles=True)
    frame_ids.append(3)
    assert vision.analyze(frames,tmp_path,review_roles=True)['screen_text_role']=='supplementary_only'
