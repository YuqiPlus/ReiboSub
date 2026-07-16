from __future__ import annotations

import os
from pathlib import Path

import pytest

from video_translate.env import load_dotenv


def test_loads_local_runtime_yaml_without_dotenv(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "configs" / "local_runtime.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """
version: 1
environment:
  VIDEO_TRANSLATE_OCR_DEVICE: gpu:0
  YTDLP_PROXY: http://127.0.0.1:7890
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIDEO_TRANSLATE_OCR_DEVICE", raising=False)
    monkeypatch.delenv("YTDLP_PROXY", raising=False)

    load_dotenv(tmp_path)

    assert os.environ["VIDEO_TRANSLATE_OCR_DEVICE"] == "gpu:0"
    assert os.environ["YTDLP_PROXY"] == "http://127.0.0.1:7890"


def test_local_runtime_precedes_dotenv_unless_override_requested(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "configs" / "local_runtime.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "version: 1\nenvironment:\n  VIDEO_TRANSLATE_PORT: 9000\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("VIDEO_TRANSLATE_PORT=9100\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIDEO_TRANSLATE_PORT", raising=False)

    load_dotenv(tmp_path)
    assert os.environ["VIDEO_TRANSLATE_PORT"] == "9000"

    load_dotenv(tmp_path, override=True)
    assert os.environ["VIDEO_TRANSLATE_PORT"] == "9100"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("version: 1\nenvironment: [broken\n", "不是有效的 YAML"),
        ("version: 2\nenvironment: {}\n", "version: 1"),
        ("version: 1\nenvironment:\n  ARK_API_KEY: secret\n", "不支持的配置项"),
        ("version: 1\nenvironment:\n  YTDLP_PROXY: [bad]\n", "必须是标量值"),
    ],
)
def test_local_runtime_rejects_invalid_or_secret_fields(
    tmp_path: Path,
    monkeypatch,
    content: str,
    message: str,
) -> None:
    config = tmp_path / "configs" / "local_runtime.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(content, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match=message):
        load_dotenv(tmp_path)
