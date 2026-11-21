from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from reibosub import (Cue, FormatRegistry, OperationCancelled, Subtitle, SubtitleCodec,
                      SubtitleFormatError, TranslationBackend, TranslationError,
                      ValidationError, convert, load, save, translate)


def sample():
    return Subtitle((Cue(3, 1.25, 2.75, "數據與美學", speaker="Speaker 1", confidence=.9), Cue(7, 3, 5, "第二行\nHello")), language="zh")


def test_data_is_immutable_and_serializable():
    cues = list(sample().cues)
    subtitle = Subtitle(cues, language="zh")
    cues.clear()
    assert len(subtitle) == 2 and subtitle[0].index == 3
    with pytest.raises(dataclasses.FrozenInstanceError):
        subtitle[0].text = "changed"
    assert Subtitle.from_dict(subtitle.to_dict()) == subtitle
    mapped = subtitle.map_text(str.upper)
    assert subtitle[1].text.endswith("Hello") and mapped[1].text.endswith("HELLO")
    assert mapped[0].speaker == "Speaker 1" and mapped[0].confidence == .9
    assert mapped.language == "zh"


@pytest.mark.parametrize("kwargs", [
    {"index": 0}, {"index": True}, {"start": -1}, {"end": 0},
    {"start": float("nan")}, {"end": float("inf")}, {"text": None},
    {"confidence": 2}, {"confidence": True}, {"speaker": 2},
])
def test_invalid_cue_data_is_rejected(kwargs):
    data = dict(index=1, start=0, end=1, text="hello")
    with pytest.raises(ValidationError):
        Cue(**(data | kwargs))


def test_invalid_subtitle_and_json_schema_are_rejected():
    with pytest.raises(ValidationError):
        Subtitle((Cue(1, 0, 1, "a"), Cue(1, 1, 2, "b")))
    with pytest.raises(ValidationError):
        Subtitle(("not a cue",))
    for data in [{"version": True, "cues": []}, {"version": 2, "cues": []}, {"cues": [{}]}, {"cues": [1]}]:
        with pytest.raises(ValidationError):
            Subtitle.from_dict(data)


@pytest.mark.parametrize("format", ["srt", "vtt", "ass", "ssa", "json", "bcc", "lrc", "txt"])
def test_all_builtin_formats_load_dump_and_file_roundtrip(tmp_path, format):
    subtitle = sample()
    content = subtitle.dumps(format)
    output = Subtitle.loads(content, format=format)
    assert len(output) >= 2
    assert output[0].text == "數據與美學"
    assert output.source_format == format
    destination = tmp_path / f"字幕.{format}"
    assert subtitle.save(destination) == destination
    assert load(destination).cues == output.cues
    if format not in {"lrc", "txt"}:
        assert [(c.start, c.end) for c in output] == [(c.start, c.end) for c in subtitle]
    if format == "json":
        assert output[0].speaker == "Speaker 1" and output[0].confidence == .9
        assert output.language == "zh"


def test_encoding_plain_text_and_no_clobber(tmp_path):
    source = tmp_path / "input.srt"
    source.write_bytes(sample().dumps("srt").encode("gb18030"))
    subtitle = Subtitle.load(source, encoding="gb18030")
    assert subtitle.to_text() == "數據與美學\n第二行\nHello"
    assert "00:00:01,250" in subtitle.to_text(timestamps=True)
    output = tmp_path / "output.vtt"
    convert(source, output, encoding="gb18030")
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        save(subtitle, output)
    assert output.read_bytes() == before
    save(subtitle.map_text(lambda _: "new"), output, overwrite=True)
    assert "new" in output.read_text()
    assert not list(tmp_path.glob(".reibosub-*"))
    with pytest.raises(SubtitleFormatError):
        subtitle.save(source, format="unknown", overwrite=True)
    assert Subtitle.load(source, encoding="gb18030")[0].text == "數據與美學"


def test_no_clobber_rejects_symlinks_and_leaves_targets_intact(tmp_path):
    target = tmp_path / "original.srt"
    target.write_text("keep")
    link = tmp_path / "link.srt"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        sample().save(link)
    assert target.read_text() == "keep"
    broken = tmp_path / "broken.srt"
    broken.symlink_to(tmp_path / "missing.srt")
    with pytest.raises(FileExistsError):
        sample().save(broken)
    assert broken.is_symlink()


@pytest.mark.parametrize("text,format", [
    ("invalid", "srt"), ("1\n00:00:61,000 --> 00:01:03,000\na", "srt"),
    ('{"cues": [{"start": 1}]}', "json"), ("null", "bcc"),
    ('{"body": [0]}', "bcc"), ("not JSON", "json"), ("bad line", "lrc"),
    ("[Events]\nFormat: Start, End\nDialogue: 0,1", "ass"),
])
def test_malformed_formats_raise_typed_errors(text, format):
    with pytest.raises(SubtitleFormatError):
        Subtitle.loads(text, format=format)


def test_format_specific_limits_and_notices():
    subtitle = Subtitle.loads("WEBVTT\n\nNOTE a comment\n\ncustom-id\n00:01.000 --> 00:02.000 align:start\nHello", format="vtt")
    assert subtitle[0].text == "Hello" and subtitle.notices
    assert Subtitle.loads("first\nsecond", format="txt").notices
    lrc = Subtitle.loads("[ar:metadata]\n[01:02.03][01:05.00]Hello", format="lrc")
    assert len(lrc) == 2 and lrc[0].start == 62.03 and lrc[0].end == 65
    with pytest.raises(SubtitleFormatError, match="precision"):
        Subtitle((Cue(1, 0, .00001, "too short"),)).dumps("srt")
    with pytest.raises(SubtitleFormatError, match="precision"):
        Subtitle((Cue(1, 0, .001, "too short"),)).dumps("ass")


