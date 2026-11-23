"""Deterministic user-directed subtitle issue editing; no model or source edits."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from video_translate.subtitle.srt import read_srt
from video_translate.agent.translation_review import replace_only_cue_text


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(source, target, issues, *, resolutions=None, guidance=None, video=None, duration=None):
    original=read_srt(Path(source));translated=read_srt(Path(target))
    if not original or len(original)!=len(translated) or any((a.index,a.start,a.end)!=(b.index,b.start,b.end) for a,b in zip(original,translated)):
        raise ValueError('中外字幕编号或时间不一致，不能直接人工改写。')
    for path in (source,target):
        blocks=re.split(r'\n\s*\n',Path(path).read_text(encoding='utf-8-sig').strip())
        ids=[int(lines[0]) if len(lines)>=2 and lines[0].isdigit() and '-->' in lines[1] else None
             for block in blocks if (lines:=block.splitlines())]
        if ids!=list(range(1,len(original)+1)):raise ValueError('字幕编号不是连续且一致的原始编号，未自动重排或改写。')
    a={c.index:c for c in original};b={c.index:c for c in translated}
    if len(a)!=len(original):raise ValueError('字幕编号重复，不能人工改写。')
    rows=[];seen=set();unscoped=[];resolutions=resolutions or {}
    for issue in issues:
        cue_id=issue.get('id')
        if type(cue_id) is not int or cue_id not in a:
            unscoped.append(issue);continue
        if cue_id in seen:continue
        seen.add(cue_id);cue=a[cue_id]
        preferred=next((r['preferred_zh'] for r in reversed(guidance or []) if r.get('cue_id')==cue_id and r.get('preferred_zh')),None)
        row={'cue_id':cue_id,'source':cue.text,'translation':b[cue_id].text,'reason':issue.get('reason_zh',''),
             'resolved':str(cue_id) in resolutions,'preferred_translation':preferred,
             'skipped':resolutions.get(str(cue_id),{}).get('action')=='skip_translation',
             'manual_resolution':resolutions.get(str(cue_id))}
        if video:
            end=cue.end+2
            if isinstance(duration,(int,float)) and duration>cue.end:end=min(end,duration)
            row['media']={'video_path':str(video),'video_start':max(0,cue.start-2),'video_end':end}
        rows.append(row)
    rows.sort(key=lambda row:row['cue_id'])
    return {'source_sha256':sha(source),'translation_sha256':sha(target),'issues':rows,'unscoped_issues':unscoped,
            'remaining_ids':[r['cue_id'] for r in rows if not r['resolved']],
            'manual_reviewed_ids':[r['cue_id'] for r in rows if r['resolved'] and not r['skipped']],
            'skipped_ids':[r['cue_id'] for r in rows if r['skipped']]}


def write_manual_translation(source, target, review, cue_id, text, expected_sha, output):
    if not expected_sha or expected_sha!=sha(target) or expected_sha!=review['translation_sha256']:
        raise ValueError('字幕版本已变化，请重新加载后操作，未覆盖文件。')
    if review['source_sha256']!=sha(source):raise ValueError('原文版本已变化，未保存修改。')
    if type(cue_id) is not int or cue_id not in {r['cue_id'] for r in review['issues']}:
        raise ValueError('只能处理当前列出的字幕疑点。')
    data=replace_only_cue_text(Path(target).read_bytes(),{cue_id:text})
    with Path(output).open('xb') as stream:stream.write(data)
    old=read_srt(Path(target));new=read_srt(Path(output))
    if len(old)!=len(new) or any((a.index,a.start,a.end)!=(b.index,b.start,b.end) or b.text!=(text if a.index==cue_id else a.text) for a,b in zip(old,new)):
        raise ValueError('人工修改改变了其他条目或时间，未采用输出。')
    row=next(r for r in review['issues'] if r['cue_id']==cue_id)
    return {'cue_id':cue_id,'action':'user_specified_translation','source':row['source'],'before':row['translation'],'after':text,
            'input_sha256':expected_sha,'output_sha256':sha(output),'machine_verified':False}


def export_skips(source, target, review, folder, language):
    """Keep a complete working pair; omit only explicit user skips in new exports."""
    from video_translate.subtitle.delivery import copy_delivery_file
    from video_translate.utils.timecode import format_srt_time
    source,target,folder=Path(source),Path(target),Path(folder)
    a=read_srt(source);b=read_srt(target);skipped=set(review['skipped_ids'])
    if any(type(i) is not int for i in skipped) or not skipped<={r['cue_id'] for r in review['issues']}:
        raise ValueError('只能从输出中跳过用户明确选择的疑点条目。')
    kept=[i for i,c in enumerate(a) if c.index not in skipped]
    mapping=[{'original_id':a[i].index,'output_id':j} for j,i in enumerate(kept,1)]
    outputs={}
    for key,original,rows,name in [('source_srt',source,a,'source.draft.srt'),('translated_srt',target,b,f'{language}.draft.srt')]:
        destination=folder/name
        if not skipped:destination=copy_delivery_file(original,destination,version='manual-output')
        else:
            blocks=[f'{j}\n{format_srt_time(rows[i].start)} --> {format_srt_time(rows[i].end)}\n{rows[i].text}' for j,i in enumerate(kept,1)]
            body=('\n\n'.join(blocks)+'\n' if blocks else '').encode('utf-8')
            with destination.open('xb') as stream:stream.write(body)
        actual=read_srt(destination)
        if [(c.start,c.end,c.text) for c in actual]!=[(rows[i].start,rows[i].end,rows[i].text) for i in kept]:
            raise ValueError('跳过导出改变了其他字幕正文或时间，未采用输出。')
        outputs[key]=str(destination)
    return {**outputs,'original_source_srt':str(source),'index_map':mapping,'skipped_cue_ids':sorted(skipped),
            'delivery_cue_count':len(kept)}
