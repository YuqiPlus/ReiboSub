from pathlib import Path
from types import SimpleNamespace

import pytest

from video_translate import video_source as source
from video_translate import web_agent
from video_translate.agent_planner import build_agent_plan
from video_translate.project_manifest import update_youtube_project_manifest, infer_project_manifest
from video_translate.youtube import download_video, download_subtitles, download_thumbnail

BILI = "https://www.bilibili.com/video/BV1GJ411x7h7"


@pytest.mark.parametrize(("raw", "expected"), [
    ("BV1GJ411x7h7", BILI), ("av170001", "https://www.bilibili.com/video/av170001"),
    (BILI + "/?p=2&spm_id_from=333.1#reply", BILI + "?p=2"),
    (BILI + "?p=1", BILI),
    ("https://m.bilibili.com/video/BV1GJ411x7h7?p=3", BILI + "?p=3"),
    ("www.bilibili.com/video/BV1GJ411x7h7", BILI),
    ("https://youtu.be/abcdefghijk?t=10", "https://www.youtube.com/watch?v=abcdefghijk"),
    ("abc123", "https://www.youtube.com/watch?v=abc123"),
])
def test_normalize_video_origin(raw, expected):
    assert source.normalize_video_url(raw) == expected


@pytest.mark.parametrize("url", [
    BILI + "?p=0", BILI + "?p=-1", BILI + "?p=", BILI + "?p=two", BILI + "?p=2&p=3",
    "https://www.bilibili.com/bangumi/play/ep123", "https://live.bilibili.com/123",
    "https://www.bilibili.com/medialist/play/ml123", "https://bilibili.com.evil.test/video/BV1GJ411x7h7",
    "https://evil-youtube.com/watch?v=abc", "https://b23.tv@localhost/abc", "file:///tmp/video",
    "https://www.bilibili.com:8080/video/BV1GJ411x7h7",
])
def test_reject_unsupported_or_ambiguous_origin(url):
    with pytest.raises(ValueError):
        source.normalize_video_url(url)


def test_short_link_resolves_only_allowlisted_hops_and_preserves_part(monkeypatch):
    requested = []
    closed = []
    def get(url, **kwargs):
        requested.append((url, kwargs))
        return SimpleNamespace(status_code=302, headers={"Location": BILI + "?p=2&share_source=copy"},
                               raise_for_status=lambda: None, close=lambda: closed.append(True))
    monkeypatch.setattr(source.requests, "get", get)
    assert source.normalize_video_url("https://b23.tv/abc123") == BILI + "?p=2"
    assert source.normalize_video_url("https://b23.tv/abc123?p=3") == BILI + "?p=3"
    assert source.normalize_video_url("https://b23.tv/abc123?p=1") == BILI
    assert len(closed) == 3 and all(not opts["allow_redirects"] for _, opts in requested)
    monkeypatch.setattr(source.requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=302, headers={"Location": "http://127.0.0.1/admin"},
        raise_for_status=lambda: None, close=lambda: None))
    with pytest.raises(ValueError):
        source.normalize_video_url("https://b23.tv/abc123")


def test_part_identity_separates_tasks_and_long_equal_titles():
    assert source.video_task_key(BILI) != source.video_task_key(BILI + "?p=2")
    assert source.video_task_key("https://www.youtube.com/watch?v=abc123") == "abc123"
    title = "很长的同名视频" * 70
    a, b = (source.video_title(title, BILI + f"?p={part}") for part in (1, 2))
    assert a != b and len(a) <= 180 and len(b) <= 180
    assert source.video_title(b, BILI + "?p=2") == b
    assert source.video_title("unchanged", "https://www.youtube.com/watch?v=abc123") == "unchanged"
    assert not source.explicit_video_url("/tmp/video.mp4")
    assert source.explicit_video_url(BILI + "?p=2") == BILI + "?p=2"
    assert web_agent._youtube_task_key(BILI) != web_agent._youtube_task_key(BILI.replace('x7h7', 'X7h7'))


def test_platform_proxy_and_cookie_are_isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("BILIBILI_PROXY", raising=False)
    monkeypatch.delenv("BILIBILI_COOKIE_FILE", raising=False)
    assert source.platform_options(BILI, youtube_proxy="http://youtube-proxy")['proxy'] == ""
    assert source.platform_options("https://www.youtube.com/watch?v=abc123", youtube_proxy="http://youtube-proxy") == {"proxy": "http://youtube-proxy"}
    cookies = tmp_path / "bilibili.cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("BILIBILI_COOKIE_FILE", str(cookies))
    monkeypatch.setenv("BILIBILI_PROXY", "http://bili-proxy")
    opts = source.platform_options(BILI)
    assert opts['cookiefile'] == str(cookies) and opts['proxy'] == "http://bili-proxy"
    assert 'cookiefile' not in source.platform_options("https://www.youtube.com/watch?v=abc123")


