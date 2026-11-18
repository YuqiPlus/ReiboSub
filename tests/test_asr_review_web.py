import json
from pathlib import Path

import pytest

from video_translate.asr_review_web import (
    ExperimentReviewService, ReviewConflict, normalize_answers, write_json_atomic,
)
from video_translate.jobs import Job


@pytest.fixture
def setup_review(tmp_path):
    root=tmp_path
    base=root/'outputs/asr3_experiments/demo'
    q={'case_id':'clip:w1','sample_id':'clip','unit_id':'w1','candidates':[
        {'slot_zh':'人物','korean':'김서환','romanization':'Kim Seo-hwan','chinese_candidates':['金瑞焕','金叙焕']}]}
    artifact={'experiment_id':'fingerprint','questions':[q]}
    write_json_atomic(base/'manifest.json',{'version':1})
    write_json_atomic(base/'human-review-questions.json',artifact)
    (base/'comparison.html').write_text('<html>original</html>')
    jobs={};tasks={};calls=[]
    def start(name,target):
        job=Job(id=f'job{len(jobs)+1}',name=name);jobs[job.id]=job;tasks[job.id]=target;return job
    def run(job_id,args):
        calls.append(args)
        output=Path(args[args.index('--output')+1]);output.mkdir(parents=True,exist_ok=True)
        write_json_atomic(output/'human-answers.json',read_json_for_test(Path(args[args.index('--answers')+1])))
        write_json_atomic(output/'human-submission-result.json',{'experiment_id':'next-fingerprint','remaining_questions':0})
        (output/'comparison.html').write_text('<html>new</html>')
    service=ExperimentReviewService(root,python='/project/python',start_job=start,run_command=run,get_job=jobs.get)
    payload={'experiment_path':str(base.relative_to(root)),'experiment_id':'fingerprint',
             'request_id':'a'*32,'answers':[{'case_id':'clip:w1','mode':'transliteration','hint':'',
                'selections':[{'slot_zh':'人物','korean':'김서환','romanization':'Kim Seo-hwan','chinese':'金瑞焕'}]}]}
    return service,payload,base,artifact,jobs,tasks,calls


def read_json_for_test(path):
    data=json.loads(path.read_text());return {'experiment_id':data['experiment_id'],'answers':data['answers']}


def test_submission_starts_once_persists_answers_and_publishes_separate_result(setup_review):
    service,payload,base,_,jobs,tasks,calls=setup_review
    result=service.submit(payload)
    assert result['status']=='queued' and len(jobs)==1
    assert service.submit(payload)['job_id']==result['job_id'] and len(jobs)==1
    assert service.submit({**payload,'request_id':'b'*32})['job_id']==result['job_id']
    request=json.loads((base/'.human-review-requests'/('a'*32+'.json')).read_text())
    assert request['answers'][0]['selections'][0]['chinese']=='金瑞焕'
    tasks[result['job_id']](result['job_id'])
    state=service.status(payload['experiment_path'])
    assert state['status']=='done' and state['result']['remaining_questions']==0
    assert '/api/file?path=' in state['result']['report_url']
    assert calls[0][0]=='/project/python' and 'human-continue' in calls[0]
    assert (base/'comparison.html').read_text()=='<html>original</html>'


def test_autonomous_experiment_uses_its_own_resume_worker(setup_review):
    service,payload,base,_,_,tasks,calls=setup_review
    write_json_atomic(base/'manifest.json',{'policy':{'autonomous_subtitle_agent':True}})
    job=service.submit(payload);tasks[job['job_id']](job['job_id'])
    assert calls[0][2].endswith('/scripts/autonomous_subtitle_agent.py')
    assert calls[0][3]=='respond' and service.status(payload['experiment_path'])['status']=='done'


def test_changed_request_or_competing_job_is_rejected(setup_review):
    service,payload,*_=setup_review
    service.submit(payload)
    changed={**payload,'answers':[{'case_id':'clip:w1','mode':'hint','hint':'可能是金瑞焕','selections':[]}]}
    with pytest.raises(ReviewConflict): service.submit(changed)
    with pytest.raises(ReviewConflict): service.submit({**changed,'request_id':'b'*32})


