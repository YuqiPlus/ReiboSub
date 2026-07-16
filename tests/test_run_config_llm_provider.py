from __future__ import annotations

from pathlib import Path

from video_translate import run_config as run_config_mod


def test_run_config_accepts_openai_compatible_translation_provider(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        f"""
mode: translate
source_srt: {source}
output_dir: {tmp_path / 'out'}
target_language: 简体中文
translation:
  provider: openai-compatible
  batch_size: 1
""",
        encoding="utf-8",
    )
    called = {}

    def fake_translate(source_srt, zh_srt, **kwargs):
        called["source_srt"] = source_srt
        called["zh_srt"] = zh_srt
        Path(zh_srt).parent.mkdir(parents=True, exist_ok=True)
        Path(zh_srt).write_text("translated", encoding="utf-8")

    monkeypatch.setattr(run_config_mod, "translate_srt_with_volcengine", fake_translate)

    run_config_mod.run_config(config_path)

    assert called["source_srt"] == source
    assert called["zh_srt"] == tmp_path / "out" / "zh.srt"


def test_run_config_disables_exact_dedupe_for_translate_only(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        f"""
mode: translate
source_srt: {source}
output_dir: {tmp_path / 'out'}
translation:
  provider: openai-compatible
  ocr_translation_mode: translate_only
  dedupe_translated: false
""",
        encoding="utf-8",
    )
    called = {}

    def fake_translate(_source_srt, zh_srt, **kwargs):
        called.update(kwargs)
        Path(zh_srt).parent.mkdir(parents=True, exist_ok=True)
        Path(zh_srt).write_text("translated", encoding="utf-8")

    monkeypatch.setattr(run_config_mod, "translate_srt_with_volcengine", fake_translate)

    run_config_mod.run_config(config_path)

    assert called["dedupe_translated"] is False
    assert called["dedupe_exact_translated"] is False


def test_run_config_keeps_exact_dedupe_for_cleanup_modes(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        f"""
mode: translate
source_srt: {source}
output_dir: {tmp_path / 'out'}
translation:
  provider: openai-compatible
  ocr_translation_mode: standard_cleanup
""",
        encoding="utf-8",
    )
    called = {}

    def fake_translate(_source_srt, zh_srt, **kwargs):
        called.update(kwargs)
        Path(zh_srt).parent.mkdir(parents=True, exist_ok=True)
        Path(zh_srt).write_text("translated", encoding="utf-8")

    monkeypatch.setattr(run_config_mod, "translate_srt_with_volcengine", fake_translate)

    run_config_mod.run_config(config_path)

    assert called["dedupe_exact_translated"] is True