@pytest.mark.parametrize("info", [{"_type": "playlist"}, {"extractor_key": "BiliBiliBangumi"}, None])
def test_cannot_accidentally_expand_to_series(info):
    with pytest.raises(ValueError): source.validate_video_info(info, BILI)


def test_nonexistent_part_cannot_silently_download_p1():
    with pytest.raises(ValueError, match='指定分 P'):
        source.validate_video_info({'id': 'BV1GJ411x7h7', 'extractor_key': 'BiliBili'}, BILI + '?p=2')


def _info():
    return {"id": "BV1GJ411x7h7_p2", "title": "同一个标题", "duration": 20, "extractor_key": "BiliBili",
            "subtitles": {"danmaku": [{"ext": "xml"}], "zh-CN": [{"ext": "srt"}], "ai-zh": [{"ext": "srt"}], "ko": [{"ext": "srt"}]},
            "formats": [{"format_id": "100026", "height": 1080, "vcodec": "avc1.640028", "acodec": "none", "ext": "mp4"},
                        {"format_id": "30280", "vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a"}]}


def _fake_ydl(monkeypatch, module, info=None, download=None):
    calls = []
    class FakeYDL:
        def __init__(self, opts): self.params = dict(opts); calls.append(("options", self.params))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            calls.append(("probe", url)); return info or _info()
        def download(self, urls):
            calls.append(("download", urls))
            if download: download(self.params)
    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.delenv("BILIBILI_COOKIE_FILE", raising=False)
    monkeypatch.delenv("BILIBILI_PROXY", raising=False)
    return calls


def test_probe_and_format_discovery_preserve_part_and_exclude_danmaku(monkeypatch):
    calls = _fake_ydl(monkeypatch, web_agent)
    monkeypatch.setattr(web_agent, "_find_or_bind_youtube_project", lambda *a: {})
    monkeypatch.setattr(web_agent, "_ensure_probe_thumbnail", lambda *a, **k: None)
    result = web_agent.probe_video(BILI + "?p=2", proxy="http://youtube-proxy", target_language='zh')
    assert result['normalized_url'] == BILI + "?p=2" and result['part'] == 2
    assert result['source_type'] == 'bilibili' and result['video_id'] == 'BV1GJ411x7h7'
    assert result['title'].endswith('[BV1GJ411x7h7 P2]')
    assert not any(t['lang'] == 'danmaku' for t in result['subtitles'])
    assert next(t for t in result['subtitles'] if t['lang'] == 'ai-zh')['kind'] == 'auto'
    assert result['agent_plan']['route'] == 'download_target_subtitle'
    formats = web_agent.download_formats(BILI + "?p=2")
    assert formats['formats'][0]['id'] == '100026+30280'
    assert all(v['proxy'] == '' and v['noplaylist'] for k, v in calls if k == 'options')
    assert all(v == BILI + '?p=2' for k, v in calls if k == 'probe')


def test_ai_only_chinese_is_not_a_manual_target_caption():
    tracks = source.bilibili_caption_tracks({'subtitles': {'danmaku': [{'ext': 'xml'}], 'ai-zh': [{'ext': 'srt'}]}})
    assert len(tracks) == 1 and tracks[0]['kind'] == 'auto'
    assert build_agent_plan(tracks, detected_source_language='ko')['route'] != 'download_target_subtitle'


@pytest.mark.parametrize(('kind', 'expected'), [('auto', ['ai-zh']), ('manual', ['zh-CN', 'ko'])])
def test_bilibili_subtitle_downloader_uses_real_tracks(kind, expected, monkeypatch, tmp_path):
    calls = _fake_ydl(monkeypatch, download_subtitles)
    download_subtitles.download_subtitles(BILI + '?p=2', output_dir=tmp_path, subtitle_languages='.*',
                                         auto_subtitles=kind == 'auto', manual_subtitles=kind == 'manual', proxy='http://youtube-proxy')
    opts = [v for k, v in calls if k == 'options'][-1]
    assert opts['subtitleslangs'] == expected
    assert opts['writesubtitles'] and opts['writeautomaticsub']
    assert '[BV1GJ411x7h7 P2]' in opts['outtmpl']
    assert opts['proxy'] == ''


