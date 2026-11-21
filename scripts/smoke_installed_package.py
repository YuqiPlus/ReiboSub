"""Offline, installed-wheel/sdist smoke test; run outside the source checkout."""
from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from reibosub import Cue, Subtitle, check_feature, convert, translate


def main() -> None:
    import reibosub
    assert "site-packages" in str(Path(reibosub.__file__).resolve())
    assert check_feature("core").ready
    assert not {"numpy", "paddle", "paddleocr", "faster_whisper", "torch", "cv2"} & sys.modules.keys()
    for module in ("numpy", "paddleocr", "faster_whisper", "cv2"):
        assert importlib.util.find_spec(module) is None, f"Default install unexpectedly contains {module}"
    assert not any(name.startswith("video_translate") for name in sys.modules)
    source = Subtitle((Cue(1, 0.5, 2.0, "繁體字幕"), Cue(2, 2.5, 4.0, "歡迎")), language="zh-Hant")
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        source.save(folder / "source.srt")
        loaded = Subtitle.load(folder / "source.srt")
        assert loaded.cues == source.cues
        convert(folder / "source.srt", folder / "converted.vtt")
        assert Subtitle.load(folder / "converted.vtt").cues == source.cues
        assert source.to_simplified()[0].text == "繁体字幕"
        assert source.to_simplified().to_traditional()[1].text == "歡迎"
        try:
            source.save(folder / "source.srt")
        except FileExistsError:
            pass
        else:
            raise AssertionError("Existing subtitles must not be overwritten by default")
        class Backend:
            def translate_batch(self, texts, *, source_language, target_language):
                return ["Subtitle", "Welcome"]
        result = translate(source, translator=Backend(), target_language="en")
        assert [(c.index, c.start, c.end) for c in result] == [(c.index, c.start, c.end) for c in source]
        assert result.to_text() == "Subtitle\nWelcome"
        subprocess.run([sys.executable, "-m", "reibosub.cli", "convert", str(folder / "source.srt"), str(folder / "cli.json")], check=True)
        assert Subtitle.load(folder / "cli.json").cues == source.cues
    print(f"PASS installed ReiboSub {metadata.version('reibosub')}: read/write, formats, scripts, translation and CLI")


if __name__ == "__main__":
    main()
