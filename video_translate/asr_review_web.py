"""Web submission bridge for the isolated multi-ASR experiments only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import quote


class ReviewConflict(ValueError):
    pass


def read_json(path: Path) -> dict:
    if path.stat().st_size > 4_000_000:
        raise ValueError('审核数据过大')
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict): raise ValueError('审核数据格式无效')
    return data


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    handle=tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.review-',delete=False)
    try:
        with handle:
            json.dump(data,handle,ensure_ascii=False,indent=2)
            handle.write('\n');handle.flush();os.fsync(handle.fileno())
        os.replace(handle.name,path)
    finally:
        Path(handle.name).unlink(missing_ok=True)


def normalize_answers(payload: dict, questions: dict) -> list[dict]:
    if payload.get('experiment_id')!=questions.get('experiment_id'):
        raise ReviewConflict('候选已更新，请刷新页面后重新确认')
    raw=payload.get('answers')
    if not isinstance(raw,list) or not 1<=len(raw)<=40: raise ValueError('请至少填写一条线索或确认音译')
    known={q['case_id']:q for q in questions['questions']}
    output=[];seen=set()
    for answer in raw:
        if not isinstance(answer,dict): raise ValueError('回答格式无效')
        case_id=answer.get('case_id')
        if case_id not in known or case_id in seen: raise ReviewConflict('回答包含重复、已处理或不存在的疑点')
        seen.add(case_id);question=known[case_id]
        mode=answer.get('mode')
        if mode not in {'hint','transliteration','unknown'}: raise ValueError('请选择线索或音译处理方式')
        hint=answer.get('hint','')
        if not isinstance(hint,str) or len(hint)>4000: raise ValueError('线索须为不超过4000字的文本')
        hint=hint.strip()
        if mode=='hint' and not hint: raise ValueError('请填写大概姓名、角色、作品等线索')
        selections=answer.get('selections') or []
        if not isinstance(selections,list) or len(selections)>12: raise ValueError('音译候选格式无效')
        slots={c['slot_zh'] for c in question['candidates']}
        selected=[];used=set()
        for choice in selections:
            if not isinstance(choice,dict): raise ValueError('音译候选格式无效')
            slot=choice.get('slot_zh')
            candidates=[c for c in question['candidates'] if c['slot_zh']==slot and c['korean']==choice.get('korean')]
            match=next((c for c in candidates if choice.get('chinese') in c['chinese_candidates']),None)
            if not match or slot in used: raise ReviewConflict('音译不在当前候选中，请重新选择')
            if choice.get('romanization') not in {None,match['romanization']}:
                raise ReviewConflict('英文转写已更新，请重新选择')
            used.add(slot)
            selected.append({'slot_zh':slot,'korean':match['korean'],'romanization':match['romanization'],
                             'chinese':choice['chinese']})
        if mode=='transliteration' and used!=slots: raise ValueError('请为本条中的每个人物分别确认音译')
        output.append({'case_id':case_id,'sample_id':question['sample_id'],'unit_id':question['unit_id'],
                       'mode':mode,'hint':hint,'selections':[] if mode=='unknown' else selected})
    return output


class ExperimentReviewService:
    def __init__(self, root: Path, *, python: str, start_job: Callable,
                 run_command: Callable, get_job: Callable):
        self.root=root.resolve()
        self.allowed=(self.root/'outputs/asr3_experiments').resolve()
        self.python=python;self.start_job=start_job;self.run_command=run_command;self.get_job=get_job
        self.lock=threading.RLock()

    def _base(self, raw: Any) -> Path:
        if not isinstance(raw,str) or not raw.strip() or len(raw)>2048: raise ValueError('缺少实验目录')
        path=Path(raw)
        base=(path if path.is_absolute() else self.root/path).resolve()
        if base==self.allowed or not base.is_relative_to(self.allowed): raise ValueError('仅允许提交ASR实验目录的人名审核')
        for name in ['manifest.json','human-review-questions.json','comparison.html']:
            file=base/name
            if not file.is_file() or not file.resolve().is_relative_to(base): raise ValueError('实验结果或人名候选不存在')
        return base

    def _relative(self,path: Path) -> str:
        return str(path.relative_to(self.root))

    def _report_url(self,base: Path) -> str:
        return '/api/file?path='+quote(self._relative(base/'comparison.html'),safe='')

    def _state(self,base: Path) -> dict:
        path=base/'.human-review-state.json'
        if not path.resolve().is_relative_to(base): raise ValueError('审核状态路径无效')
        if not path.exists(): return {'status':'idle','submissions':{}}
        return read_json(path)

    def _save(self,base: Path,state: dict) -> None:
        if not (base/'.human-review-state.json').resolve().is_relative_to(base): raise ValueError('审核状态路径无效')
        state['updated_at']=time.time()
        write_json_atomic(base/'.human-review-state.json',state)

    def _public(self,base: Path,state: dict) -> dict:
        result={k:state.get(k) for k in ['status','request_id','job_id','error','updated_at','answers']}
        result['experiment_path']=self._relative(base)
        if state.get('result'):
            result['result']=state['result']
        job=self.get_job(state['job_id']) if state.get('job_id') else None
        if job:
            snapshot=job.to_dict()
            result['logs']=snapshot['logs'][-12:]
        return result

    def _worker_busy(self,base: Path,state: dict) -> bool:
        if not state.get('request_id'): return False
        path=base/'human_reviews'/state['request_id']/'.human-run.lock'
        if not path.is_file() or not path.resolve().is_relative_to(base): return False
        try:
            import fcntl
            with path.open('r') as stream:
                try: fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError: return True
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        except ImportError: pass
        return False

    def _completed_result(self,base: Path,state: dict) -> dict | None:
        if not state.get('request_id'): return None
        child=base/'human_reviews'/state['request_id']
        paths=[child/'human-submission-result.json',child/'human-answers.json',child/'comparison.html']
        if any(not p.is_file() or not p.resolve().is_relative_to(base) for p in paths): return None
        try:
            completed=read_json(paths[0]);answers=read_json(paths[1])
        except (ValueError,OSError): return None
        digest=hashlib.sha256(json.dumps({'experiment_id':answers.get('experiment_id'),'answers':answers.get('answers')},
            ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if digest!=state.get('digest') or not isinstance(completed.get('experiment_id'),str): return None
        return {'report_url':self._report_url(child),'experiment_path':self._relative(child),
                'experiment_id':completed['experiment_id'],'remaining_questions':completed['remaining_questions'],
                'submitted_case_ids':[a['case_id'] for a in state['answers']]}

    def status(self,raw_path: str) -> dict:
        base=self._base(raw_path)
        with self.lock:
            state=self._state(base)
            completed=self._completed_result(base,state) if state.get('status')!='done' else None
            if completed:
                state.update(status='done',result=completed,error='');self._save(base,state)
            if state.get('status') in {'queued','running'}:
                job=self.get_job(state.get('job_id')) if state.get('job_id') else None
                if not job and self._worker_busy(base,state):
                    state.update(status='running');self._save(base,state)
                elif not job:
                    state.update(status='failed',error='服务重启后任务已中断，回答已保存，可重试')
                    self._save(base,state)
                elif job.status in {'failed','cancelled'}:
                    state.update(status=job.status,error='处理未完成，回答已保存，可重试')
                    self._save(base,state)
            return self._public(base,state)

    def submit(self,payload: dict) -> dict:
        base=self._base(payload.get('experiment_path'))
        request_id=payload.get('request_id')
        if not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id): raise ValueError('提交编号无效')
        questions=read_json(base/'human-review-questions.json')
        answers=normalize_answers(payload,questions)
        digest=hashlib.sha256(json.dumps({'experiment_id':questions['experiment_id'],'answers':answers},
            ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        with self.lock:
            state=self._state(base)
            completed=self._completed_result(base,state) if state.get('status')!='done' else None
            if completed:
                state.update(status='done',result=completed,error='');self._save(base,state)
            elif self._worker_busy(base,state):
                state.update(status='running');self._save(base,state)
            existing=state.get('submissions',{}).get(request_id)
            if existing and existing['digest']!=digest: raise ReviewConflict('同一提交编号不能携带不同回答')
            if state.get('status')=='done':
                if state.get('request_id')==request_id or state.get('digest')==digest:
                    return self._public(base,state)
                raise ReviewConflict('这份实验已有新结果，请打开更新后的页面再提交')
            if state.get('status') in {'queued','running'}:
                if state.get('digest')==digest: return self._public(base,state)
                raise ReviewConflict('当前提交仍在处理中，请等待完成后再提交')
            child=base/'human_reviews'/request_id
            if not child.resolve().is_relative_to(base): raise ValueError('结果目录无效')
            request_file=base/'.human-review-requests'/f'{request_id}.json'
            if not request_file.resolve().is_relative_to(base): raise ValueError('回答保存路径无效')
            request={'version':1,'experiment_id':questions['experiment_id'],'request_id':request_id,
                     'answers':answers,'source_experiment':self._relative(base)}
            write_json_atomic(request_file,request)
            submissions=state.get('submissions',{})
            submissions[request_id]={'digest':digest,'request_path':str(request_file.relative_to(base))}
            state={'status':'queued','request_id':request_id,'digest':digest,'answers':answers,
                   'submissions':submissions,'error':'','job_id':None}
            self._save(base,state)

            def run(job_id: str) -> dict:
                with self.lock:
                    current=self._state(base);current.update(status='running',job_id=job_id);self._save(base,current)
                try:
                    self.run_command(job_id,[self.python,'-u',str(self.root/'scripts/asr_review_agent.py'),
                        'human-continue','--seed-experiment',str(base),'--answers',str(request_file),'--output',str(child)])
                    result=self._completed_result(base,self._state(base))
                    if result is None: raise RuntimeError('新实验结果未完整生成或与本次回答不符')
                    with self.lock:
                        current=self._state(base);current.update(status='done',result=result,error='');self._save(base,current)
                    return result
                except Exception:
                    with self.lock:
                        current=self._state(base);current.update(status='failed',error='Agent处理未完成，回答已保存；可重试，不会改动旧字幕');self._save(base,current)
                    raise
            try:
                job=self.start_job('ASR实验：用户线索复核与翻译',run)
                # The worker uses this same lock, so it cannot finish before
                # the initial job id has been persisted.
                state['job_id']=job.id;self._save(base,state)
            except Exception:
                state.update(status='failed',error='未能启动处理，回答已保存');self._save(base,state);raise
            return self._public(base,state)
