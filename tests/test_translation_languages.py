import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_translate import web_agent as web
from video_translate.translation_languages import target_language_code, default_translation_target
from video_translate.agent import target_captions
from video_translate.agent.models import AgentSession
from video_translate.agent.verification import review_semantics
from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import write_srt
from video_translate.tools.generate_glossary import build_extraction_payload, write_glossary_yaml
from video_translate.tools.translate_subtitles import default_output_path
from video_translate.translate.volcengine import _build_payload

BILI = 'https://www.bilibili.com/video/BV1GJ411x7h7?p=2'
YT = 'https://www.youtube.com/watch?v=abcdefghijk'


@pytest.mark.parametrize(('value', 'code'), [('英语', 'en'), ('English', 'en'), ('日语', 'ja'), ('korean', 'ko'), ('简体中文', 'zh')])
def test_target_language_aliases_and_names(value, code):
    assert target_language_code(value) == code
    assert default_output_path(Path('source.srt'), value).name == f'source.{code}.srt'


def test_platform_defaults_only_apply_to_new_tasks(monkeypatch):
    monkeypatch.setattr(web, '_AGENT_SESSIONS', {})
    monkeypatch.setattr(web, '_run_agent_async', lambda *a: None)
    bili = web.start_agent_session({'url': BILI})
    assert bili.payload['source_language'] == 'chinese' and bili.payload['target_language'] == 'en'
    yt = web.start_agent_session({'url': YT, 'source_language': 'korean'})
    assert yt.payload['source_language'] == 'korean' and yt.payload['target_language'] == 'zh'
    chosen = web.start_agent_session({'url': BILI, 'source_language': 'japanese', 'target_language': 'ko'})
    assert chosen.payload['source_language'] == 'japanese' and chosen.payload['target_language'] == 'ko'
    old = web.start_agent_session({'url': BILI}, prepared_task={'id': 'old', 'run_generation': 1})
    assert old.payload['target_language'] == 'zh'


def test_chinese_ocr_is_not_final_english_delivery():
    session = AgentSession(id='test', payload={'source_language': 'chinese', 'target_language': 'en'})
    assert not web._agent_should_finish_ocr_without_translation(session)
    session.payload['target_language'] = 'zh'
    assert web._agent_should_finish_ocr_without_translation(session)


@pytest.mark.parametrize('code', ['zh', 'en', 'ja', 'ko'])
def test_translation_job_passes_target_and_uses_matching_filename(code, tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'ROOT', tmp_path)
    source = tmp_path / 'source.srt'; source.write_text('1\n00:00:00,000 --> 00:00:01,000\n你好\n')
    seen = []
    def run(job_id, args):
        seen.append(args)
        Path(args[args.index('--out')+1]).write_text(source.read_text())
    monkeypatch.setattr(web, '_run_command', run)
    monkeypatch.setattr(web, 'start_job', lambda name, fn: SimpleNamespace(result=fn('fake')))
    result = web.translate_subtitle_job({'source_srt': str(source), 'target_language': code, 'copy_sidecar': False}).result
    assert result['translated_srt'].endswith(f'.{code}.srt')
    assert '--target-language' in seen[0] and result['target_language'] == code


def test_chinese_glossary_cannot_be_silently_reused_for_english(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'ROOT', tmp_path)
    glossary = tmp_path / 'glossary.yaml'; glossary.write_text('characters: []\n')
    with pytest.raises(ValueError, match='目标语言'):
        web.translate_subtitle_job({'source_srt': str(tmp_path/'source.srt'), 'glossary': str(glossary), 'target_language': 'en'})


def test_glossary_and_translation_prompts_use_target_not_legacy_zh_key():
    payload = build_extraction_payload([{'id': 1, 'text': '小王来了'}], model='test', source_language='chinese', target_language='en')
    data = json.loads(payload['messages'][1]['content'])
    assert data['target_language'] == '英语'
    assert '英语' in data['output_schema']['characters'][0]['suggested_zh']
    assert '历史字段名' in ' '.join(data['rules'])
    payload = _build_payload([SubtitleCue(1, 0, 1, '你好？')], {}, 'test', '英语', [])
    assert '中文' in payload['messages'][0]['content'] and '英语' in payload['messages'][0]['content']
    assert '目标语言译文' in payload['messages'][1]['content']


