from pathlib import Path
import json

import pytest
import yaml

from video_translate.subtitle.delivery import export_bcc


def test_bcc_export_is_local_lossless_for_text_and_time_idempotent_and_non_destructive(tmp_path):
    source = tmp_path / 'zh.review.srt'
    source.write_text('1\n00:00:01,125 --> 00:00:03,750\n[脸红]你好\n第二行\n')
    original = source.read_bytes()
    target = export_bcc(source)
    assert target.name == 'zh.review.bcc'
    body = json.loads(target.read_text())['body']
    assert body == [{'from': 1.125, 'to': 3.75, 'location': 2, 'content': '[脸红]你好\n第二行'}]
    stamp = target.stat().st_mtime_ns
    assert export_bcc(source) == target and target.stat().st_mtime_ns == stamp
    target.write_text('DO NOT OVERWRITE')
    alternative = export_bcc(source)
    assert alternative != target and alternative.suffix == '.bcc'
    assert target.read_text() == 'DO NOT OVERWRITE'
    assert source.read_bytes() == original and export_bcc(source) == alternative
    assert not list(tmp_path.glob('.bcc-export-*'))


@pytest.fixture
def delivery(monkeypatch, tmp_path):
    from video_translate import web_agent as web
    project = tmp_path / 'downloads' / 'video'
    project.mkdir(parents=True)
    video = project / 'video.mp4'
    video.write_bytes(b'video')
    folder = tmp_path / 'tasks' / 'task-one'
    folder.mkdir(parents=True)
    source = folder / 'zh.review.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\n你好\n')
    config = tmp_path / 'configs' / 'app_settings.yaml'
    config.parent.mkdir()
    config.write_text('version: 1\ndelivery:\n  youtube_bcc: true\n')
    task = {'id': 'task-one', 'run_generation': 1, 'current_stage': 'done',
            'payload': {'source_language': 'korean', 'target_language': 'zh'},
            'stages': {'translate': {'status': 'done', 'translated_srt': str(source)}}}
    (folder / 'task.yaml').write_text(yaml.safe_dump(task))
    session = web.AgentSession(id='session', payload={'url': 'https://youtu.be/abcdefghijk', 'target_language': 'zh'},
                               result={'task_id': 'task-one', 'run_generation': 1, 'input_video': str(video)})
    monkeypatch.setattr(web, 'ROOT', tmp_path)
    monkeypatch.setattr(web, 'TASK_DIR', folder.parent)
    monkeypatch.setattr(web, 'DOWNLOAD_DIR', project.parent)
    monkeypatch.setattr(web, '_AGENT_SESSIONS', {session.id: session})
    monkeypatch.setattr(web, '_ensure_delivery_thumbnail', lambda *args: {})
    return web, session, source, project, config


@pytest.mark.parametrize('delivery_mode', ['translated', 'existing_target_subtitle'])
def test_completion_publishes_srt_and_bcc_to_assets_without_download_or_inference(delivery, delivery_mode):
    web, session, source, project, _ = delivery
    before = source.read_bytes()
    web._agent_done(session.id, {'translated_srt': str(source), 'delivery_mode': delivery_mode})
    assert session.status == 'done' and session.result['subtitle_saved'] and session.result['subtitle_library_linked']
    assert session.result['bcc_export']['status'] == 'done'
    task = web._read_task('task-one')
    assert task['stages']['translate']['translated_bcc'] == session.result['translated_bcc']
    from video_translate.project_subtitles import task_subtitle_links
    binding, files = task_subtitle_links(task, task_dir=source.parent, media_root=project.parent, validate_path=web._ensure_under_root)
    assert binding == str(project)
    assert {Path(f['path']).suffix for f in files} == {'.srt', '.bcc'}
    assert all(Path(f['path']).parent == project for f in files)
    assert source.read_bytes() == before
    sidecar = Path(session.result['translated_sidecar'])
    assert sidecar.parent == project and sidecar.read_bytes() == before
    assert Path(session.result['bcc_sidecar']).parent == project


def test_copy_keeps_old_files_and_original_task_versions(tmp_path):
    from video_translate.subtitle.delivery import copy_delivery_file
    source = tmp_path / 'source.srt'
    target = tmp_path / 'video.zh.srt'
    source.write_text('new content')
    target.write_text('user edited old content')
    copied = copy_delivery_file(source, target, version='session-one')
    assert copied.name == 'video.zh.run_session-one.srt'
    assert target.read_text() == 'user edited old content'
    assert source.read_text() == copied.read_text() == 'new content'
    stamp = copied.stat().st_mtime_ns
    assert copy_delivery_file(source, target, version='session-one') == copied
    assert copied.stat().st_mtime_ns == stamp


def test_repair_only_copies_existing_files_without_running_translation(delivery, monkeypatch):
    web, session, source, project, _ = delivery
    session.status = 'done'
    original = project.parent.parent / 'tasks' / 'task-one' / 'source.srt'
    original.write_text('1\n00:00:00,000 --> 00:00:01,000\n안녕\n')
    session.result.update(translated_srt=str(source), source_srt=str(original))
    monkeypatch.setattr(web, '_run_agent_async', lambda *_: pytest.fail('Must not resume Agent'))
    before = source.read_bytes(), original.read_bytes()
    result = web.repair_agent_delivery(session.id)
    assert Path(result['translated_sidecar']).parent == project
    assert Path(result['source_sidecar']).read_bytes() == original.read_bytes()
    assert Path(result['bcc_sidecar']).exists()
    assert session.status == 'done' and (source.read_bytes(), original.read_bytes()) == before


@pytest.mark.parametrize('origin,enabled', [('bilibili', True), ('youtube', False)])
def test_policy_is_youtube_only_and_opt_in(delivery, origin, enabled):
    web, session, source, _, config = delivery
    session.result['source_type'] = origin
    config.write_text(yaml.safe_dump({'delivery': {'youtube_bcc': enabled}}))
    web._agent_done(session.id, {'translated_srt': str(source)})
    assert session.status == 'done' and session.result['subtitle_saved']
    assert not session.result['translated_bcc'] and not list(source.parent.glob('*.bcc'))


def test_bcc_conversion_error_does_not_fail_the_translation(delivery, monkeypatch):
    web, session, source, _, _ = delivery
    from video_translate.subtitle import delivery as module
    monkeypatch.setattr(module, 'export_bcc', lambda *_: (_ for _ in ()).throw(OSError('unavailable')))
    web._agent_done(session.id, {'translated_srt': str(source), 'delivery_mode': 'existing_target_subtitle'})
    assert session.status == 'done' and source.exists()
    assert session.result['bcc_export']['status'] == 'failed'
    assert not session.result['translated_bcc']


def test_archived_task_is_never_reactivated_by_late_completion(delivery):
    web, session, source, _, _ = delivery
    session.status = 'archived'
    web._agent_done(session.id, {'translated_srt': str(source)})
    assert session.status == 'archived' and not list(source.parent.glob('*.bcc'))
