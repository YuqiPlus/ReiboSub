"""Exact identities for readable task subtitles, separate from evidence IDs."""
from pathlib import Path

from video_translate.subtitle.srt import read_srt


def catalog(state):
    rows=[{'source_id':key,'kind':source.get('kind'),'language':source.get('language')}
          for key,source in state.get('sources',{}).items()]
    rows.extend({'source_id':f'target:{key}','kind':'existing_target_caption'} for key in state.get('target_caption_checks',{}))
    if state.get('translated'):
        rows.append({'source_id':'translated','kind':'current_translation','language':state.get('target_language','zh')})
    return rows


def normalize_id(state, key):
    if not isinstance(key,str):return key
    known={row['source_id'] for row in catalog(state)}
    if key in known:return key
    # Never reinterpret a real external caption or an arbitrary numeric ID.
    if state.get('translated') and key=='target:translated':return 'translated'
    if state.get('translated') and key=='target:1' and not state.get('target_caption_checks'):return 'translated'
    return key


def question_evidence(state, cue_id, source_id=None):
    source_id=source_id or state.get('selected')
    if not source_id and len(state.get('sources',{}))==1:source_id=next(iter(state['sources']))
    source=state.get('sources',{}).get(source_id)
    if not source:raise ValueError('请用 source_id 指明问题对应的已有原文源，不能混用不同来源的字幕编号')
    cue=next((c for c in read_srt(Path(source['path'])) if c.index==cue_id),None)
    if not cue:raise ValueError('问题对应的字幕编号不在指定原文源中')
    valid={source_id,source.get('evidence_source_id',source_id)}
    texts=[cue.text]
    texts.extend(row['text'] for row in state.get('evidence',{}).get(str(cue_id),[]) if row.get('source_id') in valid and row.get('text'))
    for clip in state.get('audio_observations',[]):
        for row in clip.get('cues',[]):
            if min(row.get('end',0),cue.end)>max(row.get('start',0),cue.start) and row.get('text'):
                texts.append(row['text'])
    return source_id,list(dict.fromkeys(texts))
