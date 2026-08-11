from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import write_srt


DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
UNKNOWN_SPEAKER = "Speaker ?"


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "speaker": self.speaker,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SpeakerTurn":
        return cls(
            start=float(value["start"]),
            end=float(value["end"]),
            speaker=str(value["speaker"]),
        )


def diarization_model_source() -> str:
    return os.environ.get("PYANNOTE_DIARIZATION_MODEL", "").strip() or DEFAULT_DIARIZATION_MODEL


def diarization_token() -> str:
    return (
        os.environ.get("HF_TOKEN", "").strip()
        or os.environ.get("HUGGINGFACE_HUB_TOKEN", "").strip()
    )


def ensure_diarization_ready() -> None:
    try:
        package_available = importlib.util.find_spec("pyannote.audio") is not None
    except (ImportError, ModuleNotFoundError):
        package_available = False
    if not package_available:
        raise RuntimeError(
            '说话人分离组件未安装。请在服务环境中运行 '
            '`python -m pip install -e ".[diarization]"`，然后重启服务。'
        )

    model_source = diarization_model_source()
    if not Path(model_source).expanduser().exists() and not diarization_token():
        raise RuntimeError(
            "说话人分离模型尚未授权。请先在 Hugging Face 接受 "
            "pyannote/speaker-diarization-community-1 的使用条件，"
            "再把 HF_TOKEN 写入项目 .env 并重启服务。"
        )


def _annotation_rows(annotation: Any) -> Iterable[tuple[Any, str]]:
    if hasattr(annotation, "itertracks"):
        for segment, _track, label in annotation.itertracks(yield_label=True):
            yield segment, str(label)
        return

    for item in annotation:
        if not isinstance(item, tuple):
            continue
        if len(item) == 2:
            segment, label = item
        elif len(item) >= 3:
            segment, _track, label = item[:3]
        else:
            continue
        yield segment, str(label)


def _normalize_turns(annotation: Any) -> list[SpeakerTurn]:
    speaker_names: dict[str, str] = {}
    turns: list[SpeakerTurn] = []
    for segment, raw_speaker in _annotation_rows(annotation):
        start = float(segment.start)
        end = float(segment.end)
        if end <= start:
            continue
        speaker = speaker_names.setdefault(raw_speaker, f"Speaker {len(speaker_names) + 1}")
        turns.append(SpeakerTurn(start=start, end=end, speaker=speaker))
    return sorted(turns, key=lambda item: (item.start, item.end, item.speaker))


def _decode_audio(input_media: Path, torch_module: Any) -> dict[str, Any]:
    configured_ffmpeg = os.environ.get("FFMPEG_BINARY", "").strip()
    adjacent_ffmpeg = Path(sys.executable).with_name("ffmpeg")
    ffmpeg = configured_ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg and adjacent_ffmpeg.is_file():
        ffmpeg = str(adjacent_ffmpeg)
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法为说话人分离解码音频。")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_media),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg 解码音频失败：{detail or exc}") from exc
    if not completed.stdout:
        raise RuntimeError("ffmpeg 没有解码出可用于说话人分离的音频。")

    waveform = torch_module.frombuffer(bytearray(completed.stdout), dtype=torch_module.float32).reshape(1, -1)
    return {"waveform": waveform, "sample_rate": 16000}


def diarize_speakers(
    input_media: Path,
    *,
    model_source: str | None = None,
    token: str | None = None,
    device: str = "auto",
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[SpeakerTurn]:
    ensure_diarization_ready()

    import torch
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"\s*torchcodec is not installed correctly.*",
            category=UserWarning,
        )
        from pyannote.audio import Pipeline

    source = model_source or diarization_model_source()
    auth_token = token if token is not None else diarization_token()
    try:
        pipeline = Pipeline.from_pretrained(source, token=auth_token or None)
    except Exception as exc:
        raise RuntimeError(
            "无法加载说话人分离模型。请检查 HF_TOKEN、模型使用条件和网络连接；"
            f"原始错误：{exc}"
        ) from exc

    requested_device = device.strip().lower()
    if requested_device == "auto":
        requested_device = "cuda" if torch.cuda.is_available() else "cpu"
    if requested_device.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("说话人分离请求使用 CUDA，但当前 PyTorch 未检测到可用 GPU。")
        pipeline.to(torch.device(requested_device))
    elif requested_device != "cpu":
        pipeline.to(torch.device(requested_device))

    options: dict[str, int] = {}
    if num_speakers is not None:
        options["num_speakers"] = num_speakers
    if min_speakers is not None:
        options["min_speakers"] = min_speakers
    if max_speakers is not None:
        options["max_speakers"] = max_speakers

    try:
        audio = _decode_audio(input_media, torch)
        output = pipeline(audio, **options)
    except Exception as exc:
        raise RuntimeError(f"说话人分离失败：{exc}") from exc

    annotation = getattr(output, "exclusive_speaker_diarization", None)
    if annotation is None:
        annotation = getattr(output, "speaker_diarization", output)
    return _normalize_turns(annotation)


