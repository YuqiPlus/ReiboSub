import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

from video_translate.subtitle.srt import read_srt
from video_translate.llm_config import load_llm_task_config
from video_translate.translate.volcengine import DEFAULT_BASE_URL, _chat_completions_url, _load_dotenv, _parse_json_content
from video_translate.utils.text import comparable_text
from video_translate.translation_languages import target_language_code, target_language_name


DEFAULT_TARGET_LANGUAGE = "简体中文"
DEFAULT_BATCH_SIZE = 40
DEFAULT_MAX_CHARS_PER_BATCH = 9000
COMMON_SKIP_TERMS = [
    "Disney",
    "Disneyland",
    "Hong Kong Disneyland",
    "YouTube",
    "Vlog",
    "airport",
    "hotel",
    "cafe",
    "city",
    "country",
    "디즈니",
    "디즈니랜드",
    "홍콩 디즈니랜드",
    "유튜브",
    "브이로그",
    "공항",
    "호텔",
    "카페",
    "배우",
    "연기",
    "촬영",
    "여행",
    "식사",
    "대기",
    "티켓",
    "주년",
    "놀이기구",
    "식당",
    "가게",
]


SYSTEM_PROMPT = """你是影视字幕术语表整理助手。你的任务不是做百科式专有名词抽取，而是找出少数真正需要人工裁决固定译法的项目。宁可少提，不要泛化。"""


EXTRACTION_RULES = [
    "目标是降低人工负担：只提取如果不人工确认就可能在全片翻错、译名不一致或风格不统一的项目。",
    "必须优先提取：韩语/日语/英文人名、艺名、角色名、昵称、CP/粉丝梗、作品名、节目名、频道名、任务内反复出现且有特殊含义的固定梗。",
    "尤其关注韩语人名对应的中文汉字不确定项，例如 박보영 可能需要确认是朴宝英而不是朴宝荣；这类应进入 characters。",
    "如果 extra_hint 已经给出某个人名/作品名/角色名，也应收进草稿，并把 suggested_zh 填成 hint 中的建议译法。",
    "不要提取有稳定通用译法、模型通常不会翻错的普通地点/品牌/平台/设施，例如 Disney、Disneyland、Hong Kong Disneyland、YouTube、Vlog、airport、hotel、cafe、city/country names，除非 extra_hint 明确要求特殊译法。",
    "不要提取普通职业、动作、场景类别或直译词，例如 演员、演戏、拍摄、旅行、吃饭、排队、门票、周年、游乐设施、餐厅、商店。",
    "不要提取完整台词、寒暄、普通名词短语、一次性描述、日期、数字、表情符号、噪声。",
    "如果字幕文本包含“韩文原文：...\\n英文参考：...”，必须以韩文原文为候选来源；英文参考只用于理解上下文、罗马音和专名含义，不要把普通英文译词单独提取为术语。",
    "source 使用字幕中的原文写法；aliases 只放同一项目的昵称、简称、英文/韩文/日文变体或明显拼写变体。",
    "suggested_zh 只给出你有较高把握的建议；不确定就留空，并在 note 中写明需要人工确认的具体原因。",
    "note 必须说明为什么这个条目需要人工确认；如果说不出原因，就不要输出该条目。",
    "characters 只放人物/角色/艺名/昵称；terms 放作品名、节目名、频道名、任务内固定梗或特殊译法。",
    "program 只在能明确判断主作品/主节目/主频道且它会影响全片译名一致性时填写，否则为 null。",
    "evidence_ids 放出现这些候选项的字幕 id，最多 8 个。",
    "输出必须是 JSON 对象，不要解释，不要 Markdown。",
]