def test_mechanical_diagnostics_do_not_change_cues():
    subtitle = Subtitle((Cue(1, 2, 5, ""), Cue(2, 0, 3, "a"), Cue(3, 4, 6, "b")))
    before = subtitle.to_dict()
    assert {issue.code for issue in subtitle.check()} == {"empty_text", "non_monotonic", "overlap"}
    assert subtitle.to_dict() == before


def test_chinese_conversion_is_local_preserves_metadata_and_source():
    pytest.importorskip("opencc")
    subtitle = sample()
    output = subtitle.to_simplified()
    assert output[0].text == "数据与美学" and subtitle[0].text == "數據與美學"
    assert output.to_traditional()[0].text == "數據與美學"
    assert dataclasses.replace(output[0], text=subtitle[0].text) == subtitle[0]
    marked = Subtitle((Cue(1, 0, 1, '<font face="字體">數據</font>'),)).to_simplified()
    assert marked[0].text == '<font face="字體">数据</font>'


def test_custom_codec_instances_are_independent(tmp_path):
    class Lines:
        def loads(self, text):
            return Subtitle(tuple(Cue(i + 1, i, i + 1, line) for i, line in enumerate(text.splitlines())))
        def dumps(self, subtitle):
            return subtitle.to_text()
    registry = FormatRegistry()
    codec = Lines()
    assert isinstance(codec, SubtitleCodec)
    registry.register("lines", codec)
    assert Subtitle.loads("one\ntwo", format="lines", registry=registry)[1].text == "two"
    path = tmp_path / "custom.lines"
    sample().save(path, registry=registry)
    assert path.read_text().startswith("數據")
    assert "lines" not in FormatRegistry().formats
    with pytest.raises(ValidationError):
        registry.register("lines", codec)
    with pytest.raises(ValidationError):
        registry.register("bad", object())
    with pytest.raises(SubtitleFormatError):
        Subtitle.loads("one", format="lines")


class EchoBackend:
    def __init__(self):
        self.calls = []
    def translate_batch(self, texts, *, source_language, target_language):
        self.calls.append((list(texts), source_language, target_language))
        return [f"translated: {text}" for text in texts]


def test_custom_backend_progress_and_locked_timing():
    backend, progress = EchoBackend(), []
    assert isinstance(backend, TranslationBackend)
    source = sample()
    output = translate(source, translator=backend, target_language="en", batch_size=1, on_progress=progress.append)
    assert [(p.completed, p.total) for p in progress] == [(0, 2), (1, 2), (2, 2)]
    assert backend.calls[0][1:] == ("zh", "en")
    assert output.language == "en" and source.language == "zh"
    assert [(c.index, c.start, c.end, c.speaker, c.confidence) for c in output] == [(c.index, c.start, c.end, c.speaker, c.confidence) for c in source]
    assert all(c.text.startswith("translated:") for c in output)
    assert not source[0].text.startswith("translated:")


@pytest.mark.parametrize("output", [[], "not a list", [None, None], ["", ""], ["only one"]])
def test_bad_backend_batches_are_rejected(output):
    class Bad:
        def translate_batch(self, *args, **kwargs):
            return output
    with pytest.raises(TranslationError):
        translate(sample(), translator=Bad(), target_language="en")


def test_cancellation_prevents_more_requests_and_empty_input_does_not_call_backend():
    backend = EchoBackend()
    with pytest.raises(OperationCancelled):
        translate(sample(), translator=backend, target_language="en", cancelled=lambda: True)
    assert not backend.calls
    with pytest.raises(OperationCancelled):
        translate(sample(), translator=backend, target_language="en", batch_size=1, cancelled=lambda: bool(backend.calls))
    assert len(backend.calls) == 1
    empty = translate(Subtitle(()), translator=backend, target_language="en")
    assert len(empty) == 0 and len(backend.calls) == 1


def test_invalid_translation_arguments_and_backend_errors_are_safe():
    for batch_size in [0, True, 1.5]:
        with pytest.raises(ValidationError):
            translate(sample(), translator=EchoBackend(), target_language="en", batch_size=batch_size)
    class Failing:
        def translate_batch(self, *args, **kwargs):
            raise RuntimeError("secret-do-not-leak")
    with pytest.raises(TranslationError) as error:
        translate(sample(), translator=Failing(), target_language="en")
    assert "secret" not in str(error.value)


def test_core_import_and_io_need_no_web_storage_models_or_network(tmp_path):
    root = Path(__file__).resolve().parents[1]
    code = f'''
import sys, importlib.abc, socket
sys.path.insert(0, {str(root)!r})
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'video_translate','cv2','paddle','paddleocr','numpy','requests','yaml','redis','pymysql','faster_whisper','opencc'}}:
            raise RuntimeError('unexpected dependency: '+fullname)
sys.meta_path.insert(0, Block())
socket.socket.connect = lambda *args: (_ for _ in ()).throw(RuntimeError('network forbidden'))
from reibosub import Subtitle
s = Subtitle.loads('1\\n00:00:00,000 --> 00:00:01,000\\nHello\\n')
assert 'WEBVTT' in s.dumps('vtt')
assert Subtitle.loads(s.dumps('json'), format='json')[0].text == 'Hello'
'''
    subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, check=True, capture_output=True, text=True)