def assign_speakers_to_cues(
    cues: list[SubtitleCue],
    turns: list[SpeakerTurn],
    *,
    max_nearest_gap: float = 0.75,
) -> list[str]:
    speakers: list[str] = []
    for cue in cues:
        overlap_by_speaker: dict[str, float] = {}
        first_turn_by_speaker: dict[str, float] = {}
        for turn in turns:
            overlap = max(0.0, min(cue.end, turn.end) - max(cue.start, turn.start))
            if overlap <= 0:
                continue
            overlap_by_speaker[turn.speaker] = overlap_by_speaker.get(turn.speaker, 0.0) + overlap
            first_turn_by_speaker.setdefault(turn.speaker, turn.start)

        if overlap_by_speaker:
            speakers.append(
                max(
                    overlap_by_speaker,
                    key=lambda speaker: (
                        overlap_by_speaker[speaker],
                        -first_turn_by_speaker[speaker],
                    ),
                )
            )
            continue

        nearest: tuple[float, float, str] | None = None
        for turn in turns:
            if turn.end < cue.start:
                gap = cue.start - turn.end
            elif turn.start > cue.end:
                gap = turn.start - cue.end
            else:
                gap = 0.0
            candidate = (gap, turn.start, turn.speaker)
            if nearest is None or candidate < nearest:
                nearest = candidate
        speakers.append(nearest[2] if nearest and nearest[0] <= max_nearest_gap else UNKNOWN_SPEAKER)
    return speakers


def speaker_labeled_cues(cues: list[SubtitleCue], speakers: list[str]) -> list[SubtitleCue]:
    if len(cues) != len(speakers):
        raise ValueError("字幕片段和说话人标签数量不一致")
    return [
        SubtitleCue(
            index=cue.index,
            start=cue.start,
            end=cue.end,
            text=f"{speaker}: {cue.text.strip()}",
            source_track_id=cue.source_track_id,
        )
        for cue, speaker in zip(cues, speakers, strict=True)
    ]


def speaker_transcript_text(cues: list[SubtitleCue], speakers: list[str]) -> str:
    labeled = speaker_labeled_cues(cues, speakers)
    lines = [cue.text for cue in labeled if cue.text.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


def write_speaker_outputs(
    cues: list[SubtitleCue],
    turns: list[SpeakerTurn],
    *,
    srt_path: Path,
    text_path: Path,
) -> list[str]:
    speakers = assign_speakers_to_cues(cues, turns)
    write_srt(speaker_labeled_cues(cues, speakers), srt_path)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(speaker_transcript_text(cues, speakers), encoding="utf-8")
    return speakers


def write_turns_json(
    path: Path,
    turns: list[SpeakerTurn],
    *,
    model_source: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model_source or diarization_model_source(),
        "speaker_count": len({turn.speaker for turn in turns}),
        "turns": [turn.to_dict() for turn in turns],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_turns_json(path: Path) -> list[SpeakerTurn]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_turns = payload.get("turns") if isinstance(payload, dict) else payload
    if not isinstance(raw_turns, list):
        raise ValueError("说话人分离结果缺少 turns 数组")
    return [SpeakerTurn.from_dict(item) for item in raw_turns if isinstance(item, dict)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Separate speakers in an audio or video file.")
    parser.add_argument("input_media", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--num-speakers", type=int)
    parser.add_argument("--min-speakers", type=int)
    parser.add_argument("--max-speakers", type=int)
    args = parser.parse_args()

    turns = diarize_speakers(
        args.input_media,
        model_source=args.model or None,
        device=args.device,
        num_speakers=args.num_speakers,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
    )
    write_turns_json(args.out, turns, model_source=args.model or None)
    print(f"speaker_turns: {args.out}")
    print(f"speaker_count: {len({turn.speaker for turn in turns})}")


if __name__ == "__main__":
    main()
