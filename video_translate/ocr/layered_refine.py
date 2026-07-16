from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

from video_translate.llm_config import load_llm_task_config
from video_translate.models import OCRBox, SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.translate.volcengine import (
    DEFAULT_BASE_URL,
    _chat_completions_url,
    _load_dotenv,
    _request_translation,
)
from video_translate.utils.timecode import format_srt_time, parse_srt_time


_ALLOWED_ROLES = {"dialogue", "speaker_label", "subject_label", "visual_annotation", "noise"}
_EVENT_KEYS = {"cue_id", "layers"}
_LAYER_KEYS = {"id", "role", "text", "attach_to", "evidence_layer_ids", "reason"}
_TRAILING_SPEAKER_COLON_RE = re.compile(r"\s*[:：]+\s*$")
_ORPHAN_TRACK_ID_BASE = -1_000_000


@dataclass(slots=True)
class LayeredOCRRefinementConfig:
    """Settings for OCR Lab's spatially layered OCR refinement."""

    pipeline_version: str = "v2"
    batch_size: int = 8
    context_overlap: int = 1
    max_boxes_per_frame: int = 24
    max_frames_per_cue: int = 12
    row_y_tolerance_ratio: float = 0.60
    min_row_y_tolerance: float = 10.0
    layer_y_tolerance: float = 64.0
    max_layer_candidates: int = 20
    max_observations_per_layer: int = 8
    max_geometry_hints_per_cue: int = 12