def test_video_downloader_saves_separate_part_files(monkeypatch, tmp_path):
    def save(opts):
        template = opts['outtmpl']
        if isinstance(template, dict): template = template['default']
        output = Path(template.replace('%(ext)s', 'mp4'))
        output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b'test video')
    calls = _fake_ydl(monkeypatch, download_video, download=save)
    monkeypatch.setattr(download_video, 'download_thumbnail', lambda *a, **k: None)
    monkeypatch.setattr(download_video, 'remove_incompatible_existing_h264_targets', lambda *a: None)
    first = download_video.download_video(BILI, output_dir=tmp_path)
    second = download_video.download_video(BILI + '?p=2', output_dir=tmp_path)
    assert len(first) == len(second) == 1 and first[0] != second[0]
    assert first[0].exists() and second[0].exists()
    assert all(v['noplaylist'] and v['proxy'] == '' for k, v in calls if k == 'options')


def test_manifest_and_agent_task_keep_part_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, 'TASK_DIR', tmp_path / 'tasks')
    a = web_agent._ensure_agent_task(normalized_url=BILI, title='same', payload={})
    b = web_agent._ensure_agent_task(normalized_url=BILI + '?p=2', title='same', payload={})
    assert a['id'] != b['id'] and a['source_type'] == b['source_type'] == 'bilibili'
    assert b['url'] == BILI + '?p=2'
    video = tmp_path / 'media' / 'video.mp4'; video.parent.mkdir(); video.write_bytes(b'video')
    manifest = update_youtube_project_manifest(video, source_url=BILI + '?p=2')
    assert manifest['source_type'] == 'bilibili' and manifest['part'] == 2
    assert manifest['video_id'] == 'BV1GJ411x7h7'
    assert infer_project_manifest(video.parent)['normalized_url'] == BILI + '?p=2'


def test_direct_download_job_resolves_its_own_part_without_ui_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, 'ROOT', tmp_path)
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', tmp_path / 'media')
    monkeypatch.setattr(web_agent, 'start_job', lambda name, fn: SimpleNamespace(result=fn('test-bilibili')))
    seen = []
    title = source.video_title('同名视频', BILI + '?p=2')
    monkeypatch.setattr(web_agent, 'probe_video', lambda url: (seen.append(url) or {'title': title}))
    def run(job_id, args):
        assert args[3] == BILI + '?p=2'
        folder = tmp_path / 'media' / args[args.index('--project-title') + 1]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (folder.name + '.mp4')).write_bytes(b'video')
        (folder / (folder.name + '.jpg')).write_bytes(b'cover')
    monkeypatch.setattr(web_agent, '_run_command', run)
    result = web_agent.download_video_job({'url': BILI + '?p=2'}).result
    assert seen == [BILI + '?p=2']
    assert Path(result['input_video']).exists() and 'P2' in result['project_dir']
    assert result['project']['source_type'] == 'bilibili'


def test_same_title_ocr_cache_cannot_cross_bilibili_parts(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, 'TASK_DIR', tmp_path / 'tasks')
    monkeypatch.setattr(web_agent, 'JOB_DIR', tmp_path / 'jobs')
    a = web_agent._ensure_agent_task(normalized_url=BILI, title='same title', payload={})
    path = Path(a['task_dir']) / 'source.srt'
    path.write_text('1\n00:00:00,000 --> 00:00:02,000\n안녕\n')
    web_agent._update_task_stage(a['id'], 'ocr', 'done', source_srt=str(path),
                                ocr_pipeline_version='v1', ocr_extraction_mode='auto')
    query = {'title': 'same title', 'translation_mode': 'standard_cleanup'}
    assert web_agent._find_reusable_ocr_result(url=BILI, **query) is not None
    assert web_agent._find_reusable_ocr_result(url=BILI + '?p=2', **query) is None


def test_simultaneous_subtitle_download_cannot_take_other_parts_file(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, 'ROOT', tmp_path)
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', tmp_path / 'media')
    monkeypatch.setattr(web_agent, 'start_job', lambda name, fn: SimpleNamespace(result=fn('test-bilibili')))
    title = source.video_title('same title', BILI + '?p=2')
    def run(job_id, args):
        for part in (2, 1):
            name = source.video_title('same title', BILI + f'?p={part}')
            folder = tmp_path / 'media' / name; folder.mkdir(parents=True)
            (folder / (name + '.ko.srt')).write_text(f'part {part}')
    monkeypatch.setattr(web_agent, '_run_command', run)
    result = web_agent.download_subtitle_job({'url': BILI + '?p=2', 'title': title, 'lang': 'ko'}).result
    assert Path(result['subtitle_path']).read_text() == 'part 2'
