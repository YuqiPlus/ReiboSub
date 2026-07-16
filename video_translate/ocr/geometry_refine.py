from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median, pstdev
from typing import Any, Callable, Iterable, Mapping, Sequence

from video_translate.llm_config import load_llm_task_config
from video_translate.models import OCRBox, SubtitleCue, TextTrack
from video_translate.pipeline import tracks_to_cues
from video_translate.subtitle.srt import write_srt
from video_translate.translate.volcengine import (
    DEFAULT_BASE_URL,
    _chat_completions_url,
    _load_dotenv,
    _parse_json_content,
    _request_translation,
)
from video_translate.utils.text import text_similarity


GEOMETRY_CLASSIFICATIONS = frozenset(
    {
        "subtitle",
        "program_caption",
        "visual_annotation",
        "scene_text",
        "logo",
        "uncertain",
    }
)

GEOMETRY_DECISION_EVIDENCE = frozenset(
    {
        "bottom_region",
        "subtitle_semantics",
        "program_graphics_semantics",
        "annotation_semantics",
        "scene_object_semantics",
        "logo_semantics",
        "persistent_position",
        "stable_position",
        "stable_slanted_style",
        "center_motion",
        "scale_change",
        "rotation_change",
        "perspective_distortion",
        "perspective_change",
        "coexists_with_subtitle",
        "temporal_context",
    }
)

_DECISION_KEYS = {"track_id", "classification", "evidence", "reason"}
_DYNAMIC_PERSPECTIVE_FLAGS = (
    "center_motion",
    "scale_change",
    "rotation_change",
    "perspective_distortion",
    "perspective_change",
)


@dataclass(frozen=True, slots=True)
class GeometryRefinementConfig:
    """Conservative OCR 3.0 geometry-refinement settings.

    Geometry creates evidence, never a direct delete rule. In particular,
    ``slanted_angle_degrees`` only identifies a potentially stylised caption.
    """

    batch_size: int = 20
    max_observations_per_track: int = 10
    min_output_duration_seconds: float = 0.35
    slanted_angle_degrees: float = 8.0
    stable_angle_std_degrees: float = 3.5
    motion_range_box_diagonals: float = 0.45
    motion_displacement_box_diagonals: float = 0.35
    scale_ratio_threshold: float = 1.45
    scale_cv_threshold: float = 0.22
    rotation_change_degrees: float = 8.0
    perspective_distortion_threshold: float = 0.18
    perspective_change_threshold: float = 0.12
    scene_text_min_dynamic_perspective_evidence: int = 2
    persistent_logo_min_duration_seconds: float = 8.0
    persistent_logo_min_samples: int = 8