def build_extraction_payload(
    cues: list[dict[str, Any]],
    *,
    model: str,
    source_language: str,
    target_language: str,
    extra_hint: str = "",
) -> dict[str, Any]:
    user = {
        "source_language": source_language,
        "target_language": target_language,
        "rules": EXTRACTION_RULES,
        "output_schema": {
            "program": {
                "source": "原文标题或品牌名",
                "suggested_zh": "建议中文名，可为空",
                "aliases": ["别名"],
                "type": "program|show_title|brand|channel",
                "note": "为什么需要固定译法",
                "evidence_ids": [1, 2],
                "confidence": 0.0,
            },
            "characters": [
                {
                    "source": "原文人名/角色名",
                    "suggested_zh": "建议中文译名，可为空",
                    "aliases": ["别名/英文名/昵称"],
                    "type": "person|character|nickname",
                    "note": "需要人工确认的原因",
                    "evidence_ids": [1, 2],
                    "confidence": 0.0,
                }
            ],
            "terms": [
                {
                    "source": "原文术语",
                    "suggested_zh": "建议中文译名，可为空",
                    "aliases": ["别名"],
                    "type": "term|brand|place|work|phrase",
                    "note": "使用语境",
                    "evidence_ids": [1, 2],
                    "confidence": 0.0,
                }
            ],
        },
        "extra_hint": extra_hint,
        "subtitles": cues,
    }
    code = target_language_code(target_language)
    user['target_language'] = target_language_name(code)
    user['rules'] = [*EXTRACTION_RULES,
        'source、aliases保留原文；suggested_zh是历史字段名，内容必须是目标语言的推荐译名，不代表必须翻成中文。',
        '原文也可能是中文；中文人名翻成英语时优先可靠的官方英文名或规范拼音，不猜英文身份，不确定时留空让用户确认。']
    if code != 'zh':
        user['rules'] = [r for r in user['rules'] if '韩语人名对应的中文汉字' not in r]
    for section in ('program', 'characters', 'terms'):
        schema = user['output_schema'][section]
        (schema[0] if isinstance(schema, list) else schema)['suggested_zh'] = f'建议{target_language_name(code)}译名，可为空'
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }


def generate_glossary_draft(
    source_srt: Path,
    out_yaml: Path,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    source_language: str = "korean",
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_chars_per_batch: int = DEFAULT_MAX_CHARS_PER_BATCH,
    extra_hint: str = "",
    fill_suggestions: bool = False,
) -> Path:
    source_srt = source_srt.expanduser().resolve()
    out_yaml = out_yaml.expanduser().resolve()
    if not source_srt.exists():
        raise FileNotFoundError(f"字幕文件不存在: {source_srt}")

    _load_dotenv(source_srt)
    task_llm = load_llm_task_config("glossary", explicit_model=model, explicit_base_url=base_url)
    key = api_key or getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    selected_model = task_llm.model
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置 OpenAI-compatible API Key。")
    if not selected_model:
        raise RuntimeError("缺少 LLM_MODEL 或 glossary 任务专用模型配置。")

    cues = read_srt(source_srt)
    if not cues:
        raise ValueError(f"字幕里没有可读取的 SRT 条目: {source_srt}")

    draft: dict[str, Any] = {"program": None, "characters": [], "terms": []}
    batches = list(_chunk_cues(cues, batch_size=batch_size, max_chars=max_chars_per_batch))
    for batch_index, batch in enumerate(batches, start=1):
        print(f"glossary_batch: {batch_index}/{len(batches)} cues {batch[0]['id']}-{batch[-1]['id']}", flush=True)
        parsed = _request_batch_candidates(
            batch,
            endpoint=endpoint,
            api_key=key,
            model=selected_model,
            source_language=source_language,
            target_language=target_language,
            extra_hint=extra_hint,
            batch_label=f"{batch_index}/{len(batches)}",
        )
        draft = merge_candidate_drafts(draft, parsed)

    draft = filter_low_value_candidates(draft, extra_hint=extra_hint)
    normalized = normalize_draft_for_yaml(draft, fill_suggestions=fill_suggestions)
    normalized['target_language'] = target_language_code(target_language)
    normalized['source_language'] = source_language
    write_glossary_yaml(normalized, out_yaml, source_srt=source_srt, fill_suggestions=fill_suggestions)
    return out_yaml


