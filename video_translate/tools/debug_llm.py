from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from video_translate.tools.correct_asr import build_correction_payload
from video_translate.llm_config import LLMTaskConfig, load_llm_task_config
from video_translate.subtitle.srt import read_srt
from video_translate.translate.glossary import load_glossary
from video_translate.translate.volcengine import DEFAULT_BASE_URL, _chat_completions_url, _load_dotenv


ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _load_dotenv(ROOT)
    task_llm = resolve_debug_llm(args)
    key = task_llm.api_key or ""
    model = task_llm.model or ""
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 LLM_API_KEY")
    if not model:
        raise RuntimeError("缺少 LLM_MODEL 或任务专用模型配置")

    payload = build_payload(args, model)
    payload_json = json.dumps(payload, ensure_ascii=False)
    print("llm_debug_config:")
    print(f"  endpoint: {endpoint}")
    print(f"  model: {model}")
    print(f"  api_key: {mask_secret(key)}")
    print(f"  mode: {args.mode}")
    print(f"  timeout: {args.timeout}s")
    print(f"  repeats: {args.repeats}")
    print(f"  payload_chars: {len(payload_json)}")
    print(f"  user_content_chars: {len(payload['messages'][1]['content'])}")
    if args.dry_run:
        print("llm_debug_dry_run_payload:")
        print(payload_json[: args.preview_chars])
        return

    for attempt in range(1, args.repeats + 1):
        run_once(endpoint, key, payload, timeout=args.timeout, attempt=attempt, preview_chars=args.preview_chars)


def resolve_debug_llm(args: argparse.Namespace) -> LLMTaskConfig:
    if args.mode == "asr-correct":
        return load_llm_task_config(
            "asr_correction",
            root=ROOT,
            explicit_model=args.model,
            explicit_base_url=args.base_url,
        )
    return LLMTaskConfig(
        model=args.model or os.environ.get("LLM_MODEL") or os.environ.get("ARK_MODEL", ""),
        base_url=args.base_url or os.environ.get("LLM_BASE_URL") or os.environ.get("ARK_BASE_URL") or DEFAULT_BASE_URL,
        api_key=os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY", ""),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Directly diagnose Volcengine Ark chat/completions latency and response.")
    parser.add_argument("--mode", choices=["simple", "asr-correct"], default="simple")
    parser.add_argument("--source-srt", type=Path, default=None, help="SRT used by --mode asr-correct")
    parser.add_argument("--glossary", type=Path, default=None)
    parser.add_argument("--start-index", type=int, default=1, help="First SRT cue index for asr-correct mode")
    parser.add_argument("--batch-size", type=int, default=5, help="Number of cues for asr-correct mode")
    parser.add_argument("--source-language", default="korean")
    parser.add_argument("--extra-prompt", default="")
    parser.add_argument("--prompt", default="请用 JSON 回复：{\"ok\": true, \"message\": \"pong\"}")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--preview-chars", type=int, default=1200)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def build_payload(args: argparse.Namespace, model: str) -> dict[str, Any]:
    if args.mode == "simple":
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是接口连通性诊断助手。只输出 JSON。"},
                {"role": "user", "content": args.prompt},
            ],
            "temperature": 0.1,
        }
    if args.mode == "asr-correct":
        if not args.source_srt:
            raise ValueError("--mode asr-correct 需要 --source-srt")
        cues = select_cues(args.source_srt, start_index=args.start_index, batch_size=args.batch_size)
        glossary = load_glossary(args.glossary)
        return build_correction_payload(
            cues,
            model=model,
            source_language=args.source_language,
            glossary_context=glossary.to_context([cue.text for cue in cues]),
            extra_prompt=args.extra_prompt,
        )
    raise ValueError(f"未知 mode: {args.mode}")


def select_cues(source_srt: Path, *, start_index: int, batch_size: int):
    cues = read_srt(source_srt.expanduser().resolve())
    selected = [cue for cue in cues if cue.index >= start_index][:batch_size]
    if not selected:
        raise ValueError(f"没有选中字幕: start_index={start_index}, batch_size={batch_size}")
    return selected


def run_once(endpoint: str, key: str, payload: dict[str, Any], *, timeout: float, attempt: int, preview_chars: int) -> None:
    start = time.monotonic()
    print(f"llm_debug_request_start: attempt={attempt}")
    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        print(f"llm_debug_response: attempt={attempt} status={response.status_code} elapsed={elapsed:.2f}s")
        text = response.text
        print(f"llm_debug_response_chars: {len(text)}")
        print(text[:preview_chars])
        response.raise_for_status()
    except requests.Timeout as exc:
        elapsed = time.monotonic() - start
        print(f"llm_debug_timeout: attempt={attempt} elapsed={elapsed:.2f}s {exc}")
    except requests.RequestException as exc:
        elapsed = time.monotonic() - start
        print(f"llm_debug_request_error: attempt={attempt} elapsed={elapsed:.2f}s {exc}")


def mask_secret(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 7) + value[-4:]


if __name__ == "__main__":
    main()
