"""Durable, scoped receipts: human translation clues must be reviewed before re-asking."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def guidance(state, cue_id):
    return [row for row in state.get('translation_guidance', []) if row.get('cue_id') == cue_id]


def signature(state, cue_id):
    source = state.get('sources', {}).get(state.get('selected'), {})
    payload = {'cue_id': cue_id, 'source_id': state.get('selected'), 'source_sha256': sha(source['path']),
               'target_language': state.get('target_language', 'zh'), 'guidance': guidance(state, cue_id)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def completed(state, cue_id=None):
    for record in reversed(state.get('human_reply_reviews', [])):
        if cue_id is not None and record['cue_id'] != cue_id:
            continue
        if (record['signature'] == signature(state, record['cue_id'])
                and record['output_sha256'] == sha(state['translated'])):
            return record
    return None


def queue(state, cue_id, review_limit=2):
    if type(cue_id) is not int or not guidance(state, cue_id):
        raise ValueError('没有这条字幕已提交的译文线索，不能伪造用户回复')
    issues = state.get('verification', {}).get('issues', [])
    if not any(row.get('id') == cue_id for row in issues):
        raise ValueError('线索对应的字幕不在当前疑点中')
    allowed = state.get('execution_policy', {}).get('allowed_repair_cue_ids')
    if allowed is not None and cue_id not in allowed:
        raise ValueError('该条字幕不在本轮授权的局部复核范围内')
    existing = completed(state, cue_id)
    if existing:
        return existing
    state['pending_reply_review'] = {'cue_id': cue_id, 'signature': signature(state, cue_id),
                                     'input_sha256': sha(state['translated'])}
    # Preserve total tool history. One new human reply grants at most one extra
    # attempt if the ordinary budget is exhausted; it never resets counters.
    count = state.get('counts', {}).get('review_translation', 0)
    allowances = state.setdefault('recovery_allowances', {})
    allowances['review_translation'] = max(allowances.get('review_translation', 0), count + 1 - review_limit, 0)
    state.pop('reply_review_hold', None)
    return None


def assert_pending(state):
    pending = state['pending_reply_review']
    if (pending['signature'] != signature(state, pending['cue_id'])
            or pending['input_sha256'] != sha(state['translated'])):
        raise ValueError('回复后的复核输入发生变化；未重用旧结论或修改其他字幕')
    return pending


def source_context(state, cue_id):
    """Reuse recorded observations, clearly separated from verified original text."""
    from video_translate.subtitle.srt import read_srt
    source=state['sources'][state['selected']]
    cue=next(c for c in read_srt(Path(source['path'])) if c.index==cue_id)
    audio=[]
    for observation in state.get('audio_observations', []):
        window=observation.get('window', [0,0])
        if min(window[1],cue.end)<=max(window[0],cue.start):continue
        audio.append({'kind':'local_asr_candidate','window':window,'cues':observation.get('cues', []),
                      'notice':'已有局部ASR候选，不是经过确认的听音真值。'})
    visual=[]
    for observation in state.get('screen_observations', []):
        times=[f['time_seconds'] for f in observation.get('frames', []) if cue.start<=f['time_seconds']<=cue.end]
        if times:visual.append({'kind':'recorded_visual_observation','time_seconds':times,'summary_zh':observation.get('summary_zh'),
                                'notice':'已有视觉模型摘要，不是本轮亲自看图，也不能据此补出未识别文字。'})
    return {'source_kind':source.get('kind'),'cue_id':cue_id,'start':cue.start,'end':cue.end,
            'local_asr_candidates':audio[-4:],'recorded_visual_observations':visual[-4:]}


def record(state, result):
    pending = state.get('pending_reply_review')
    if not pending:
        return None
    cue_id = pending['cue_id']
    if result.get('target_ids') != [cue_id] or result.get('translation_sha256') != pending['input_sha256']:
        raise ValueError('回复复核必须只处理收到线索的这一条字幕')
    row = next(row for row in result['decisions'] if row['id'] == cue_id)
    record = {**pending, 'outcome': 'unresolved' if cue_id in result.get('unresolved_ids', []) else row['action'],
              'guidance': guidance(state, cue_id), 'source': row['source'], 'before': row['before'], 'after': row['after'],
              'reason_zh': row['reason_zh'], 'independent_reason_zh': row['independent_review']['reason_zh'],
              'audit': result['audit'], 'output_sha256': result['output_sha256'], 'translated_srt': result['translated_srt']}
    state.setdefault('human_reply_reviews', []).append(record)
    state.pop('pending_reply_review', None)
    return record
