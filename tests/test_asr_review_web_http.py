import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from video_translate import web_agent
from video_translate.asr_review_web import ReviewConflict


@pytest.fixture
def review_http(monkeypatch):
    seen=[]
    def submit(payload):
        seen.append(payload)
        if payload.get('stale'): raise ReviewConflict('候选已更新')
        return {'status':'queued','job_id':'test-job'}
    monkeypatch.setattr(web_agent,'_experiment_review_service',lambda:SimpleNamespace(
        submit=submit,status=lambda p:{'status':'idle','experiment_path':p}))
    server=ThreadingHTTPServer(('127.0.0.1',0),web_agent.AgentHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield server.server_address,seen
    finally: server.shutdown();server.server_close();thread.join(timeout=5)


def request(address,method,target,payload=None,headers=None):
    connection=HTTPConnection(*address,timeout=5)
    body=json.dumps(payload).encode() if payload is not None else None
    try:
        connection.request(method,target,body=body,headers={'Content-Type':'application/json',**(headers or {})})
        response=connection.getresponse();return response.status,json.loads(response.read())
    finally: connection.close()


def test_experiment_get_and_submit_use_new_routes(review_http):
    address,seen=review_http
    status,data=request(address,'GET','/api/asr-experiments/review?path='+quote('outputs/asr3_experiments/实验'))
    assert status==200 and data['experiment_path'].endswith('实验')
    origin=f'http://{address[0]}:{address[1]}'
    status,data=request(address,'POST','/api/asr-experiments/review',{'answers':[]},headers={'Origin':origin})
    assert status==200 and data['job_id']=='test-job' and len(seen)==1


def test_cross_site_submission_is_rejected_before_start(review_http):
    address,seen=review_http
    status,_=request(address,'POST','/api/asr-experiments/review',{},headers={'Origin':'https://other.example'})
    assert status==403 and not seen
    status,_=request(address,'POST','/api/asr-experiments/review',{},headers={'Sec-Fetch-Site':'cross-site'})
    assert status==403 and not seen


def test_non_json_oversized_and_stale_submission_fail_safely(review_http):
    address,seen=review_http
    status,_=request(address,'POST','/api/asr-experiments/review',{},headers={'Content-Type':'text/plain'})
    assert status==400 and not seen
    status,_=request(address,'POST','/api/asr-experiments/review',{'hint':'x'*70000})
    assert status==400 and not seen
    status,data=request(address,'POST','/api/asr-experiments/review',{'stale':True})
    assert status==409 and data['error']=='候选已更新'
