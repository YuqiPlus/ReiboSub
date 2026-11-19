"""Goal-first checks for existing target-language captions; no translation."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from video_translate.subtitle.srt import read_srt


def candidate_indexes(state):
    policy=state.get('execution_policy',{})
    if any(policy.get(key) for key in ('verification_only','targeted_translation_review','continue_existing_translation','reuse_existing_source')):
        return []  # Explicitly scoped recovery must not change its inputs/goal.
    if state.get('translated') or state.get('target_route_choice')=='translate_from_source':return []
    wanted=state.get('target_language','zh').lower().replace('_','-')
    def matches(language):
        language=language.lower().replace('_','-')
        return language.split('-')[0]=='zh' if wanted in {'zh','zho','chi','cn'} else language.split('-')[0]==wanted.split('-')[0]
    indexes=[i for i,c in enumerate(state.get('captions',[])) if c.get('kind')=='manual' and matches(c.get('lang',''))]
    # Prefer simplified/generic Chinese over traditional when the requested goal is zh.
    rank={'zh-hans':0,'zh-cn':1,'zh':2,'zh-sg':3,'zh-hant':4,'zh-tw':5,'zh-hk':6}
    return sorted(indexes,key=lambda i:(rank.get(state['captions'][i]['lang'].lower(),7),i))[:3]


def route(state):
    indexes=candidate_indexes(state);reports=state.get('target_caption_checks',{})
    accepted=[i for i in indexes if reports.get(str(i),{}).get('status')=='passed']
    if accepted:return {'stage':'deliver','index':accepted[0]}
    unchecked=[i for i in indexes if str(i) not in reports]
    if unchecked:return {'stage':'inspect','indexes':unchecked}
    ambiguous=[i for i in indexes if reports.get(str(i),{}).get('status')=='needs_review']
    if ambiguous:return {'stage':'question','index':ambiguous[0]}
    return None


def assess(path,duration=None,target_language='zh'):
    from video_translate.translation_languages import target_language_code
    target_language=target_language_code(target_language)
    path=Path(path)
    report={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'status':'rejected','issues':[]}
    try:rows=read_srt(path)
    except (ValueError,UnicodeError):
        return {**report,'issues':['字幕无法解析为有效SRT']}
    report['cue_count']=len(rows)
    if not rows:return {**report,'issues':['字幕为空']}
    if any(not math.isfinite(c.start) or not math.isfinite(c.end) or not 0<=c.start<c.end or not c.text.strip() for c in rows):
        return {**report,'issues':['存在无效时间轴或空字幕']}
    if any(b.start<a.start-.02 for a,b in zip(rows,rows[1:])):
        return {**report,'issues':['字幕起始时间顺序异常']}
    text='\n'.join(c.text for c in rows)
    letters=sum(c.isalpha() for c in text)
    chinese=sum('\u3400'<=c<='\u9fff' or '\U00020000'<=c<='\U0002fa1f' for c in text)
    ratio=chinese/max(1,letters)
    report.update(chinese_characters=chinese,chinese_letter_ratio=round(ratio,3),
        first_start=min(c.start for c in rows),last_end=max(c.end for c in rows),samples=[c.text for c in rows[:4]])
    report['target_language']=target_language
    script_counts={
        'zh':chinese,
        'en':sum(('a'<=c.lower()<='z') for c in text),
        'ko':sum('\uac00'<=c<='\ud7a3' or '\u1100'<=c<='\u11ff' for c in text),
        'ja':sum('\u3040'<=c<='\u30ff' for c in text),
    }
    target_chars=script_counts[target_language]
    report['target_script_characters']=target_chars
    if letters>40 and target_chars==0 and target_language!='ja':
        return {**report,'issues':['字幕正文未见所选目标语言的基本文字特征，不能直接交付']}
    warnings=[]
    if target_chars==0 or target_chars/max(1,letters)<.2:warnings.append('目标语言字符特征偏少，语言或双语格式需确认')
    if isinstance(duration,(float,int)) and math.isfinite(duration) and duration>0:
        report['video_duration']=duration
        report['subtitle_end_ratio']=round(report['last_end']/duration,3)
        if report['last_end']>duration+5:return {**report,'issues':['字幕时间明显超出视频时长']}
        if report['last_end']<duration-max(5,duration*.15):warnings.append('字幕结束较早，可能只覆盖部分视频；仅凭时间范围不能确认完整性')
        if report['first_start']>max(5,duration*.15):warnings.append('字幕开始较晚，需要确认前段是否有未覆盖对白')
    else:warnings.append('没有视频时长，暂不能检查首尾覆盖范围')
    return {**report,'status':'needs_review' if warnings else 'passed','issues':warnings,
        'notice':'只检查了语言字符、SRT结构和首尾时间范围，未逐句听音或保证翻译语义正确。'}