def _request_batch_candidates(
    batch: list[dict[str, Any]],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    source_language: str,
    target_language: str,
    extra_hint: str,
    batch_label: str,
) -> dict[str, Any]:
    payload = build_extraction_payload(
        batch,
        model=model,
        source_language=source_language,
        target_language=target_language,
        extra_hint=extra_hint,
    )
    try:
        content = _request_chat_completion(endpoint, api_key, payload, max_attempts=1)
    except (requests.Timeout, requests.ConnectionError) as exc:
        if len(batch) <= 1:
            print(f"glossary_batch_skipped: {batch_label} request_failed {exc}", flush=True)
            return {"program": None, "characters": [], "terms": []}
        mid = max(1, len(batch) // 2)
        left = batch[:mid]
        right = batch[mid:]
        print(
            f"glossary_batch_split: {batch_label} size={len(batch)} -> {len(left)}+{len(right)} after {type(exc).__name__}",
            flush=True,
        )
        return merge_candidate_drafts(
            _request_batch_candidates(
                left,
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                source_language=source_language,
                target_language=target_language,
                extra_hint=extra_hint,
                batch_label=f"{batch_label}a",
            ),
            _request_batch_candidates(
                right,
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                source_language=source_language,
                target_language=target_language,
                extra_hint=extra_hint,
                batch_label=f"{batch_label}b",
            ),
        )
    return parse_or_repair_candidate_response(
        content,
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        batch_index=0,
        total_batches=0,
        batch_label=batch_label,
    )


def parse_or_repair_candidate_response(
    content: str,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    batch_index: int,
    total_batches: int,
    batch_label: str | None = None,
) -> dict[str, Any]:
    label = batch_label or f"{batch_index}/{total_batches}"
    try:
        return parse_candidate_response(content)
    except Exception as exc:  # noqa: BLE001 - LLM JSON can be malformed in several ways.
        print(f"glossary_batch_parse_retry: {label} {exc}", flush=True)

    try:
        repaired = _request_chat_completion(endpoint, api_key, build_json_repair_payload(content, model=model))
        return parse_candidate_response(repaired)
    except Exception as exc:  # noqa: BLE001 - skip one batch instead of failing whole glossary.
        print(f"glossary_batch_skipped: {label} invalid_json_after_repair {exc}", flush=True)
        return {"program": None, "characters": [], "terms": []}


def parse_candidate_response(content: str) -> dict[str, Any]:
    parsed = _parse_json_candidate(content)
    if not isinstance(parsed, dict):
        raise ValueError("术语候选响应必须是 JSON 对象")
    return {
        "program": parsed.get("program"),
        "characters": _list_of_dicts(parsed.get("characters")),
        "terms": _list_of_dicts(parsed.get("terms")),
    }


def build_json_repair_payload(content: str, *, model: str) -> dict[str, Any]:
    user = {
        "task": "把 invalid_json 修复成合法 JSON 对象。只输出 JSON，不要解释，不要 Markdown。",
        "required_schema": {"program": None, "characters": [], "terms": []},
        "invalid_json": content,
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只负责修复 JSON 语法，不新增、不翻译、不解释。"},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.0,
    }


def _parse_json_candidate(content: str) -> Any:
    try:
        return _parse_json_content(content)
    except json.JSONDecodeError:
        extracted = _extract_json_object(content)
        if extracted and extracted != content.strip():
            return _parse_json_content(extracted)
        raise


def _extract_json_object(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1]


def merge_candidate_drafts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    program = left.get("program")
    incoming_program = right.get("program")
    if isinstance(incoming_program, dict) and _entry_source(incoming_program):
        if not isinstance(program, dict) or _confidence(incoming_program) >= _confidence(program):
            program = incoming_program

    return {
        "program": program,
        "characters": _merge_entry_lists(left.get("characters", []), right.get("characters", [])),
        "terms": _merge_entry_lists(left.get("terms", []), right.get("terms", [])),
    }


def filter_low_value_candidates(draft: dict[str, Any], *, extra_hint: str = "") -> dict[str, Any]:
    hint_key = comparable_text(extra_hint)
    return {
        "program": draft.get("program"),
        "characters": [
            item for item in draft.get("characters", [])
            if not _is_common_skip_candidate(item, hint_key=hint_key)
        ],
        "terms": [
            item for item in draft.get("terms", [])
            if not _is_common_skip_candidate(item, hint_key=hint_key)
        ],
    }


def _is_common_skip_candidate(item: Any, *, hint_key: str) -> bool:
    if not isinstance(item, dict):
        return True
    names = [_entry_source(item), *_string_list(item.get("aliases")), str(item.get("suggested_zh") or "")]
    name_keys = [comparable_text(name) for name in names if comparable_text(name)]
    if hint_key and any(key in hint_key for key in name_keys):
        return False
    common_keys = [comparable_text(value) for value in COMMON_SKIP_TERMS]
    return any(key and any(key == common or key in common or common in key for common in common_keys) for key in name_keys)


def normalize_draft_for_yaml(draft: dict[str, Any], *, fill_suggestions: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    program = draft.get("program")
    if isinstance(program, dict) and _entry_source(program):
        result["program"] = _yaml_entry(program, default_type="program", always=True, fill_suggestions=fill_suggestions)
    characters = [_yaml_entry(item, default_type="person", always=True, fill_suggestions=fill_suggestions) for item in draft.get("characters", []) if _entry_source(item)]
    terms = [_yaml_entry(item, default_type="term", always=False, fill_suggestions=fill_suggestions) for item in draft.get("terms", []) if _entry_source(item)]
    if characters:
        result["characters"] = characters
    if terms:
        result["terms"] = terms
    if not result:
        result["characters"] = []
        result["terms"] = []
    return result


def write_glossary_yaml(data: dict[str, Any], out_yaml: Path, *, source_srt: Path, fill_suggestions: bool = False) -> None:
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# Draft glossary generated from downloaded subtitles.",
        f"# source_srt: {source_srt}",
    ]
    if fill_suggestions:
        header.append("# zh fields were filled with model suggestions. Please review before translation.")
    else:
        header.append("# Fill zh fields manually before using this glossary for final translation.")
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    out_yaml.write_text("\n".join(header) + "\n" + text, encoding="utf-8")


def _request_chat_completion(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    max_attempts: int | None = None,
) -> str:
    timeout = _request_timeout_seconds()
    max_attempts = max(1, max_attempts or _request_max_attempts())
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                status = response.status_code
                if attempt < max_attempts and (status == 429 or 500 <= status < 600):
                    _sleep_before_retry(attempt, max_attempts, f"status={status}")
                    continue
                body = response.text.strip()
                model = payload.get("model", "")
                raise RuntimeError(f"Volcengine request failed: status={status}, model={model}, url={url}, body={body}") from exc
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt >= max_attempts:
                raise
            _sleep_before_retry(attempt, max_attempts, repr(exc))
    raise RuntimeError("Volcengine request failed after retries")


def _request_timeout_seconds() -> float:
    return float(os.environ.get("LLM_REQUEST_TIMEOUT") or os.environ.get("ARK_REQUEST_TIMEOUT", "240"))


def _request_max_attempts() -> int:
    return max(1, int(os.environ.get("LLM_REQUEST_RETRIES") or os.environ.get("ARK_REQUEST_RETRIES", "3")))


def _sleep_before_retry(attempt: int, max_attempts: int, reason: str) -> None:
    wait_seconds = min(2 ** (attempt - 1), 8)
    print(f"glossary_request_retry: attempt {attempt}/{max_attempts} wait={wait_seconds}s {reason}", flush=True)
    time.sleep(wait_seconds)


def _chunk_cues(cues, *, batch_size: int, max_chars: int):
    batch: list[dict[str, Any]] = []
    char_count = 0
    for cue in cues:
        text = cue.text.strip()
        item = {"id": cue.index, "source": text}
        projected = char_count + len(text)
        if batch and (len(batch) >= batch_size or projected > max_chars):
            yield batch
            batch = []
            char_count = 0
        batch.append(item)
        char_count += len(text)
    if batch:
        yield batch


def _merge_entry_lists(left: list[Any], right: list[Any]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in [*left, *right]:
        if not isinstance(item, dict):
            continue
        source = _entry_source(item)
        if not source:
            continue
        key = comparable_text(source)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = dict(item)
            order.append(key)
        else:
            by_key[key] = _merge_entry(by_key[key], item)
    return [by_key[key] for key in order]


def _merge_entry(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    if _confidence(right) > _confidence(left):
        for name in ["source", "suggested_zh", "type", "note", "confidence"]:
            if _has_value(right.get(name)):
                merged[name] = right[name]
    else:
        if not _has_value(merged.get("suggested_zh")) and _has_value(right.get("suggested_zh")):
            merged["suggested_zh"] = right["suggested_zh"]
        if not _has_value(merged.get("note")) and _has_value(right.get("note")):
            merged["note"] = right["note"]
    merged["aliases"] = _unique_strings([*_string_list(left.get("aliases")), *_string_list(right.get("aliases"))])
    merged["evidence_ids"] = _unique_ints([*_int_list(left.get("evidence_ids")), *_int_list(right.get("evidence_ids"))])[:8]
    merged["confidence"] = max(_confidence(left), _confidence(right))
    return merged


def _yaml_entry(item: dict[str, Any], *, default_type: str, always: bool, fill_suggestions: bool) -> dict[str, Any]:
    suggested = str(item.get("suggested_zh") or item.get("zh") or "").strip()
    entry: dict[str, Any] = {
        "source": _entry_source(item),
        "zh": suggested if fill_suggestions else "",
    }
    if suggested:
        entry["suggested_zh"] = suggested
    aliases = _unique_strings(_string_list(item.get("aliases")))
    if aliases:
        entry["aliases"] = aliases
    entry["type"] = str(item.get("type") or default_type)
    entry["always"] = always
    note_parts = []
    if item.get("note"):
        note_parts.append(str(item["note"]).strip())
    evidence = _int_list(item.get("evidence_ids"))[:8]
    if evidence:
        note_parts.append("evidence_ids: " + ", ".join(str(value) for value in evidence))
    confidence = item.get("confidence")
    if confidence is not None:
        note_parts.append(f"confidence: {_confidence(item):.2f}")
    if note_parts:
        entry["note"] = " | ".join(note_parts)
    return entry


def _entry_source(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("source") or item.get("name") or "").strip()


def _confidence(item: dict[str, Any]) -> float:
    try:
        return float(item.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _int_list(value: Any) -> list[int]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[int] = []
    for item in values:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        key = comparable_text(value)
        if value and key and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _unique_ints(values: list[int]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def main(argv=None):
    _configure_stdout()
    parser = argparse.ArgumentParser(description="Generate a draft glossary YAML from downloaded subtitle text using an LLM.")
    parser.add_argument("source_srt", type=Path, help="Downloaded .srt subtitle file")
    parser.add_argument("--out", type=Path, required=True, help="Output draft glossary YAML path")
    parser.add_argument("--source-language", default="korean")
    parser.add_argument("--target-language", default=DEFAULT_TARGET_LANGUAGE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-chars-per-batch", type=int, default=DEFAULT_MAX_CHARS_PER_BATCH)
    parser.add_argument("--model", default=None, help="Override LLM_MODEL")
    parser.add_argument("--base-url", default=None, help="Override LLM_BASE_URL")
    parser.add_argument("--extra-hint", default="", help="Extra context, e.g. known cast, show name, channel name")
    parser.add_argument("--fill-suggestions", action="store_true", help="Copy suggested_zh into zh for a quick first pass")
    args = parser.parse_args(argv)

    out = generate_glossary_draft(
        args.source_srt,
        args.out,
        model=args.model,
        base_url=args.base_url,
        source_language=args.source_language,
        target_language=args.target_language,
        batch_size=args.batch_size,
        max_chars_per_batch=args.max_chars_per_batch,
        extra_hint=args.extra_hint,
        fill_suggestions=args.fill_suggestions,
    )
    print(f"draft_glossary: {out}")


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


if __name__ == "__main__":
    main()