@dataclass(frozen=True, slots=True)
class GeometryDecision:
    track_id: int
    classification: str
    evidence: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "classification": self.classification,
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GeometryParseResult:
    decisions: dict[int, GeometryDecision]
    errors: dict[int, str]
    global_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GeometryAction:
    track_id: int
    classification: str
    action: str
    reason: str
    fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def refine_ocr_geometry_with_llm(
    tracks_json: Path,
    ocr_boxes_json: Path,
    out_srt: Path,
    debug_json: Path,
    *,
    cue_timing: Any | None = None,
    model: str | None = None,
    base_url: str | None = None,
    config: GeometryRefinementConfig | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Path]:
    """Classify OCR 3.0 tracks using geometry and write conservative output.

    The model only assigns a semantic class. Keep/drop is always derived by
    :func:`derive_geometry_action`, so malformed or missing model output cannot
    silently delete a track.
    """

    config = config or GeometryRefinementConfig()
    _validate_config(config)
    tracks = _load_tracks(tracks_json)
    boxes = _load_boxes(ocr_boxes_json)
    evidence_by_track = {
        track.id: build_track_geometry_evidence(track, boxes, config=config)
        for track in tracks
    }
    debug: dict[str, Any] = {
        "version": 3,
        "mode": "ocr3_geometry_semantic_refinement",
        "tracks_json": str(tracks_json),
        "ocr_boxes_json": str(ocr_boxes_json),
        "config": asdict(config),
        "track_count": len(tracks),
        "box_count": len(boxes),
        "track_evidence": [evidence_by_track[track.id] for track in tracks],
        "batches": [],
    }

    if not tracks:
        write_srt([], out_srt)
        debug.update({"decisions": [], "actions": [], "output_cues": []})
        _write_debug(debug_json, debug)
        _emit(progress_callback, "ocr3_geometry_refine: no tracks; wrote empty subtitle")
        return {"refined_srt": out_srt, "debug_json": debug_json}

    _load_dotenv(Path.cwd())
    task_llm = load_llm_task_config(
        "ocr_geometry_refinement",
        explicit_model=model,
        explicit_base_url=base_url,
    )
    api_key = getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    selected_model = task_llm.model
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置 OpenAI-compatible API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ocr_geometry_refinement 模型配置或 LLM_MODEL。")
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    debug["model"] = selected_model

    decisions: dict[int, GeometryDecision] = {}
    errors: dict[int, str] = {}
    batch_size = max(1, config.batch_size)
    total_batches = max(1, (len(tracks) + batch_size - 1) // batch_size)
    _emit(progress_callback, f"ocr3_geometry_refine_model: {selected_model}")
    _emit(progress_callback, f"ocr3_geometry_refine: {len(tracks)} tracks in {total_batches} batches")

    for batch_number, offset in enumerate(range(0, len(tracks), batch_size), start=1):
        batch = tracks[offset : offset + batch_size]
        label = f"{batch_number}/{total_batches}"
        _emit(progress_callback, f"ocr3_geometry_refine_batch: {label}")
        payload = build_geometry_refinement_payload(
            batch,
            boxes,
            model=selected_model,
            all_tracks=tracks,
            evidence_by_track=evidence_by_track,
            config=config,
        )
        batch_debug: dict[str, Any] = {
            "batch": label,
            "track_ids": [track.id for track in batch],
        }
        expected_ids = [track.id for track in batch]
        try:
            content = _request_translation(endpoint, api_key, payload)
            parsed = parse_geometry_refinement_response(content, expected_ids)
            decisions.update(parsed.decisions)
            errors.update(parsed.errors)
            batch_debug.update(
                {
                    "status": "ok" if not parsed.errors and not parsed.global_errors else "partial",
                    "response": content,
                    "decisions": [item.to_dict() for item in parsed.decisions.values()],
                    "errors": {str(key): value for key, value in parsed.errors.items()},
                    "global_errors": list(parsed.global_errors),
                }
            )
        except Exception as exc:  # network/schema failure must preserve every affected track
            message = f"{type(exc).__name__}: {exc}"
            for track_id in expected_ids:
                errors[track_id] = message
            batch_debug.update({"status": "fallback", "error": message})
            _emit(progress_callback, f"ocr3_geometry_refine_fallback: {label} {message}")
        debug["batches"].append(batch_debug)

    kept_tracks, actions = apply_geometry_decisions(
        tracks,
        decisions,
        evidence_by_track=evidence_by_track,
        config=config,
    )
    cues = tracks_to_geometry_cues(kept_tracks, config=config, cue_timing=cue_timing)
    write_srt(cues, out_srt)
    debug.update(
        {
            "decisions": [decisions[key].to_dict() for key in sorted(decisions)],
            "decision_errors": {str(key): value for key, value in sorted(errors.items())},
            "actions": [action.to_dict() for action in actions],
            "output_cues": [cue.to_dict() for cue in cues],
        }
    )
    _write_debug(debug_json, debug)
    _emit(progress_callback, f"ocr3_geometry_refine: finished; kept {len(kept_tracks)}/{len(tracks)} tracks")
    return {"refined_srt": out_srt, "debug_json": debug_json}


def build_geometry_refinement_payload(
    tracks: Sequence[TextTrack],
    ocr_boxes: Sequence[OCRBox],
    *,
    model: str,
    all_tracks: Sequence[TextTrack] | None = None,
    evidence_by_track: Mapping[int, dict[str, Any]] | None = None,
    config: GeometryRefinementConfig | None = None,
) -> dict[str, Any]:
    """Build the independent, classification-only OCR 3.0 LLM request."""

    config = config or GeometryRefinementConfig()
    _validate_config(config)
    all_tracks = all_tracks or tracks
    known_evidence = evidence_by_track or {}
    targets: list[dict[str, Any]] = []
    for track in tracks:
        item = dict(
            known_evidence.get(track.id)
            or build_track_geometry_evidence(track, ocr_boxes, config=config)
        )
        item["overlapping_tracks"] = _overlapping_track_context(track, all_tracks)
        targets.append(item)

    evidence_json = json.dumps(
        {
            "target_track_ids": [track.id for track in tracks],
            "tracks": targets,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 OCR 3.0 的几何语义分类器，只判断原语言屏幕文字的角色，绝不翻译、改写、合并或删除。"
                    "每条 TextTrack 必须且只能分类为 subtitle、program_caption、visual_annotation、scene_text、"
                    "logo、uncertain 之一。subtitle 是人物对白字幕；program_caption 是节目主文案、标题或强调发言；"
                    "visual_annotation 是拟声、表情、动作和短效果字；scene_text 是印在真实物品、招牌、菜单、包装、"
                    "衣服或场景表面上的文字；logo 是台标、水印和品牌标识；无法可靠判断必须选 uncertain。"
                    "几何只是证据，不是结论。angle 的绝对值再大也不能单独证明 scene_text/logo，更不能据此删字。"
                    "稳定、持续、斜着排版但位置/尺度/透视稳定的节目花字，优先考虑 program_caption 或 visual_annotation；"
                    "server_features.stable_slanted_program_candidate=true 是强保护提示。真实物品字通常随物品或镜头出现"
                    "中心移动、尺度变化、旋转变化、透视畸变或透视变化等多个相互独立证据。"
                    "scene_text 应同时具备明确的场景物体语义和至少两类 dynamic_perspective_flags；不足时选 uncertain。"
                    "logo 必须有明确 logo_semantics，不能只因为固定、倾斜或位于角落就判 logo；"
                    "服务端还会要求长时间固定出现才允许自动删除，证据不足时应选 uncertain。"
                    "同时出现的底部对白与上方节目效果字可分别是 subtitle 和 program_caption/visual_annotation，"
                    "不要因为共现就把上方文字当噪声。不得输出 keep/drop/action；最终保留或删除完全由服务端派生。"
                    "evidence 只能使用允许的枚举值，reason 用一句简短原语言或中文说明。严格返回 JSON，不能带 markdown。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "严格返回且只返回此结构："
                    '{"decisions":[{"track_id":1,"classification":"subtitle",'
                    '"evidence":["subtitle_semantics","bottom_region"],"reason":"人物对白字幕"}]}。'
                    "decision 对象必须恰好包含 track_id、classification、evidence、reason 四个字段；"
                    "每个 target_track_id 恰好出现一次。evidence 允许值："
                    + ", ".join(sorted(GEOMETRY_DECISION_EVIDENCE))
                    + "。输入：\n"
                    + evidence_json
                ),
            },
        ],
    }


