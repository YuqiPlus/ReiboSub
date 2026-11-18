"""Exact, actionable subtitle-pair diagnostics (not acoustic alignment)."""
from __future__ import annotations

import math

VERSION=2
LOCAL_TRANSLATION_KINDS={'translation_error','semantic_uncertain','empty_translation'}


def inspect_pairs(source,target,suppressed_ids=()):
    issues=[]
    suppressed_ids=set(suppressed_ids)
    empty_ids={a.index for a,b in zip(source,target) if not b.text.strip()}
    if suppressed_ids-empty_ids:issues.append({'kind':'invalid_suppression','reason_zh':'交付清理只能排除经过复核的真实空译文条目'})
    if not source:issues.append({'kind':'no_source','reason_zh':'原文字幕为空，不能验收'})
    if len(source)!=len(target):
        issues.append({'kind':'cue_count_mismatch','source_count':len(source),'target_count':len(target),
            'reason_zh':f'原文{len(source)}条、中文{len(target)}条，不能靠音频重对齐修复缺失或多出的条目'})
    for i,(a,b) in enumerate(zip(source,target)):
        common={'id':a.index,'source_quote':a.text,'translation_quote':b.text,
                'source_time':[a.start,a.end],'translation_time':[b.start,b.end]}
        if a.index!=b.index:issues.append({**common,'kind':'cue_id_mismatch','reason_zh':f'第{i+1}对字幕编号不一致：{a.index}/{b.index}'})
        if not all(math.isfinite(t) for t in (a.start,a.end)) or not 0<=a.start<a.end:
            issues.append({**common,'kind':'invalid_source_time','reason_zh':f'原文第{a.index}条时间区间无效'})
        if not all(math.isfinite(t) for t in (b.start,b.end)) or not 0<=b.start<b.end:
            issues.append({**common,'kind':'invalid_translation_time','reason_zh':f'中文第{a.index}条时间区间无效'})
        if (a.start,a.end)!=(b.start,b.end):
            issues.append({**common,'kind':'timing_mismatch','reason_zh':f'第{a.index}条中外文时间不同，先核查文件对应关系，不要盲目重听整片'})
        if not a.text.strip():issues.append({**common,'kind':'empty_source','reason_zh':f'原文第{a.index}条正文为空'})
        if not b.text.strip() and a.index not in suppressed_ids:
            issues.append({**common,'kind':'empty_translation','reason_zh':f'中文第{a.index}条正文为空；先结合相邻原句做局部译文复核，空条不是时轴错误',
                'recommended_tool':'review_translation',
                'context':[{'id':x.index,'source':x.text,'zh':y.text} for x,y in zip(source[max(0,i-2):i+3],target[max(0,i-2):i+3])]})
    if len({a.index for a in source})!=len(source):issues.append({'kind':'duplicate_source_id','reason_zh':'原文编号重复'})
    return {'schema_version':VERSION,'source_count':len(source),'target_count':len(target),'acceptable':not issues,
            'suppressed_ids':sorted(suppressed_ids),'delivery_cue_count':len(target)-len(suppressed_ids),
            'issue_count':len(issues),'issues':issues[:100],'truncated':len(issues)>100,
            'notice':'逐条检查正文和配对时间；相邻自动字幕重叠本身不等于中外文不匹配。'}
