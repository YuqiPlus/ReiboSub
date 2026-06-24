from __future__ import annotations

import pytest

from video_translate.youtube_url import extract_youtube_video_id, normalize_youtube_url


def test_normalize_watch_url_removes_time_playlist_and_share_noise():
    url = "https://www.youtube.com/watch?v=VIDEO_ID_01&t=63s&list=PL123&index=4&si=abc"

    assert normalize_youtube_url(url) == "https://www.youtube.com/watch?v=VIDEO_ID_01"


def test_normalize_short_youtu_be_url():
    assert normalize_youtube_url("https://youtu.be/VIDEO_ID_01?t=11") == "https://www.youtube.com/watch?v=VIDEO_ID_01"


def test_normalize_shorts_and_embed_urls():
    assert normalize_youtube_url("https://www.youtube.com/shorts/VIDEO_ID_01?feature=share") == "https://www.youtube.com/watch?v=VIDEO_ID_01"
    assert normalize_youtube_url("https://www.youtube.com/embed/VIDEO_ID_01?start=20") == "https://www.youtube.com/watch?v=VIDEO_ID_01"


def test_normalize_plain_video_id():
    assert normalize_youtube_url("VIDEO_ID_01") == "https://www.youtube.com/watch?v=VIDEO_ID_01"


def test_extract_video_id_rejects_unknown_url():
    with pytest.raises(ValueError, match="无法从输入中解析 YouTube 视频 ID"):
        extract_youtube_video_id("https://example.com/watch?v=VIDEO_ID_01")
