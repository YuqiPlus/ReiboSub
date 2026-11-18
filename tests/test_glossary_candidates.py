from concurrent.futures import ThreadPoolExecutor
import json
import threading

from video_translate import glossary_candidates as cache


def test_persistent_cache_deduplicates_contexts_and_never_edits_glossary(tmp_path):
    path=tmp_path/'draft.yaml';path.write_text('characters: []\n');before=path.read_bytes();calls=[]
    def translate(text):calls.append(text);return '参考：'+text
    result=cache.prepare(path,['a','a','b'],'model',translate)
    assert result['ready']==2 and sorted(calls)==['a','b']
    assert path.read_bytes()==before
    assert cache.cached(path,['a','b'],'model')['values']=={'a':'参考：a','b':'参考：b'}
    cache.prepare(path,['a','b'],'model',lambda *a:(_ for _ in ()).throw(AssertionError('不应重新请求')))
    assert cache.cached(path,['a'],'different-model')['summary']['pending']==1


def test_cache_reads_do_not_wait_for_pending_provider_calls(tmp_path):
    path=tmp_path/'draft.yaml';started=threading.Event();release=threading.Event()
    def translate(text):started.set();assert release.wait(3);return '参考'
    with ThreadPoolExecutor() as pool:
        future=pool.submit(cache.prepare,path,['a'],'model',translate)
        assert started.wait(2)
        try:assert cache.cached(path,['a'],'model')['summary']['pending']==1
        finally:release.set()
        assert future.result()['ready']==1


def test_failures_are_cached_without_secrets_and_only_explicitly_retried(tmp_path):
    path=tmp_path/'draft.yaml';calls=[]
    def fail(text):calls.append(text);raise RuntimeError('secret-key endpoint-private-body')
    assert cache.prepare(path,['a'],'model',fail)['failed']==1
    cache.prepare(path,['a'],'model',fail)
    assert calls==['a']
    assert 'secret-key' not in cache.cache_path(path).read_text()
    assert cache.prepare(path,['a'],'model',lambda text:'成功',retry_failed=True)['ready']==1


def test_parallel_prepare_requests_share_results(tmp_path):
    path=tmp_path/'draft.yaml';calls=[];mutex=threading.Lock()
    def translate(text):
        with mutex:calls.append(text)
        return '参考'
    with ThreadPoolExecutor() as pool:
        jobs=[pool.submit(cache.prepare,path,['a','b'],'model',translate) for _ in range(2)]
        assert all(job.result()['ready']==2 for job in jobs)
    assert sorted(calls)==['a','b']
