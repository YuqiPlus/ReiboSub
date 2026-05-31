from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.translate.glossary import load_glossary


DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


def translate_srt_with_volcengine(
    source_srt: Path,
    out_srt: Path,
    *,
    glossary_path: Path | None = None,
    batch_size: int = 40,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    target_language: str = "简体中文",
) -> Path:
    _load_dotenv(source_srt)
    key = api_key or os.environ.get("ARK_API_KEY")
    selected_model = model or os.environ.get("ARK_MODEL")
    endpoint = _chat_completions_url(base_url or os.environ.get("ARK_BASE_URL") or DEFAULT_BASE_URL)

    if not key:
        raise RuntimeError("缺少 ARK_API_KEY，请先配置火山方舟 API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ARK_MODEL，请先配置火山方舟模型名或接入点 ID。")

    cues = read_srt(source_srt)
    glossary = load_glossary(glossary_path)
    translated: list[SubtitleCue] = []

    for offset in range(0, len(cues), batch_size):
        batch = cues[offset : offset + batch_size]
        payload = _build_payload(
            batch,
            glossary.to_context([cue.text for cue in batch]),
            selected_model,
            target_language,
        )
        result = _request_translation(endpoint, key, payload)
        mapping = _parse_translation_mapping(result)
        for cue in batch:
            translated.append(
                SubtitleCue(
                    index=cue.index,
                    start=cue.start,
                    end=cue.end,
                    text=mapping.get(cue.index, cue.text),
                    source_track_id=cue.source_track_id,
                )
            )

    write_srt(translated, out_srt)
    return out_srt


def _build_payload(
    cues: list[SubtitleCue],
    context: dict[str, Any],
    model: str,
    target_language: str,
) -> dict[str, Any]:
    subtitles = [
        {
            "id": cue.index,
            "start": cue.start,
            "end": cue.end,
            "source": cue.text,
        }
        for cue in cues
    ]
    system = (
        f"你是专业影视字幕翻译。把韩语/日语等原文字幕翻译成自然、简洁、口语化的{target_language}。"
        "必须保持 id 不变，不要增删字幕条目，不要解释。只输出 JSON 数组。"
    )
    user = {
        "context": context,
        "rules": [
            "遵守术语表和角色名翻译。",
            "修复明显 OCR 断字或多余空格。",
            "不要翻译 logo、水印或节目固定标题，输入里若出现也保持克制处理。",
            "输出格式为 [{\"id\": 1, \"zh\": \"中文字幕\"}]。",
        ],
        "subtitles": subtitles,
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.2,
    }


def _request_translation(url: str, api_key: str, payload: dict[str, Any]) -> str:
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"])


def _parse_translation_mapping(content: str) -> dict[int, str]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        parsed = parsed.get("translations") or parsed.get("items") or []
    mapping: dict[int, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id") or item.get("index")
        raw_text = item.get("zh") or item.get("text") or item.get("translation")
        if raw_id is not None and raw_text is not None:
            mapping[int(raw_id)] = str(raw_text)
    return mapping


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _load_dotenv(anchor: Path) -> None:
    for candidate in [Path.cwd() / ".env", anchor.resolve().parent / ".env"]:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
