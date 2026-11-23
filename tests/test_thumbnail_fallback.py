import io
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

from video_translate.youtube import download_video as module


def image_bytes():
    data = io.BytesIO()
    Image.new('RGB', (480, 360), 'green').save(data, 'JPEG')
    return data.getvalue()


def test_youtube_cover_retries_other_sizes_and_validates_bytes(monkeypatch, tmp_path):
    url = 'https://www.youtube.com/watch?v=abcdefghijk'
    preferred = 'https://i.ytimg.com/vi_webp/abcdefghijk/maxresdefault.webp'
    candidates = module.thumbnail_candidates({'thumbnail': preferred}, url)
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if 'hqdefault' not in url:
            raise requests.HTTPError('404')
        return SimpleNamespace(content=image_bytes(), headers={'Content-Type':'image/jpeg'}, raise_for_status=lambda:None)
    monkeypatch.setattr(module.requests, 'get', fetch)
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'keep video')
    result = module.download_thumbnail(preferred, video, fallback_urls=candidates)
    assert result == tmp_path / 'video.jpg' and len(calls) == 4
    with Image.open(result) as image:
        assert image.size == (480, 360)
    assert video.read_bytes() == b'keep video'


def test_invalid_image_and_all_failed_sizes_do_not_leave_partial_images(monkeypatch, tmp_path):
    calls=[]
    def fetch(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(content=b'<html>not an image</html>', headers={}, raise_for_status=lambda:None)
    monkeypatch.setattr(module.requests, 'get', fetch)
    with pytest.raises(RuntimeError, match='尺寸均下载失败'):
        module.download_thumbnail('https://example/a', tmp_path/'video.mp4', fallback_urls=['https://example/b'])
    assert len(calls)==2 and not list(tmp_path.iterdir())


def test_other_platforms_do_not_generate_youtube_urls_and_keep_proxy_disabled(monkeypatch,tmp_path):
    url='https://www.bilibili.com/video/BV1GJ411x7h7'
    candidates=module.thumbnail_candidates({'thumbnail':'https://example/bili.jpg'},url)
    assert candidates==['https://example/bili.jpg']
    seen={}
    def fetch(url,**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(content=image_bytes(),headers={},raise_for_status=lambda:None)
    monkeypatch.setattr(module.requests,'get',fetch)
    module.download_thumbnail(candidates[0],tmp_path/'video.mp4',proxy='',disable_env_proxy=True)
    assert seen['proxies']=={'http':'','https':''}


def test_delivery_repairs_cover_without_rerunning_recognition_or_translation(monkeypatch, tmp_path):
    from video_translate import web_agent as web
    project=tmp_path/'project'
    project.mkdir()
    video=project/'video.mp4'
    video.write_bytes(b'original video')
    session=web.AgentSession(id='repair',status='done',payload={'url':'https://youtu.be/abcdefghijk'})
    def fetch(url,**kwargs):
        if 'hqdefault' not in url:raise requests.HTTPError('404')
        return SimpleNamespace(content=image_bytes(),headers={},raise_for_status=lambda:None)
    monkeypatch.setattr(module.requests,'get',fetch)
    monkeypatch.setattr(web,'_run_command',lambda *_:pytest.fail('No recognition or translation command'))
    result=web._ensure_delivery_thumbnail(session,video,{'title':'Test cover'})
    assert Path(result['thumbnail_path']).exists()
    from video_translate.project_manifest import load_project_manifest
    manifest=load_project_manifest(project)
    assert manifest['thumbnail']==result['thumbnail_path'] and manifest['primary_video']==str(video)
    assert session.status=='done' and video.read_bytes()==b'original video'
