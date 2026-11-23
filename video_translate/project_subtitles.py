"""Read-only links from delivered subtitles to an exact media project.

Prefer video-directory delivery copies when available; task/run originals remain
in history. Indexing itself does no copying, title matching or inference.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

EXTENSIONS = {'.srt', '.vtt', '.ass', '.ssa', '.bcc'}
LANGUAGES = {'chinese': 'zh', 'korean': 'ko', 'japanese': 'ja', 'english': 'en',
             '简体中文': 'zh', '英语': 'en', '日语': 'ja', '韩语': 'ko'}


def _language(value, default='und'):
    text = str(value or '').lower().replace('_', '-')
    code = LANGUAGES.get(text, text.split('-')[0])
    return code if code in {'zh', 'en', 'ja', 'ko'} else default


def _time(value):
    try:
        result = float(value or 0)
        return result if math.isfinite(result) and result >= 0 else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def task_subtitle_links(task: dict, *, task_dir: Path, media_root: Path,
                        validate_path: Callable[[Path], None], archived=False) -> tuple[str, list[dict]]:
    """Use explicit project/video bindings only; never attach by similar titles."""
    stages = task.get('stages') if isinstance(task.get('stages'), dict) else {}
    stage = lambda name: stages.get(name) if isinstance(stages.get(name), dict) else {}
    translation = stage('translate')
    ordered = [translation, stage('probe'), stage('ocr'), stage('asr'), stage('glossary'), task]
    root = media_root.resolve()
    project = None
    for row in ordered:
        raw = row.get('project_dir')
        video = row.get('input_video') or row.get('input_media')
        try:
            if raw:
                candidate = Path(str(raw)).expanduser().resolve()
                # A downloaded video's parent and its project must agree. An
                # explicitly bound local upload may live outside the media root.
                if video:
                    media = Path(str(video)).expanduser().resolve()
                    if media.is_relative_to(root) and media.parent != candidate:
                        continue
            elif video:
                candidate = Path(str(video)).expanduser().resolve().parent
            else:
                continue
            if candidate == root or not candidate.is_relative_to(root) or not candidate.is_dir():
                continue
            validate_path(candidate)
            project = candidate
            break
        except (OSError, ValueError):
            continue
    if project is None:
        return '', []

    def artifact(rows, fields):
        for row in rows:
            for field in fields:
                raw = row.get(field)
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    path = Path(raw).expanduser().resolve()
                    if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                        continue
                    validate_path(path)
                    return path
                except (OSError, ValueError):
                    continue
        return None

    done_translation = translation.get('status') == 'done'
    source_rows = ([translation] if done_translation else []) + [row for row in (stage('ocr'), stage('asr')) if row.get('status') == 'done']
    source = artifact(source_rows, ('source_sidecar', 'source_srt'))
    target = artifact([translation], ('translated_sidecar', 'translated_srt', 'subtitle_path')) if done_translation else None
    bcc = artifact([translation], ('bcc_sidecar', 'translated_bcc')) if done_translation and translation.get('bcc_export', {}).get('status') == 'done' else None
    payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
    try:
        generation = max(1, int(task.get('run_generation') or 1))
    except (ValueError, TypeError, OverflowError):
        generation = 1
    common = {'task_id': str(task.get('id') or task_dir.name), 'run_generation': generation,
              'version_label': f'第 {generation} 轮', 'is_archived': bool(archived),
              'origin': 'agent_task', 'linked': True,
              'delivered_at': _time(translation.get('updated_at') or task.get('completed_at') or task.get('updated_at'))}
    if translation.get('completion_status') in {'completed_with_issues','completed_manually'}:
        manual=translation['completion_status']=='completed_manually'
        common.update(completion_status=translation['completion_status'],review_passed=False,
                      version_label=f'第 {generation} 轮 · '+('人工处理稿' if manual else '未核准草稿'),unresolved_cue_ids=translation.get('unresolved_cue_ids',[]))
    results = []
    for path, role, language in [(source, 'source', _language(payload.get('source_language'))),
                                  (target, 'translated', _language(payload.get('target_language'), 'zh')),
                                  (bcc, 'translated', _language(payload.get('target_language'), 'zh'))]:
        if path is None or (role == 'source' and path == target):
            continue
        results.append({**common, 'path': str(path), 'role': role, 'language': language})
    return str(project), results
