"""Final-text audio alignment for isolated ASR Agent revisions only."""
from __future__ import annotations

import argparse
import copy
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.asr3_benchmark import load_json, normalized, save_json


def groups(cues, duration):
    result = []
    for cue in cues:
        if (result and cue['end']-result[-1][0]['start'] <= 90
                and cue['start']-result[-1][-1]['end'] <= 3):
            result[-1].append(cue)
        else:
            result.append([cue])
    return [{'indexes':[c['index'] for c in rows], 'text':' '.join(c['text'] for c in rows),
             'start':max(0,rows[0]['start']-2), 'end':min(duration,rows[-1]['end']+3)} for rows in result]


def map_words(cues, words, bounds):
    """Map exact normalized characters back to existing cues, without rewriting."""
    clean = [w for w in words if normalized(w['text'])]
    if normalized(''.join(w['text'] for w in clean)) != normalized(''.join(c['text'] for c in cues)):
        raise ValueError('Alignment changed final transcript characters')
    positions=[]; cursor=0
    for w in clean:
        a,b=w['start'],w['end']
        if (not math.isfinite(a) or not math.isfinite(b) or a>b
                or a<bounds[0]-.001 or b>bounds[1]+.001):
            raise ValueError('Invalid alignment timestamp')
        length=len(normalized(w['text']));positions.append((cursor,cursor+length,w));cursor+=length
    output={};cursor=0
    for cue in cues:
        end=cursor+len(normalized(cue['text']))
        selected=[(a,b,w) for a,b,w in positions if a<end and b>cursor]
        reason=None
        if not selected or selected[0][0]!=cursor or selected[-1][1]!=end:
            reason='token_crossed_cue_boundary'
        elif selected[0][2]['end']<=selected[0][2]['start'] or selected[-1][2]['end']<=selected[-1][2]['start']:
            reason='unresolved_edge_word'
        elif any(selected[i][2]['start']<selected[i-1][2]['end']-.001 for i in range(1,len(selected))):
            reason='nonmonotonic_words'
        if reason:
            output[cue['index']]={'accepted':False,'reason':reason}
        else:
            a,b=selected[0][2]['start'],selected[-1][2]['end']
            if max(abs(a-cue['start']),abs(b-cue['end']))>3:
                output[cue['index']]={'accepted':False,'reason':'shift_exceeds_three_seconds'}
            else:
                zeros=sum(w['end']<=w['start'] for _,_,w in selected)
                output[cue['index']]={'accepted':True,'start':a,'end':b,'reason':'final_text_audio_alignment',
                                     'interior_zero_units':zeros,'needs_review':bool(zeros)}
        cursor=end
    return output


def settle(cues, proposals, duration):
    """Rollback conflicting proposals rather than cutting off someone's speech."""
    chosen=copy.deepcopy(proposals)
    for _ in range(len(cues)+1):
        times=[(chosen[c['index']]['start'],chosen[c['index']]['end'])
               if chosen[c['index']]['accepted'] else (c['start'],c['end']) for c in cues]
        conflicts=set()
        for i in range(1,len(cues)):
            if times[i][0]<times[i-1][1]-.001:
                for j in (i-1,i):
                    if chosen[cues[j]['index']]['accepted']:conflicts.add(cues[j]['index'])
        if not conflicts:break
        for index in conflicts:chosen[index]={'accepted':False,'reason':'conflicting_neighbor_alignment'}
    output=[];audit=[]
    for i,cue in enumerate(cues):
        p=chosen[cue['index']];new=dict(cue)
        if p['accepted']:
            new['start']=round(p['start'],3)
            # Small release tail, never through the next cue or a long pause.
            next_start=(chosen[cues[i+1]['index']]['start'] if chosen[cues[i+1]['index']]['accepted']
                        else cues[i+1]['start']) if i+1<len(cues) else duration
            new['end']=round(min(duration,p['end']+.12,next_start),3)
        if not 0<=new['start']<new['end']<=duration:raise ValueError('Invalid calibrated cue')
        output.append(new)
        audit.append({'index':cue['index'],'text':cue['text'],'before':[cue['start'],cue['end']],
                      'after':[new['start'],new['end']],**p,
                      'needs_review':not p['accepted'] or p.get('needs_review',False)})
    return output,audit


