from __future__ import annotations

import pytest

from video_translate.youtube_url import extract_youtube_video_id, normalize_youtube_url


def test_normalize_watch_url_removes_time_playlist_and_share_noise():
    url = "https://www.youtube.com/watch?v=slOguO6zpbA&t=63s&list=PL123&index=4&si=abc"

    assert normalize_youtube_url(url) == "https://www.youtube.com/watch?v=slOguO6zpbA"


def test_normalize_short_youtu_be_url():
    assert normalize_youtube_url("https://youtu.be/slOguO6zpbA?t=11") == "https://www.youtube.com/watch?v=slOguO6zpbA"


def test_normalize_shorts_and_embed_urls():
    assert normalize_youtube_url("https://www.youtube.com/shorts/slOguO6zpbA?feature=share") == "https://www.youtube.com/watch?v=slOguO6zpbA"
    assert normalize_youtube_url("https://www.youtube.com/embed/slOguO6zpbA?start=20") == "https://www.youtube.com/watch?v=slOguO6zpbA"


def test_normalize_plain_video_id():
    assert normalize_youtube_url("slOguO6zpbA") == "https://www.youtube.com/watch?v=slOguO6zpbA"


def test_extract_video_id_rejects_unknown_url():
    with pytest.raises(ValueError, match="无法从输入中解析 YouTube 视频 ID"):
        extract_youtube_video_id("https://example.com/watch?v=slOguO6zpbA")