def test_stale_completed_page_cannot_fork_over_newer_result(setup_review):
    service,payload,_,_,_,tasks,_=setup_review
    job=service.submit(payload);tasks[job['job_id']](job['job_id'])
    with pytest.raises(ReviewConflict):
        service.submit({**payload,'request_id':'b'*32,'answers':[{'case_id':'clip:w1','mode':'hint','hint':'另一条线索'}]})


def test_restart_preserves_answers_and_allows_retry(setup_review):
    service,payload,_,_,jobs,_,_=setup_review
    service.submit(payload);jobs.clear()
    state=service.status(payload['experiment_path'])
    assert state['status']=='failed' and state['answers']
    restarted=service.submit(payload)
    assert restarted['status']=='queued'


@pytest.mark.parametrize('path',['configs','../outside','outputs/asr3_experiments/../../configs'])
def test_paths_outside_experiments_are_rejected(setup_review,path):
    service,payload,*_=setup_review
    with pytest.raises(ValueError): service.submit({**payload,'experiment_path':path})


def test_symlink_escape_is_rejected(setup_review,tmp_path):
    service,payload,base,*_=setup_review
    outside=tmp_path/'private';outside.mkdir()
    link=base.parent/'escape';link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError): service.submit({**payload,'experiment_path':str(link)})


def test_stale_fingerprint_and_invented_candidates_are_rejected(setup_review):
    _,payload,_,artifact,*_=setup_review
    with pytest.raises(ReviewConflict): normalize_answers({**payload,'experiment_id':'stale'},artifact)
    changed=json.loads(json.dumps(payload));changed['answers'][0]['selections'][0]['chinese']='未经确认的名字'
    with pytest.raises(ReviewConflict): normalize_answers(changed,artifact)
    changed=json.loads(json.dumps(payload));changed['answers'][0]['selections'][0]['romanization']='Other Person'
    with pytest.raises(ReviewConflict): normalize_answers(changed,artifact)


def test_hint_is_not_treated_as_confirmed_name(setup_review):
    _,payload,_,artifact,*_=setup_review
    answers=normalize_answers({**payload,'answers':[{'case_id':'clip:w1','mode':'hint','hint':'也许是某个角色，不确定'}]},artifact)
    assert answers[0]['mode']=='hint' and not answers[0]['selections']
    with pytest.raises(ValueError): normalize_answers({**payload,'answers':[{'case_id':'clip:w1','mode':'hint','hint':''}]},artifact)


def test_transliteration_requires_each_person_not_only_first(setup_review):
    _,payload,_,artifact,*_=setup_review
    artifact['questions'][0]['candidates'].append({'slot_zh':'第二人','korean':'재원','romanization':'Jae-won','chinese_candidates':['在元']})
    with pytest.raises(ValueError,match='每个'): normalize_answers(payload,artifact)


def test_worker_failure_retains_answers_without_publishing_partial_result(setup_review):
    service,payload,base,_,_,tasks,_=setup_review
    def fail(*args): raise RuntimeError('test failure')
    service.run_command=fail
    job=service.submit(payload)
    with pytest.raises(RuntimeError): tasks[job['job_id']](job['job_id'])
    state=service.status(payload['experiment_path'])
    assert state['status']=='failed' and state['answers'] and 'result' not in state
    assert (base/'comparison.html').read_text()=='<html>original</html>'


def test_finished_child_is_recovered_even_if_server_did_not_publish_state(setup_review):
    service,payload,base,_,jobs,tasks,_=setup_review
    job=service.submit(payload);tasks[job['job_id']](job['job_id'])
    state=json.loads((base/'.human-review-state.json').read_text());state.update(status='running');state.pop('result')
    write_json_atomic(base/'.human-review-state.json',state);jobs.clear()
    recovered=service.status(payload['experiment_path'])
    assert recovered['status']=='done' and recovered['result']['remaining_questions']==0


def test_running_child_after_server_restart_cannot_be_started_twice(setup_review):
    fcntl=pytest.importorskip('fcntl')
    service,payload,base,_,jobs,_,_=setup_review
    service.submit(payload);jobs.clear()
    child=base/'human_reviews'/payload['request_id'];child.mkdir(parents=True)
    with (child/'.human-run.lock').open('w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert service.status(payload['experiment_path'])['status']=='running'
        assert service.submit(payload)['status']=='running'
        assert not jobs