def test_run_config_runs_complete_v3_refinement_chain_from_machine_source(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    output_dir = tmp_path / "out"
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        f"""
mode: extract
input_video: {video}
output_dir: {output_dir}
source_srt: {output_dir / 'source.srt'}
ocr:
  extraction_mode: region_v3
  shape_mode: horizontal_preferred
ocr_refinement:
  mode: llm_geometry
  batch_size: 7
  max_observations_per_track: 9
  text_batch_size: 11
  window_padding_seconds: 0.75
  max_boxes_per_frame: 14
  layered_batch_size: 6
  layered_context_overlap: 2
source_cleanup:
  mode: none
sidecar:
  enabled: false
""",
        encoding="utf-8",
    )
    called = {"order": []}

    def fake_extract(_video, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        source = out_dir / "source.srt"
        tracks = out_dir / "tracks.json"
        boxes = out_dir / "ocr_boxes.json"
        source.write_text("machine", encoding="utf-8")
        tracks.write_text("[]", encoding="utf-8")
        boxes.write_text("[]", encoding="utf-8")
        called["extract_kwargs"] = kwargs
        return {"source_srt": source, "tracks": tracks, "ocr_boxes": boxes}

    def fake_geometry(tracks, boxes, out_srt, debug_json, **kwargs):
        called["order"].append("geometry")
        called.update({"tracks": tracks, "boxes": boxes, "geometry_kwargs": kwargs})
        out_srt.write_text("geometry", encoding="utf-8")
        debug_json.write_text("{}", encoding="utf-8")
        return {"refined_srt": out_srt, "debug_json": debug_json}

    def fake_text_refine(source, boxes, out_srt, **kwargs):
        called["order"].append("text")
        called.update({"text_source": source, "text_boxes": boxes, "text_kwargs": kwargs})
        out_srt.write_text("v3 text refined", encoding="utf-8")
        return {"refined_srt": out_srt}

    def fake_layered_refine(source, boxes, out_srt, debug_json, **kwargs):
        called["order"].append("layered")
        called.update({"layered_source": source, "layered_boxes": boxes, "layered_kwargs": kwargs})
        out_srt.write_text("v3 layered", encoding="utf-8")
        debug_json.write_text('{"layers": []}', encoding="utf-8")
        return {"layered_srt": out_srt, "layers_json": debug_json}

    monkeypatch.setattr(run_config_mod, "extract_subtitles_from_video", fake_extract)
    monkeypatch.setattr(run_config_mod, "refine_ocr_geometry_with_llm", fake_geometry)
    monkeypatch.setattr(run_config_mod, "refine_ocr_source_with_llm", fake_text_refine)
    monkeypatch.setattr(run_config_mod, "refine_ocr_layers_with_llm", fake_layered_refine)

    run_config_mod.run_config(config_path)

    assert (output_dir / "source.machine.srt").read_text(encoding="utf-8") == "machine"
    assert (output_dir / "source.geometry_refined.srt").read_text(encoding="utf-8") == "geometry"
    assert (output_dir / "source.v3.refined.srt").read_text(encoding="utf-8") == "v3 text refined"
    assert (output_dir / "source.v3.layered.srt").read_text(encoding="utf-8") == "v3 layered"
    assert (output_dir / "ocr_v3_layers.json").read_text(encoding="utf-8") == '{"layers": []}'
    assert (output_dir / "source.srt").read_text(encoding="utf-8") == "v3 layered"
    assert called["order"] == ["geometry", "text", "layered"]
    assert called["extract_kwargs"]["extraction_mode"] == "region_v3"
    assert called["geometry_kwargs"]["config"].batch_size == 7
    assert called["geometry_kwargs"]["config"].max_observations_per_track == 9
    assert called["text_source"] == output_dir / "source.machine.srt"
    assert called["text_boxes"] == output_dir / "ocr_boxes.json"
    assert called["text_kwargs"]["config"].batch_size == 11
    assert called["text_kwargs"]["config"].window_padding_seconds == 0.75
    assert called["text_kwargs"]["config"].max_boxes_per_frame == 14
    assert called["layered_source"] == output_dir / "source.v3.refined.srt"
    assert called["layered_boxes"] == output_dir / "ocr_boxes.json"
    assert called["layered_kwargs"]["recovery_srt"] == output_dir / "source.machine.srt"
    assert called["layered_kwargs"]["geometry_json"] == output_dir / "ocr_geometry.json"
    assert called["layered_kwargs"]["config"].pipeline_version == "v3"
    assert called["layered_kwargs"]["config"].batch_size == 6
    assert called["layered_kwargs"]["config"].context_overlap == 2


def test_run_config_v2_never_calls_v3_geometry_or_layered_refinement(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    output_dir = tmp_path / "out"
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        f"""
mode: extract
input_video: {video}
output_dir: {output_dir}
source_srt: {output_dir / 'source.srt'}
ocr:
  extraction_mode: region
ocr_refinement:
  mode: llm_boxes
source_cleanup:
  mode: none
sidecar:
  enabled: false
""",
        encoding="utf-8",
    )
    called = {}

    def fake_extract(_video, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        source = out_dir / "source.srt"
        boxes = out_dir / "ocr_boxes.json"
        source.write_text("v2 machine", encoding="utf-8")
        boxes.write_text("[]", encoding="utf-8")
        return {"source_srt": source, "ocr_boxes": boxes}

    def fake_text_refine(source, boxes, out_srt, **kwargs):
        called.update({"source": source, "boxes": boxes, "kwargs": kwargs})
        out_srt.write_text("v2 refined", encoding="utf-8")
        return {"refined_srt": out_srt}

    def unexpected_v3_call(*args, **kwargs):
        raise AssertionError("OCR 2.0 must not call an OCR 3.0 refinement stage")

    monkeypatch.setattr(run_config_mod, "extract_subtitles_from_video", fake_extract)
    monkeypatch.setattr(run_config_mod, "refine_ocr_source_with_llm", fake_text_refine)
    monkeypatch.setattr(run_config_mod, "refine_ocr_geometry_with_llm", unexpected_v3_call)
    monkeypatch.setattr(run_config_mod, "refine_ocr_layers_with_llm", unexpected_v3_call)

    run_config_mod.run_config(config_path)

    assert called["source"] == output_dir / "source.machine.srt"
    assert called["boxes"] == output_dir / "ocr_boxes.json"
    assert (output_dir / "source.refined.srt").read_text(encoding="utf-8") == "v2 refined"
    assert (output_dir / "source.srt").read_text(encoding="utf-8") == "v2 refined"
    assert not (output_dir / "source.geometry_refined.srt").exists()
    assert not (output_dir / "source.v3.refined.srt").exists()
    assert not (output_dir / "source.v3.layered.srt").exists()
