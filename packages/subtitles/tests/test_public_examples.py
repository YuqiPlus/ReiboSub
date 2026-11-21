from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from reibosub import Subtitle


def test_offline_development_examples_run_from_an_unrelated_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root)}
    for name, arguments in [
        ("subtitle_basics.py", ["--out-dir", str(tmp_path / "basic")]),
        ("custom_backend.py", ["--out", str(tmp_path / "custom.en.srt")]),
        ("custom_format.py", ["--out", str(tmp_path / "custom.tsv")]),
        ("translate_service.py", ["--help"]),
    ]:
        subprocess.run([sys.executable, str(root / "examples" / "python_api" / name), *arguments], cwd=tmp_path, env=env, check=True, capture_output=True, text=True)
    assert Subtitle.load(tmp_path / "basic" / "simplified.srt")[0].text == "数据与美学。"
    assert Subtitle.load(tmp_path / "custom.en.srt")[0].text == "Hello."
    assert "自定义格式" in (tmp_path / "custom.tsv").read_text()
