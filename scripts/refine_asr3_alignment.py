"""Re-align only anomalous timing, reusing the saved Qwen transcript and audio."""
from __future__ import annotations

import argparse
import copy
import hashlib
import shutil
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.asr3_alignment import refine_part, zero_runs, subtitle_cues_with_unresolved
from scripts.asr3_benchmark import load_json, save_json, versions


def export_alignment(dest, words, duration, raw):
    from video_translate.models import SubtitleCue
    from video_translate.subtitle.srt import write_srt
    cues = subtitle_cues_with_unresolved(words, duration)
    snapshot = dest / "export_before_text_restore"
    if not snapshot.exists() and (dest / "source.qwen3.srt").exists():
        snapshot.mkdir()
        for filename in ["source.qwen3.srt", "cues.qwen3.json", "benchmark.json"]:
            shutil.copy2(dest / filename, snapshot / filename)
    write_srt([SubtitleCue(c.index, c.start, c.end, c.text) for c, _ in cues], dest / "source.qwen3.srt")
    save_json(dest / "cues.qwen3.json", {
        "engine": "qwen3-asr-1.7b", "aligner": "local-retry-fp32",
        "cues": [{**c.to_dict(), "unresolved_word_indexes": ids, "timing_review_required": bool(ids)} for c, ids in cues],
    })
    (dest / "transcript.full.txt").write_text("\n".join(part["text"] for part in raw) + "\n", encoding="utf-8")
    inserted = {i for _, ids in cues for i in ids}
    zero_indices = {w.index for w in words if w.end <= w.start + 1e-6}
    return {"subtitle_retained_unresolved_words": len(inserted),
            "subtitle_unexported_zero_words": len(zero_indices - inserted)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--aligner-model", type=Path, default=ROOT / "models/asr3/Qwen3-ForcedAligner-0.6B")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    if args.export_only:
        from video_translate.asr_v2 import AsrWord
        for sample in load_json(args.manifest)["samples"]:
            dest = args.manifest.resolve().parent / sample["id"] / "qwen_vad_aligned"
            words = [AsrWord.from_dict(w, fallback_index=i) for i, w in enumerate(load_json(dest / "words.json")["words"], 1)]
            stats = export_alignment(dest, words, sample["duration"], load_json(dest / "raw.json"))
            save_json(dest / "benchmark.json", {**load_json(dest / "benchmark.json"), **stats})
            print(sample["id"], stats, flush=True)
        return
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ForcedAligner
    from video_translate.asr_v2 import AsrWord
    torch.set_num_threads(4)
    root = args.manifest.resolve().parent
    model = Qwen3ForcedAligner.from_pretrained(str(args.aligner_model), dtype=torch.float32,
                                              device_map="cuda:0", attn_implementation="sdpa")
    # Input tokens have already been tokenized by the original aligner. Keep
    # them intact during a local retry instead of splitting them a second time.
    processor = model.aligner_processor
    processor.tokenize_korean = lambda tokenizer, text: processor.tokenize_space_lang(text)
    summary = []
    for sample in load_json(args.manifest)["samples"]:
        started = time.perf_counter()
        source = root / sample["id"] / "qwen_vad"
        dest = root / sample["id"] / "qwen_vad_aligned"
        if dest.exists():
            raise FileExistsError(f"Refusing to overwrite previous experiment: {dest}")
        raw = load_json(source / "raw.json")
        vad = load_json(source.parent / "vad.json")
        waveform, sr = sf.read(source.parent / "audio.wav", dtype="float32")
        if hashlib.sha256((source.parent / "audio.wav").read_bytes()).hexdigest() != vad["audio_sha256"]:
            raise ValueError("Audio does not match VAD metadata")
        speech = [{"start": r["start"] / sr, "end": r["end"] / sr} for r in vad["regions"]]
        benchmark = load_json(source / "benchmark.json")
        all_words, new_raw, audit = [], [], []
        for part_index, part in enumerate(raw):
            window = benchmark["inference_windows"][part_index]
            def align(plan, words):
                a, b = round(plan["audio_start"] * sr), round(plan["audio_end"] * sr)
                # Use the actual cropped sample offset, not rounded display time.
                with torch.inference_mode():
                    result = model.align(audio=(waveform[a:b], sr),
                                         text=" ".join(w["text"] for w in words), language="Korean")[0]
                return [{"text": item.text, "start": item.start_time + a / sr,
                         "end": item.end_time + a / sr} for item in result]
            before = part["alignment"]
            revised, attempts = refine_part(before, (window["start"], window["end"]), speech, align)
            if [w["text"] for w in before] != [w["text"] for w in revised]:
                raise ValueError("Alignment retry changed recognized text")
            new_raw.append({**copy.deepcopy(part), "alignment": revised})
            for w in revised:
                all_words.append(AsrWord(len(all_words) + 1, w["start"], w["end"], " " + w["text"], None, part_index))
            unresolved = [{"word_index": i, **w} for i, w in enumerate(revised) if w["end"] <= w["start"] + 1e-6]
            audit.append({"part": part_index, "window": window, "text": part["text"],
                          "zero_before": sum(b-a for a,b in zero_runs(before)),
                          "zero_after": len(unresolved), "attempts": attempts, "unresolved": unresolved})
        save_json(dest / "raw.json", new_raw)
        save_json(dest / "words.json", {"words": [w.to_dict() for w in all_words]})
        save_json(dest / "alignment_audit.json", audit)
        export_stats = export_alignment(dest, all_words, sample["duration"], new_raw)
        zero_before = sum(x["zero_before"] for x in audit)
        zero_after = sum(x["zero_after"] for x in audit)
        result = {**benchmark, **export_stats, "alignment_refine_seconds": time.perf_counter()-started,
                  "alignment_zero_before": zero_before, "alignment_zero_duration_words": zero_after,
                  "alignment_text_preserved": True, "alignment_refined": True,
                  "accepted_retries": sum(a["accepted"] for p in audit for a in p["attempts"]),
                  "review_required": zero_after > 0,
                  "alignment_versions": versions(["qwen-asr", "torch", "transformers"])}
        save_json(dest / "benchmark.json", result)
        summary.append({"sample": sample["id"], "zero_before": zero_before, "zero_after": zero_after,
                        "accepted_retries": result["accepted_retries"], "seconds": result["alignment_refine_seconds"]})
        print(summary[-1], flush=True)
    save_json(root / "alignment_summary.json", summary)


if __name__ == "__main__":
    main()
