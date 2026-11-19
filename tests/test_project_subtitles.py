"""Task artifacts remain independent files while appearing in their media project."""
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from video_translate.project_subtitles import task_subtitle_links


@pytest.fixture
def sample(tmp_path):
    media = tmp_path / 'downloads'
    project = media / 'same title [BVtest P1]'
    project.mkdir(parents=True)
    video = project / 'clip.mp4'
    video.write_bytes(b'video')
    task_dir = tmp_path / 'tasks' / 'task1'
    task_dir.mkdir(parents=True)
    source, target = task_dir / 'source.review.srt', task_dir / 'en.review.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\n你好\n')
    target.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n')
    task = {'id': 'task1', 'run_generation': 2,
            'payload': {'source_language': 'chinese', 'target_language': 'en'},
            'stages': {'probe': {'input_video': str(video), 'project_dir': str(project)},
                       'ocr': {'status': 'done', 'source_srt': str(source)},
                       'translate': {'status': 'done', 'source_srt': str(source),
                                     'translated_srt': str(target), 'updated_at': 200}}}
    return media, project, task_dir, source, target, task


def links(sample, **kwargs):
    media, _, task_dir, _, _, task = sample
    return task_subtitle_links(task, task_dir=task_dir, media_root=media,
                               validate_path=lambda path: None, **kwargs)


def test_exact_binding_publishes_both_languages_without_copying(sample):
    _, project, _, source, target, task = sample
    before = deepcopy(task)
    binding, entries = links(sample)
    assert binding == str(project)
    assert [(row['path'], row['role'], row['language']) for row in entries] == [
        (str(source), 'source', 'zh'), (str(target), 'translated', 'en')]
    assert all(row['run_generation'] == 2 and row['linked'] for row in entries)
    assert list(project.iterdir()) == [project / 'clip.mp4']
    assert task == before


@pytest.mark.parametrize('status', ['running', 'pending', 'failed'])
def test_no_publication_of_unfinished_translation(sample, status):
    sample[-1]['stages']['translate']['status'] = status
    assert [row['role'] for row in links(sample)[1]] == ['source']


def test_missing_artifacts_and_unbound_tasks_are_ignored(sample):
    sample[4].unlink()
    assert [row['role'] for row in links(sample)[1]] == ['source']
    sample[-1]['stages'].pop('probe')
    assert links(sample) == ('', [])


def test_part_mismatch_is_not_attached_by_title(sample):
    media, _, _, _, _, task = sample
    other = media / 'same title [BVtest P2]'
    other.mkdir()
    task['stages']['probe']['project_dir'] = str(other)
    assert links(sample) == ('', [])


def test_validation_rejects_private_files_and_archives_keep_metadata(sample):
    media, project, task_dir, source, target, task = sample
    def validate(path):
        if path == target:
            raise ValueError('private artifact')
    binding, entries = task_subtitle_links(task, task_dir=task_dir, media_root=media,
                                           validate_path=validate, archived=True)
    assert binding == str(project)
    assert len(entries) == 1
    assert entries[0]['path'] == str(source) and entries[0]['is_archived']


def test_asset_index_links_current_and_archived_files_once(sample, monkeypatch):
    from video_translate import web_agent as app
    media, project, task_dir, source, target, task = sample
    tasks = task_dir.parent
    jobs = media.parent / 'jobs'
    jobs.mkdir()
    monkeypatch.setattr(app, 'ROOT', media.parent)
    monkeypatch.setattr(app, 'DOWNLOAD_DIR', media)
    monkeypatch.setattr(app, 'TASK_DIR', tasks)
    monkeypatch.setattr(app, 'JOB_DIR', jobs)
    task_path = task_dir / 'task.yaml'
    task_path.write_text(yaml.safe_dump(task))
    archive_dir = task_dir / 'runs' / 'generation_1'
    archive_dir.mkdir(parents=True)
    old_target = archive_dir / 'en.srt'
    old_target.write_bytes(target.read_bytes())
    old = deepcopy(task)
    old['run_generation'] = 1
    old['stages']['translate'].update(translated_srt=str(old_target), updated_at=100)
    (archive_dir / 'run.yaml').write_text(yaml.safe_dump(old))
    # A local file already linked from a task must not be counted twice.
    local_source = project / 'source.srt'
    local_source.write_bytes(source.read_bytes())
    task['stages']['translate']['source_srt'] = str(local_source)
    task_path.write_text(yaml.safe_dump(task))
    before = {p: p.read_bytes() for p in (source, target, old_target, local_source)}
    assets = app.list_local_assets(refresh=True)
    row = next(row for row in assets['projects'] if row['path'] == str(project))
    assert row['counts']['subtitles'] == 4  # current + old source/target, deduped paths
    assert len({entry['path'] for entry in row['subtitles']}) == 4
    assert {entry['path'] for entry in row['subtitles']} <= {entry['path'] for entry in assets['subtitles']}
    assert next(entry for entry in row['subtitles'] if entry['path'] == str(target))['language'] == 'en'
    assert next(entry for entry in row['subtitles'] if entry['path'] == str(old_target))['is_archived']
    assert next(entry for entry in row['subtitles'] if entry['path'] == str(local_source))['role'] == 'source'
    assert {p: p.read_bytes() for p in before} == before
    assert not (project / target.name).exists()
