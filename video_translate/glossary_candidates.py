"""Persist optional context translations without touching human glossary fields."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import threading

from video_translate.asr_review_web import write_json_atomic

_LOCK=threading.Lock()
_PREPARE_LOCKS={}


def cache_path(path):return Path(path).with_name(Path(path).name+'.candidates.json')


def key(context,profile):
    return hashlib.sha256(json.dumps([1,profile,context],ensure_ascii=False).encode()).hexdigest()


def load(path):
    try:
        value=json.loads(cache_path(path).read_text(encoding='utf-8'))
        if isinstance(value,dict) and value.get('version')==1 and isinstance(value.get('entries'),dict):return value
    except (OSError,ValueError):pass
    return {'version':1,'entries':{}}


def cached(path,contexts,profile):
    entries=load(path)['entries'];values={};errors={};pending=[]
    contexts=list(dict.fromkeys(contexts))
    for context in contexts:
        row=entries.get(key(context,profile),{})
        if row.get('status')=='ready' and isinstance(row.get('candidate'),str) and row['candidate'].strip():values[context]=row['candidate']
        elif row.get('status')=='failed':errors[context]='原句参考译文暂不可用；仍可直接填写和确认译名。'
        else:pending.append(context)
    return {'values':values,'errors':errors,'pending_contexts':pending,
        'summary':{'state':'preparing' if pending else 'partial' if errors else 'ready','total':len(contexts),
            'ready':len(values),'failed':len(errors),'pending':len(pending)}}


def prepare(path,contexts,profile,translate,*,retry_failed=False,progress=None):
    identity=str(cache_path(path).resolve())
    with _LOCK:lock=_PREPARE_LOCKS.setdefault(identity,threading.Lock())
    with lock:
        current=cached(path,contexts,profile)
        pending=[*current['pending_contexts'],*(current['errors'] if retry_failed else [])]
        data=load(path)
        if not pending:return current['summary']
        for context in pending:data['entries'][key(context,profile)]={'status':'pending'}
        write_json_atomic(cache_path(path),data)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(translate,context):context for context in pending}
            for i,future in enumerate(as_completed(futures),start=1):
                context=futures[future]
                try:
                    candidate=future.result()
                    if not isinstance(candidate,str) or not candidate.strip():raise ValueError('empty candidate')
                    record={'status':'ready','candidate':candidate.strip()[:8000]}
                except Exception as exc:
                    # No provider URLs, keys or raw error bodies in public caches.
                    record={'status':'failed','error_kind':type(exc).__name__}
                data['entries'][key(context,profile)]=record
                write_json_atomic(cache_path(path),data)
                if progress:progress(i,len(pending))
        return cached(path,contexts,profile)['summary']