def refine_ocr_layers_with_llm(
    source_srt: Path,
    ocr_boxes_json: Path,
    out_srt: Path,
    debug_json: Path,
    *,
    recovery_srt: Path | None = None,
    geometry_json: Path | None = None,
    model: str | None = None,
    base_url: str | None = None,
    config: LayeredOCRRefinementConfig | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Path]:
    """Refine OCR cues without flattening vertically separate on-screen text.

    The LLM can classify and rewrite layers, but cannot provide timestamps. Each
    response event is bound to one input cue, so the resulting timing remains
    inside the source cue. Invalid responses safely fall back to the trusted
    OCR 2.0 baseline while untrusted recovery candidates are dropped.
    """

    config = config or LayeredOCRRefinementConfig()
    _validate_config(config)
    baseline_cues = read_srt(source_srt)
    boxes = _load_ocr_boxes(ocr_boxes_json)
    geometry_hints: list[dict[str, Any]] = []
    geometry_hint_error: str | None = None
    if geometry_json:
        try:
            geometry_hints = _load_geometry_hints(geometry_json)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            # Geometry is deliberately a soft prior. A missing/older debug
            # schema must never block text cleanup or silently erase the
            # trusted machine/refined baseline.
            geometry_hint_error = f"{type(exc).__name__}: {exc}"
    recovery_cues = (
        read_srt(recovery_srt)
        if recovery_srt and recovery_srt.is_file() and recovery_srt.resolve() != source_srt.resolve()
        else []
    )
    machine_cues, recovery_debug = _merge_recovery_cues(
        baseline_cues,
        recovery_cues,
        boxes,
        config=config,
    )
    debug_config = asdict(config)
    if config.pipeline_version == "v2" and geometry_json is None:
        # Keep OCR 2.0's established debug schema byte-for-byte compatible in
        # spirit: V3-only knobs must not make an unchanged V2 run look like a
        # different refinement format.
        debug_config.pop("pipeline_version", None)
        debug_config.pop("max_geometry_hints_per_cue", None)
    debug: dict[str, Any] = {
        "version": 3 if config.pipeline_version == "v3" else 2,
        "mode": (
            "ocr3_geometry_assisted_layered_refinement"
            if config.pipeline_version == "v3"
            else "ocr2_semantic_layered_refinement"
        ),
        "source_srt": str(source_srt),
        "recovery_srt": str(recovery_srt) if recovery_srt else None,
        "ocr_boxes_json": str(ocr_boxes_json),
        "config": debug_config,
        "baseline_cue_count": len(baseline_cues),
        "recovery": recovery_debug,
        "cue_count": len(machine_cues),
        "box_count": len(boxes),
        "batches": [],
    }
    if geometry_json is not None or config.pipeline_version == "v3":
        debug["geometry_json"] = str(geometry_json) if geometry_json else None
        debug["geometry_hint_count"] = len(geometry_hints)
        if geometry_hint_error:
            debug["geometry_hint_error"] = geometry_hint_error
            _emit(
                progress_callback,
                f"ocr_layered_refine_geometry_hint_warning: {geometry_hint_error}; continuing with text evidence",
            )

    if not machine_cues:
        write_srt([], out_srt)
        debug["output_cues"] = []
        _write_debug(debug_json, debug)
        _emit(progress_callback, "ocr_layered_refine: no cues; wrote empty subtitle")
        return {"refined_srt": out_srt, "debug_json": debug_json}

    _load_dotenv(Path.cwd())
    # Reuse OCR 2.0's configured refinement model. This Lab-only module remains
    # independently callable and does not alter llm_refine.py's behavior.
    task_llm = load_llm_task_config(
        "ocr_source_refinement",
        explicit_model=model,
        explicit_base_url=base_url,
    )
    api_key = getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    selected_model = task_llm.model
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置 OpenAI-compatible API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ocr_source_refinement 模型配置或 LLM_MODEL。")
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    debug["model"] = selected_model

    batch_size = max(1, config.batch_size)
    total_batches = max(1, (len(machine_cues) + batch_size - 1) // batch_size)
    _emit(progress_callback, f"ocr_layered_refine_model: {selected_model}")
    _emit(progress_callback, f"ocr_layered_refine: {len(machine_cues)} cues in {total_batches} batches")

    refined: list[SubtitleCue] = []
    for batch_index, offset in enumerate(range(0, len(machine_cues), batch_size), start=1):
        batch = machine_cues[offset : offset + batch_size]
        context_start = max(0, offset - max(0, config.context_overlap))
        context_end = min(len(machine_cues), offset + batch_size + max(0, config.context_overlap))
        context = machine_cues[context_start:context_end]
        label = f"{batch_index}/{total_batches}"
        _emit(
            progress_callback,
            f"ocr_layered_refine_batch: {label} cues {batch[0].index}-{batch[-1].index}",
        )
        batch_cues, batch_debug = _request_layered_batch(
            batch,
            boxes,
            context=context,
            endpoint=endpoint,
            api_key=api_key,
            model=selected_model,
            config=config,
            batch_label=label,
            progress_callback=progress_callback,
            geometry_hints=geometry_hints,
        )
        refined.extend(batch_cues)
        debug["batches"].append(batch_debug)

    refined = _make_non_overlapping(refined)
    for index, cue in enumerate(refined, start=1):
        cue.index = index
    write_srt(refined, out_srt)
    debug["output_cues"] = [cue.to_dict() for cue in refined]
    _write_debug(debug_json, debug)
    _emit(progress_callback, f"ocr_layered_refine: finished; wrote {len(refined)} cues")
    return {"refined_srt": out_srt, "debug_json": debug_json}


def build_layered_refinement_payload(
    batch: list[SubtitleCue],
    boxes: list[OCRBox],
    *,
    model: str,
    config: LayeredOCRRefinementConfig | None = None,
    context: list[SubtitleCue] | None = None,
    geometry_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an LLM payload whose candidates remain separated by spatial row."""

    config = config or LayeredOCRRefinementConfig()
    _validate_config(config)
    context = context or batch
    cue_evidence = [
        build_cue_layer_evidence(cue, boxes, config=config, geometry_hints=geometry_hints)
        for cue in batch
    ]
    target_ids = {cue.index for cue in batch}
    trusted_baseline_kind = _trusted_baseline_kind(config)
    context_cues = [
        {
            "id": cue.index,
            "start": format_srt_time(cue.start),
            "end": format_srt_time(cue.end),
            "text": cue.text,
            "baseline_kind": "orphan_candidate" if _is_orphan_cue(cue) else trusted_baseline_kind,
            "target": cue.index in target_ids,
        }
        for cue in context
    ]
    evidence_json = json.dumps(
        {
            "target_ids": [cue.index for cue in batch],
            "context_cues": context_cues,
            "cue_evidence": cue_evidence,
        },
        ensure_ascii=False,
    )
    geometry_instruction = (
        "本次是 OCR 3.0，cue_evidence.geometry_hints 来自独立几何分类器，只是软先验而不是删除指令。"
        "即使 hint 中 server_action='drop' 或 classification='scene_text'，也必须结合逐帧文字层、语义和上下文重新判断；"
        "切镜、字幕动画和轨迹抖动会产生误导性的 motion/scale 证据。清晰的对白、节目主文案、人物姓名牌和效果说明"
        "不得仅凭几何 hint 删除。stable_slanted_program_candidate 是保护提示；短暂乱码则仍应依据文字证据判 noise。"
        "相邻 context cue 的文字如果在当前 target 的 frame_observations 中又清晰出现至少两帧，不是所谓 previous-cue "
        "leakage，而是同一字幕跨过机器切分边界继续显示；当前 event 必须继续保留它，再与同时出现的新层组合。"
        "例如当前 machine_text='선물 줍줍'，但当前帧同时稳定出现上一句 '아니 왜냐면!'，应返回 dialogue='아니 왜냐면!'，"
        "并把 '선물 줍줍' 判 visual_annotation attach_to 该 dialogue，最终成为 '[선물 줍줍]아니 왜냐면!'。"
        "同一 row 内若最左侧是短人物姓名 box，右侧隔着明显空白或竖线才是长主句，不得把整行都判 dialogue；"
        "例如 '박보영 | 이렇게 하고 나갔는데' 应拆成 subject_label='박보영' 与 dialogue='이렇게 하고 나갔는데'，"
        "最终成为 '[박보영] 이렇게 하고 나갔는데'。候选行尾孤立的 QC、AU、TDKO 等拉丁串没有一致语义证据时必须判 noise。"
        if config.pipeline_version == "v3"
        else ""
    )
    baseline_instruction = (
        f"cue_evidence.baseline_kind 必须严格区分：{trusted_baseline_kind} 的 machine_text 已完成文字拼写、"
        "变体合并和时间轴精修，但尚未完成物品字/环境字的语义筛选。通常应保留它；如果文字本身明确是现实场景中的"
        "停车场标识、路牌、店名、菜单、建筑招牌或界面控件，并且逐帧文字、上下文与几何提示相互印证，则必须判 noise。"
        "反过来，不能只凭 server_action='drop' 删除对白、节目主文案、人物姓名牌或效果说明；文字语义与画面证据冲突时"
        "宁可保留。orphan_candidate 是从基线空窗找回的未审核原始候选，默认可以全部判 noise，只有逐帧稳定且语义明确时"
        "才能恢复为字幕。"
        if config.pipeline_version == "v3"
        else (
            f"cue_evidence.baseline_kind 必须严格区分：{trusted_baseline_kind} 的 machine_text 是已完成轨迹合并和专属精修的"
            "高质量基线，必须优先保留；orphan_candidate 是从基线空窗找回的未审核原始候选，默认可以全部判 noise，"
            "只有逐帧稳定且语义明确时才能恢复为字幕。"
        )
    )
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 OCR Lab 的原文字幕空间分层精修器，只整理原语言，绝不翻译。"
                    f"{geometry_instruction}"
                    "每个 target cue 都包含逐帧 frame_observations；每帧的 rows 是按纵向 y 聚类后独立保留的文字行，"
                    "layer_candidates 也是单行空间轨迹。不同 y 行可能同时存在，绝对不能先扁平拼成一个候选。"
                    "你必须按语义而不是位置把证据分成 dialogue、speaker_label、subject_label、"
                    "visual_annotation 或 noise。dialogue 在这里表示观众应主要阅读的主字幕/主文案："
                    "既包括人物实际说的话，也包括节目组的主叙述、主说明，以及画面上对人物话语的强调、重复、"
                    "补全或转写；这类文字最终都不加方括号，绝不能因为位于画面上方就改成说明标签。"
                    "subject_label 是画面中标识人物或叙述主体的浮动姓名牌，不代表此人此刻一定在说话；"
                    "它必须 attach_to 对应的主 dialogue，系统会输出为 '[姓名] 主字幕'。"
                    "speaker_label 则只用于明确标注当前对白说话人的标签，系统会输出为 '说话人: 对白'。"
                    "visual_annotation 只用于紧贴主文案的辅助动作、表情、状态、音效或简短剪辑效果说明，"
                    "例如人物说‘我有点害羞’时画面效果字‘脸红’，应返回 visual_annotation='脸红' 并 attach_to 对白。"
                    "节目组的完整主叙述即使不是人物发言也仍应判 dialogue；例如韩综主文案 "
                    "'유난히 말을 아끼는 한 사람'（格外惜字如金的一个人）应不加方括号。"
                    "而 '아니에요x4'、'콩?콩?' 这类人物实际连续否认或反问仍是 dialogue，即使位于画面中部。"
                    "noise 是 Logo、水印、误识别等。"
                    "现实场景中的店名、路牌、停车场字样、楼层号、菜单、建筑招牌和界面文字默认也属于 noise，"
                    "除非上下文明确表明节目在引用或解释它；它们不能仅因文字清晰或持续多帧就成为 visual_annotation。"
                    "speaker_label、subject_label 和 visual_annotation 应通过 attach_to 指向对应 dialogue 的 id；"
                    "只有一条 dialogue 时可以省略 attach_to。多个说明可分别指向同一 dialogue；"
                    "如果画面只有拟声、表情或状态等短辅助效果且确实没有主字幕，visual_annotation 才可不带 attach_to 独立保留；"
                    "完整的节目叙述或主说明即使没有人物发言，也必须作为 dialogue 主文案保留而不加括号。"
                    "纵向相距很远的证据必须先保持为独立语义层，不能仅因处在同一 cue 就拼成一段文字。"
                    "特别是 18 秒示例中若 L1='이선빈'、L3='섭외한 방으로 피신'，应返回 "
                    "subject_label='이선빈' attach_to 主 dialogue，另返回 dialogue='섭외한 방으로 피신'；"
                    "绝不能合并成 visual_annotation='이선빈 섭외한 방으로 피신'。"
                    "画面字和底部字幕同时出现时要逐项判断语义：若画面字是状态说明则保留为 visual_annotation；"
                    "若它本身是人物说的话，或与底部对白重复/包含/互为补全，则合并为一条最完整准确的 dialogue，"
                    "不要输出两行重复对白。若同一 cue 确有多个人物先后发言，则保留多条 dialogue，"
                    "并按各自 evidence 首次出现的时间排序，不能按纵坐标排序。成组对照的节目说明也要区分"
                    "辅助标签与主文案，不能把上下两层全部合成一个 visual_annotation。"
                    f"{baseline_instruction}"
                    "节目片头片尾、圆形转场标题、栏目 bumper 和动态节目 Logo"
                    "即使持续多帧也属于 noise；像 '핵-'、'빼꼼'、'으허엉...' 这类人物呼气、反应或拟声效果字"
                    "应作为独立 visual_annotation 保留，而不是 dialogue。"
                    "variant_families 按相同画面位置汇总逐帧 OCR 拼写变体；同一 family 的多个低频拼写合计支持很高时，"
                    "代表一条稳定但字体难识别的文字，不能把每个变体分别当成瞬时噪声。应结合韩语语义选最合理的完整拼写："
                    "例如 빼꼭/빼콤/빼끔 应规范为 '빼꼼'，으허성 与 으허엉 000 应规范为 '으허엉...'，"
                    "클리식명쇄/클래식명패 等同位置变体应恢复为主文案 '클래식 명패'，흐드/등드/흔들 应恢复为动作效果 '흔들'。"
                    "但 MBC 圆形转场牌 '엠뚜루 마뚜루' 及其误识别 에뜨는/에뜨르/미또루/미뜨루/마또를/마뜨루"
                    "始终是 bumper noise，绝不能作为 dialogue 或 visual_annotation。"
                    "只有原始 bbox、center_y、逐帧支持和各行文字形成明确且一致的证据时，才纠正基线或补充新的语义层。"
                    "不要把随机拉丁字母、单个符号、短暂乱码或 Logo 变体提升为 dialogue/visual_annotation。"
                    "对于一个字或一个词逐步出现的字幕，应沿同一位置的时间序列选择最后、最完整且与稳定变体一致的句子，"
                    "不能因为较短残片出现帧数更多就截断完整句；若 machine_text 已是完整句，保持完整句。"
                    "layer_candidates.role_hint 只是中性视觉候选提示，不是语义结论："
                    "upper_text_candidate 仅表示文字位置较高，既可能是 visual_annotation，也可能是 dialogue、"
                    "speaker_label、subject_label 或 noise；short_bracketed_candidate 也不能直接当作说话人，"
                    "例如 [脸红] 可能是状态说明，[꽃게] 是否为身份标签必须结合邻近姓名和对白判断。"
                    "典型情况下，[꽃게] 一类短标签位于上一小行，人物姓名（如 이선빈）位于下行最左且与对白有明显 x 间隔；"
                    "应把两者组合为 speaker_label='[꽃게] 이선빈'，dialogue 中去掉姓名，最终由系统输出为 '[꽃게] 이선빈: 对白'。"
                    "系统最终把 visual_annotation 紧贴在对应主字幕前，例如 '[脸红]我有点害羞'；"
                    "subject_label 则以带空格的主体前缀呈现，例如 '[이선빈] 섭외한 방으로 피신'；"
                    "有说话人时为 '说话人: [脸红]我有点害羞'。不要自行在 text 中添加用于输出格式的方括号。"
                    "不可凭空补写无视觉证据的长句。每个 target cue 必须且只能返回一个 event。"
                    "orphan_candidate 中每个非 noise layer 都必须填写 evidence_layer_ids，并至少引用一个 recovery_eligible=true"
                    "的 L 层；可以同时引用同一 variant_family 的稳定多数层和提供正确拼写的低频层。"
                    "不要返回 start/end/time/duration，也不要合并不同 cue；事件时间由系统锁定为输入 cue。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回严格 JSON，不要 markdown 或解释。格式："
                    '{"events":[{"cue_id":1,"layers":['
                    '{"id":"annotation_1","role":"visual_annotation","text":"脸红","attach_to":"dialogue_1","evidence_layer_ids":["L1"]},'
                    '{"id":"subject_1","role":"subject_label","text":"人物姓名","attach_to":"dialogue_1","evidence_layer_ids":["L2"]},'
                    '{"id":"speaker_1","role":"speaker_label","text":"说话人","attach_to":"dialogue_1","evidence_layer_ids":["L2"]},'
                    '{"id":"dialogue_1","role":"dialogue","text":"主字幕原文","evidence_layer_ids":["L3"]},'
                    '{"id":"noise_1","role":"noise","text":"水印","reason":"persistent logo"}'
                    "]}]}。非 noise layer 的 text 必须非空；"
                    + trusted_baseline_kind
                    + " 不确定时沿用 machine_text，"
                    "orphan_candidate 不确定时必须判 noise。输入：\n"
                    + evidence_json
                ),
            },
        ],
        "temperature": 0.1,
    }


def build_cue_layer_evidence(
    cue: SubtitleCue,
    boxes: list[OCRBox],
    *,
    config: LayeredOCRRefinementConfig | None = None,
    geometry_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return raw per-frame rows plus non-flattened, row-level candidates."""

    config = config or LayeredOCRRefinementConfig()
    _validate_config(config)
    cue_boxes = [box for box in boxes if cue.start <= box.time <= cue.end and box.text.strip()]
    all_frames = _build_frame_observations(cue_boxes, config)
    frames = _uniform_sample_frames(all_frames, config.max_frames_per_cue)
    # Candidate support is computed from every observed frame. Only the raw
    # frame detail is sampled, which keeps prompts bounded without turning a
    # brief first/last appearance into misleading support statistics.
    candidates = _build_layer_candidates(all_frames, config)
    variant_families = _build_variant_families(candidates, frame_count=len(all_frames), config=config)
    evidence = {
        "cue_id": cue.index,
        "start": format_srt_time(cue.start),
        "end": format_srt_time(cue.end),
        "machine_text": cue.text,
        "baseline_kind": "orphan_candidate" if _is_orphan_cue(cue) else _trusted_baseline_kind(config),
        "observed_frame_count": len(all_frames),
        "sampled_frame_count": len(frames),
        "frame_sampling": {
            "strategy": "uniform_with_endpoints",
            "total": len(all_frames),
            "included": len(frames),
        },
        "frame_observations": frames,
        "layer_candidates": candidates,
        "variant_families": variant_families,
    }
    if geometry_hints:
        evidence["geometry_hints"] = _geometry_hints_for_cue(
            cue,
            geometry_hints,
            layer_candidates=candidates,
            config=config,
        )
    if _is_orphan_cue(cue):
        _annotate_recovery_evidence(evidence, cue.end - cue.start)
    return evidence


def _merge_recovery_cues(
    baseline_cues: list[SubtitleCue],
    recovery_cues: list[SubtitleCue],
    boxes: list[OCRBox],
    *,
    config: LayeredOCRRefinementConfig,
) -> tuple[list[SubtitleCue], dict[str, Any]]:
    """Add stable raw candidates only inside gaps in the refined baseline."""

    debug: dict[str, Any] = {
        "raw_cue_count": len(recovery_cues),
        "accepted": [],
        "rejected_counts": {},
    }
    if not recovery_cues:
        return baseline_cues, debug

    baseline = sorted(baseline_cues, key=lambda cue: (cue.start, cue.end))
    guard_seconds = 0.12
    orphan_cues: list[SubtitleCue] = []
    orphan_metadata: list[dict[str, Any]] = []

    def reject(reason: str) -> None:
        counts = debug["rejected_counts"]
        counts[reason] = int(counts.get(reason, 0)) + 1

    for raw in sorted(recovery_cues, key=lambda cue: (cue.start, cue.end)):
        if raw.end <= raw.start or raw.end - raw.start < 0.30:
            reject("too_short")
            continue
        if any(raw.start < cue.end + guard_seconds and raw.end > cue.start - guard_seconds for cue in baseline):
            reject("covered_by_baseline")
            continue

        evidence = build_cue_layer_evidence(raw, boxes, config=config)
        _annotate_recovery_evidence(evidence, raw.end - raw.start)
        eligible = [
            candidate
            for candidate in evidence["layer_candidates"]
            if bool(candidate.get("recovery_eligible"))
        ]
        if not eligible:
            reject("no_stable_text")
            continue
        best = max(
            eligible,
            key=lambda candidate: (
                int(candidate.get("family_frame_support") or 0),
                int(candidate.get("frame_support") or 0),
                len(_semantic_compact_text(candidate.get("text"))),
                _candidate_median_confidence(candidate),
            ),
        )
        observed_start, observed_end = _candidate_observed_interval(best, raw.start, raw.end)
        provisional = SubtitleCue(
            index=raw.index,
            start=observed_start,
            end=observed_end,
            text=_clean_layer_text(best.get("text")),
            source_track_id=_ORPHAN_TRACK_ID_BASE - max(1, raw.index),
        )
        provisional_metadata = {
            "text": provisional.text,
            "average_bbox": best.get("family_average_bbox") or best.get("average_bbox"),
            "average_center_y": best.get("family_average_center_y") or best.get("average_center_y"),
            "variant_family_id": best.get("variant_family_id"),
            "family_frame_support": int(best.get("family_frame_support") or 0),
            "frame_support": int(best.get("frame_support") or 0),
            "median_confidence": _candidate_median_confidence(best),
        }

        if orphan_cues and _can_merge_orphan_cues(
            orphan_cues[-1],
            provisional,
            left_metadata=orphan_metadata[-1],
            right_metadata=provisional_metadata,
            config=config,
        ):
            previous = orphan_cues[-1]
            previous.end = max(previous.end, provisional.end)
            if _recovery_candidate_score(provisional_metadata) > _recovery_candidate_score(orphan_metadata[-1]):
                previous.text = provisional.text
                orphan_metadata[-1] = provisional_metadata
            debug["accepted"][-1]["end"] = previous.end
            debug["accepted"][-1]["provisional_text"] = previous.text
            debug["accepted"][-1]["frame_support"] = orphan_metadata[-1]["frame_support"]
            debug["accepted"][-1]["family_frame_support"] = orphan_metadata[-1]["family_frame_support"]
            debug["accepted"][-1]["variant_family_id"] = orphan_metadata[-1]["variant_family_id"]
            debug["accepted"][-1]["median_confidence"] = round(orphan_metadata[-1]["median_confidence"], 3)
            debug["accepted"][-1]["merged_raw_ids"].append(raw.index)
            continue

        orphan_cues.append(provisional)
        orphan_metadata.append(provisional_metadata)
        debug["accepted"].append(
            {
                "raw_id": raw.index,
                "merged_raw_ids": [raw.index],
                "start": provisional.start,
                "end": provisional.end,
                "raw_text": raw.text,
                "provisional_text": provisional.text,
                "frame_support": int(best.get("frame_support") or 0),
                "family_frame_support": int(best.get("family_frame_support") or 0),
                "variant_family_id": best.get("variant_family_id"),
                "median_confidence": round(_candidate_median_confidence(best), 3),
            }
        )

    merged = [*baseline, *orphan_cues]
    merged.sort(key=lambda cue: (cue.start, cue.end, 1 if _is_orphan_cue(cue) else 0))
    for index, cue in enumerate(merged, start=1):
        cue.index = index
    debug["accepted_count"] = len(orphan_cues)
    return merged, debug


def _eligible_orphan_candidate(candidate: dict[str, Any], cue_duration: float) -> bool:
    text = _clean_layer_text(candidate.get("text"))
    support = int(candidate.get("frame_support") or 0)
    confidence = _candidate_median_confidence(candidate)
    signal_duration = _candidate_signal_duration(candidate, cue_duration)
    return _eligible_orphan_signal(text, support, signal_duration, confidence)


def _eligible_orphan_signal(text: str, support: int, duration: float, confidence: float) -> bool:
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return False
    # Stylized captions often split one stable visual track into several close
    # OCR spellings; four repeats is sufficient here because an orphan is
    # still sent through the semantic/noise classifier and never raw-fallbacks.
    long_stable = support >= 4 and duration >= 0.65 and confidence >= 0.55
    short_high_confidence = support >= 3 and duration >= 0.33 and confidence >= 0.85
    if not (long_stable or short_high_confidence):
        return False
    if all(character.isascii() for character in letters) and len(letters) <= 2:
        return False
    if len(letters) == 1:
        if letters[0].isascii():
            return False
        # A single Hangul syllable plus editorial punctuation (for example
        # "핵-") is a common short effect caption. Keep its high-confidence
        # three-frame lead-in so a later stable segment can extend it.
        has_effect_punctuation = any(not character.isalnum() and not character.isspace() for character in text)
        if has_effect_punctuation and support >= 3 and duration >= 0.40 and confidence >= 0.95:
            return True
        return support >= 5 and duration >= 0.75 and confidence >= 0.90
    return True


def _annotate_recovery_evidence(evidence: dict[str, Any], cue_duration: float) -> None:
    families = {
        str(family.get("family_id")): family
        for family in evidence.get("variant_families", [])
        if isinstance(family, dict) and family.get("family_id")
    }
    for family in families.values():
        family_duration = _observed_signal_duration(
            family.get("first_seen"),
            family.get("last_seen"),
            cue_duration,
        )
        family["signal_duration"] = round(family_duration, 3)
        family["recovery_eligible"] = _eligible_orphan_signal(
            _clean_layer_text(family.get("canonical_text")),
            int(family.get("frame_support") or 0),
            family_duration,
            float(family.get("median_confidence") or 0.0),
        )

    for candidate in evidence.get("layer_candidates", []):
        if not isinstance(candidate, dict):
            continue
        family = families.get(str(candidate.get("variant_family_id") or ""))
        own_eligible = _eligible_orphan_candidate(candidate, cue_duration)
        family_eligible = bool(family and family.get("recovery_eligible"))
        candidate["recovery_eligible"] = own_eligible or family_eligible
        if family:
            candidate["family_frame_support"] = int(family.get("frame_support") or 0)
            candidate["family_first_seen"] = family.get("first_seen")
            candidate["family_last_seen"] = family.get("last_seen")
            candidate["family_average_bbox"] = family.get("average_bbox")
            candidate["family_average_center_y"] = family.get("average_center_y")


def _candidate_signal_duration(candidate: dict[str, Any], cue_duration: float) -> float:
    return _observed_signal_duration(
        candidate.get("first_seen"),
        candidate.get("last_seen"),
        cue_duration,
    )


def _observed_signal_duration(first_seen: Any, last_seen: Any, cue_duration: float) -> float:
    try:
        observed = max(0.0, parse_srt_time(str(last_seen)) - parse_srt_time(str(first_seen))) + 0.25
    except Exception:
        return max(0.0, cue_duration)
    return min(max(0.0, cue_duration), observed)


def _candidate_observed_interval(candidate: dict[str, Any], raw_start: float, raw_end: float) -> tuple[float, float]:
    first_seen = candidate.get("family_first_seen") or candidate.get("first_seen")
    last_seen = candidate.get("family_last_seen") or candidate.get("last_seen")
    try:
        start = max(raw_start, parse_srt_time(str(first_seen)) - 0.10)
        end = min(raw_end, parse_srt_time(str(last_seen)) + 0.25)
    except Exception:
        return raw_start, raw_end
    if end - start < 0.30:
        end = min(raw_end, start + 0.30)
    return (start, end) if end > start else (raw_start, raw_end)


def _candidate_median_confidence(candidate: dict[str, Any]) -> float:
    stored = candidate.get("median_confidence")
    if stored is not None:
        return float(stored)
    values = [
        float(observation.get("confidence") or 0.0)
        for observation in candidate.get("observations", [])
        if isinstance(observation, dict)
    ]
    return median(values) if values else 0.0


def _can_merge_orphan_cues(
    left: SubtitleCue,
    right: SubtitleCue,
    *,
    left_metadata: dict[str, Any] | None = None,
    right_metadata: dict[str, Any] | None = None,
    config: LayeredOCRRefinementConfig | None = None,
) -> bool:
    if right.start - left.end > 0.25:
        return False
    left_text = _semantic_compact_text(left.text)
    right_text = _semantic_compact_text(right.text)
    if not left_text or not right_text:
        return False
    text_matches = left_text in right_text or right_text in left_text
    if not text_matches:
        left_jamo = unicodedata.normalize("NFKD", left_text)
        right_jamo = unicodedata.normalize("NFKD", right_text)
        text_matches = SequenceMatcher(None, left_jamo, right_jamo).ratio() >= 0.50
    if not text_matches:
        return False
    if not left_metadata or not right_metadata:
        return True
    config = config or LayeredOCRRefinementConfig()
    return _same_visual_slot(left_metadata, right_metadata, config=config)


def _recovery_candidate_score(metadata: dict[str, Any]) -> tuple[int, int, int, float]:
    return (
        int(metadata.get("family_frame_support") or 0),
        int(metadata.get("frame_support") or 0),
        len(_semantic_compact_text(metadata.get("text"))),
        float(metadata.get("median_confidence") or 0.0),
    )


def _is_orphan_cue(cue: SubtitleCue) -> bool:
    return cue.source_track_id is not None and cue.source_track_id <= _ORPHAN_TRACK_ID_BASE


def parse_layered_refinement_response(content: str, target_ids: Iterable[int]) -> list[dict[str, Any]]:
    """Strictly parse and validate the event/layer response schema."""

    parsed = _strict_json_loads(content)
    if not isinstance(parsed, dict) or set(parsed) != {"events"}:
        raise ValueError("layered refinement response must be exactly {events: [...]} JSON")
    events = parsed["events"]
    if not isinstance(events, list):
        raise ValueError("events must be a JSON array")

    expected = {int(value) for value in target_ids}
    seen: set[int] = set()
    validated: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or set(event) != _EVENT_KEYS:
            raise ValueError("each event must contain only cue_id and layers")
        cue_id = _strict_int(event.get("cue_id"), "cue_id")
        if cue_id not in expected or cue_id in seen:
            raise ValueError(f"invalid or duplicate cue_id: {cue_id}")
        layers = event.get("layers")
        if not isinstance(layers, list) or not layers:
            raise ValueError(f"cue {cue_id} layers must be a non-empty array")
        validated_layers = _validate_layers(cue_id, layers)
        validated.append({"cue_id": cue_id, "layers": validated_layers})
        seen.add(cue_id)
    if seen != expected:
        raise ValueError(f"events must cover every target cue exactly once; missing={sorted(expected - seen)}")
    return validated


def _parse_layered_refinement_response_partial(
    content: str,
    target_ids: Iterable[int],
) -> tuple[list[dict[str, Any]], dict[int, str], list[str]]:
    """Salvage valid cue events without letting one bad event drop its batch."""

    parsed = _strict_json_loads(content)
    if not isinstance(parsed, dict) or set(parsed) != {"events"}:
        raise ValueError("layered refinement response must be exactly {events: [...]} JSON")
    raw_events = parsed["events"]
    if not isinstance(raw_events, list):
        raise ValueError("events must be a JSON array")

    ordered_ids = [int(value) for value in target_ids]
    expected = set(ordered_ids)
    validated_by_id: dict[int, dict[str, Any]] = {}
    errors: dict[int, str] = {}
    response_errors: list[str] = []
    encountered: set[int] = set()

    for position, event in enumerate(raw_events):
        cue_id: int | None = None
        try:
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            raw_cue_id = event.get("cue_id")
            cue_id = _strict_int(raw_cue_id, "cue_id")
            if cue_id not in expected:
                raise ValueError(f"unexpected cue_id: {cue_id}")
            if cue_id in encountered:
                validated_by_id.pop(cue_id, None)
                errors[cue_id] = f"duplicate cue_id: {cue_id}"
                continue
            encountered.add(cue_id)
            if set(event) != _EVENT_KEYS:
                raise ValueError("event must contain only cue_id and layers")
            layers = event.get("layers")
            if not isinstance(layers, list) or not layers:
                raise ValueError("layers must be a non-empty array")
            validated_by_id[cue_id] = {
                "cue_id": cue_id,
                "layers": _validate_layers(cue_id, layers),
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if cue_id in expected:
                validated_by_id.pop(cue_id, None)
                errors[cue_id] = message
            else:
                response_errors.append(f"event[{position}] {message}")

    for cue_id in ordered_ids:
        if cue_id not in validated_by_id and cue_id not in errors:
            errors[cue_id] = "missing event"
    return [validated_by_id[cue_id] for cue_id in ordered_ids if cue_id in validated_by_id], errors, response_errors


def apply_layered_events(batch: list[SubtitleCue], events: list[dict[str, Any]]) -> list[SubtitleCue]:
    """Render validated layers while retaining each source cue's exact timing."""

    events_by_id = {int(event["cue_id"]): event for event in events}
    output: list[SubtitleCue] = []
    for cue in batch:
        event = events_by_id.get(cue.index)
        if event is None:
            if not _is_orphan_cue(cue):
                output.append(_copy_cue(cue))
            continue
        text = _render_layers(event["layers"])
        # A valid all-noise event intentionally removes the cue. Parse/schema
        # failures never reach this point and therefore cannot lose subtitles.
        if text:
            output.append(
                SubtitleCue(
                    index=cue.index,
                    start=cue.start,
                    end=cue.end,
                    text=text,
                    source_track_id=cue.source_track_id,
                )
            )
    return output


def _request_layered_batch(
    batch: list[SubtitleCue],
    boxes: list[OCRBox],
    *,
    context: list[SubtitleCue],
    endpoint: str,
    api_key: str,
    model: str,
    config: LayeredOCRRefinementConfig,
    batch_label: str,
    progress_callback: Callable[[str], None] | None,
    geometry_hints: list[dict[str, Any]] | None = None,
) -> tuple[list[SubtitleCue], dict[str, Any]]:
    payload = build_layered_refinement_payload(
        batch,
        boxes,
        model=model,
        config=config,
        context=context,
        geometry_hints=geometry_hints,
    )
    evidence = [
        build_cue_layer_evidence(cue, boxes, config=config, geometry_hints=geometry_hints)
        for cue in batch
    ]
    debug: dict[str, Any] = {
        "batch": batch_label,
        "target_ids": [cue.index for cue in batch],
        "evidence": evidence,
    }
    try:
        content = _request_translation(endpoint, api_key, payload)
        debug["raw_response"] = content
        try:
            model_events, event_errors, response_errors = _parse_layered_refinement_response_partial(
                content,
                (cue.index for cue in batch),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as first_error:
            if config.pipeline_version != "v3":
                raise
            # OCR 3.0 prompts are larger and occasionally elicit a valid JSON
            # object followed by an extra brace/explanation.  Never trim and
            # trust malformed output: request one clean replacement, while
            # leaving OCR 2.0's established single-request behavior intact.
            debug["schema_retry_error"] = f"{type(first_error).__name__}: {first_error}"
            _emit(
                progress_callback,
                f"ocr_layered_refine_schema_retry: {batch_label} {type(first_error).__name__}: {first_error}",
            )
            retry_payload = dict(payload)
            retry_payload["messages"] = [
                *payload["messages"],
                {
                    "role": "user",
                    "content": (
                        "上一条回复不是单个可解析的严格 JSON 对象。请重新处理同一输入，只返回一个完整的 "
                        '{"events":[...]} JSON 对象；不要代码围栏、解释、前后缀或多余括号。'
                    ),
                },
            ]
            content = _request_translation(endpoint, api_key, retry_payload)
            debug["schema_retry_raw_response"] = content
            model_events, event_errors, response_errors = _parse_layered_refinement_response_partial(
                content,
                (cue.index for cue in batch),
            )
        if config.pipeline_version == "v3" and event_errors:
            # A well-formed batch may still contain one structurally invalid
            # event (for example a subject_label without its dialogue). Ask
            # once for replacements and merge only the previously invalid
            # cue ids; already-valid decisions remain byte-for-byte intact.
            invalid_ids = sorted(event_errors)
            retry_payload = dict(payload)
            retry_payload["messages"] = [
                *payload["messages"],
                {
                    "role": "user",
                    "content": (
                        f"上一条回复中 cue_id={invalid_ids} 的 event 结构无效。请重新返回这些 cue 的正确 event；"
                        "可以同时重发其他 cue，但仍只能返回一个严格 JSON 对象。subject_label、speaker_label 或 "
                        "visual_annotation 若要 attach_to，必须同时给出被引用的 dialogue；不要遗漏任何需要保留的主文案。"
                    ),
                },
            ]
            try:
                retry_content = _request_translation(endpoint, api_key, retry_payload)
                debug["event_retry_raw_response"] = retry_content
                retry_events, retry_errors, retry_response_errors = _parse_layered_refinement_response_partial(
                    retry_content,
                    (cue.index for cue in batch),
                )
                retry_by_id = {int(event["cue_id"]): event for event in retry_events}
                original_by_id = {int(event["cue_id"]): event for event in model_events}
                repaired_ids = [
                    cue_id
                    for cue_id in invalid_ids
                    if cue_id in retry_by_id and cue_id not in retry_errors
                ]
                for cue_id in repaired_ids:
                    original_by_id[cue_id] = retry_by_id[cue_id]
                    event_errors.pop(cue_id, None)
                model_events = [
                    original_by_id[cue.index]
                    for cue in batch
                    if cue.index in original_by_id
                ]
                debug["event_retry_ids"] = invalid_ids
                debug["event_retry_repaired_ids"] = repaired_ids
                if retry_response_errors:
                    response_errors.extend(retry_response_errors)
                _emit(
                    progress_callback,
                    f"ocr_layered_refine_event_retry: {batch_label} repaired "
                    + (",".join(str(cue_id) for cue_id in repaired_ids) or "none"),
                )
            except Exception as retry_error:
                debug["event_retry_error"] = f"{type(retry_error).__name__}: {retry_error}"
                _emit(
                    progress_callback,
                    f"ocr_layered_refine_event_retry_failed: {batch_label} "
                    f"{type(retry_error).__name__}: {retry_error}",
                )
        events = apply_spatial_role_guard(model_events, evidence)
        result = apply_layered_events(batch, events)
        debug["status"] = "refined" if not event_errors else ("partial" if model_events else "fallback")
        debug["model_events"] = model_events
        debug["events"] = events
        if event_errors:
            debug["event_errors"] = {str(cue_id): error for cue_id, error in event_errors.items()}
            fallback_ids = ",".join(str(cue_id) for cue_id in sorted(event_errors))
            _emit(progress_callback, f"ocr_layered_refine_partial: {batch_label} fallback cues {fallback_ids}")
        if response_errors:
            debug["response_errors"] = response_errors
        return result, debug
    except Exception as exc:
        message = f"ocr_layered_refine_fallback: {batch_label} {type(exc).__name__}: {exc}"
        _emit(progress_callback, message)
        debug["status"] = "fallback"
        debug["error"] = f"{type(exc).__name__}: {exc}"
        return [_copy_cue(cue) for cue in batch if not _is_orphan_cue(cue)], debug


def _build_frame_observations(boxes: list[OCRBox], config: LayeredOCRRefinementConfig) -> list[dict[str, Any]]:
    by_frame: dict[tuple[int, float], list[OCRBox]] = {}
    for box in boxes:
        by_frame.setdefault((box.frame_index, round(box.time, 3)), []).append(box)

    frames: list[dict[str, Any]] = []
    for (frame_index, time), frame_boxes in sorted(by_frame.items(), key=lambda item: (item[0][1], item[0][0])):
        # Cluster before applying the payload cap. A dense, high-confidence
        # title near the top must never consume every slot and hide the lower
        # dialogue row. Row text/bounds are computed from all boxes; only each
        # row's raw box detail is spatially sampled below.
        rows = _cluster_boxes_into_rows(frame_boxes, config)
        frames.append(
            {
                "frame_index": frame_index,
                "time": format_srt_time(time),
                "rows": rows,
            }
        )
    return frames


def _cluster_boxes_into_rows(boxes: list[OCRBox], config: LayeredOCRRefinementConfig) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for box in sorted(boxes, key=lambda item: (_center_y(item.bbox), item.bbox[0])):
        center_y = _center_y(box.bbox)
        height = max(1.0, box.bbox[3] - box.bbox[1])
        best: dict[str, Any] | None = None
        best_distance = float("inf")
        for cluster in clusters:
            tolerance = max(
                config.min_row_y_tolerance,
                min(height, float(cluster["average_height"])) * config.row_y_tolerance_ratio,
            )
            distance = abs(center_y - float(cluster["center_y"]))
            if distance <= tolerance and distance < best_distance:
                best = cluster
                best_distance = distance
        if best is None:
            clusters.append(
                {
                    "center_y": center_y,
                    "average_height": height,
                    "boxes": [box],
                }
            )
            continue
        best["boxes"].append(box)
        best["center_y"] = sum(_center_y(item.bbox) for item in best["boxes"]) / len(best["boxes"])
        best["average_height"] = sum(max(1.0, item.bbox[3] - item.bbox[1]) for item in best["boxes"]) / len(
            best["boxes"]
        )

    ordered_clusters = sorted(clusters, key=lambda item: item["center_y"])
    box_allocations = _allocate_boxes_across_rows(
        [len(cluster["boxes"]) for cluster in ordered_clusters],
        config.max_boxes_per_frame,
    )
    rows: list[dict[str, Any]] = []
    for row_index, (cluster, box_limit) in enumerate(zip(ordered_clusters, box_allocations), start=1):
        row_boxes = sorted(cluster["boxes"], key=lambda item: item.bbox[0])
        representative_boxes = _uniform_sample_items(row_boxes, box_limit) if box_limit else []
        bbox = _union_bbox(item.bbox for item in row_boxes)
        text = " ".join(item.text.strip() for item in row_boxes if item.text.strip())
        region_counts = Counter(item.region for item in row_boxes)
        row: dict[str, Any] = {
            "row_id": f"R{row_index}",
            "text": text,
            "center_y": round(_center_y(bbox), 1),
            "y_range": [round(bbox[1], 1), round(bbox[3], 1)],
            "bbox": [round(value, 1) for value in bbox],
            "region": region_counts.most_common(1)[0][0],
            "average_confidence": round(sum(item.confidence for item in row_boxes) / len(row_boxes), 3),
            "box_count": len(row_boxes),
            "sampled_box_count": len(representative_boxes),
            "boxes": [_box_payload(item) for item in representative_boxes],
        }
        rows.append(row)
    return rows


def _build_layer_candidates(frames: list[dict[str, Any]], config: LayeredOCRRefinementConfig) -> list[dict[str, Any]]:
    observations_by_text: dict[str, list[dict[str, Any]]] = {}
    frame_count = max(1, len(frames))
    for frame in frames:
        for row in frame["rows"]:
            compact = _compact_text(str(row["text"]))
            if not compact:
                continue
            observation = {
                "frame_index": frame["frame_index"],
                "time": frame["time"],
                "text": row["text"],
                "center_y": row["center_y"],
                "bbox": row["bbox"],
                "region": row["region"],
                "confidence": row["average_confidence"],
            }
            observations_by_text.setdefault(compact, []).append(observation)

    # Quantized y bands split a stable line when it happens to move across a
    # bucket boundary. Cluster each compact text around an incremental center
    # instead: small bbox-height/jitter changes stay together, while identical
    # text hundreds of pixels apart remains distinct evidence.
    groups: list[list[dict[str, Any]]] = []
    for text_observations in observations_by_text.values():
        spatial_groups: list[dict[str, Any]] = []
        for observation in sorted(text_observations, key=lambda item: float(item["center_y"])):
            nearest = min(
                spatial_groups,
                key=lambda group: abs(float(group["center_y"]) - float(observation["center_y"])),
                default=None,
            )
            if nearest is None or abs(float(nearest["center_y"]) - float(observation["center_y"])) > config.layer_y_tolerance:
                spatial_groups.append({"center_y": float(observation["center_y"]), "observations": [observation]})
                continue
            nearest["observations"].append(observation)
            nearest["center_y"] = sum(float(item["center_y"]) for item in nearest["observations"]) / len(
                nearest["observations"]
            )
        groups.extend(group["observations"] for group in spatial_groups)

    ranked = sorted(
        groups,
        key=lambda observations: (
            len({item["frame_index"] for item in observations}),
            sum(float(item["confidence"]) for item in observations),
            len(str(observations[0]["text"])),
        ),
        reverse=True,
    )[: config.max_layer_candidates]
    candidates: list[dict[str, Any]] = []
    for observations in ranked:
        bbox = [
            round(sum(float(item["bbox"][coordinate]) for item in observations) / len(observations), 1)
            for coordinate in range(4)
        ]
        distinct_frames = len({item["frame_index"] for item in observations})
        text_counts = Counter(str(item["text"]) for item in observations)
        candidates.append(
            {
                "text": text_counts.most_common(1)[0][0],
                "frame_support": distinct_frames,
                "support_ratio": round(distinct_frames / frame_count, 3),
                "median_confidence": round(
                    median(float(item["confidence"]) for item in observations),
                    3,
                ),
                "first_seen": min(str(item["time"]) for item in observations),
                "last_seen": max(str(item["time"]) for item in observations),
                "average_center_y": round(sum(float(item["center_y"]) for item in observations) / len(observations), 1),
                "average_bbox": bbox,
                "regions": dict(Counter(str(item["region"]) for item in observations)),
                "observations": observations[: config.max_observations_per_layer],
                "_frame_indexes": sorted({int(item["frame_index"]) for item in observations}),
                "_confidence_values": [float(item["confidence"]) for item in observations],
            }
        )
    ordered = sorted(candidates, key=lambda item: (item["average_center_y"], -item["frame_support"]))
    for index, candidate in enumerate(ordered, start=1):
        candidate["layer_id"] = f"L{index}"
    _annotate_candidate_role_hints(ordered)
    return ordered


def _build_variant_families(
    candidates: list[dict[str, Any]],
    *,
    frame_count: int,
    config: LayeredOCRRefinementConfig,
) -> list[dict[str, Any]]:
    """Group OCR spellings that occupy the same visual slot.

    Stylized captions commonly change OCR spelling from frame to frame. Exact
    text support alone makes a stable caption look transient, so this summary
    exposes the combined spatial track without erasing the raw variants.
    """

    groups: list[list[dict[str, Any]]] = []
    for candidate in sorted(candidates, key=lambda item: float(item.get("average_center_y") or 0.0)):
        group = next(
            (
                existing
                for existing in groups
                if any(_same_visual_slot(candidate, member, config=config) for member in existing)
            ),
            None,
        )
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    families: list[dict[str, Any]] = []
    for family_index, group in enumerate(groups, start=1):
        family_id = f"F{family_index}"
        frame_indexes = {
            int(frame_index)
            for candidate in group
            for frame_index in candidate.get("_frame_indexes", [])
        }
        confidence_values = [
            float(confidence)
            for candidate in group
            for confidence in candidate.get("_confidence_values", [])
        ]
        representative = max(
            group,
            key=lambda item: (
                int(item.get("frame_support") or 0),
                _candidate_median_confidence(item),
                len(_semantic_compact_text(item.get("text"))),
            ),
        )
        total_weight = max(1, sum(int(item.get("frame_support") or 0) for item in group))
        average_bbox = [
            round(
                sum(
                    float(item["average_bbox"][coordinate]) * int(item.get("frame_support") or 0)
                    for item in group
                )
                / total_weight,
                1,
            )
            for coordinate in range(4)
        ]
        first_seen = min(str(item.get("first_seen")) for item in group)
        last_seen = max(str(item.get("last_seen")) for item in group)
        family = {
            "family_id": family_id,
            "canonical_text": _clean_layer_text(representative.get("text")),
            "layer_ids": [str(item["layer_id"]) for item in group],
            "frame_support": min(max(1, frame_count), len(frame_indexes)),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "median_confidence": round(median(confidence_values), 3) if confidence_values else 0.0,
            "average_bbox": average_bbox,
            "average_center_y": round((average_bbox[1] + average_bbox[3]) / 2, 1),
            "variants": [
                {
                    "layer_id": str(item["layer_id"]),
                    "text": _clean_layer_text(item.get("text")),
                    "frame_support": int(item.get("frame_support") or 0),
                    "median_confidence": round(_candidate_median_confidence(item), 3),
                }
                for item in sorted(
                    group,
                    key=lambda item: (
                        int(item.get("frame_support") or 0),
                        _candidate_median_confidence(item),
                    ),
                    reverse=True,
                )
            ],
        }
        for candidate in group:
            candidate["variant_family_id"] = family_id
            candidate.pop("_frame_indexes", None)
            candidate.pop("_confidence_values", None)
        families.append(family)
    return families


def _same_visual_slot(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    config: LayeredOCRRefinementConfig,
) -> bool:
    left_bbox = [float(value) for value in left.get("average_bbox", [])]
    right_bbox = [float(value) for value in right.get("average_bbox", [])]
    if len(left_bbox) != 4 or len(right_bbox) != 4:
        return False
    left_width = max(1.0, left_bbox[2] - left_bbox[0])
    right_width = max(1.0, right_bbox[2] - right_bbox[0])
    horizontal_overlap = max(0.0, min(left_bbox[2], right_bbox[2]) - max(left_bbox[0], right_bbox[0]))
    horizontal_ratio = horizontal_overlap / min(left_width, right_width)
    left_height = max(1.0, left_bbox[3] - left_bbox[1])
    right_height = max(1.0, right_bbox[3] - right_bbox[1])
    y_tolerance = max(config.layer_y_tolerance, 0.25 * max(left_height, right_height))
    center_delta = abs(float(left.get("average_center_y") or 0.0) - float(right.get("average_center_y") or 0.0))
    return horizontal_ratio >= 0.60 and center_delta <= y_tolerance


def apply_spatial_role_guard(
    events: list[dict[str, Any]],
    cue_evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep baseline semantics intact and gate untrusted orphan insertions.

    ``role_hint`` describes OCR geometry only. Upper text can be a spoken line,
    a visual annotation, a speaker label, or noise, so changing a model role
    from spatial evidence would be semantic overreach. Recovery candidates are
    different: they may add a cue that did not exist in the trusted baseline,
    so every retained non-noise layer must cite stable evidence whose text is
    compatible with the model's correction.
    """

    evidence_by_id = {int(item["cue_id"]): item for item in cue_evidence}
    guarded: list[dict[str, Any]] = []
    for event in events:
        cue_id = int(event["cue_id"])
        evidence = evidence_by_id.get(cue_id, {})
        if evidence.get("baseline_kind") != "orphan_candidate":
            guarded.append({"cue_id": cue_id, "layers": [dict(layer) for layer in event["layers"]]})
            continue
        if _looks_like_known_transition_bumper(evidence):
            guarded.append(
                {
                    "cue_id": cue_id,
                    "layers": [
                        {
                            "id": "recovery_guard_noise",
                            "role": "noise",
                            "text": _clean_layer_text(evidence.get("machine_text")),
                            "reason": "known full-screen transition bumper",
                        }
                    ],
                }
            )
            continue

        candidates = {
            str(candidate.get("layer_id")): candidate
            for candidate in evidence.get("layer_candidates", [])
            if isinstance(candidate, dict) and candidate.get("layer_id")
        }
        layers: list[dict[str, Any]] = []
        for layer in event["layers"]:
            copied = dict(layer)
            if copied.get("role") == "noise":
                layers.append(copied)
                continue
            evidence_ids = copied.get("evidence_layer_ids")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                continue
            referenced = [
                candidates.get(str(layer_id))
                for layer_id in evidence_ids
                if candidates.get(str(layer_id)) is not None
            ]
            stable_referenced = [candidate for candidate in referenced if candidate.get("recovery_eligible")]
            if not stable_referenced:
                continue
            if not any(
                _orphan_layer_matches_candidate(copied.get("text"), candidate.get("text"))
                for candidate in stable_referenced
            ):
                continue
            layers.append(copied)
        guarded.append({"cue_id": cue_id, "layers": layers})
    return guarded


def _orphan_layer_matches_candidate(layer_text: Any, candidate_text: Any) -> bool:
    layer = _semantic_compact_text(layer_text)
    candidate = _semantic_compact_text(candidate_text)
    if not layer or not candidate:
        return False
    if layer in candidate or candidate in layer:
        return True
    return SequenceMatcher(None, layer, candidate).ratio() >= 0.45


def _looks_like_known_transition_bumper(evidence: dict[str, Any]) -> bool:
    texts = {
        _semantic_compact_text(candidate.get("text"))
        for candidate in evidence.get("layer_candidates", [])
        if isinstance(candidate, dict)
    }
    if any(value in texts for value in ("엠뚜루", "엠뚜룬")):
        return True
    combined = " ".join(sorted(texts))
    if "엠뚜루" in combined and "마뚜루" in combined:
        return True
    upper_variants = ("엠뚜루", "엠뚜룬", "에뜨는", "에뜨르")
    lower_variants = ("마뚜루", "마뜨루", "마또를", "미또루", "미뜨루")
    return any(value in texts for value in upper_variants) and any(value in texts for value in lower_variants)


def _annotate_candidate_role_hints(candidates: list[dict[str, Any]]) -> None:
    stable = [candidate for candidate in candidates if int(candidate.get("frame_support") or 0) >= 2]
    primary_lower = max(stable, key=lambda item: float(item["average_center_y"]), default=None)
    for candidate in candidates:
        support = int(candidate.get("frame_support") or 0)
        text = str(candidate.get("text") or "").strip()
        if support < 2:
            candidate["role_hint"] = "transient_text_candidate"
            candidate["role_hint_reason"] = "text was observed in fewer than two frames"
            continue
        if _looks_like_short_bracketed_text(text):
            candidate["role_hint"] = "short_bracketed_candidate"
            candidate["role_hint_reason"] = "stable short bracketed text; semantics remain unknown"
            continue
        if primary_lower is not None and candidate is not primary_lower:
            candidate_height = max(1.0, float(candidate["average_bbox"][3]) - float(candidate["average_bbox"][1]))
            primary_height = max(
                1.0,
                float(primary_lower["average_bbox"][3]) - float(primary_lower["average_bbox"][1]),
            )
            separation = float(primary_lower["average_center_y"]) - float(candidate["average_center_y"])
            threshold = max(140.0, 1.8 * max(candidate_height, primary_height))
            if separation > threshold:
                candidate["role_hint"] = "upper_text_candidate"
                candidate["role_hint_reason"] = (
                    f"stable layer is {round(separation, 1)}px above primary lower layer "
                    f"(threshold {round(threshold, 1)}px); position does not determine semantics"
                )
                continue
        candidate["role_hint"] = "lower_text_candidate"
        candidate["role_hint_reason"] = "stable primary/lower text; semantics remain unknown"


def _uniform_sample_frames(frames: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(frames) <= limit:
        return frames
    if limit == 1:
        return [frames[len(frames) // 2]]
    indexes = [round(position * (len(frames) - 1) / (limit - 1)) for position in range(limit)]
    return [frames[index] for index in indexes]


def _allocate_boxes_across_rows(row_sizes: list[int], limit: int) -> list[int]:
    """Distribute a frame box budget across y rows before adding extras."""

    allocations = [0] * len(row_sizes)
    remaining = limit
    # First preserve at least one raw observation for every spatial row when
    # possible. Rows themselves remain in the payload even if there are more
    # rows than the raw-box budget.
    for index, size in enumerate(row_sizes):
        if remaining <= 0:
            break
        if size:
            allocations[index] = 1
            remaining -= 1
    while remaining > 0:
        changed = False
        for index, size in enumerate(row_sizes):
            if remaining <= 0:
                break
            if allocations[index] < size:
                allocations[index] += 1
                remaining -= 1
                changed = True
        if not changed:
            break
    return allocations


def _uniform_sample_items(items: list[OCRBox], limit: int) -> list[OCRBox]:
    if limit <= 0:
        return []
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[len(items) // 2]]
    indexes = [round(position * (len(items) - 1) / (limit - 1)) for position in range(limit)]
    return [items[index] for index in indexes]


def _validate_layers(cue_id: int, layers: list[Any]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    ids: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict) or not set(layer).issubset(_LAYER_KEYS):
            raise ValueError(f"cue {cue_id} contains an invalid layer object")
        role = str(layer.get("role") or "").strip()
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"cue {cue_id} contains invalid role: {role or '<missing>'}")
        text = _clean_layer_text(layer.get("text"))
        if role != "noise" and not text:
            raise ValueError(f"cue {cue_id} {role} layer requires non-empty text")
        layer_id = str(layer.get("id") or "").strip()
        if layer_id:
            if layer_id in ids:
                raise ValueError(f"cue {cue_id} contains duplicate layer id: {layer_id}")
            ids.add(layer_id)
        attach_to = str(layer.get("attach_to") or "").strip()
        evidence_ids = layer.get("evidence_layer_ids")
        if evidence_ids is not None and (
            not isinstance(evidence_ids, list) or any(not isinstance(value, str) or not value.strip() for value in evidence_ids)
        ):
            raise ValueError(f"cue {cue_id} evidence_layer_ids must be an array of strings")
        item = dict(layer)
        item["role"] = role
        item["text"] = text
        if layer_id:
            item["id"] = layer_id
        if attach_to:
            item["attach_to"] = attach_to
        validated.append(item)

    dialogue_ids = {str(layer.get("id")) for layer in validated if layer["role"] == "dialogue" and layer.get("id")}
    dialogues = [layer for layer in validated if layer["role"] == "dialogue"]
    for layer in validated:
        if layer["role"] not in {"speaker_label", "subject_label", "visual_annotation"}:
            continue
        attach_to = str(layer.get("attach_to") or "")
        if attach_to and attach_to not in dialogue_ids:
            raise ValueError(f"cue {cue_id} {layer['role']} attach_to must reference a dialogue id")
        if layer["role"] in {"speaker_label", "subject_label"} and not attach_to and not dialogues:
            raise ValueError(f"cue {cue_id} {layer['role']} has no dialogue to attach to")
    return validated


def _render_layers(layers: list[dict[str, Any]]) -> str:
    dialogues = [layer for layer in layers if layer["role"] == "dialogue"]
    annotations = [layer for layer in layers if layer["role"] == "visual_annotation"]
    speakers = [layer for layer in layers if layer["role"] == "speaker_label"]
    subjects = [layer for layer in layers if layer["role"] == "subject_label"]
    dialogue_groups = _group_duplicate_dialogues(dialogues)
    original_to_group = {
        dialogue_index: group_index
        for group_index, group in enumerate(dialogue_groups)
        for dialogue_index in group
    }
    dialogue_id_to_group = {
        str(dialogue.get("id")): original_to_group[index]
        for index, dialogue in enumerate(dialogues)
        if str(dialogue.get("id") or "").strip()
    }

    speaker_by_dialogue: dict[int, list[str]] = {}
    subject_by_dialogue: dict[int, list[str]] = {}
    annotation_by_dialogue: dict[int, list[str]] = {}
    standalone_annotations: list[str] = []
    _assign_attached_layers(
        speakers,
        dialogue_groups,
        dialogue_id_to_group,
        speaker_by_dialogue,
        cleaner=lambda value: _clean_speaker_label(str(value or "")),
    )
    _assign_attached_layers(
        subjects,
        dialogue_groups,
        dialogue_id_to_group,
        subject_by_dialogue,
        cleaner=_clean_subject_label,
    )
    _assign_attached_layers(
        annotations,
        dialogue_groups,
        dialogue_id_to_group,
        annotation_by_dialogue,
        cleaner=_clean_visual_annotation,
        unattached=standalone_annotations,
    )

    lines: list[str] = []
    if standalone_annotations:
        lines.append(_format_annotations(standalone_annotations))
    for group_index, group in enumerate(dialogue_groups):
        representative_index = max(
            group,
            key=lambda index: (
                len(_semantic_compact_text(dialogues[index].get("text"))),
                len(_clean_layer_text(dialogues[index].get("text"))),
                -index,
            ),
        )
        text = _clean_layer_text(dialogues[representative_index].get("text"))
        annotation_prefix = _format_annotations(annotation_by_dialogue.get(group_index, []))
        text = f"{annotation_prefix}{text}"
        subject_prefix = _format_subject_labels(subject_by_dialogue.get(group_index, []))
        text = f"{subject_prefix}{text}"
        speakers_for_dialogue = speaker_by_dialogue.get(group_index, [])
        if speakers_for_dialogue:
            # A styled role tag and a person's name are often emitted as two
            # adjacent OCR boxes (for example "[꽃게]" + "이선빈"). They are
            # separate spatial labels, not alternatives, so keep all of them.
            combined_speaker = " ".join(_dedupe_preserving_order(speakers_for_dialogue))
            text = _attach_speaker(combined_speaker, text)
        if text:
            lines.append(text)
    return "\n".join(_dedupe_preserving_order(lines))


def _group_duplicate_dialogues(dialogues: list[dict[str, Any]]) -> list[list[int]]:
    """Group exact/contained dialogue variants and keep unrelated lines apart."""

    parents = list(range(len(dialogues)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    compact = [_semantic_compact_text(layer.get("text")) for layer in dialogues]
    for left in range(len(dialogues)):
        for right in range(left + 1, len(dialogues)):
            left_text = compact[left]
            right_text = compact[right]
            if left_text and right_text and (left_text in right_text or right_text in left_text):
                union(left, right)

    grouped: dict[int, list[int]] = {}
    for index in range(len(dialogues)):
        grouped.setdefault(find(index), []).append(index)
    return sorted(grouped.values(), key=lambda group: group[0])


def _assign_attached_layers(
    layers: list[dict[str, Any]],
    dialogue_groups: list[list[int]],
    dialogue_id_to_group: dict[str, int],
    destination: dict[int, list[str]],
    *,
    cleaner: Callable[[Any], str],
    unattached: list[str] | None = None,
) -> None:
    fallback_index = 0
    for layer in layers:
        text = cleaner(layer.get("text"))
        if not text:
            continue
        attach_to = str(layer.get("attach_to") or "")
        group_index = dialogue_id_to_group.get(attach_to)
        if group_index is None and len(dialogue_groups) == 1:
            group_index = 0
        elif group_index is None and dialogue_groups:
            # A missing attach_to with several dialogues remains ambiguous;
            # preserve source order as the least destructive fallback.
            group_index = min(fallback_index, len(dialogue_groups) - 1)
            fallback_index += 1
        if group_index is None:
            if unattached is not None:
                unattached.append(text)
            continue
        destination.setdefault(group_index, []).append(text)


def _format_annotations(values: Iterable[str]) -> str:
    return "".join(f"[{value}]" for value in _dedupe_preserving_order(values) if value)


def _format_subject_labels(values: Iterable[str]) -> str:
    labels = [f"[{value}]" for value in _dedupe_preserving_order(values) if value]
    return f"{' '.join(labels)} " if labels else ""


def _attach_speaker(speaker: str, dialogue: str) -> str:
    speaker = _clean_speaker_label(speaker)
    dialogue = _clean_layer_text(dialogue)
    if not speaker:
        return dialogue
    prefix = re.compile(rf"^{re.escape(speaker)}\s*[:：]\s*")
    if prefix.match(dialogue):
        remainder = prefix.sub("", dialogue, count=1).strip()
        return f"{speaker}: {remainder}" if remainder else f"{speaker}:"
    return f"{speaker}: {dialogue}" if dialogue else f"{speaker}:"


def _make_non_overlapping(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    """Flatten overlapping source intervals using only their own boundaries."""

    valid = sorted((cue for cue in cues if cue.end > cue.start and cue.text.strip()), key=lambda cue: (cue.start, cue.end))
    if not valid:
        return []
    boundaries = sorted({value for cue in valid for value in (cue.start, cue.end)})
    output: list[SubtitleCue] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        active = [cue for cue in valid if cue.start <= start and cue.end >= end]
        if not active:
            continue
        lines: list[str] = []
        for cue in active:
            lines.extend(line.strip() for line in cue.text.splitlines() if line.strip())
        text = "\n".join(_dedupe_preserving_order(lines))
        if output and output[-1].end == start and output[-1].text == text:
            output[-1].end = end
        else:
            output.append(SubtitleCue(index=len(output) + 1, start=start, end=end, text=text))
    return output


def _strict_json_loads(content: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(content.strip(), object_pairs_hook=reject_duplicate_keys, parse_constant=reject_constant)


def _trusted_baseline_kind(config: LayeredOCRRefinementConfig) -> str:
    return "ocr3_refined" if config.pipeline_version == "v3" else "ocr2_refined"


def _load_geometry_hints(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("geometry_json must contain a JSON object")
    raw_evidence = data.get("track_evidence")
    raw_actions = data.get("actions")
    if not isinstance(raw_evidence, list) or not isinstance(raw_actions, list):
        raise ValueError("geometry_json must contain track_evidence and actions arrays")

    actions_by_id = {
        int(item["track_id"]): item
        for item in raw_actions
        if isinstance(item, dict) and isinstance(item.get("track_id"), int)
    }
    hints: list[dict[str, Any]] = []
    for item in raw_evidence:
        if not isinstance(item, dict) or not isinstance(item.get("track_id"), int):
            continue
        action = actions_by_id.get(int(item["track_id"]), {})
        server_features = item.get("server_features") if isinstance(item.get("server_features"), dict) else {}
        geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
        angle = geometry.get("angle") if isinstance(geometry.get("angle"), dict) else {}
        hint = {
            "track_id": int(item["track_id"]),
            "text": _clean_layer_text(item.get("text")),
            "start": round(float(item.get("start") or 0.0), 3),
            "end": round(float(item.get("end") or item.get("start") or 0.0), 3),
            "sample_count": int(item.get("sample_count") or 0),
            "average_confidence": round(float(item.get("average_confidence") or 0.0), 3),
            "classification": str(action.get("classification") or "uncertain"),
            "server_action": str(action.get("action") or "keep"),
            "server_reason": str(action.get("reason") or ""),
            "dynamic_perspective_flags": list(server_features.get("dynamic_perspective_flags") or []),
            "dynamic_perspective_evidence_count": int(
                server_features.get("dynamic_perspective_evidence_count") or 0
            ),
            "stable_slanted_program_candidate": bool(
                server_features.get("stable_slanted_program_candidate")
            ),
            "persistent_logo_candidate": bool(server_features.get("persistent_logo_candidate")),
            "median_abs_angle_degrees": angle.get("median_abs_degrees"),
            "average_bbox": item.get("average_bbox"),
            "soft_prior_only": True,
        }
        hints.append(hint)
    return hints


def _geometry_hints_for_cue(
    cue: SubtitleCue,
    geometry_hints: list[dict[str, Any]],
    *,
    layer_candidates: list[dict[str, Any]],
    config: LayeredOCRRefinementConfig,
) -> list[dict[str, Any]]:
    cue_text = _semantic_compact_text(cue.text)
    ranked: list[tuple[tuple[int, float, float, int, int, float], dict[str, Any]]] = []
    for hint in geometry_hints:
        try:
            start = float(hint.get("start") or 0.0)
            end = float(hint.get("end") or start)
        except (TypeError, ValueError):
            continue
        overlap = min(cue.end, end) - max(cue.start, start)
        if overlap < -0.12:
            continue
        hint_text = _semantic_compact_text(hint.get("text"))
        cue_similarity = _normalized_text_similarity(cue_text, hint_text)
        matched_layers: list[tuple[float, str]] = []
        for candidate in layer_candidates:
            candidate_text = _semantic_compact_text(candidate.get("text"))
            similarity = _normalized_text_similarity(candidate_text, hint_text)
            if not _geometry_hint_matches_layer(hint, candidate, similarity, config=config):
                continue
            matched_layers.append((similarity, str(candidate.get("layer_id") or "")))
        matched_layers.sort(reverse=True)
        matched_layer_ids = [layer_id for _, layer_id in matched_layers if layer_id]
        layer_similarity = matched_layers[0][0] if matched_layers else 0.0
        semantic_class = str(hint.get("classification") or "uncertain")
        class_specificity = int(semantic_class != "uncertain")
        stable_slanted = int(bool(hint.get("stable_slanted_program_candidate")))
        cue_duration = max(0.001, cue.end - cue.start)
        overlap_seconds = max(0.0, overlap)
        enriched = dict(hint)
        enriched["matched_layer_ids"] = matched_layer_ids
        enriched["overlap_seconds"] = round(overlap_seconds, 3)
        enriched["overlap_ratio"] = round(min(1.0, overlap_seconds / cue_duration), 3)
        score = (
            int(bool(matched_layer_ids)),
            max(layer_similarity, cue_similarity),
            min(1.0, overlap_seconds / cue_duration),
            class_specificity,
            stable_slanted,
            float(hint.get("sample_count") or 0),
        )
        ranked.append((score, enriched))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [hint for _, hint in ranked[: config.max_geometry_hints_per_cue]]


def _normalized_text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return 1.0
    return SequenceMatcher(
        None,
        unicodedata.normalize("NFKD", left),
        unicodedata.normalize("NFKD", right),
    ).ratio()


def _geometry_hint_matches_layer(
    hint: dict[str, Any],
    candidate: dict[str, Any],
    text_similarity: float,
    *,
    config: LayeredOCRRefinementConfig,
) -> bool:
    if text_similarity >= 0.80:
        return True
    hint_bbox = hint.get("average_bbox")
    candidate_bbox = candidate.get("average_bbox")
    if not (
        isinstance(hint_bbox, list)
        and len(hint_bbox) == 4
        and isinstance(candidate_bbox, list)
        and len(candidate_bbox) == 4
    ):
        return False
    try:
        hint_center = (float(hint_bbox[1]) + float(hint_bbox[3])) / 2
        candidate_center = (float(candidate_bbox[1]) + float(candidate_bbox[3])) / 2
        hint_height = max(1.0, float(hint_bbox[3]) - float(hint_bbox[1]))
        candidate_height = max(1.0, float(candidate_bbox[3]) - float(candidate_bbox[1]))
    except (TypeError, ValueError):
        return False
    y_tolerance = max(config.layer_y_tolerance, 1.5 * max(hint_height, candidate_height))
    return abs(hint_center - candidate_center) <= y_tolerance and text_similarity >= 0.42


def _load_ocr_boxes(path: Path) -> list[OCRBox]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("ocr_boxes_json must contain a JSON array")
    boxes: list[OCRBox] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"ocr_boxes_json item {index} must be an object")
        boxes.append(OCRBox.from_dict(item))
    return boxes


def _validate_config(config: LayeredOCRRefinementConfig) -> None:
    if config.pipeline_version not in {"v2", "v3"}:
        raise ValueError("pipeline_version must be v2 or v3")
    if config.batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if config.max_boxes_per_frame <= 0:
        raise ValueError("max_boxes_per_frame must be greater than zero")
    if config.max_frames_per_cue <= 0:
        raise ValueError("max_frames_per_cue must be greater than zero")
    if config.row_y_tolerance_ratio <= 0 or config.min_row_y_tolerance < 0 or config.layer_y_tolerance <= 0:
        raise ValueError("row y tolerances must be positive")
    if config.max_layer_candidates <= 0 or config.max_observations_per_layer <= 0:
        raise ValueError("layer candidate limits must be greater than zero")
    if config.max_geometry_hints_per_cue <= 0:
        raise ValueError("max_geometry_hints_per_cue must be greater than zero")


def _box_payload(box: OCRBox) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": box.text,
        "bbox": [round(value, 1) for value in box.bbox],
        "center_y": round(_center_y(box.bbox), 1),
        "confidence": round(box.confidence, 3),
        "region": box.region,
    }
    if box.angle_degrees is not None:
        payload["angle_degrees"] = round(box.angle_degrees, 3)
    return payload


def _center_y(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[1] + bbox[3]) / 2


def _union_bbox(bboxes: Iterable[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    values = list(bboxes)
    return (
        min(value[0] for value in values),
        min(value[1] for value in values),
        max(value[2] for value in values),
        max(value[3] for value in values),
    )


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _looks_like_short_bracketed_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact or len(compact) > 20:
        return False
    pairs = (("[", "]"), ("(", ")"), ("（", "）"), ("【", "】"), ("<", ">"), ("〈", "〉"))
    return any(compact.startswith(left) and compact.endswith(right) and len(compact) > 2 for left, right in pairs)


def _clean_layer_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _semantic_compact_text(value: Any) -> str:
    return re.sub(r"[\W_]+", "", _clean_layer_text(value), flags=re.UNICODE).casefold()


def _clean_visual_annotation(value: Any) -> str:
    text = _clean_layer_text(value)
    pairs = (("[", "]"), ("［", "］"), ("【", "】"))
    for left, right in pairs:
        if text.startswith(left) and text.endswith(right) and len(text) > len(left) + len(right):
            return text[len(left) : -len(right)].strip()
    return text


def _clean_subject_label(value: Any) -> str:
    return _clean_visual_annotation(value)


def _clean_speaker_label(text: str) -> str:
    return _TRAILING_SPEAKER_COLON_RE.sub("", _clean_layer_text(text)).strip()


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _strict_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _copy_cue(cue: SubtitleCue) -> SubtitleCue:
    return SubtitleCue(
        index=cue.index,
        start=cue.start,
        end=cue.end,
        text=cue.text.strip(),
        source_track_id=cue.source_track_id,
    )


def _write_debug(path: Path, debug: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit(callback: Callable[[str], None] | None, message: str) -> None:
    print(message, flush=True)
    if callback:
        callback(message)
