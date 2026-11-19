# ReiboSub

[中文说明](README.zh-CN.md)

ReiboSub is a YouTube/video subtitle production assistant. It can download YouTube videos, subtitles, and thumbnails; extract embedded hard subtitles with OCR; transcribe speech with ASR; generate and review glossary drafts; translate subtitles with an OpenAI-compatible LLM; edit and convert subtitle files; and copy playable sidecar subtitles next to the video.

The project is designed for a human-in-the-loop workflow: the Agent can run multiple video flows at the same time, pause when it needs your decision, and continue after you review glossary terms.

[Install and start](#quick-start) · [Model settings](#llm-configuration) · [GPU and experiments](#gpu-and-model-cache) · [Troubleshooting](#troubleshooting)

## What It Can Do

- **Agent cockpit**: paste a YouTube URL or video ID, let the Agent probe subtitles, choose a route, and wait for confirmation when needed.
- **Project-based downloads**: each YouTube video is stored in its own folder with video, source subtitles, translated subtitles, thumbnail, and metadata.
- **YouTube subtitles**: detect manual and auto subtitles, download selected tracks, and prefer source-language/manual tracks for translation.
- **OCR subtitles**: use the stabilized OCR 3.0 workflow for new Agent tasks while retaining isolated OCR 1.0 and 2.0 compatibility routes.
- **ASR subtitles**: transcribe speech with `faster-whisper`, then optionally correct ASR text with an LLM.
- **Video upload flow**: upload a local video from the browser and start an ASR-to-Chinese subtitle job directly.
- **Hybrid workflows**: use a reliable uploaded subtitle timeline, such as English, while reconstructing original-language text from OCR when the embedded source subtitle is more accurate.
- **Glossary review**: review names, nicknames and titles with romanization and context translations. Play evidence from the associated video/audio inside each term card, switch occurrences, slow down/repeat playback, and inspect adjacent source subtitles. Clips include 3 seconds on each side, expandable to 10; playback never confirms or edits a translation.
- **Subtitle editing**: edit text and timing, keep 50 undo steps, preview one cue with a live sidecar overlay, and add/merge/delete/clean cues.
- **Subtitle conversion**: convert to common formats including SRT, VTT, ASS/SSA, LRC, TXT, JSON, and Bilibili BCC.
- **Video overlay tool**: place watermark/logo masks on a video and export a new video without overwriting the original.
- **Model provider settings**: manage providers and search for one shared model; optionally use a separate vision model and keep per-module overrides under advanced settings.

For Agent routing design notes, see [docs/youtube_agent_workflows.md](docs/youtube_agent_workflows.md). That document includes background and future ideas, so not every item is necessarily implemented.

### Independent goal-driven Agent experiment

Choose the experimental autonomous mode in the Agent cockpit and provide a YouTube link. New sessions use an evidence-linked controller: the model chooses each next tool, revises a short plan after observations or failures, and selects delivery when artifact checks allow it. There is no mandatory run-through of every tool. The legacy workflow and saved older experimental sessions retain their existing protocols.

Tools include caption discovery and reuse, subtitle-context queries, frame sampling at model-selected times, vision/OCR trials, ASR, bounded 4–30 second audio checks, source comparison, and local translation review. Vision requires a configured image-capable model; local recognition requires its optional dependencies. The model cannot run arbitrary commands, select arbitrary files, change providers, bypass human glossary review for translation, or overwrite existing translated results. Reusing existing Chinese captions does not require glossary generation or retranslation.

Normal new tasks must save both the video and Chinese subtitles. The Agent may inspect captions and decide its approach before scheduling the download, and reuses an existing project video when available. Missing video prevents completion even when Chinese captions are ready. The UI shows saved-video status and a download link. Explicit verification-only, local-review and source-reuse continuations retain their original narrower scope.

The UI shows concise evidence summaries, the current action, its expected observable result, and a revisable plan—not private reasoning. Recognition candidates, structural checks and sampled semantic checks are not ground truth or a full human audit. Current limits include one-hour media for whole-video download/re-recognition, 24 decisions per invocation, and per-tool budgets. Exhausted or failed runs retain their artifacts and report the actual internal failure instead of asking users to approve it as a subtitle issue.

Verification identifies specific empty cues and count/timing mismatches. A narrowly recognized Korean rolling-caption ending may be omitted only from delivery copies when its neighboring source text and overlapping interval cover it, and both the local proposal and independent checker approve keeping its translation empty. Original files and an explicit original-to-delivery ID mapping are preserved. Other empty translations remain errors; placeholder text is not used to force acceptance.

> [!IMPORTANT]
> This is a trusted-user local tool. The Web UI has no accounts or login layer. It listens on `127.0.0.1` by default; do not expose it directly to the public Internet. Use SSH forwarding for a remote server and read [SECURITY.md](SECURITY.md).

## Quick Start

### What cloning does and does not provide

This is a source project, not a double-click installer. Git does not include `frontend/dist`, recognition weights, API keys, user media or machine-local settings. The UI can start without credentials; translation and Agent decisions need your own configured model service. Recognition weights are downloaded on first use.

Start with **Linux x86_64 or WSL2 and Python 3.11** for the UI, translation and CPU OCR. Package metadata allows Python 3.10+, but third-party engine wheels also depend on platform. Do not copy a maintainer's CUDA environment blindly.

| Capability | Additional requirements |
| --- | --- |
| Downloads, conversion and subtitle editing | FFmpeg/ffprobe; YouTube also needs Node.js 22+ and network access |
| Translation and glossary | Your own OpenAI-compatible model service and quota |
| OCR 1.0 / 2.0 / 3.0 | CPU or GPU PaddlePaddle engine and recognition weights; LLM cleanup requires a model service |
| Web ASR 2.2 | faster-whisper, Whisper weights and NVIDIA CUDA; the current UI submits CUDA/float16, while basic CPU transcription is available through the CLI below |
| Agent visual inspection | An image-capable model, which may be the shared model |

The standard public setup does not require MySQL, Redis or a maintainer's `.env`. Qwen/multi-model ASR experiments have separate requirements below.

### 1. Install the recommended CPU starter environment

Install Git and Conda/Miniforge first, then run:

```bash
git clone https://github.com/YuqiPlus/ReiboSub.git
cd ReiboSub
conda env create -f environment.yml
conda activate reibosub
```

This installs Python 3.11, FFmpeg/ffprobe, Node.js 22+, CPU OCR and faster-whisper. Installation and initial model loading require network access; long videos may be slow on CPU. **For GPU OCR, skip this CPU environment and follow [GPU and Model Cache](#gpu-and-model-cache).**

If you already have a suitable Python environment, use this alternative instead. You must separately install FFmpeg/ffprobe and Node.js 22+ in `PATH`:

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
```

For downloads or existing subtitles only, `python -m pip install -e .` omits the PaddlePaddle inference engine and faster-whisper. Add `.[ocr-cpu]` or `.[asr]` when needed. The `.[dev]` extra is optional and only needed for testing.

The `yt-dlp[default]` dependency includes YouTube JS challenge components. ReiboSub enables Node from `PATH`; an old Node runtime or missing challenge components can break downloads even when a browser can play the video. See the [official yt-dlp EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

### 2. Verify the active environment

```bash
python -c "import sys, shutil; print(sys.executable); print('ffmpeg:', shutil.which('ffmpeg')); print('ffprobe:', shutil.which('ffprobe')); print('node:', shutil.which('node'))"
ffmpeg -version
ffprobe -version
node --version
python -m pip check
```

None of the three tool paths should be `None`; Node should be version 22 or newer. Start the server from the same activated terminal. Calling a Python executable by absolute path does not automatically add its environment's `bin` directory to `PATH`. `reibosub doctor` checks some Python imports/cache paths, not every external tool, CUDA library, model download or API connection.

### 3. Build the frontend

```bash
cd frontend
npm ci
npm run build
cd ..
```

Do not skip this step. The server reads `frontend/dist`, not the source files directly; rebuild after pulling frontend changes as well.

### 4. Optional machine-local settings

Optionally copy the single machine-local startup template. The defaults already start safely, so create this file only when you want to change the media directory, YouTube proxy, listen address, or port.

```bash
cp configs/reibosub.example.yaml configs/reibosub.yaml
```

Example:

```yaml
media_dir: YoutubeDownloads
youtube_proxy: ""
host: 127.0.0.1
port: 7860
```

If YouTube needs a proxy on your network, set `youtube_proxy`, for example:

```yaml
youtube_proxy: http://127.0.0.1:7890
```

Local OCR/ASR/LLM child processes do not use generic `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` by default; this keeps a YouTube proxy from slowing down local processing.

Existing installations can keep their old `configs/local_runtime.yaml`, `.env`, and `configs/llm.yaml` files. They remain compatibility inputs and do not need to be migrated or deleted.

### 5. Start the UI

```bash
python run_agent_ui.py
```

Open:

```text
http://127.0.0.1:7860
```

On a remote server, keep the loopback bind and create a tunnel from your own machine:

```bash
ssh -L 7860:127.0.0.1:7860 user@server
```

Then still open `http://127.0.0.1:7860` locally. Use `python run_agent_ui.py --host 0.0.0.0` only on a trusted LAN.

### 6. Configure your model service in the UI

After opening the UI for the first time:

1. Open **Settings → Provider management → Add provider**. A clean checkout has no working API key.
2. Enter a stable provider ID, label, OpenAI-compatible API base URL, and API key.
3. Click **Create and fetch models**; if the service has no `/models` endpoint, enter static model IDs instead.
4. In common settings, choose the default provider and shared model, then **Save settings**. Translation, glossary, OCR cleanup and Agent decisions can use the same model.
5. Vision needs image input support: inherit the shared model if supported, or select a separate provider/model. Search the model list, or enter an ID manually when no list is available.

Model discovery only lists names: it does not prove account quota or image support. New users do not need per-module overrides. Existing installations can use the unify-text action and save to reset text bindings while retaining their vision configuration.

The UI stores provider metadata in the Git-ignored `configs/provider_profiles.yaml` and connection URLs/API keys in the equally ignored `configs/provider_secrets.yaml`. Keys are write-only and are never returned by the backend. New installations do not need to copy or maintain files under `configs/providers/`.

### 7. Test a short clip first

1. Use **Downloads & links** for a video you are authorized to process, or import local media in **Assets**. Download-only use does not require an Agent or LLM.
2. Test a short captioned clip with OCR Lab 3.0. With NVIDIA CUDA configured, test speech-only media using ASR Lab 2.2; CPU users should use the basic CLI below instead of assuming the Web ASR path is CPU-ready. Initial recognition downloads models.
3. Once recognition and your API work, provide a full link in the subtitle assistant. Formal translation pauses for human glossary review: fill or confirm names and terms, then save to continue.
4. Download the SRT or open it from Assets for editing. Task history provides stage states, artifacts and reruns. Deleting a task removes its task-directory artifacts but preserves downloaded video; download any subtitles you want to keep first.

Automatic checks are not a word-for-word human audit. Test short inputs before long videos to avoid wasting processing time and API quota on setup errors.

## Frontend Development

The Python service reads `frontend/dist`. Use `npm ci && npm run build` for a production-style local build. For development, run the backend and Vite separately:

```bash
# terminal 1
python run_agent_ui.py

# terminal 2
cd frontend
npm ci
npm run dev
```

Vite defaults to `http://127.0.0.1:5173` and proxies `/api` to port `7860`. Still run `npm run build` before committing.

A successful build does not imply vulnerability-free dependencies; run `npm audit` from `frontend` to inspect the lockfile. Do not expose the Vite development server publicly or apply untested major upgrades with `npm audit fix --force`.

## LLM Configuration

The project uses OpenAI-compatible chat-completions APIs. The Web UI **Settings** page can persist the default language for new tasks, the default provider profile, and the model used by every LLM module.

Create and manage providers from Settings, fetch their model lists, and select one shared model for everyday use. Vision requires image input support. Existing per-module overrides remain under advanced settings and are never silently cleared. The unify-text action resets the eight text bindings to inheritance while preserving vision; changes apply after saving. Sharing a model does not merge processing steps: each still runs and validates separately. Endpoints without `/models` support can use manual IDs or a static list.

API keys and endpoints are managed directly from Settings; `.env` is not required. Provider names, model lists, and default models are stored in `configs/provider_profiles.yaml`; connection URLs and keys are stored in `configs/provider_secrets.yaml`. Both files are Git-ignored, and the secrets file is forced to mode `0600`. Keys are write-only: the backend returns only configured/source status and never echoes the current key or a suffix.

Remote pages may write or replace a key, but changing the provider to a different origin requires a server-local connection or SSH port forwarding; model discovery URLs must share the API origin. Use HTTPS or an SSH tunnel when entering credentials remotely instead of sending them over an untrusted plaintext HTTP network.

Settings also supports creating, editing, and deleting local OpenAI-compatible providers. Users do not need to edit these local files. Provider IDs stay immutable because saved task bindings reference them. Deleting a provider migrates affected bindings to the selected replacement and resets their model to that provider's default.

Older `.env`, `configs/llm.yaml`, and `configs/providers/*.yml` setups remain readable for compatibility, but they are no longer the setup path for a new installation.

## GPU and Model Cache

Recognition weights are not included in Git. The project configures local cache paths such as `models/`; some upstream components may also use their own caches. Initial recognition needs network access to model sources and sufficient disk space. LLM APIs do not automatically download a local LLM.

Choose this instead of the CPU starter environment. After cloning, create an environment without CPU Paddle from the repository root:

```bash
conda create -n reibosub -c conda-forge python=3.11 pip ffmpeg "nodejs>=22" -y
conda activate reibosub
```

The following is a **Linux NVIDIA / CUDA 12.6 example**, not a universal driver/GPU recipe. Check Paddle's official compatibility guidance before choosing an index. The [PaddleOCR installation guide](https://www.paddleocr.ai/main/en/quick_start.html) distinguishes the OCR package from its inference engine.

```bash
python -m pip uninstall -y paddlepaddle paddlepaddle-gpu
python -m pip install -r requirements-gpu-cu126.txt
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
# Optional for development and tests:
python -m pip install -e ".[dev]"
```

The GPU requirements file installs the common project dependencies, `faster-whisper`, and its usual CUDA Python wheels, but not CPU Paddle. Install Paddle GPU itself from the CUDA-specific index in the next command.

Then return to steps 2–6 above to check tools, build the frontend and configure your service. Do not install the CPU `requirements.txt` or `environment.yml` afterward: that can reintroduce CPU Paddle.

Check CUDA visibility:

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

When the OCR device is `auto`, ReiboSub selects an available device. Individual OCR routes can still choose CPU or a GPU explicitly. Advanced device overrides from an existing legacy local runtime file remain compatible.

For ASR with `faster-whisper`, the project tries to prepend CUDA library paths from installed `nvidia-*` Python packages. If CUDA libraries are still missing, verify your environment's `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` packages.

The current Web ASR entry submits CUDA/float16; CPU Paddle does not make that ASR path CPU-ready. Without NVIDIA CUDA, try basic transcription through the CLI:

```bash
python -m video_translate.tools.transcribe_audio "input.mp4" \
  --out "outputs/demo/source.srt" --language ko \
  --model-size small --device cpu --compute-type int8
```

This is basic faster-whisper transcription, not the complete ASR Lab 2.2 recovery/review/translation pipeline. Also check the [official faster-whisper requirements](https://github.com/SYSTRAN/faster-whisper#requirements) for CUDA/cuDNN compatibility.

### ASR experiments require a separate setup

ASR 2.2 is the normal route. Qwen multi-model review and autonomous ASR Lab experiments additionally require a separate Qwen Python environment, weights at `models/asr3/Qwen3-ASR-1.7B` and `models/asr3/Qwen3-ForcedAligner-0.6B`, and two NVIDIA GPUs. The current experimental launcher only accepts Korean. Set `REIBOSUB_QWEN_PYTHON` to that environment's Python when needed. Standard requirements do not create it or download those weights; do not choose the experimental versions until those prerequisites are ready.

### Updating an installation

Wait for jobs to finish and stop the server before updating from the existing environment:

```bash
conda activate reibosub
git pull --ff-only
python -m pip install -e .
cd frontend
npm ci
npm run build
cd ..
python run_agent_ui.py
```

`pip install -e .` updates base dependencies without requesting CPU Paddle over an existing GPU installation. Git normally leaves ignored settings/media alone, but back them up first. There is no automatic updater or built-in service manager; configure your own long-running service and ensure it starts in the correct environment.

### Optional speaker diarization

ASR Lab can label speech segments as `Speaker 1`, `Speaker 2`, and so on. This is speaker diarization: it separates voices but does not identify a person's real name.

Install the optional runtime in the same Python environment that runs ReiboSub:

```bash
python -m pip install -e ".[diarization]"
```

Then accept the access conditions for
[`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1),
create a Hugging Face access token, and store it in the Git-ignored project `.env`:

```dotenv
HF_TOKEN=hf_your_token
```

Restart the service after changing `.env`. For an offline/local model, set
`PYANNOTE_DIARIZATION_MODEL=/absolute/path/to/model` instead. ASR Lab uses
Community-1's exclusive diarization timeline when available and aligns each
faster-whisper subtitle cue with the speaker who overlaps it the most. Media is
decoded through the project's FFmpeg runtime and passed to pyannote as a 16 kHz
mono in-memory waveform, so this route does not depend on TorchCodec's FFmpeg
dynamic-library integration.

### ASR Lab versions

ASR Lab keeps the original pipeline as **ASR 1.0** and adds an independent
**ASR 2.x** path. The current ASR 2.x pipeline version is **2.2**. Existing API
callers that omit `asr_version` continue to use 1.0 unchanged.

ASR 2.2 retains faster-whisper word timestamps and confidence metadata. With
the default high-recall option enabled, it runs a normal transcription followed
by an independent low-VAD pass. Only second-pass phrases that fall fully inside
primary transcript gaps and pass both word- and region-confidence checks are
merged into the final word timeline. Lower-confidence candidates remain in the
quality report as suspected missing-speech regions. ASR 2.2 then decodes only
those short regions, applies bounded local loudness normalization, and runs an
independent no-VAD focused pass. High-confidence or cross-pass-consistent phrases
are merged automatically; the remaining candidates are exposed in ASR Lab for
bounded audio playback, text editing, accept, or ignore decisions.

The final cue builder splits internal sentence punctuation, meaningful
faster-whisper segment boundaries, short speech pauses, long cues, and speaker
changes. It also removes duplicate flashes, merges adjacent micro-cues, caps
normal cues at 4.5 seconds / 30 characters, and does not introduce overlaps.
ASR 2.2 is the recommended path for both single- and multi-speaker audio;
speaker diarization remains a separate optional feature. Each high-recall run
writes:

- `source.raw.srt`: the untouched faster-whisper segment output;
- `source.recovery.raw.srt`: the untouched low-VAD recovery-pass output;
- `source.asr2.srt`: the rebuilt ASR 2.2 subtitle;
- `words.json` and `segments.json`: detailed timing and confidence metadata;
- `words.recovery.json` and `segments.recovery.json`: complete second-pass
  diagnostics;
- `words.focused.json` and `segments.focused.json`: focused local re-listening
  evidence for unresolved gaps;
- `quality.json`: low-confidence words, suspicious segments, recovered phrases,
  and unresolved suspected missing-speech regions;
- `cues.asr2.json`: the final cue-to-word mapping.

Review decisions are stored in `asr_review.json`. Accepted candidates rebuild a
separate `source.asr2.reviewed.srt` from the word timeline and synchronize the
material-folder source subtitle, leaving the original ASR output available for
comparison and rollback.

Optional hotwords can bias names and domain terms. When speaker diarization is
enabled, a known speaker count can be supplied and words are aligned against
Community-1's exclusive speaker timeline before cue construction.

High-recall recovery is enabled by default in ASR Lab and can be disabled for a
faster single-pass comparison. It runs sequentially on one GPU and does not
require a second GPU.

Dual-GPU execution is optional and disabled by default. When enabled, ASR 2.0
runs faster-whisper on GPU 0 and speaker diarization on GPU 1 only if at least
two NVIDIA GPUs are detected. Single-GPU and CPU-only systems automatically
fall back to sequential execution instead of failing.

## Agent Workflows

The Agent page defaults to **自主 Agent · 实验** (autonomous tool selection).
Paste a YouTube link; no test interval is required. A bounded controller chooses
among existing subtitle tracks, frame sampling, visual analysis, OCR 3.0, ASR 2.2,
local Korean audio review, translation, and verification. It records each tool
choice and asks for a short clue or explicit candidate confirmation when evidence
is insufficient. Tool limits and prerequisites are enforced outside the model.

Source selection is autonomous, but **Glossary review is a required human step**
before formal translation. The Agent prepares context translations before opening
the Glossary page; names and terminology are not automatically
confirmed: fill or confirm them and save to continue. Translation and local review
use the frozen, user-approved glossary; the autonomous route cannot skip this gate.

Configure **视频画面分析** in Settings with an image-capable model to enable visual
inspection. Logo exclusions must pass a sampled OCR comparison; original frames
and OCR Lab results are retained. This first experimental mode limits video
download and fresh recognition to one hour; longer videos may still use existing
subtitle tracks. Semantic checks are sampled, not a guarantee of word-for-word
accuracy. Downloadable source/Chinese SRT files remain drafts for user review.

Select **经典工作流** to keep using the original guided route below. Its processing
steps and the ASR 2.2 baseline are unchanged.

Typical guided UI flow:

1. Paste a YouTube URL or video ID in **Agent**.
2. Tell the Agent whether embedded subtitles are present if you know.
3. Let it probe metadata and subtitle tracks, then show the route choice without waiting for a full video download.
4. Choose the recommended route or manually switch to OCR/ASR/downloaded subtitles. After the route is chosen, the Agent downloads the project video or reuses an existing one before continuing.
5. If OCR is needed, preview a frame and tune the crop region immediately.
6. Generate a glossary draft and review terms in the glossary UI.
7. Save the glossary; the Agent continues translation for that specific flow.
8. Review the generated subtitle or convert it to another format.

Multiple Agent flows can run in parallel. Running sessions are polled independently; when a flow waits for confirmation or glossary review, click its card in the Agent task list and handle it without stopping other flows.

Common routes:

- **Existing Chinese subtitle**: download and optionally convert/rename.
- **Source-language manual subtitle**: lock the uploaded timeline and translate with glossary guidance.
- **Auto subtitle**: optionally correct source text, then glossary and translate.
- **Embedded hard subtitle**: OCR source text, generate glossary, translate.
- **Speech only**: ASR source text, optionally correct, generate glossary, translate.
- **Hybrid anchor OCR**: use an uploaded subtitle's timeline as anchor while OCR reconstructs original-language source text.

### Choosing an OCR version

| Version | Pipeline | Recommended use |
| --- | --- | --- |
| OCR 1.0 (legacy) | automatic main-subtitle OCR → legacy cleanup → legacy translation | Reproduce old results or keep old tasks compatible |
| OCR 2.0 (preserved) | region OCR → box/track-specific cleanup → locked-timeline translation | Reproduce existing 2.0 results or use as a comparison |
| OCR 3.0 (stable, default) | region OCR → geometry hints → text repair → scene/dialogue layering → locked timeline | New Agent tasks and videos combining slanted text, scene captions, and dialogue |

The Agent frame preview lets you drag/resize the subtitle region and optionally mark a logo/fixed-text exclusion box. OCR Lab keeps 2.0 and 3.0 in separate debug directories. When `tracks.json` and `ocr_boxes.json` already exist, you can rerun only the matching refinement stages without decoding the video or rerunning PaddleOCR. Existing tasks continue with their recorded OCR version instead of being silently migrated.

This default applies to full-frame OCR and ASR-with-OCR-reference routes. The English-timeline + source-language OCR hybrid keeps its independent timeline-fusion implementation and is not silently switched to OCR 3.0.

### Subtitle refinement

1. Choose a subtitle in Assets and open **Subtitle editor**. The UI tries to locate the matching project video; you can also enter a video path manually.
2. Edit text and start/end timestamps directly, or use `±0.1s`, the current player time, and previous/next cue snapping.
3. Click **Play cue** to play exactly that interval, stop at its end, and render the edited sidecar text over the video.
4. Use the always-visible undo action after a mistake. Text, timing, insert/delete/merge, and batch cleanup changes share up to 50 undo steps.
5. Overwrite the source or save as `edited.srt`. Undo remains available after saving; restoring an older state marks it unsaved until you save again.

## Manual Commands

The Web UI does not require an extra pipeline configuration. For the advanced YAML-driven CLI only, copy the dedicated example and edit it:

```bash
cp examples/cli/run.yaml configs/run.yaml
```

The public command is `reibosub`. The legacy `video-translate` command, the
internal `video_translate` Python module, and the `VIDEO_TRANSLATE_*`
configuration keys remain available for compatibility.

If this environment installed the project before the rename, refresh its
editable package metadata once:

```bash
python -m pip uninstall -y video-translate
python -m pip install --no-deps -e .
```

Probe dependencies and cache paths:

```bash
reibosub doctor
```

Run from `configs/run.yaml`:

```bash
python run_from_config.py
# or
reibosub run-config configs/run.yaml
```

Extract hard subtitles from a local video:

```bash
reibosub extract "input.mp4" --lang korean --out "outputs/demo"
```

Extract with full-screen assist:

```bash
reibosub extract "input.mp4" --lang korean --out "outputs/demo" --scan-full-frame
```

Translate an existing SRT with the configured OpenAI-compatible provider:

```bash
reibosub translate-volcengine "outputs/demo/source.srt" \
  --glossary "configs/glossaries/examples/glossary.example.yaml" \
  --out "outputs/demo/zh.srt"
```

YouTube and subtitle helper modules:

```bash
python -m video_translate.youtube.download_subtitles "https://www.youtube.com/watch?v=..." --sub-langs ko,en
python -m video_translate.youtube.download_video "https://www.youtube.com/watch?v=..."
python -m video_translate.tools.generate_glossary "YoutubeDownloads/example.ko.srt" --out "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.translate_subtitles "YoutubeDownloads/example.ko.srt" --glossary "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.convert_subtitle "YoutubeDownloads/example.zh.srt" --format bcc
```

Script wrappers under `scripts/` provide equivalent manual entry points.

## Output Layout

Downloaded YouTube projects are stored under `YoutubeDownloads/<video-title>/` by default. Typical files:

```text
<video-title>.mp4
<video-title>.jpg
<video-title>.source.srt
<video-title>.zh.srt
project.yaml
```

Agent task state and intermediate artifacts live under:

```text
outputs/agent_tasks/<task-id>/
outputs/agent_jobs/<job-id>/
```

Common pipeline outputs:

- `source.srt`: source-language subtitle from OCR/ASR/downloaded track.
- `zh.srt`: translated Chinese subtitle.
- `tracks.json`: OCR text tracks with boxes and metadata.
- `ignored_tracks.json`: tracks filtered as persistent overlays/noise.
- `tracks_debug.csv`: spreadsheet-friendly OCR/debug table.
- `*.bcc`: Bilibili subtitle JSON output.

If sidecar copying is enabled, generated subtitles are copied next to the video so common players can auto-load them.

## Files You Should Not Commit

The repository ignores local data by default:

- `configs/provider_secrets.yaml`
- `configs/provider_profiles.yaml`
- `configs/providers/*.yml` and `*.yaml` (legacy compatibility profiles)
- `configs/reibosub.yaml`
- `configs/app_settings.yaml`
- `.env*`
- legacy/advanced local files: `configs/local_runtime.yaml`, `configs/run.yaml`, and `configs/llm.yaml`
- `YoutubeDownloads/`
- `outputs/`
- `models/`
- generated media/subtitle files such as `*.mp4`, `*.srt`, `*.vtt`, `*.ass`, `*.bcc`
- logs, cookies, private keys, certificates, and service-account JSON files

Keep reusable glossary examples under `configs/glossaries/examples/`. Per-task glossary drafts belong in `outputs/agent_tasks/<task-id>/` or another ignored working directory.

Before publishing a branch, run at least:

```bash
git status --short --ignored
git diff --check
git diff --cached --name-only
```

This repository does not ship user videos, subtitles, model caches, or real credentials. Process and share only material you have the right to use, and follow the source platform and model-provider terms. See [SECURITY.md](SECURITY.md) for deployment and leak-response guidance.

## Troubleshooting

- **The page says the frontend is not built**: run `cd frontend && npm ci && npm run build`, then refresh.
- **FFmpeg is installed but the service cannot find it**: activate the project environment, verify the actual Python/ffmpeg/ffprobe paths and launch from that terminal. Installing Python packages does not install a system FFmpeg executable.
- **YouTube reports no JS runtime or challenge solver**: ensure Node.js 22+ is in the service's `PATH`, run `python -m pip install -U "yt-dlp[default]"`, and restart. Proxies, login requirements and geographic restrictions may still affect access separately.
- **`libGL.so.1` / `libgomp.so.1` is missing**: this is a system-library issue, not an API-key or model issue. On Ubuntu/Debian an administrator can install `libgl1 libglib2.0-0 libgomp1`; use corresponding packages on other distributions.
- **You cannot find the Conda environment**: run `conda info --envs` and `conda config --show envs_dirs`, or choose a path explicitly with `conda env create -p /path/to/envs/reibosub -f environment.yml`.
- **A CPU Paddle build cannot use the GPU**: select `cpu`/`auto`, or uninstall `paddlepaddle` and install a `paddlepaddle-gpu` build matching your CUDA version. Do not keep both packages.
- **Provider model discovery fails**: many compatible APIs do not expose `/models`; maintain static model IDs in Settings and continue normally.
- **A model list loads but translation fails**: check API base URL, key permissions, quota and model access. Listing models does not prove inference requests will succeed.
- **ASR fails with CUDA or float16 errors on CPU**: the current UI uses CUDA/float16. Use explicit `--device cpu --compute-type int8` with the basic CLI, or configure NVIDIA CUDA before using Web ASR.
- **YouTube cannot connect**: set `youtube_proxy` in `configs/reibosub.yaml`; it applies only to downloads and does not proxy OCR/ASR.
- **Visible text is missing from OCR**: verify language, the green subtitle crop, the logo exclusion box, and the selected OCR version. A first run may also be downloading models. Compare 2.0 and 3.0 in their own directories.
- **`h264 mmco: unref short failure` appears**: this is normally a decoder warning. If OCR progress keeps moving, the job has not necessarily failed.
- **A running step no longer continues after restart**: active jobs, live logs, and worker processes are in memory. Agent task records and existing artifacts remain, so continue from task history, Assets, or OCR Lab and rerun the relevant stage.

## Testing

Backend tests:

```bash
python -m pytest -q
```

Frontend unit tests:

```bash
cd frontend
node --test src/*.test.mjs
```

Frontend build:

```bash
cd frontend
npm run build
```

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
