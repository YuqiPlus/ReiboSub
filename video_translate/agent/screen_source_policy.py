"""Evidence gates for screen-first extraction, not a prescribed tool sequence.

Only newly created autonomous sessions opt in. Saved experiments and explicitly
scoped continuations keep their original source and approval boundaries.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

VERSION = 1
SCOPED = ('verification_only', 'targeted_translation_review',
          'continue_existing_translation', 'reuse_existing_source')


def enabled(state):
    return (state.get('screen_source_policy_version') == VERSION
            and state.get('controller_version', 1) >= 2
            and not any(state.get('execution_policy', {}).get(k) for k in SCOPED))


def observe(state, frames, vision):
    """Record actual analyzed frame evidence; sampling alone proves nothing."""
    state.setdefault('screen_observations', []).append({
        'frames': [{'time_seconds': f['time_seconds'], 'path': f['path']} for f in frames],
        'has_burned_subtitles': vision.get('has_burned_subtitles'),
        'subtitle_regions': vision.get('subtitle_regions', []),
        'summary_zh': vision.get('summary_zh', ''),
        'model': vision.get('model'),
    })


def assessment(state):
    observations = state.get('screen_observations', [])
    times = sorted({f['time_seconds'] for row in observations for f in row.get('frames', [])
                    if type(f.get('time_seconds')) in (int, float) and math.isfinite(f['time_seconds'])})
    duration = state.get('probe', {}).get('duration')
    spread = (times[-1] - times[0]) / duration if len(times) >= 2 and isinstance(duration, (int, float)) and duration > 0 else 0
    surveyed = len(times) >= 4 and spread >= .6
    present = any(row.get('has_burned_subtitles') is True for row in observations)
    negative_times = {f['time_seconds'] for row in observations
                      if row.get('has_burned_subtitles') is False and not row.get('subtitle_regions')
                      for f in row.get('frames', []) if f.get('time_seconds') in times}
    absent = (surveyed and len(negative_times) >= 4 and duration
              and (max(negative_times) - min(negative_times)) / duration >= .6)
    status = 'present' if present else 'not_seen_in_samples' if absent else 'unknown'
    return {'enabled': enabled(state), 'status': status, 'surveyed': surveyed,
            'analyzed_frame_count': len(times), 'sample_times': times,
            'sample_span_ratio': round(spread, 3), 'primary_source_required': 'ocr' if present else None,
            'notice': '有内嵌字幕时以画面原文为底本；无字幕结论仅适用于已抽查画面，不代表整片证明。'}


def protected_regions(state):
    return [box for row in state.get('screen_observations', []) for box in row.get('subtitle_regions', [])]


def source_allowed(state, source):
    check = assessment(state)
    if source.get('kind') not in {'ocr', 'captions', 'asr'}:
        return False
    if not check['surveyed'] or check['status'] == 'unknown':
        return False
    return check['status'] != 'present' or source.get('kind') == 'ocr'


def target_matches_screen(state):
    """A Chinese label cannot bypass OCR when hard subtitles are present."""
    from video_translate.agent.target_captions import route
    target = route(state)
    if not target or target.get('stage') != 'deliver':
        return False
    ocr_hashes = set()
    for source in state.get('sources', {}).values():
        if source.get('kind') == 'ocr' and Path(source.get('path', '')).is_file():
            ocr_hashes.add(hashlib.sha256(Path(source['path']).read_bytes()).hexdigest())
    return any(review.get('source_kind') == 'ocr' and review.get('source_sha256') in ocr_hashes
               and review.get('target_sha256') == report.get('sha256')
               and review.get('checked_ids') and not review.get('unmatched_ids') and not review.get('issues')
               for report in [state.get('target_caption_checks', {}).get(str(target['index']), {})]
               if report.get('status') == 'passed'
               for review in report.get('semantic_reviews', []))


def block_reason(state, name, args=None):
    if not enabled(state):
        return None
    args = args or {}
    check = assessment(state)
    final_source_tools = {'select_source', 'glossary', 'translate', 'finish', 'deliver_target'}
    if (not check['surveyed'] or check['status'] == 'unknown') and name in final_source_tools | {'asr', 'ocr_trial', 'ocr', 'refine_screen_ocr', 'finalize_screen_ocr'}:
        return '尚未完成画面字幕核查：请抽查至少4个跨越视频60%时长的时间点并分析画面，不能直接把音频或外挂字幕当作底本。'
    if check['status'] == 'present':
        if name == 'asr':
            return '已发现内嵌字幕，必须以OCR画面原文为底本；只能用局部音频工具核查缺口或疑句，不能改走整片ASR。'
        if name == 'select_source' and not source_allowed(state, state.get('sources', {}).get(args.get('source_id'), {})):
            return '已发现内嵌字幕，只能选择本次OCR生成的原文；外挂字幕和ASR只能作参考。'
        if name in {'glossary', 'translate', 'finish'} and not source_allowed(state, state.get('sources', {}).get(state.get('selected'), {})):
            return '当前底本不是内嵌字幕OCR结果，不能继续术语审核或正式翻译。'
        if name == 'deliver_target' and not target_matches_screen(state):
            return '现成中文字幕尚未与本次OCR画面原文对照，不能只凭中文标签交付。'
        if name == 'review_target' and state.get('sources', {}).get(args.get('source_id'), {}).get('kind') != 'ocr':
            return '有内嵌字幕时，现成中文必须对照OCR画面原文，而不是用另一份外挂或ASR自证。'
    return None


def filter_tools(state, allowed):
    if not enabled(state):
        return
    for name in list(allowed):
        # Argument-specific checks are repeated at dispatch. Listing this tool
        # only when a valid source exists prevents an impossible planner choice.
        if name in {'select_source', 'review_target'}:
            check = assessment(state)
            allowed[name] = allowed[name] and check['surveyed'] and check['status'] != 'unknown' and any(
                source_allowed(state, source) for source in state.get('sources', {}).values())
        elif block_reason(state, name):
            allowed[name] = False
