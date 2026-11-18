import copy
from pathlib import Path

import pytest

from video_translate.models import SubtitleCue
from video_translate.glossary_evidence import evidence_locations
from video_translate.agent.models import AgentSession
from video_translate.subtitle.srt import write_srt
from video_translate import web_agent as app


def cues():
    return [SubtitleCue(61,100,102,'앞 문장'),SubtitleCue(63,105,106,'철구!'),
            SubtitleCue(64,110,112,'도버키!'),SubtitleCue(65,114,116,'도버키가!'),SubtitleCue(68,120,122,'뒷 문장')]


def test_real_cue_ids_not_array_offsets_and_adjacent_context():
    result=evidence_locations(cues(),[63,65],'철구')
    assert [c['cue_id'] for c in result['evidence']]==[63,65]
    assert result['evidence'][0]['start']==105
    assert [c['cue_id'] for c in result['evidence'][0]['context']]==[61,63,64,65]
    assert result['evidence'][1]['literal_match'] is False


def test_missing_ids_only_fall_back_to_exact_occurrences_not_a_guessed_time():
    result=evidence_locations(cues(),[999],'도버키')
    assert result['missing_ids']==[999]
    assert [c['cue_id'] for c in result['evidence']]==[64,65]
    assert result['evidence'][0]['match_method']=='literal_match'
    assert not evidence_locations(cues(),[999],'未知名字')['evidence']


def test_invalid_and_duplicate_timestamps_do_not_produce_a_seek_location():
    rows=[SubtitleCue(1,-1,2,'name'),SubtitleCue(2,3,3,'name'),SubtitleCue(3,4,float('nan'),'name'),
          SubtitleCue(5,4,5,'name'),SubtitleCue(5,6,7,'name')]
    assert not evidence_locations(rows,[1,2,3,5],'name')['evidence']


def test_literal_occurrences_bounded_and_aliases_supported():
    rows=[SubtitleCue(i,i*2,i*2+1,'별명') for i in range(1,21)]
    result=evidence_locations(rows,[],'原名',['별명'])
    assert len(result['evidence'])==12 and result['total_occurrences']==20 and result['truncated']


@pytest.fixture
def glossary(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'ROOT',tmp_path)
    monkeypatch.setattr(app,'TASK_DIR',tmp_path/'tasks')
    monkeypatch.setattr(app,'_AGENT_SESSIONS',{})
    path=tmp_path/'review.yaml';source=tmp_path/'source.srt'
    # The glossary generator numbers parsed SRT cues sequentially. Keep real
    # positions 63/64/65 in the file, not just those labels on five blocks.
    examples={c.index:c for c in cues()}
    extra_times={62:103,66:117,67:119}
    write_srt([examples.get(i,SubtitleCue(i,extra_times.get(i,i),extra_times.get(i,i)+.5,f'context {i}'))
               for i in range(1,69)],source)
    path.write_text(f'# source_srt: {source}\ncharacters:\n- source: 철구\n  zh: ""\n  reviewed: false\n  note: "evidence_ids: 63 | confidence: 0.50"\n- source: 도버키\n  evidence_ids: [64, 65]\n  zh: ""\n  reviewed: false\n',encoding='utf-8')
    payload={'path':str(path),'section':'characters','index':0,'source':'철구'}
    return path,source,payload


def test_read_only_endpoint_resolves_matching_session_media_and_never_calls_a_model(glossary,tmp_path,monkeypatch):
    path,source,payload=glossary
    video=tmp_path/'项目 !'/'画面.mp4';video.parent.mkdir();video.write_bytes(b'video')
    session=AgentSession(id='pending',status='waiting',result={'glossary_path':str(path),'input_video':str(video)})
    app._AGENT_SESSIONS['pending']=session
    original=path.read_bytes();original_source=source.read_bytes();original_session=copy.deepcopy(session.to_dict())
    monkeypatch.setattr(app,'start_job',lambda *a,**k:pytest.fail('不能启动后台任务'))
    monkeypatch.setattr(app,'_blind_translate_glossary_context',lambda *a:pytest.fail('不能调用模型'))
    result=app.read_glossary_evidence(payload)
    assert result['media']['path']==str(video) and result['media']['kind']=='video'
    assert result['media']['url'].startswith('/api/file?path=') and '%21' in result['media']['url']
    assert result['evidence'][0]['cue_id']==63 and result['evidence'][0]['start']==105
    assert path.read_bytes()==original and source.read_bytes()==original_source
    assert session.to_dict()==original_session


def test_other_sessions_video_is_not_attached_to_this_glossary(glossary,tmp_path):
    path,_,payload=glossary
    video=tmp_path/'other'/'other.mp4';video.parent.mkdir();video.write_bytes(b'video')
    app._AGENT_SESSIONS['other']=AgentSession(id='other',result={'glossary_path':str(tmp_path/'different.yaml'),'input_video':str(video)})
    result=app.read_glossary_evidence(payload)
    assert result['media'] is None and result['evidence']
    assert '未找到关联' in result['message']


def test_standalone_project_source_can_use_its_existing_video(glossary,tmp_path):
    _,_,payload=glossary;video=tmp_path/'project.mp4';video.write_bytes(b'video')
    assert app.read_glossary_evidence(payload)['media']['path']==str(video)


def test_audio_only_review_has_same_bounded_source_timeline(glossary,tmp_path):
    path,_,payload=glossary;audio=tmp_path/'source.wav';audio.write_bytes(b'audio')
    app._AGENT_SESSIONS['audio']=AgentSession(id='audio',result={'glossary_path':str(path),'input_media':str(audio)})
    assert app.read_glossary_evidence(payload)['media']['kind']=='audio'


@pytest.mark.parametrize('change',[{'index':True},{'index':-1},{'section':'providers'},{'source':'另一个人'},
    {'media_path':'/etc/passwd'},{'cue_ids':[999]}])
def test_endpoint_does_not_accept_arbitrary_term_or_media_selection(glossary,change):
    _,_,payload=glossary
    with pytest.raises(ValueError):app.read_glossary_evidence({**payload,**change})


def test_glossary_source_and_symlinks_cannot_escape_workspace(glossary,tmp_path):
    path,_,payload=glossary
    path.write_text('# source_srt: /etc/passwd\ncharacters:\n- source: 철구\n')
    with pytest.raises(ValueError):app.read_glossary_evidence(payload)
    link=tmp_path/'outside.srt';link.symlink_to('/etc/passwd')
    path.write_text(f'# source_srt: {link}\ncharacters:\n- source: 철구\n')
    with pytest.raises(ValueError):app.read_glossary_evidence(payload)


def test_stale_glossary_without_a_source_reports_missing_not_fake_timestamps(glossary):
    path,_,payload=glossary;path.write_text('characters:\n- source: 철구\n')
    result=app.read_glossary_evidence(payload)
    assert not result['evidence'] and '没有关联' in result['message']


def test_evidence_ids_reject_boolean_fractional_and_negative_values():
    assert app._evidence_ids_from_item({'evidence_ids':[True,1.5,-1,'2',3]})==[2,3]
    assert app._evidence_ids_from_item({'note':'evidence_ids: -1, 1.5, 63, 64 | confidence: 0.5'})==[63,64]