def build_track_geometry_evidence(
    track: TextTrack,
    ocr_boxes: Sequence[OCRBox] = (),
    *,
    config: GeometryRefinementConfig | None = None,
) -> dict[str, Any]:
    """Compute angle, motion, scale and perspective evidence for one track."""

    config = config or GeometryRefinementConfig()
    _validate_config(config)
    samples = _enrich_track_boxes(track, ocr_boxes)
    ordered = sorted(samples, key=lambda box: (box.time, box.frame_index))
    widths = [max(1.0, box.bbox[2] - box.bbox[0]) for box in ordered]
    heights = [max(1.0, box.bbox[3] - box.bbox[1]) for box in ordered]
    areas = [width * height for width, height in zip(widths, heights)]
    centers = [((box.bbox[0] + box.bbox[2]) / 2, (box.bbox[1] + box.bbox[3]) / 2) for box in ordered]
    diagonals = [math.hypot(width, height) for width, height in zip(widths, heights)]
    typical_diagonal = median(diagonals) if diagonals else 1.0

    angles = [angle for box in ordered if (angle := _box_angle_degrees(box)) is not None]
    absolute_angles = [abs(angle) for angle in angles]
    angle_median = median(angles) if angles else None
    angle_abs_median = median(absolute_angles) if absolute_angles else None
    angle_std = pstdev(angles) if len(angles) > 1 else 0.0 if angles else None
    angle_range = max(angles) - min(angles) if angles else None

    direct_displacement = _distance(centers[0], centers[-1]) if len(centers) > 1 else 0.0
    center_x_range = max((item[0] for item in centers), default=0.0) - min(
        (item[0] for item in centers), default=0.0
    )
    center_y_range = max((item[1] for item in centers), default=0.0) - min(
        (item[1] for item in centers), default=0.0
    )
    center_range = math.hypot(center_x_range, center_y_range)
    center_path = sum(_distance(left, right) for left, right in zip(centers, centers[1:]))
    displacement_normalized = direct_displacement / max(1.0, typical_diagonal)
    range_normalized = center_range / max(1.0, typical_diagonal)
    path_normalized = center_path / max(1.0, typical_diagonal)
    center_motion = len(ordered) >= 3 and (
        range_normalized >= config.motion_range_box_diagonals
        or displacement_normalized >= config.motion_displacement_box_diagonals
    )

    width_ratio = _max_min_ratio(widths)
    height_ratio = _max_min_ratio(heights)
    area_ratio = _max_min_ratio(areas)
    area_cv = _coefficient_of_variation(areas)
    scale_change = len(ordered) >= 3 and (
        area_ratio >= config.scale_ratio_threshold
        or max(width_ratio, height_ratio) >= config.scale_ratio_threshold
        or area_cv >= config.scale_cv_threshold
    )
    rotation_change = len(angles) >= 3 and bool(angle_range is not None and angle_range >= config.rotation_change_degrees)

    perspective_scores = [
        score
        for box in ordered
        if (score := _polygon_perspective_score(box.polygon)) is not None
    ]
    perspective_median = median(perspective_scores) if perspective_scores else None
    perspective_max = max(perspective_scores) if perspective_scores else None
    perspective_range = (
        max(perspective_scores) - min(perspective_scores)
        if len(perspective_scores) >= 2
        else 0.0 if perspective_scores else None
    )
    perspective_distortion = bool(
        perspective_median is not None
        and perspective_median >= config.perspective_distortion_threshold
    )
    perspective_change = len(perspective_scores) >= 3 and bool(
        perspective_range is not None
        and perspective_range >= config.perspective_change_threshold
    )

    flags = {
        "center_motion": center_motion,
        "scale_change": scale_change,
        "rotation_change": rotation_change,
        "perspective_distortion": perspective_distortion,
        "perspective_change": perspective_change,
    }
    active_flags = [name for name in _DYNAMIC_PERSPECTIVE_FLAGS if flags[name]]
    stable_slanted = bool(
        len(angles) >= 2
        and angle_abs_median is not None
        and angle_abs_median >= config.slanted_angle_degrees
        and angle_std is not None
        and angle_std <= config.stable_angle_std_degrees
        and len(active_flags) <= 1
    )
    stable_position = not center_motion and not scale_change and not rotation_change and not perspective_change
    persistent_logo_candidate = bool(
        stable_position
        and track.duration >= config.persistent_logo_min_duration_seconds
        and len(ordered) >= config.persistent_logo_min_samples
    )

    average_bbox = track.average_bbox
    region_counts = Counter(box.region for box in ordered)
    observations = _sample_observations(ordered, config.max_observations_per_track)
    return {
        "track_id": track.id,
        "text": track.text,
        "start": round(track.start, 3),
        "end": round(track.end, 3),
        "duration_seconds": round(track.duration, 3),
        "sample_count": len(ordered),
        "average_confidence": round(track.average_confidence, 4),
        "prior_kind": track.kind.value,
        "prior_reason": track.reason,
        "region_counts": dict(sorted(region_counts.items())),
        "average_bbox": [round(value, 2) for value in average_bbox],
        "geometry": {
            "angle": {
                "sample_count": len(angles),
                "median_degrees": _rounded(angle_median),
                "median_abs_degrees": _rounded(angle_abs_median),
                "std_degrees": _rounded(angle_std),
                "range_degrees": _rounded(angle_range),
                "slanted": bool(angle_abs_median is not None and angle_abs_median >= config.slanted_angle_degrees),
            },
            "motion": {
                "direct_displacement_px": round(direct_displacement, 3),
                "center_range_px": round(center_range, 3),
                "center_path_px": round(center_path, 3),
                "direct_displacement_box_diagonals": round(displacement_normalized, 4),
                "center_range_box_diagonals": round(range_normalized, 4),
                "center_path_box_diagonals": round(path_normalized, 4),
                "center_motion": center_motion,
            },
            "scale": {
                "width_ratio": round(width_ratio, 4),
                "height_ratio": round(height_ratio, 4),
                "area_ratio": round(area_ratio, 4),
                "area_cv": round(area_cv, 4),
                "scale_change": scale_change,
            },
            "perspective": {
                "sample_count": len(perspective_scores),
                "median_distortion": _rounded(perspective_median, 4),
                "max_distortion": _rounded(perspective_max, 4),
                "distortion_range": _rounded(perspective_range, 4),
                "perspective_distortion": perspective_distortion,
                "perspective_change": perspective_change,
            },
        },
        "server_features": {
            "dynamic_perspective_flags": active_flags,
            "dynamic_perspective_evidence_count": len(active_flags),
            "stable_position": stable_position,
            "stable_slanted_program_candidate": stable_slanted,
            "persistent_logo_candidate": persistent_logo_candidate,
            "angle_alone_can_drop": False,
        },
        "observations": observations,
    }


