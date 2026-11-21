from pathlib import Path

import pytest

from video_translate.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_reibosub_and_legacy_cli_alias() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "reibosub"' in pyproject
    assert 'reibosub = "reibosub.cli:main"' in pyproject
    assert 'video-translate = "video_translate.cli:main"' in pyproject
    assert "https://github.com/YuqiPlus/ReiboSub" in pyproject


def test_cli_help_uses_reibosub_brand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith("usage: reibosub")
