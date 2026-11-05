"""Run an isolated, local ASR comparison without changing Agent defaults.

Use the project Python for prepare/whisper/report and the separate Qwen
environment for qwen. Every command takes the same --manifest JSON path.
The report measures disagreement, not accuracy: no reference transcript exists.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import subprocess
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def versions(names):
    return {name: importlib.metadata.version(name) for name in names}


def prepare(manifest, root, _args):
    for sample in manifest["samples"]:
        folder = root / sample["id"]
        folder.mkdir(parents=True, exist_ok=True)
        audio = folder / "audio.wav"
        if not audio.exists():
            source = (["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono"] if sample.get("silence_control")
                      else ["-ss", str(sample["start"]), "-i", sample["input"]])
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-n", *source, "-t", str(sample["duration"]),
                *(["-af", f"volume={sample['gain_db']}dB"] if "gain_db" in sample else []),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
            ], check=True)
        import wave
        with wave.open(str(audio)) as stream:
            duration = stream.getnframes() / stream.getframerate()
        if abs(duration - sample["duration"]) > 0.1:
            raise ValueError(f"Incomplete clip: {sample['id']} ({duration})")
        save_json(folder / "sample.json", {
            **sample, "audio": str(audio), "actual_duration": duration,
            "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        })
        print("prepared", sample["id"], duration, flush=True)


def overlap_seconds(start, end, intervals):
    return sum(max(0.0, min(end, region["end"]) - max(start, region["start"])) for region in intervals)


def vad(manifest, root, _args):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    from faster_whisper.utils import get_assets_path
    model_path = Path(get_assets_path()) / "silero_vad_v6.onnx"
    model_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
    for sample in manifest["samples"]:
        started = time.perf_counter()
        audio_path = root / sample["id"] / "audio.wav"
        waveform = decode_audio(str(audio_path), sampling_rate=16000)
        parameters = dict(threshold=0.25, min_speech_duration_ms=80,
                          min_silence_duration_ms=350, speech_pad_ms=500,
                          max_speech_duration_s=30)
        regions = get_speech_timestamps(waveform, VadOptions(**parameters))
        strict = get_speech_timestamps(waveform, VadOptions(**{**parameters, "threshold": 0.5}))
        seconds = [{"start": r["start"] / 16000, "end": r["end"] / 16000} for r in regions]
        excluded = []
        for engine in ["whisper", "qwen"]:
            path = root / sample["id"] / engine / "words.json"
            if not path.exists():
                continue
            for word in load_json(path)["words"]:
                start, end = word["start"], word["end"]
                # Alignment can produce a zero-duration word. Check a small
                # interval around it rather than declaring every point absent.
                if end == start:
                    start, end = max(0, start - 0.02), min(sample["duration"], end + 0.02)
                covered = overlap_seconds(start, end, seconds)
                if end > start and covered / (end - start) < 0.5:
                    excluded.append({"engine": engine, "start": word["start"],
                                     "end": word["end"], "text": word["text"],
                                     "speech_coverage": round(covered / (end - start), 3)})
        save_json(root / sample["id"] / "vad.json", {
            "provider": "faster-whisper/Silero VAD v6 ONNX", "model_sha256": model_sha,
            "versions": versions(["faster-whisper", "onnxruntime"]),
            "audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest(),
            "sample_rate": 16000, "audio_frames": len(waveform), "parameters": parameters,
            "regions": regions, "strict_regions": strict,
            "speech_seconds": sum(r["end"] - r["start"] for r in regions) / 16000,
            "strict_speech_seconds": sum(r["end"] - r["start"] for r in strict) / 16000,
            "excluded_previous_words": excluded,
            "review_note": "旧引擎有文字而 VAD 未覆盖的位置仅是回听候选，不能直接判定漏词。",
            "wall_seconds": time.perf_counter() - started,
        })
        print("vad done", sample["id"], len(regions), "speech regions", flush=True)


def inference_windows(frame_count, sample_rate, chunk_seconds, regions=None):
    """Keep original offsets; never concatenate disjoint speech regions."""
    if frame_count < 0 or sample_rate <= 0 or not math.isfinite(chunk_seconds) or chunk_seconds <= 0:
        raise ValueError("Invalid audio/window size")
    maximum = round(chunk_seconds * sample_rate)
    if maximum < 1:
        raise ValueError("Chunk size must contain at least one frame")
    ranges = [{"start": 0, "end": frame_count}] if regions is None else regions
    windows = []
    previous_end = 0
    for region in ranges:
        start, end = region["start"], region["end"]
        if not (isinstance(start, int) and isinstance(end, int) and previous_end <= start < end <= frame_count):
            raise ValueError("Speech regions must be ordered, disjoint and inside the audio")
        windows.extend((offset, min(end, offset + maximum)) for offset in range(start, end, maximum))
        previous_end = end
    return windows


def vad_inference_windows(frame_count, sample_rate, chunk_seconds, regions, mode="gate"):
    # Validate detector offsets even when only gating the original windows.
    speech = inference_windows(frame_count, sample_rate, chunk_seconds, regions)
    if mode == "speech":
        return speech
    if mode != "gate":
        raise ValueError("Unknown VAD window mode")
    return [(start, end) for start, end in inference_windows(frame_count, sample_rate, chunk_seconds)
            if any(region["start"] < end and region["end"] > start for region in regions)]


def whisper(manifest, root, args):
    from video_translate.tools.transcribe_audio_v2 import transcribe_audio_v2
    from video_translate.asr_v2 import read_words_json, write_asr_v2_outputs
    for sample in manifest["samples"]:
        folder = root / sample["id"] / "whisper"
        if (folder / "benchmark.json").exists() and not args.force:
            continue
        started = time.perf_counter()
        result = transcribe_audio_v2(
            root / sample["id"] / "audio.wav", folder,
            model_size="large-v3", language="korean", device="cuda",
            compute_type="float16", recovery_enabled=True,
        )
        _, words = read_words_json(result["words_path"])
        write_asr_v2_outputs(folder, words)
        save_json(folder / "benchmark.json", {
            "wall_seconds": time.perf_counter() - started,
            "includes_model_loading": True, "recovery": True,
            "versions": versions(["faster-whisper", "ctranslate2"]),
        })
        print("whisper done", sample["id"], flush=True)


def qwen(manifest, root, args):
    import torch
    import soundfile as sf
    from qwen_asr import Qwen3ASRModel
    from video_translate.asr_v2 import AsrWord, write_asr_v2_outputs
    torch.set_num_threads(4)
    started = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        str(args.asr_model), dtype=torch.bfloat16, device_map="cuda:0",
        attn_implementation="sdpa", max_inference_batch_size=1,
        max_new_tokens=2048, forced_aligner=str(args.aligner_model),
        forced_aligner_kwargs={"dtype": torch.bfloat16, "device_map": "cuda:0", "attn_implementation": "sdpa"},
    )
    torch.cuda.synchronize()
    save_json(root / f"{args.qwen_dir}_runtime.json", {
        "model_load_seconds": time.perf_counter() - started,
        "asr_model": str(args.asr_model), "aligner_model": str(args.aligner_model),
        "gpu": torch.cuda.get_device_name(), "attention": "sdpa",
        "versions": versions(["torch", "torchaudio", "transformers", "qwen-asr"]),
    })
    for sample in manifest["samples"]:
        folder = root / sample["id"] / args.qwen_dir
        if (folder / "benchmark.json").exists() and not args.force:
            continue
        started = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        audio_path = root / sample["id"] / "audio.wav"
        waveform, sample_rate = sf.read(audio_path, dtype="float32")
        vad_data = None
        if args.qwen_dir in {"qwen_vad", "qwen_vad_tight"}:
            vad_data = load_json(root / sample["id"] / "vad.json")
            if vad_data["sample_rate"] != sample_rate or vad_data["audio_frames"] != len(waveform):
                raise ValueError("VAD audio dimensions do not match")
            if vad_data["audio_sha256"] != hashlib.sha256(audio_path.read_bytes()).hexdigest():
                raise ValueError("VAD was computed for different audio")
        windows = (vad_inference_windows(len(waveform), sample_rate, args.qwen_chunk_seconds,
                                         vad_data["regions"], args.vad_window_mode) if vad_data
                   else inference_windows(len(waveform), sample_rate, args.qwen_chunk_seconds))
        audios = [(waveform[start:end], sample_rate) for start, end in windows]
        with torch.inference_mode():
            results = model.transcribe(
                audio=audios,
                language="Korean", return_time_stamps=True,
            ) if audios else []
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        raw = []
        words = []
        if len(results) != len(windows):
            raise ValueError("Qwen result count does not match inference windows")
        for result_index, result in enumerate(results):
            offset_seconds = windows[result_index][0] / sample_rate
            if not result.time_stamps and result.text.strip():
                raise ValueError("Qwen returned text without timestamps")
            aligned = []
            for item in result.time_stamps or []:
                start_time = item.start_time + offset_seconds
                end_time = item.end_time + offset_seconds
                aligned.append({"text": item.text, "start": start_time, "end": end_time})
                if not item.text.strip():
                    continue
                if not (math.isfinite(item.start_time) and math.isfinite(item.end_time)):
                    raise ValueError("Nonfinite alignment timestamp")
                if start_time < 0 or end_time > sample["duration"] + 0.1 or end_time < start_time:
                    raise ValueError(f"Invalid timestamp: {item}")
                words.append(AsrWord(
                    index=len(words) + 1, start=start_time, end=end_time,
                    text=" " + item.text, probability=None, segment_id=result_index,
                ))
            raw.append({"language": result.language, "text": result.text, "offset_seconds": offset_seconds, "alignment": aligned})
        save_json(folder / "raw.json", raw)
        save_json(folder / "words.json", {"words": [word.to_dict() for word in words]})
        write_asr_v2_outputs(folder, words)
        (folder / "source.asr2.srt").rename(folder / "source.qwen3.srt")
        cues_data = load_json(folder / "cues.asr2.json")
        save_json(folder / "cues.qwen3.json", {
            "engine": "qwen3-asr-1.7b", "aligner": "qwen3-forcedaligner-0.6b",
            "segmenter_version": cues_data["version"], "cues": cues_data["cues"],
        })
        (folder / "cues.asr2.json").unlink()
        save_json(folder / "benchmark.json", {
            "wall_seconds": elapsed, "includes_model_loading": False,
            "peak_allocated_gib": torch.cuda.max_memory_allocated() / 1024**3,
            "peak_reserved_gib": torch.cuda.max_memory_reserved() / 1024**3,
            "hotwords": False, "llm_rewrite": False,
            "chunk_seconds": args.qwen_chunk_seconds,
            "vad_enabled": vad_data is not None,
            "vad_window_mode": args.vad_window_mode if vad_data else None,
            "vad_wall_seconds": vad_data["wall_seconds"] if vad_data else 0,
            "inference_windows": [{"start": start / sample_rate, "end": end / sample_rate} for start, end in windows],
            "skipped_no_speech": not windows,
            "inference_audio_seconds": sum(end - start for start, end in windows) / sample_rate,
            "alignment_zero_duration_words": sum(word.end == word.start for word in words),
            "alignment_text_preserved": normalized("".join(r["text"] for r in raw)) == normalized("".join(word.text for word in words)),
        })
        print("qwen done", sample["id"], round(elapsed, 2), flush=True)


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if c.isalnum())


def report(manifest, root, args):
    samples = []
    windows = []
    for sample in manifest["samples"]:
        item = {**sample, "audio": str(root / sample["id"] / "audio.wav"), "engines": {}}
        engines = ["whisper", "qwen_before_vad", "qwen"] if args.qwen_dir.startswith("qwen_vad") else ["whisper", "qwen"]
        for engine in engines:
            before_folder = "qwen_vad" if args.qwen_dir == "qwen_vad_aligned" else "qwen"
            folder_name = args.qwen_dir if engine == "qwen" else (before_folder if engine == "qwen_before_vad" else engine)
            folder = root / sample["id"] / folder_name
            suffix = "asr2" if engine == "whisper" else "qwen3"
            cues = load_json(folder / f"cues.{suffix}.json")["cues"]
            if any(cue["end"] <= cue["start"] or cue["start"] < 0 for cue in cues):
                raise ValueError(f"Invalid SRT timing: {sample['id']} {engine}")
            item["engines"][engine] = {
                "cues": cues, "benchmark": load_json(folder / "benchmark.json"),
                "srt": str(folder / f"source.{suffix}.srt"),
                "characters": len(normalized(" ".join(c["text"] for c in cues))),
            }
        if args.qwen_dir.startswith("qwen_vad"):
            item["vad"] = load_json(root / sample["id"] / "vad.json")
        if args.qwen_dir == "qwen_vad_aligned":
            audit_path = root / sample["id"] / args.qwen_dir / "alignment_audit.json"
            item["alignment_audit"] = str(audit_path)
            item["alignment_transcript"] = str(audit_path.parent / "transcript.full.txt")
            item["alignment_review"] = [
                {"start": part["window"]["start"], "end": part["window"]["end"],
                 "text": " ".join(w["text"] for w in part["unresolved"])}
                for part in load_json(audit_path) if part["unresolved"]
            ]
        for start in range(0, int(math.ceil(sample["duration"])), 10):
            end = min(start + 10, sample["duration"])
            text = {}
            for engine, data in item["engines"].items():
                text[engine] = " ".join(c["text"] for c in data["cues"] if start <= (c["start"] + c["end"]) / 2 < end)
            # A timing-only third column must not hide cross-engine differences.
            a, b = normalized(text["whisper"]), normalized(text["qwen"])
            if not any(normalized(value) for value in text.values()):
                continue
            disagreement = 1 - SequenceMatcher(None, a, b, autojunk=False).ratio()
            windows.append({"sample_id": sample["id"], "start": start, "end": end,
                            "disagreement": round(disagreement, 4), **text})
        samples.append(item)
    windows.sort(key=lambda x: x["disagreement"], reverse=True)
    chunk_seconds = samples[0]["engines"]["qwen"]["benchmark"].get("chunk_seconds")
    mode = (f"Qwen 使用 {chunk_seconds:g} 秒分块识别和对齐。" if chunk_seconds
            else "第一轮：片段整段识别和对齐。")
    if args.qwen_dir.startswith("qwen_vad"):
        window_mode = samples[0]["engines"]["qwen"]["benchmark"].get("vad_window_mode", "speech")
        strategy = "整窗无语音才跳过，保留原 30 秒上下文" if window_mode == "gate" else "按逐段检测到的语音裁剪"
        mode = f"Qwen 加语音检测：{strategy}，保留原音时间偏移；下表优先回听 ASR 2.2 与 Qwen 的分歧。"
    labels = {"whisper": "ASR 2.2：Whisper（含恢复）"}
    if args.qwen_dir.startswith("qwen_vad"):
        labels["qwen_before_vad"] = "Qwen：原 30 秒分块"
    labels["qwen"] = "Qwen ＋ 语音检测" if args.qwen_dir.startswith("qwen_vad") else "Qwen ＋ ForcedAligner"
    if args.qwen_dir == "qwen_vad_aligned":
        labels["qwen_before_vad"] = "Qwen：原时间轴（含语音检测）"
        labels["qwen"] = "Qwen：局部重新对齐"
        mode = "Qwen 新方案：保守语音检测＋30 秒上下文＋异常词局部重对齐；重对齐不修改原识别文字，不补造最小时长。左列为 ASR 2.2，中列为 Qwen 重对齐前，右列为 Qwen 最终结果。下表优先回听 ASR 2.2 与 Qwen 最终结果的分歧。"
    payload = {"samples": samples, "windows": windows, "engine_labels": labels,
               "note": mode + "未提供人工真值。字符数和分歧比例不代表准确率；分歧窗口采用字幕中点归属，时间轴偏移也会产生分歧。Whisper 耗时包含每段模型加载、两遍识别与局部恢复；Qwen 耗时包含识别和对齐，模型加载单列，不宜直接比较引擎速度。"}
    stem = {"qwen_long": "comparison-long", "qwen_vad": "comparison-vad", "qwen_vad_tight": "comparison-vad-tight", "qwen_vad_aligned": "comparison-aligned"}.get(args.qwen_dir, "comparison")
    save_json(root / f"{stem}.json", payload)
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    (root / f"{stem}.html").write_text(HTML.replace("__DATA__", embedded), encoding="utf-8")
    print("report", root / f"{stem}.html", flush=True)


HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ASR 3 实验对照</title>
<style>body{font:16px/1.6 system-ui;margin:30px auto;padding:0 20px;max-width:1100px;color:#24352f;background:#f6f9f7}h1{font-size:26px}section{background:white;border:1px solid #dce7df;border-radius:12px;padding:20px;margin:20px 0}select,button{font:inherit;padding:8px;max-width:100%}audio{width:100%;margin:12px 0}.columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}.columns>div{min-width:0}.subtitle{font-size:22px;min-height:90px;background:#edf5ef;padding:15px;border-radius:8px}small,.muted{color:#617568}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #dde7e1;vertical-align:top;overflow-wrap:anywhere}tr[data-time]{cursor:pointer}tr[data-time]:hover{background:#edf5ef}.scroll{max-height:480px;overflow:auto}a{color:#19734c}@media(max-width:650px){.columns{grid-template-columns:1fr}body{padding:0 10px;margin:12px auto}td{font-size:14px;padding:5px}}</style>
<h1>ASR 2.2 与 Qwen3-ASR 新方案对照</h1><p id="note"></p>
<section><label>测试片段 <select id="sample"></select></label><p id="origin" class="muted"></p><audio id="audio" controls preload="metadata"></audio><p id="clock"></p><div class="columns" id="columns"></div><p id="stats" class="muted"></p></section>
<section id="listening-points" hidden><h2>低音量与停顿回听点</h2><p>由音量与语音检测筛选，只是候选；低音量不等于耳语，检测到的停顿也不等于绝对静音。点击按钮从对应位置前 1 秒试听。</p><div id="listening-items"></div></section>
<section id="alignment-review" hidden><h2>仍需复核的对齐</h2><p>点击回听原识别窗口。以下文字未获得可靠的逐词区间。位于已定位句子内部的文字保留在该条 SRT 中；整段没有定位依据的文字仍留在审核清单。显示时长不代表逐词对齐已完成。</p><div id="review-items"></div><a id="audit-link" target="_blank" rel="noreferrer">查看逐次对齐记录</a> · <a id="transcript-link" target="_blank" rel="noreferrer">查看完整原始识别文字</a></section>
<p id="warning" class="muted"></p><p id="vadstats" class="muted"></p><section><h2>当前片段文字对照</h2><p>点击一行，从该处前 1 秒开始播放。分歧可能来自文字，也可能来自时间轴。</p><div class="scroll"><table><thead id="rowhead"></thead><tbody id="rows"></tbody></table></div></section>
<section><h2>优先回听：分歧最大的 15 处</h2><div class="scroll"><table><thead id="tophead"></thead><tbody id="top"></tbody></table></div></section>
<script>const data=__DATA__;const $=s=>document.getElementById(s);const audio=$('audio');const engines=Object.keys(data.engine_labels);let selected;
function url(path){if(location.protocol==='file:'){const sample=data.samples.find(s=>path.startsWith(s.audio.slice(0,-9)));if(sample)return './'+sample.id+'/'+path.split('/'+sample.id+'/')[1];}return '/api/file?path='+encodeURIComponent(path)}
function clock(t){return Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0')}
function row(w,target){const tr=document.createElement('tr');tr.dataset.time=w.start;[target?(w.sample_id+' '+clock(w.start)):clock(w.start),...engines.map(e=>w[e])].forEach(text=>{const td=document.createElement('td');td.textContent=text;tr.append(td)});tr.onclick=()=>play(w.sample_id,w.start);return tr}
function change(id){selected=data.samples.find(s=>s.id===id);$('sample').value=id;audio.src=url(selected.audio);$('origin').textContent=selected.label+' · 原视频 '+clock(selected.start)+'–'+clock(selected.start+selected.duration);for(const e of engines)$(e+'srt').href=url(selected.engines[e].srt);$('stats').textContent=engines.map(e=>data.engine_labels[e]+': '+selected.engines[e].cues.length+' 条 / '+selected.engines[e].characters+' 字符').join('；')+'（数量不表示准确率）';$('rows').replaceChildren(...data.windows.filter(w=>w.sample_id===id).sort((a,b)=>a.start-b.start).map(w=>row(w,false)));update();renderAlignmentReview()}
function play(id,t){if(selected.id!==id){change(id);audio.addEventListener('loadedmetadata',()=>{audio.currentTime=Math.max(0,t-1);audio.play().catch(()=>{})},{once:true})}else{audio.currentTime=Math.max(0,t-1);audio.play().catch(()=>{})}}
function renderAlignmentReview(){const points=selected.review_points||[];$('listening-points').hidden=!points.length;$('listening-items').replaceChildren(...points.map(item=>{const p=document.createElement('p');const button=document.createElement('button');button.type='button';button.textContent=item.label+' · 原视频 '+clock(selected.start+item.start)+'–'+clock(selected.start+item.end);button.onclick=()=>play(selected.id,item.start);p.append(button);return p}));const benchmark=selected.engines.qwen.benchmark;const review=selected.alignment_review;$('alignment-review').hidden=!benchmark.alignment_refined;if(!benchmark.alignment_refined)return;const nodes=[];const summary=document.createElement('p');summary.textContent='零时长词 '+benchmark.alignment_zero_before+' → '+benchmark.alignment_zero_duration_words+'；接受 '+benchmark.accepted_retries+' 次原音重对齐。原始识别文字未改。SRT 句内另保留 '+(benchmark.subtitle_retained_unresolved_words||0)+' 个未逐词定位项，仍有 '+(benchmark.subtitle_unexported_zero_words||0)+' 项无法自动写入 SRT，请回听。';nodes.push(summary);for(const item of review||[]){const p=document.createElement('p');const button=document.createElement('button');button.type='button';button.textContent='回听 '+clock(item.start)+'–'+clock(item.end);button.onclick=()=>play(selected.id,item.start);const span=document.createElement('span');span.textContent=' '+item.text;p.append(button,span);nodes.push(p)}if(!review?.length){const p=document.createElement('p');p.textContent='本片段没有剩余零时长词；边界精度仍需回听确认。';nodes.push(p)}$('review-items').replaceChildren(...nodes);$('audit-link').href=url(selected.alignment_audit);$('transcript-link').href=url(selected.alignment_transcript)}
function update(){for(const engine of engines)$(engine).textContent=selected.engines[engine].cues.filter(c=>c.start<=audio.currentTime&&audio.currentTime<c.end).map(c=>c.text).join(' / ')||'（此时无字幕）';$('clock').textContent='片段 '+clock(audio.currentTime)+' / 原视频 '+clock(selected.start+audio.currentTime);$('warning').textContent=selected.silence_control?'静音负样本应无任何字幕，请特别检查幻觉输出。':'Qwen 有 '+selected.engines.qwen.benchmark.alignment_zero_duration_words+' 个词的原始对齐时长为零，请重点回听时间边界。SRT 使用了和现有 ASR 相同的显示时长整理规则。';const benchmark=selected.engines.qwen.benchmark;const inferenceSeconds=benchmark.inference_audio_seconds??benchmark.input_speech_seconds??selected.duration;$('vadstats').textContent=selected.vad?'检测到语音（含边界余量）'+selected.vad.speech_seconds.toFixed(2)+' / '+selected.duration+' 秒；实际送入识别 '+inferenceSeconds.toFixed(2)+' 秒；旧结果中有 '+selected.vad.excluded_previous_words.length+' 个词落在检测未覆盖位置，需回听，不能据此判定误删。':''}
$('note').textContent=data.note;for(const e of engines){const div=document.createElement('div');const b=document.createElement('b');b.textContent=data.engine_labels[e];const sub=document.createElement('div');sub.id=e;sub.className='subtitle';const link=document.createElement('a');link.id=e+'srt';link.textContent='下载 SRT';link.download=e+'.srt';div.append(b,sub,link);$('columns').append(div)}for(const [id,label] of [['rowhead','时间'],['tophead','片段 / 时间']]){const tr=document.createElement('tr');for(const text of [label,...Object.values(data.engine_labels)]){const th=document.createElement('th');th.textContent=text;tr.append(th)}$(id).append(tr)}for(const s of data.samples){const o=document.createElement('option');o.value=s.id;o.textContent=s.label;$('sample').append(o)}$('sample').onchange=()=>change($('sample').value);audio.ontimeupdate=update;$('top').replaceChildren(...data.windows.filter(w=>w.disagreement>0).slice(0,15).map(w=>row(w,true)));change(data.samples[0].id);
</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "vad", "whisper", "qwen", "report"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--qwen-chunk-seconds", type=float, default=30)
    parser.add_argument("--qwen-dir", choices=["qwen", "qwen_long", "qwen_vad", "qwen_vad_tight", "qwen_vad_aligned"], default="qwen")
    parser.add_argument("--vad-window-mode", choices=["gate", "speech"], default="gate")
    parser.add_argument("--asr-model", type=Path, default=ROOT / "models/asr3/Qwen3-ASR-1.7B")
    parser.add_argument("--aligner-model", type=Path, default=ROOT / "models/asr3/Qwen3-ForcedAligner-0.6B")
    args = parser.parse_args()
    if args.command == "qwen" and args.qwen_dir == "qwen_vad_aligned":
        parser.error("Use scripts/refine_asr3_alignment.py to refine the saved transcript")
    if not 0 < args.qwen_chunk_seconds <= 300:
        raise ValueError("Qwen chunks must be in (0, 300] seconds")
    manifest = load_json(args.manifest)
    root = args.manifest.resolve().parent
    ids = [sample["id"] for sample in manifest["samples"]]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", x) for x in ids):
        raise ValueError("Sample IDs must be unique directory-safe identifiers")
    for sample in manifest["samples"]:
        if not math.isfinite(sample["start"]) or not math.isfinite(sample["duration"]) or sample["start"] < 0 or sample["duration"] <= 0:
            raise ValueError("Invalid sample interval")
    globals()[args.command](manifest, root, args)


if __name__ == "__main__":
    main()