def test_glossary_target_survives_review_save_and_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'ROOT', tmp_path)
    monkeypatch.setattr(web, '_glossary_candidate_profile', lambda *a: 'test-profile')
    monkeypatch.setattr(web, '_record_glossary_review_save', lambda *a: '')
    monkeypatch.setattr(web, 'JOB_DIR', tmp_path/'jobs')
    path = tmp_path / 'jobs' / 'sample' / 'glossary.yaml'
    write_glossary_yaml({'target_language': 'en', 'characters': [{'source': '小王', 'zh': '', 'reviewed': False}]}, path, source_srt=tmp_path/'source.srt')
    assert web.read_glossary_items({'path': str(path)})['target_language'] == 'en'
    web.write_glossary_items({'path': str(path), 'items': [{'section': 'characters', 'index': 0, 'zh': 'Xiao Wang', 'reviewed': True}]})
    result = web.read_glossary_items({'path': str(path)})
    assert result['target_language'] == 'en' and result['items'][0]['zh'] == 'Xiao Wang'


@pytest.mark.parametrize(('code', 'text'), [('en', 'Welcome to our program. Thank you for watching this episode.'), ('ko', '안녕하세요 오늘도 즐거운 하루 보내세요'), ('ja', 'こんにちは。今日はとても楽しいですね。')])
def test_existing_foreign_captions_do_not_require_chinese_characters(tmp_path, code, text):
    path = tmp_path/'caption.srt'; write_srt([SubtitleCue(1, 0, 20, text)], path)
    result = target_captions.assess(path, 20, target_language=code)
    assert result['status'] == 'passed' and result['target_language'] == code
    indexes = target_captions.candidate_indexes({'target_language': code, 'captions': [{'lang': 'zh-CN', 'kind': 'manual'}, {'lang': code+'-US', 'kind': 'manual'}]})
    assert indexes == [1]


def test_wrong_language_cannot_pass_english_caption_delivery(tmp_path):
    path = tmp_path/'caption.srt'; write_srt([SubtitleCue(1, 0, 20, '这是一段只有中文的字幕。'*8)], path)
    assert target_captions.assess(path, 20, target_language='en')['status'] == 'rejected'


def test_semantic_review_receives_target_language_on_schema_retry(tmp_path):
    calls=[]
    def model(root, name, task, instruction, data):
        calls.append(data)
        return {'checks': [{'id': 1, 'verdict': 'pass'}]} if len(calls)>1 else {}
    result=review_semantics(tmp_path,'review',[{'id':1,'source':'你好','zh':'Hello'}],model,target_language='en')
    assert not result['issues'] and len(calls)==2
    assert all(data['target_language']=='en' and data['target_language_name']=='英语' for data in calls)


def test_local_review_exports_english_without_renaming_it_zh(tmp_path):
    from video_translate.agent.translation_review import TranslationReview
    source=tmp_path/'source.srt';target=tmp_path/'en.srt'
    write_srt([SubtitleCue(1,0,1,'你好')],source);write_srt([SubtitleCue(1,0,1,'Hello')],target)
    review=TranslationReview(source,target,[],[1],tmp_path/'review',None,target_language='en')
    review.proposals={'1':{'id':1,'action':'keep','replacement':None,'reason_zh':'对应原意','evidence':[{'id':1,'quote':'你好'}]}}
    review.reviews={'1':{'id':1,'verdict':'approve','reason_zh':'对应原意','evidence':[{'id':1,'quote':'你好'}]}}
    result=review.export()
    assert Path(result['translated_srt']).name=='en.local_review.v1.srt' and result['target_language']=='en'


def test_reference_candidate_cache_is_separate_for_each_target(monkeypatch):
    monkeypatch.setattr(web,'load_llm_task_config',lambda *a:SimpleNamespace(provider_profile='demo',model='demo',base_url='https://example.com/v1'))
    assert web._glossary_candidate_profile('en') != web._glossary_candidate_profile('zh')
    assert web._glossary_candidate_profile('en') != web._glossary_candidate_profile('ja')


def test_english_sidecar_does_not_overwrite_chinese(tmp_path, monkeypatch):
    video=tmp_path/'video.mp4';video.write_bytes(b'video')
    original=tmp_path/'video.zh.srt';original.write_text('之前的中文字幕')
    source=tmp_path/'source.srt';source.write_text('中文原文')
    translated=tmp_path/'english.srt';translated.write_text('English subtitle')
    session=AgentSession(id='test',payload={'target_language':'en'})
    monkeypatch.setattr(web,'_agent_input_video_path',lambda s:video)
    monkeypatch.setattr(web,'_session_task_is_current',lambda s:True)
    result=web._copy_agent_translated_sidecar(session,str(source),str(translated))
    assert Path(result['translated_sidecar']).name=='video.en.srt'
    assert original.read_text()=='之前的中文字幕'
