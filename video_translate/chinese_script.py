"""Chinese ASR presentation only; never alter raw recognition or timing evidence."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCRIPT_FILE = "text_presentation.json"
SCRIPTS = {"simplified", "traditional", "original"}


def normalize_chinese_script(value=None) -> str:
    script = str(value or "simplified").strip().lower()
    if script not in SCRIPTS:
        raise ValueError("中文输出须选择简体、繁体或保留识别原样")
    return script


@lru_cache(maxsize=2)
def _converter(script: str):
    try:
        from opencc import OpenCC
    except ImportError as exc:
        raise RuntimeError("中文简繁转换缺少依赖，请安装 opencc-python-reimplemented，或选择保留识别原样") from exc
    return OpenCC("t2s" if script == "simplified" else "s2t")


def convert_chinese_text(text: str, script: str) -> str:
    script = normalize_chinese_script(script)
    return text if script == "original" else _converter(script).convert(text)


def configure_chinese_output(output_dir: Path, script: str, language: str) -> str:
    """Persist resolved policy for gap-review rebuilds; non-Chinese is untouched."""
    script = normalize_chinese_script(script)
    is_chinese = str(language or "").strip().lower().replace("_", "-") in {"zh", "chinese", "zh-cn", "zh-tw", "zh-hans", "zh-hant"}
    resolved = script if is_chinese else "original"
    if resolved != "original":
        _converter(resolved)  # Fail before writing any converted outputs.
    (output_dir / SCRIPT_FILE).write_text(json.dumps({"chinese_script": resolved, "language": language}, ensure_ascii=False) + "\n", encoding="utf-8")
    return resolved


def output_chinese_script(output_dir: Path) -> str:
    path = output_dir / SCRIPT_FILE
    if not path.exists():
        return "original"  # Legacy/experimental output directories retain old behavior.
    return normalize_chinese_script(json.loads(path.read_text(encoding="utf-8"))["chinese_script"])