def parse_geometry_refinement_response(
    content: str,
    expected_track_ids: Iterable[int],
) -> GeometryParseResult:
    """Strictly parse decisions while isolating per-track failures."""

    expected = list(dict.fromkeys(int(value) for value in expected_track_ids))
    expected_set = set(expected)
    errors: dict[int, str] = {}
    global_errors: list[str] = []
    decisions: dict[int, GeometryDecision] = {}
    try:
        data = _parse_json_content(content)
    except Exception as exc:
        message = f"invalid JSON: {exc}"
        return GeometryParseResult({}, {track_id: message for track_id in expected}, (message,))
    if not isinstance(data, dict) or set(data) != {"decisions"} or not isinstance(data.get("decisions"), list):
        message = "root must be exactly {'decisions': [...]}"
        return GeometryParseResult({}, {track_id: message for track_id in expected}, (message,))

    seen: set[int] = set()
    for index, raw in enumerate(data["decisions"]):
        if not isinstance(raw, dict):
            global_errors.append(f"decision[{index}] must be an object")
            continue
        raw_id = raw.get("track_id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, int):
            global_errors.append(f"decision[{index}].track_id must be an integer")
            continue
        track_id = raw_id
        if track_id not in expected_set:
            global_errors.append(f"unexpected track_id {track_id}")
            continue
        if track_id in seen:
            decisions.pop(track_id, None)
            errors[track_id] = "duplicate decision"
            continue
        seen.add(track_id)
        if set(raw) != _DECISION_KEYS:
            errors[track_id] = "decision fields must be exactly track_id/classification/evidence/reason"
            continue
        classification = raw.get("classification")
        evidence = raw.get("evidence")
        reason = raw.get("reason")
        if classification not in GEOMETRY_CLASSIFICATIONS:
            errors[track_id] = f"invalid classification: {classification!r}"
            continue
        if (
            not isinstance(evidence, list)
            or any(not isinstance(item, str) or item not in GEOMETRY_DECISION_EVIDENCE for item in evidence)
            or len(set(evidence)) != len(evidence)
        ):
            errors[track_id] = "evidence must be a unique list of allowed strings"
            continue
        if not isinstance(reason, str) or not reason.strip():
            errors[track_id] = "reason must be a non-empty string"
            continue
        decisions[track_id] = GeometryDecision(
            track_id=track_id,
            classification=classification,
            evidence=tuple(evidence),
            reason=reason.strip(),
        )

    for track_id in expected:
        if track_id not in decisions and track_id not in errors:
            errors[track_id] = "missing decision"
    return GeometryParseResult(decisions, errors, tuple(global_errors))


def derive_geometry_action(
    track: TextTrack,
    decision: GeometryDecision | None,
    evidence: Mapping[str, Any],
    *,
    config: GeometryRefinementConfig | None = None,
) -> GeometryAction:
    """Derive keep/drop without accepting an LLM-authored action field."""

    config = config or GeometryRefinementConfig()
    if decision is None:
        return GeometryAction(track.id, "uncertain", "keep", "missing/invalid LLM decision; conservative keep", True)
    classification = decision.classification
    if classification in {"subtitle", "program_caption", "visual_annotation", "uncertain"}:
        return GeometryAction(track.id, classification, "keep", f"semantic class {classification}")

    features = evidence.get("server_features") if isinstance(evidence, Mapping) else {}
    if not isinstance(features, Mapping):
        features = {}
    stable_slanted = bool(features.get("stable_slanted_program_candidate"))
    persistent_logo = bool(features.get("persistent_logo_candidate"))
    evidence_count = int(features.get("dynamic_perspective_evidence_count") or 0)
    if classification == "scene_text":
        if stable_slanted:
            return GeometryAction(track.id, classification, "keep", "stable slanted program-text protection")
        if evidence_count < config.scene_text_min_dynamic_perspective_evidence:
            return GeometryAction(
                track.id,
                classification,
                "keep",
                f"scene_text has only {evidence_count} dynamic/perspective evidence types; conservative keep",
            )
        return GeometryAction(
            track.id,
            classification,
            "drop",
            f"scene_text confirmed by {evidence_count} independent dynamic/perspective evidence types",
        )

    # A model-authored semantic label is not enough to erase static program
    # graphics. Automatic logo deletion requires both explicit logo semantics
    # and the server-computed long-persistence signal. A user-drawn exclusion
    # region is already enforced in extraction and never reaches this stage.
    if classification == "logo":
        if stable_slanted and not persistent_logo:
            return GeometryAction(track.id, classification, "keep", "stable slanted program-text protection")
        if persistent_logo and "logo_semantics" in decision.evidence:
            return GeometryAction(track.id, classification, "drop", "persistent semantic logo classification")
        return GeometryAction(track.id, classification, "keep", "logo evidence is not persistent enough; conservative keep")

    return GeometryAction(track.id, "uncertain", "keep", "unsupported classification; conservative keep", True)


def apply_geometry_decisions(
    tracks: Sequence[TextTrack],
    decisions: Mapping[int, GeometryDecision] | Iterable[GeometryDecision],
    *,
    evidence_by_track: Mapping[int, Mapping[str, Any]] | None = None,
    ocr_boxes: Sequence[OCRBox] = (),
    config: GeometryRefinementConfig | None = None,
) -> tuple[list[TextTrack], list[GeometryAction]]:
    """Apply server policy and preserve tracks with missing/invalid decisions."""

    config = config or GeometryRefinementConfig()
    decision_map = (
        dict(decisions)
        if isinstance(decisions, Mapping)
        else {decision.track_id: decision for decision in decisions}
    )
    known_evidence = evidence_by_track or {}
    kept: list[TextTrack] = []
    actions: list[GeometryAction] = []
    for track in tracks:
        evidence = known_evidence.get(track.id) or build_track_geometry_evidence(track, ocr_boxes, config=config)
        action = derive_geometry_action(track, decision_map.get(track.id), evidence, config=config)
        actions.append(action)
        if action.action == "keep":
            kept.append(track)
    return kept, actions


def tracks_to_geometry_cues(
    tracks: Sequence[TextTrack],
    *,
    config: GeometryRefinementConfig | None = None,
    cue_timing: Any | None = None,
) -> list[SubtitleCue]:
    """Render retained tracks through the canonical OCR cue pipeline.

    The geometry decision stays track-based, but simultaneous spatial rows and
    timing transitions must remain identical to the machine extraction path.
    """

    config = config or GeometryRefinementConfig()
    if cue_timing is None:
        # Keep the module's documented minimum when called outside run_config.
        from video_translate.pipeline import CueTimingConfig

        cue_timing = CueTimingConfig(min_duration_seconds=config.min_output_duration_seconds)
    return tracks_to_cues(list(tracks), cue_timing=cue_timing)


def _enrich_track_boxes(track: TextTrack, ocr_boxes: Sequence[OCRBox]) -> list[OCRBox]:
    if not track.boxes:
        return [
            box
            for box in ocr_boxes
            if track.start - 0.05 <= box.time <= track.end + 0.05
            and text_similarity(track.text, box.text) >= 0.68
        ]
    by_frame: dict[int, list[OCRBox]] = defaultdict(list)
    for box in ocr_boxes:
        by_frame[box.frame_index].append(box)
    result: list[OCRBox] = []
    for sample in track.boxes:
        best: OCRBox | None = None
        best_score = float("-inf")
        for candidate in by_frame.get(sample.frame_index, ()):
            similarity = text_similarity(sample.text, candidate.text)
            if similarity < 0.60:
                continue
            overlap = _bbox_iou(sample.bbox, candidate.bbox)
            center_distance = _distance(_bbox_center(sample.bbox), _bbox_center(candidate.bbox))
            typical_height = max(1.0, sample.bbox[3] - sample.bbox[1], candidate.bbox[3] - candidate.bbox[1])
            if overlap < 0.05 and center_distance / typical_height > 1.5:
                continue
            geometry_bonus = 1.0 if candidate.polygon is not None else 0.0
            score = similarity * 3 + overlap * 2 + geometry_bonus
            if score > best_score:
                best = candidate
                best_score = score
        result.append(best or sample)
    return result


def _sample_observations(boxes: Sequence[OCRBox], limit: int) -> list[dict[str, Any]]:
    if not boxes or limit <= 0:
        return []
    if len(boxes) <= limit:
        sampled = list(boxes)
    elif limit == 1:
        sampled = [boxes[len(boxes) // 2]]
    else:
        indexes = {round(index * (len(boxes) - 1) / (limit - 1)) for index in range(limit)}
        sampled = [boxes[index] for index in sorted(indexes)]
    return [
        {
            "time": round(box.time, 3),
            "frame_index": box.frame_index,
            "text": box.text,
            "confidence": round(box.confidence, 4),
            "region": box.region,
            "bbox": [round(value, 2) for value in box.bbox],
            "angle_degrees": _rounded(_box_angle_degrees(box)),
            "perspective_distortion": _rounded(_polygon_perspective_score(box.polygon), 4),
        }
        for box in sampled
    ]


def _overlapping_track_context(track: TextTrack, tracks: Sequence[TextTrack]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for other in tracks:
        if other.id == track.id or min(track.end, other.end) < max(track.start, other.start):
            continue
        result.append(
            {
                "track_id": other.id,
                "text": other.text,
                "start": round(other.start, 3),
                "end": round(other.end, 3),
                "average_bbox": [round(value, 2) for value in other.average_bbox],
            }
        )
    return result[:12]


def _box_angle_degrees(box: OCRBox) -> float | None:
    if box.angle_degrees is not None and math.isfinite(box.angle_degrees):
        return _normalize_angle(box.angle_degrees)
    polygon = box.polygon
    if not polygon or len(polygon) < 2:
        return None
    first_dx = polygon[1][0] - polygon[0][0]
    first_dy = polygon[1][1] - polygon[0][1]
    dx, dy = first_dx, first_dy
    if len(polygon) >= 4:
        opposite_dx = polygon[2][0] - polygon[3][0]
        opposite_dy = polygon[2][1] - polygon[3][1]
        if math.hypot(opposite_dx, opposite_dy) > 1e-6:
            dx += opposite_dx
            dy += opposite_dy
    if math.hypot(dx, dy) <= 1e-6:
        dx, dy = first_dx, first_dy
    if math.hypot(dx, dy) <= 1e-6:
        return None
    return _normalize_angle(math.degrees(math.atan2(dy, dx)))


def _polygon_perspective_score(polygon: Sequence[tuple[float, float]] | None) -> float | None:
    if polygon is None or len(polygon) < 4:
        return None
    points = list(polygon[:4])
    top = _distance(points[0], points[1])
    right = _distance(points[1], points[2])
    bottom = _distance(points[3], points[2])
    left = _distance(points[0], points[3])
    if min(top, right, bottom, left) <= 1e-6:
        return None
    opposite_edge_imbalance = max(abs(math.log(top / bottom)), abs(math.log(left / right)))
    top_angle = math.degrees(math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0]))
    bottom_angle = math.degrees(math.atan2(points[2][1] - points[3][1], points[2][0] - points[3][0]))
    left_angle = math.degrees(math.atan2(points[3][1] - points[0][1], points[3][0] - points[0][0]))
    right_angle = math.degrees(math.atan2(points[2][1] - points[1][1], points[2][0] - points[1][0]))
    parallel_divergence = max(
        _parallel_angle_delta(top_angle, bottom_angle),
        _parallel_angle_delta(left_angle, right_angle),
    ) / 45.0
    return max(opposite_edge_imbalance, parallel_divergence)


def _parallel_angle_delta(left: float, right: float) -> float:
    delta = abs((left - right + 90.0) % 180.0 - 90.0)
    return min(90.0, delta)


def _normalize_angle(value: float) -> float:
    return (value + 90.0) % 180.0 - 90.0


def _max_min_ratio(values: Sequence[float]) -> float:
    if not values:
        return 1.0
    return max(values) / max(1e-6, min(values))


def _coefficient_of_variation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return pstdev(values) / max(1e-6, mean)


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    if intersection <= 0:
        return 0.0
    left_area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    right_area = max(1.0, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / max(1.0, left_area + right_area - intersection)


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def _rounded(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _load_tracks(path: Path) -> list[TextTrack]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("tracks_json must contain a JSON array")
    tracks: list[TextTrack] = []
    seen: set[int] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"tracks_json item {index} must be an object")
        track = TextTrack.from_dict(item)
        if track.id in seen:
            raise ValueError(f"tracks_json contains duplicate track id {track.id}")
        seen.add(track.id)
        tracks.append(track)
    return sorted(tracks, key=lambda item: (item.start, item.end, item.id))


def _load_boxes(path: Path) -> list[OCRBox]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("ocr_boxes_json must contain a JSON array")
    boxes: list[OCRBox] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"ocr_boxes_json item {index} must be an object")
        boxes.append(OCRBox.from_dict(item))
    return boxes


def _validate_config(config: GeometryRefinementConfig) -> None:
    if config.batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if config.max_observations_per_track < 1:
        raise ValueError("max_observations_per_track must be at least 1")
    if config.scene_text_min_dynamic_perspective_evidence < 2:
        raise ValueError("scene_text_min_dynamic_perspective_evidence must be at least 2")
    if config.min_output_duration_seconds <= 0:
        raise ValueError("min_output_duration_seconds must be positive")


def _write_debug(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit(callback: Callable[[str], None] | None, message: str) -> None:
    print(message, flush=True)
    if callback:
        callback(message)