def worker(output):
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ForcedAligner
    manifest=load_json(output/'manifest.json')
    for s in manifest['samples']:
        if hashlib.sha256(Path(s['audio']).read_bytes()).hexdigest()!=s['audio_sha256']:
            raise ValueError('Frozen audio checksum mismatch')
    torch.set_num_threads(4)
    model=Qwen3ForcedAligner.from_pretrained(str(ROOT/'models/asr3/Qwen3-ForcedAligner-0.6B'),
                dtype=torch.float32,device_map='cuda:0',attn_implementation='sdpa')
    # Use the model's native Korean morpheme tokenizer. Treating whole Korean
    # whitespace words as tokens can collapse their spoken endings.
    for sample in manifest['samples']:
        folder=output/sample['id'];dest=folder/'timing-alignment.json'
        if dest.exists():continue
        audio,sr=sf.read(sample['audio'],dtype='float32')
        cues=load_json(folder/'agent/source.json')['cues'];lookup={c['index']:c for c in cues}
        proposals={};attempts=[]
        def align(plan):
            a,b=round(plan['start']*sr),round(plan['end']*sr)
            with torch.inference_mode():
                result=model.align(audio=(audio[a:b],sr),text=plan['text'],language='Korean')[0]
            actual_end=b/sr
            words=[{'text':w.text,'start':w.start_time+a/sr,'end':w.end_time+a/sr} for w in result]
            # The aligner's timestamp grid may round at most one 80ms step
            # beyond the final sample. Never accept a larger out-of-audio drift.
            for word in words:
                for key in ('start','end'):
                    if actual_end<word[key]<=actual_end+.08:word[key]=actual_end
            return words
        for plan in groups(cues,sample['duration']):
            words=align(plan);rows=[lookup[i] for i in plan['indexes']]
            try: mapped=map_words(rows,words,(plan['start'],plan['end']))
            except ValueError as exc: mapped={c['index']:{'accepted':False,'reason':str(exc)} for c in rows}
            proposals.update(mapped);attempts.append({'plan':plan,'words':words,'result':mapped})
        retry_budget=8
        for cue_position,cue in enumerate(cues):
            p=proposals[cue['index']]
            if p['accepted'] and not p.get('needs_review'):continue
            if retry_budget<=0:break
            retry_budget-=1
            context=cues[max(0,cue_position-1):cue_position+2]
            plan={'start':max(0,context[0]['start']-1),'end':min(sample['duration'],context[-1]['end']+2),
                  'text':' '.join(c['text'] for c in context),'indexes':[c['index'] for c in context]}
            if plan['end']-plan['start']>24:continue
            words=align(plan)
            try:mapped=map_words(context,words,(plan['start'],plan['end']))
            except ValueError as exc:mapped={cue['index']:{'accepted':False,'reason':str(exc)}}
            if mapped[cue['index']]['accepted']:proposals[cue['index']]=mapped[cue['index']]
            attempts.append({'retry':True,'plan':plan,'words':words,'result':mapped})
        revised,audit=settle(cues,proposals,sample['duration'])
        save_json(dest,{'audio_sha256':sample['audio_sha256'],'source_sha256':hashlib.sha256(
            (folder/'agent/source.json').read_bytes()).hexdigest(),'attempts':attempts,'cues':revised,'audit':audit,
            'policy':{'text_changed':False,'max_extra_local_retries':8,'zero_edges_interpolated':False,
                      'tokenization':'native_korean_morphemes'}})
        print('timing_aligned',sample['id'],len(cues),'cues;',sum(r['needs_review'] for r in audit),'flagged',flush=True)


