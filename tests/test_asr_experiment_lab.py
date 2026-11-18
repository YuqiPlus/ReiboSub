import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_translate import asr_experiment_lab as lab
from video_translate import web_agent


@pytest.mark.parametrize('value,expected',[('01:30',90),('1:02:03.5',3723.5),(3,3),('12.5',12.5)])
def test_time_formats(value,expected):assert lab.seconds(value)==expected


@pytest.mark.parametrize('value',['',None,True,'NaN','inf',-1,'1:60','1:-1','1:2:3:4'])
def test_bad_times(value):
    with pytest.raises(ValueError):lab.seconds(value)


@pytest.mark.parametrize('raw', [[],[{'start':0,'end':4}],[{'start':0,'end':181}],
    [{'start':20,'end':30}],[{'start':0,'end':10},{'start':9,'end':15}],
    [{'start':0,'end':5}]*4])
def test_range_limits(raw):
    with pytest.raises(ValueError):lab.ranges(raw,25)


def test_out_of_order_ranges_sorted_and_nonoverlapping():
    assert lab.ranges([{'start':10,'end':15},{'start':0,'end':10}],20)==[
        {'start':0,'end':10},{'start':10,'end':15}]


def test_old_lab_dispatch_unchanged_and_experiment_is_explicit(monkeypatch):
    monkeypatch.setattr(lab,'launch',lambda p,a:'experiment')
    assert web_agent.asr_lab_job({'asr_version':'agent-experimental'})=='experiment'
    with pytest.raises(ValueError):web_agent.asr_lab_job({'asr_version':'2.0'})


@pytest.mark.parametrize('mode',['agent-experimental','autonomous-experimental'])
def test_launcher_stages_isolation_and_results(tmp_path,monkeypatch,mode):
    from video_translate import llm_config
    from scripts.asr3_benchmark import save_json
    media=tmp_path/'video.mp4';media.write_bytes(b'test')
    prefix=tmp_path/'envs/project/bin';prefix.mkdir(parents=True)
    for name in ('python','ffprobe'):(prefix/name).write_text('test')
    qwen=tmp_path/'envs/reibosub-asr3/bin/python';qwen.parent.mkdir(parents=True);qwen.write_text('test')
    for name in ('Qwen3-ASR-1.7B','Qwen3-ForcedAligner-0.6B'):
        p=tmp_path/'models/asr3'/name;p.mkdir(parents=True);(p/'config.json').write_text('{}')
    monkeypatch.setattr(llm_config,'load_llm_task_config',lambda task:SimpleNamespace(api_key='private',model='test',base_url='https://example.org'))
    monkeypatch.setattr(lab.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps({'format':{'duration':'90'}})))
    monkeypatch.delenv('REIBOSUB_QWEN_PYTHON',raising=False)
    calls=[];logs=[]
    def run(job,command,env_overrides):
        calls.append((command,env_overrides))
        if 'calibrate-timing' in command or any(str(c).endswith('/autonomous_subtitle_agent.py') for c in command):
            out=Path(command[command.index('--output')+1]);save_json(out/'human-review-questions.json',{'questions':[]})
            save_json(out/'timing-summary.json',{'samples':[{'total':3,'timing_needs_review':1}]})
            save_json(out/'autonomous-trace.json',{'quality':{'translation_issues':{}}})
    app=SimpleNamespace(ROOT=tmp_path,PYTHON=str(prefix/'python'),_nvidia_gpu_count=lambda:2,
        _resolve_project_path=lambda p:Path(p),_required_str=lambda p,k:p[k],_ensure_under_root=lambda p:None,
        _append_log=lambda j,s:logs.append(s),_run_command=run,start_job=lambda name,target:target('testjob'))
    result=lab.launch({'asr_version':mode,'input_video':str(media),'test_ranges':[{'start':10,'end':30}]},app)
    assert len(calls)==(6 if mode=='autonomous-experimental' else 7) and len(logs)==len(calls)+1
    assert calls[2][1]['CUDA_VISIBLE_DEVICES']=='0' and calls[3][1]['CUDA_VISIBLE_DEVICES']=='1'
    assert result['kind']=='asr_experiment_lab' and result['cue_count']==3
    assert result['source_srt'].endswith('agent.original-timeline.ko.srt')
    assert result['report_url'].startswith('/api/file?path=outputs/')
    assert media.read_bytes()==b'test' and not (tmp_path/'video.srt').exists()
    prefix_name='autonomous_lab_testjob' if mode=='autonomous-experimental' else 'lab_testjob'
    saved=(tmp_path/'outputs/asr3_experiments'/prefix_name/'lab-request.json').read_text()
    assert 'private' not in saved
    with pytest.raises(FileExistsError):lab.launch({'asr_version':mode,'input_video':str(media),'test_ranges':[{'start':10,'end':30}]},app)
