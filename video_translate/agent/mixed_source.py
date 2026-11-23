"""Lossless assembly of screen captions and a separately identified voice track."""
import hashlib
from pathlib import Path
from uuid import uuid4

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt,write_srt


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def format_screen_text(text: str) -> str:
    """Put brackets around the actual on-screen text, without doubling existing groups."""
    text=text.strip()
    if not text:return text
    pairs={'[':']','［':'］','【':'】'}
    brackets=[];normalized=list(text)
    for index,char in enumerate(text):
        if char in pairs:
            if not brackets:normalized[index]='['
            brackets.append(pairs[char])
        elif char in pairs.values():
            if not brackets or brackets.pop()!=char:break
            if not brackets:normalized[index]=']'
        elif not brackets and not char.isspace():break
    else:
        if not brackets:return ''.join(normalized)
    return f'[{text}]'


def format_screen_translation(text: str) -> str:
    # A model may echo a category label even when asked to translate only the content.
    value=text.strip()
    for label in ('【画面配字】','[画面配字]'):
        if value.startswith(label):
            value=value.removeprefix(label).lstrip()
            break
    return format_screen_text(value)


def screen_cue_ids(source: dict) -> set[int]:
    if source.get('kind')!='mixed':return set()
    return set(source.get('mixed_provenance',{}).get('screen_cue_ids',[]))


def format_translated_file(source: dict, translated: str) -> str:
    """Restore missing brackets only when the provenance still maps to the translated cues."""
    ids=screen_cue_ids(source)
    if not ids:return translated
    original=read_srt(Path(source['path']));path=Path(translated);target=read_srt(path)
    if not ids<={c.index for c in original} or len(original)!=len(target) or any(
        (a.index,a.start,a.end)!=(b.index,b.start,b.end) for a,b in zip(original,target)
    ):
        return translated  # Leave mismatches to the existing structure verification.
    replacements={}
    for cue in target:
        if cue.index in ids and cue.text.strip():
            formatted=format_screen_translation(cue.text)
            if not formatted:raise ValueError(f'第{cue.index}条画面文字只有类别标签，缺少译文内容')
            if formatted!=cue.text:replacements[cue.index]=formatted
    if not replacements:return translated
    from video_translate.agent.translation_review import replace_only_cue_text
    output=path.with_name(f'{path.stem}.screen_{uuid4().hex[:10]}.srt')
    with output.open('xb') as stream:
        stream.write(replace_only_cue_text(path.read_bytes(),replacements))
    return str(output)


def role_valid(state):
    review=state.get('screen_role_review',{})
    times=review.get('reviewed_frame_times',[]);duration=state.get('probe',{}).get('duration')
    return bool(review.get('screen_text_role')=='supplementary_only' and len(set(times))>=4
                and duration and (max(times)-min(times))/duration>=.6)


def assemble(state, screen_id, voice_id, root):
    screen=state['sources'][screen_id];voice=state['sources'][voice_id]
    if screen.get('kind')!='ocr' or voice.get('kind') not in {'captions','asr'}:
        raise ValueError('混合原文必须保留正式OCR配字，并使用另一条原声来源')
    if not role_valid(state):
        raise ValueError('未确认画面文字仅为独立配字，不能用音频替代对白字幕')
    a=read_srt(Path(screen['path']));b=read_srt(Path(voice['path']))
    if not a or not b:raise ValueError('混合来源不能使用空字幕')
    rows=[(c.start,c.end,0,c.index,format_screen_text(c.text)) for c in a]+[(c.start,c.end,1,c.index,c.text) for c in b]
    rows.sort(key=lambda row:(row[0],row[2],row[1],row[3]))
    folder=Path(root)/('mixed_source_'+uuid4().hex[:12]);folder.mkdir()
    output=folder/'source.mixed.srt'
    write_srt([SubtitleCue(i,start,end,text) for i,(start,end,_,_,text) in enumerate(rows,1)],output)
    return str(output),{'screen_source_id':screen_id,'voice_source_id':voice_id,
        'screen_sha256':sha(screen['path']),'voice_sha256':sha(voice['path']),'output_sha256':sha(output),
        'screen_cue_count':len(a),'voice_cue_count':len(b),'all_text_and_timing_retained':True,
        'screen_cue_ids':[i for i,row in enumerate(rows,1) if row[2]==0],
        'notice':'画面配字与语音字幕分别保留，可能同时显示；自动字幕仍可能有识别错误，不是已听音核准。'}


def valid(state, source):
    proof=source.get('mixed_provenance',{})
    try:
        a=state['sources'][proof['screen_source_id']];b=state['sources'][proof['voice_source_id']]
        return (role_valid(state)
                and a.get('kind')=='ocr' and b.get('kind') in {'captions','asr'}
                and proof.get('all_text_and_timing_retained') is True
                and sha(a['path'])==proof['screen_sha256'] and sha(b['path'])==proof['voice_sha256']
                and sha(source['path'])==proof['output_sha256'])
    except (KeyError,OSError,TypeError):return False
