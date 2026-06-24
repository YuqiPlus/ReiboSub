from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from video_translate.tools import debug_llm


def test_mask_secret_keeps_only_edges():
    assert debug_llm.mask_secret("abcdefghi1234") == "abc******1234"
    assert debug_llm.mask_secret("short") == "*****"


def test_build_simple_payload_uses_prompt():
    args = Namespace(mode="simple", prompt='{"ping": true}')

    payload = debug_llm.build_payload(args, "model-id")

    assert payload["model"] == "model-id"
    assert payload["messages"][1]["content"] == '{"ping": true}'


def test_resolve_debug_llm_uses_asr_task_config_for_asr_mode(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text(
        "defaults:\n  model: default-model\n"
        "tasks:\n  asr_correction:\n    model: configured-lite\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_llm, "ROOT", tmp_path)
    monkeypatch.setenv("ARK_MODEL", "env-model")
    args = Namespace(mode="asr-correct", model=None, base_url=None)

    task = debug_llm.resolve_debug_llm(args)

    assert task.model == "configured-lite"


def test_select_cues_uses_srt_indices(tmp_path: Path):
    source = tmp_path / "source.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n하나\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n둘\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\n셋\n",
        encoding="utf-8",
    )

    cues = debug_llm.select_cues(source, start_index=2, batch_size=2)

    assert [cue.index for cue in cues] == [2, 3]
    assert [cue.text for cue in cues] == ["둘", "셋"]