def finish(output):
    from video_translate.models import SubtitleCue
    from video_translate.subtitle.srt import write_srt
    from scripts.asr_review_agent import report
    manifest=load_json(output/'manifest.json');questions=load_json(output/'human-review-questions.json')
    summary=[]
    for sample in manifest['samples']:
        folder=output/sample['id'];result=load_json(folder/'timing-alignment.json')
        source=load_json(folder/'agent/source.json');zh=load_json(folder/'agent/translated.json')
        if hashlib.sha256((folder/'agent/source.json').read_bytes()).hexdigest()!=result['source_sha256']:
            raise ValueError('Transcript changed after alignment')
        if [(c['index'],c['start'],c['end']) for c in source['cues']]!=[(c['index'],c['start'],c['end']) for c in zh['cues']]:
            raise ValueError('Original translation timeline mismatch')
        if [c['text'] for c in source['cues']]!=[c['text'] for c in result['cues']]:raise ValueError('Alignment rewrote text')
        for old,new,translated in zip(source['cues'],result['cues'],zh['cues']):
            translated.update(start=new['start'],end=new['end'])
        save_json(folder/'agent/source.json',{'cues':result['cues']})
        save_json(folder/'agent/translated.json',zh)
        for rows,name in [(result['cues'],'source.ko.srt'),(zh['cues'],'translated.zh.srt')]:
            write_srt([SubtitleCue(**c) for c in rows],folder/'agent'/name)
        audit=load_json(folder/'audit.json');exported=[r for r in audit['decisions'] if r['after']]
        if len(exported)!=len(result['cues']):raise ValueError('Cue/audit mapping mismatch')
        for row,cue,timing in zip(exported,result['cues'],result['audit']):
            if row['after']!=cue['text']:raise ValueError('Cue/audit text mismatch')
            row.update(start=cue['start'],end=cue['end'],timing_review=timing)
            for q in questions['questions']:
                if q['sample_id']==sample['id'] and q['unit_id']==row['id']:
                    q.update(start=cue['start'],end=cue['end'],original_time=sample['start']+cue['start'])
        save_json(folder/'audit.json',audit)
        summary.append({'sample_id':sample['id'],'total':len(result['cues']),
                        'aligned':sum(r['accepted'] for r in result['audit']),
                        'timing_needs_review':sum(r['needs_review'] for r in result['audit'])})
        render_path=output/'human-name-renderings.json'
        if render_path.exists():
            renderings=load_json(render_path)
            for entry in renderings.get('renderings',[]):
                if entry.get('sample_id')!=sample['id']:continue
                match=next((r for r in result['audit'] if abs(r['before'][0]-entry.get('cue_start',-99))<.001),None)
                if match:entry['cue_start']=match['after'][0]
            save_json(render_path,renderings)
    save_json(output/'human-review-questions.json',questions)
    save_json(output/'timing-summary.json',{'samples':summary,'ground_truth_verified':False})
    report(output)


def align_current(out, qwen_python=None):
    """Finish an unpublished experimental revision before it becomes available."""
    out=Path(out).resolve()
    python=qwen_python or Path(os.environ.get('REIBOSUB_QWEN_PYTHON',
                                              str(Path(sys.prefix).parent/'reibosub-asr3/bin/python')))
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
         'OMP_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4'}
    with (out/'timing-worker.log').open('a') as log:
        subprocess.run([str(python),'-u',str(Path(__file__).resolve()),'worker','--output',str(out)],
                       env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    finish(out)


def calibrate(args):
    seed=args.seed_experiment.resolve();out=args.output.resolve()
    if out.exists() or seed.is_relative_to(out):raise ValueError('Timing calibration requires a new output directory')
    manifest=load_json(seed/'manifest.json')
    for s in manifest['samples']:
        if hashlib.sha256(Path(s['audio']).read_bytes()).hexdigest()!=s['audio_sha256']:raise ValueError('Frozen audio changed')
    out.mkdir(parents=True)
    for name in ['human-review-questions.json','protected-names.json','name-context-review.json',
                 'name-context-references.json','human-name-renderings.json']:
        if (seed/name).exists():shutil.copy2(seed/name,out/name)
    save_json(out/'manifest.json',{**manifest,'policy':{**manifest.get('policy',{}),'timing_parent':str(seed),
        'final_text_audio_alignment':True,'production_asr_changed':False,'translation_text_reused':True}})
    for s in manifest['samples']:
        folder=out/s['id'];folder.mkdir()
        for name in ['evidence.json','audit.json','pending-review-analysis.json']:
            if (seed/s['id']/name).exists():shutil.copy2(seed/s['id']/name,folder/name)
        for name in ['agent','asr22','qwen','retries']:shutil.copytree(seed/s['id']/name,folder/name)
    align_current(out,args.qwen_python)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['worker']);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();worker(args.output.resolve())
