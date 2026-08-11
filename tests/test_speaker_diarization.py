from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt
from video_translate.tools.diarize_speakers import (
    UNKNOWN_SPEAKER,
    SpeakerTurn,
    _decode_audio,
    _normalize_turns,
    assign_speakers_to_cues,
    read_turns_json,
    write_speaker_outputs,
    write_turns_json,
)


class _Segment:
    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


class _Annotation:
    def itertracks(self, *, yield_label: bool):
        assert yield_label is True
        yield _Segment(1.0, 2.0), "track-b", "raw-b"
        yield _Segment(0.0, 1.0), "track-a", "raw-a"
        yield _Segment(2.0, 3.0), "track-c", "raw-a"


def _cue(index: int, start: float, end: float, text: str = "text") -> SubtitleCue:
    return SubtitleCue(index=index, start=start, end=end, text=text)


def test_normalize_turns_uses_stable_human_labels_and_sorts() -> None:
    turns = _normalize_turns(_Annotation())

    assert [(turn.start, turn.end, turn.speaker) for turn in turns] == [
        (0.0, 1.0, "Speaker 2"),
        (1.0, 2.0, "Speaker 1"),
        (2.0, 3.0, "Speaker 2"),
    ]


def test_assign_speakers_prefers_largest_total_overlap() -> None:
    cues = [_cue(1, 0.0, 2.0), _cue(2, 2.0, 3.0)]
    turns = [
        SpeakerTurn(0.0, 0.6, "Speaker 1"),
        SpeakerTurn(0.6, 2.0, "Speaker 2"),
        SpeakerTurn(2.0, 3.0, "Speaker 1"),
    ]

    assert assign_speakers_to_cues(cues, turns) == ["Speaker 2", "Speaker 1"]


def test_assign_speakers_uses_nearest_turn_only_for_small_gap() -> None:
    turns = [SpeakerTurn(1.0, 2.0, "Speaker 1")]
    cues = [_cue(1, 2.4, 2.8), _cue(2, 4.0, 5.0)]

    assert assign_speakers_to_cues(cues, turns) == ["Speaker 1", UNKNOWN_SPEAKER]


def test_write_speaker_outputs_labels_srt_and_text(tmp_path: Path) -> None:
    cues = [
        _cue(1, 0.0, 1.0, "Hello"),
        _cue(2, 1.0, 2.0, "Hi"),
    ]
    turns = [
        SpeakerTurn(0.0, 1.0, "Speaker 1"),
        SpeakerTurn(1.0, 2.0, "Speaker 2"),
    ]
    srt_path = tmp_path / "speakers.srt"
    text_path = tmp_path / "transcript.txt"

    speakers = write_speaker_outputs(cues, turns, srt_path=srt_path, text_path=text_path)

    assert speakers == ["Speaker 1", "Speaker 2"]
    assert [cue.text for cue in read_srt(srt_path)] == [
        "Speaker 1: Hello",
        "Speaker 2: Hi",
    ]
    assert text_path.read_text(encoding="utf-8") == "Speaker 1: Hello\nSpeaker 2: Hi\n"


def test_turns_json_round_trip(tmp_path: Path) -> None:
    turns = [
        SpeakerTurn(0.12345, 1.23456, "Speaker 1"),
        SpeakerTurn(1.5, 2.0, "Speaker 2"),
    ]
    path = tmp_path / "turns.json"

    write_turns_json(path, turns, model_source="local-model")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["model"] == "local-model"
    assert payload["speaker_count"] == 2
    assert read_turns_json(path) == [
        SpeakerTurn(0.123, 1.235, "Speaker 1"),
        SpeakerTurn(1.5, 2.0, "Speaker 2"),
    ]


def test_decode_audio_uses_ffmpeg_and_returns_mono_16khz(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr(
        "video_translate.tools.diarize_speakers.shutil.which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )

    def fake_run(command, *, check, capture_output):
        calls.append(command)
        assert check is True
        assert capture_output is True
        return SimpleNamespace(stdout=b"\x00" * 8)

    monkeypatch.setattr("video_translate.tools.diarize_speakers.subprocess.run", fake_run)

    class FakeTensor:
        def reshape(self, *shape):
            self.shape = shape
            return self

    tensor = FakeTensor()
    torch_module = SimpleNamespace(
        float32="float32",
        frombuffer=lambda value, *, dtype: tensor,
    )

    result = _decode_audio(tmp_path / "input.m4a", torch_module)

    assert result == {"waveform": tensor, "sample_rate": 16000}
    assert tensor.shape == (1, -1)
    assert calls[0][0] == "/usr/bin/ffmpeg"
    assert calls[0][calls[0].index("-ar") + 1] == "16000"
    assert calls[0][calls[0].index("-ac") + 1] == "1"
