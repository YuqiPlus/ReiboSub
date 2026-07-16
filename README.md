# ReiboSub

[中文说明](README.zh-CN.md)

ReiboSub is a YouTube/video subtitle production assistant. It can download YouTube videos, subtitles, and thumbnails; extract embedded hard subtitles with OCR; transcribe speech with ASR; generate and review glossary drafts; translate subtitles with an OpenAI-compatible LLM; edit and convert subtitle files; and copy playable sidecar subtitles next to the video.

The project is designed for a human-in-the-loop workflow: the Agent can run multiple video flows at the same time, pause when it needs your decision, and continue after you review glossary terms.

## What It Can Do

- **Agent cockpit**: paste a YouTube URL or video ID, let the Agent probe subtitles, choose a route, and wait for confirmation when needed.
- **Project-based downloads**: each YouTube video is stored in its own folder with video, source subtitles, translated subtitles, thumbnail, and metadata.
- **YouTube subtitles**: detect manual and auto subtitles, download selected tracks, and prefer source-language/manual tracks for translation.
- **OCR subtitles**: keep the legacy pipeline while providing isolated OCR 2.0 stable and OCR 3.0 geometry/layered experimental workflows.
- **ASR subtitles**: transcribe speech with `faster-whisper`, then optionally correct ASR text with an LLM.
- **Video upload flow**: upload a local video from the browser and start an ASR-to-Chinese subtitle job directly.
- **Hybrid workflows**: use a reliable uploaded subtitle timeline, such as English, while reconstructing original-language text from OCR when the embedded source subtitle is more accurate.
- **Glossary review**: generate draft terms, review names/nicknames/program titles in the UI, use romanization and blind candidates, then continue translation.
- **Subtitle editing**: edit text and timing, keep 50 undo steps, preview one cue with a live sidecar overlay, and add/merge/delete/clean cues.
- **Subtitle conversion**: convert to common formats including SRT, VTT, ASS/SSA, LRC, TXT, JSON, and Bilibili BCC.
- **Video overlay tool**: place watermark/logo masks on a video and export a new video without overwriting the original.
- **Generic LLM config**: one OpenAI-compatible configuration path; the examples use Volcengine Ark/Doubao, but the variable names are provider-neutral.

For Agent routing design notes, see [docs/youtube_agent_workflows.md](docs/youtube_agent_workflows.md). That document includes background and future ideas, so not every item is necessarily implemented.

> [!IMPORTANT]
> This is a trusted-user local tool. The Web UI has no accounts or login layer. It listens on `127.0.0.1` by default; do not expose it directly to the public Internet. Use SSH forwarding for a remote server and read [SECURITY.md](SECURITY.md).

## Quick Start

Install system tools first:

- Python 3.10 or newer, Python 3.11 recommended.
- `ffmpeg` in `PATH` for video/audio processing and subtitle muxing.
- Node.js 20 or newer is required for the first Web UI build from a source checkout because compiled assets are not committed.

Clone and create a Python environment:

```bash
git clone https://github.com/YuqiPlus/ReiboSub.git
cd ReiboSub
conda create -n reibosub python=3.11 -y
conda activate reibosub
python -m pip install -U pip
python -m pip install -e ".[dev,asr]"
```

If you prefer one conda command, use the provided environment file:

```bash
conda env create -f environment.yml
conda activate reibosub
```

For a smaller install without ASR/test dependencies:

```bash
python -m pip install -e .
```

Build the frontend once after cloning:

```bash
cd frontend
npm ci
npm run build
cd ..
```

Optionally copy the machine-local runtime template. The defaults already start safely on the local machine; create this file only to change ports, download/cache paths, or the OCR device.

```bash
cp configs/local_runtime.example.yaml configs/local_runtime.yaml
```

Example:

```yaml
version: 1
environment:
  YTDLP_PROXY: ""
  VIDEO_TRANSLATE_HOST: 127.0.0.1
  VIDEO_TRANSLATE_PORT: 7860
  VIDEO_TRANSLATE_DOWNLOAD_DIR: YoutubeDownloads
  VIDEO_TRANSLATE_CACHE_DIR: models
  VIDEO_TRANSLATE_OCR_DEVICE: auto
```

If YouTube needs a proxy on your network, set only `YTDLP_PROXY`, for example:

```yaml
environment:
  YTDLP_PROXY: http://127.0.0.1:7890
```

Local OCR/ASR/LLM child processes do not use generic `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` by default; this keeps a YouTube proxy from slowing down local processing.

Start the Agent UI:

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

### First provider setup

After opening the UI for the first time:

1. Open **Settings → Add provider**.
2. Enter a stable provider ID, label, OpenAI-compatible API base URL, API key, and default model.
3. Fetch remote models; if the service has no `/models` endpoint, enter static model IDs instead.
4. Bind providers/models to translation, glossary, OCR refinement, and the other LLM tasks, then save.

The connection URL and key are written to Git-ignored `configs/provider_secrets.yaml`. Keys are write-only and are never returned by the backend. You may also copy the [provider profile example](configs/providers/openai-compatible.yml.example) to create public metadata manually, then enter connection fields in Settings.

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

## LLM Configuration

The project uses OpenAI-compatible chat-completions APIs. The Web UI **Settings** page can persist the default language for new tasks, the default provider profile, and the model used by every LLM module.

Provider profiles come from local `configs/providers/*.yml` files. Creating one in Settings is the easiest route, or copy the public non-secret template:

```bash
cp configs/providers/openai-compatible.yml.example configs/providers/example.yml
```

The filename stem (`example`) becomes the provider ID. The template stores only display/model metadata:

```yaml
label: Example OpenAI-compatible provider
provider: openai-compatible
backend: openai-compatible
model_name: example-model
model_names:
  - example-model
```

Enter the base URL and key in Settings instead of the provider file. When the UI requests remote models, the Python server calls `/models` through the selected trusted profile and falls back to its static model list if discovery fails.

API keys and endpoints are managed directly from Settings; `.env` is not required. They are stored in Git-ignored YAML file `configs/provider_secrets.yaml` with mode `0600`, using the precedence “local secret settings > process environment > provider profile.” Keys are write-only: the backend returns only configured/source status and never echoes the current key or a suffix. Legacy `.env` / profile connections can still be imported without exposing their keys.

Remote pages may write or replace a key, but changing the provider to a different origin requires a server-local connection or SSH port forwarding; model discovery URLs must share the API origin. Use HTTPS or an SSH tunnel when entering credentials remotely instead of sending them over an untrusted plaintext HTTP network.

Settings also supports creating, editing, and deleting local OpenAI-compatible providers. Creating writes non-secret metadata to `configs/providers/<id>.yml` and connection data to `configs/provider_secrets.yaml`; it does not contact the new endpoint until model discovery or a task is explicitly requested. Editing can change the display label, default model, and static model list while connection fields remain in the write-only connection editor. Provider IDs are immutable because saved settings reference them. Deleting removes both records and migrates saved default/task bindings to the selected replacement provider, resetting affected task models to that provider's default. These management requests require same-origin JSON, while redirecting an existing credential to a different API origin remains restricted to loopback/SSH access.

The UI writes local overrides to `configs/app_settings.yaml`. These settings take precedence over legacy `configs/llm.yaml` values, which remain available as a compatibility fallback. Model selection order is:

```text
explicit --model or caller override
> configs/app_settings.yaml task model / provider_profile
> task-specific environment variable, e.g. ASR_CORRECTION_MODEL
> configs/llm.yaml task model or model role
> process environment (or legacy `.env`) global LLM_MODEL / ARK_MODEL
> configs/llm.yaml default model
```

The recommended path is the Settings page. Existing installations can still use the legacy configuration path:

1. Process environment or legacy `.env`: set `LLM_API_KEY` and optionally `LLM_BASE_URL` / `LLM_MODEL`.
2. `configs/llm.yaml`: update `defaults.base_url` and `defaults.models.*` if model IDs changed.

Example `configs/llm.yaml` values use Volcengine Ark / Doubao:

```yaml
defaults:
  provider: openai-compatible
  base_url: https://ark.cn-beijing.volces.com/api/coding/v3
  api_key_env: LLM_API_KEY
  models:
    default: doubao-seed-2.0-pro
    pro: doubao-seed-2.0-pro
    lite: doubao-seed-2.0-lite
```

Legacy `ARK_*` environment variables remain compatible for older local installs, but new setups should use `LLM_*`.

## GPU and Model Cache

Model caches default to the project-local `models/` directory. You can override the root in `configs/local_runtime.yaml`:

```yaml
environment:
  VIDEO_TRANSLATE_CACHE_DIR: /srv/reibosub-models
```

For PaddleOCR GPU support, install a PaddlePaddle GPU build that matches your CUDA runtime. Example for CUDA 12.6:

```bash
python -m pip uninstall -y paddlepaddle
python -m pip install -r requirements-gpu-cu126.txt
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
python -m pip install -e ".[dev,asr]" --no-deps
```

The GPU requirements file avoids installing CPU `paddlepaddle`; it only lists the common runtime packages plus CUDA Python wheels used by `faster-whisper`.

Check CUDA visibility:

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

If `ocr.device` is `auto`, `configs/local_runtime.yaml` can choose the default device:

```yaml
environment:
  VIDEO_TRANSLATE_OCR_DEVICE: gpu:0
```

For ASR with `faster-whisper`, the project tries to prepend CUDA library paths from installed `nvidia-*` Python packages. If CUDA libraries are still missing, verify your environment's `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` packages.

## Agent Workflows

Typical UI flow:

1. Paste a YouTube URL or video ID in **Agent**.
2. Tell the Agent whether embedded subtitles are present if you know.
3. Let it probe video metadata, available subtitles, title, and route options.
4. Choose the recommended route or manually switch to OCR/ASR/downloaded subtitles.
5. If OCR is needed, download/preview a frame and tune the crop region.
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
| OCR 2.0 (stable) | region OCR → box/track-specific cleanup → locked-timeline translation | Normal bottom hard subtitles; preferred default |
| OCR 3.0 (initial) | region OCR → geometry hints → text repair → scene/dialogue layering → locked timeline | Experiments with slanted text, scene captions, and dialogue together |

The Agent frame preview lets you drag/resize the subtitle region and optionally mark a logo/fixed-text exclusion box. OCR Lab keeps 2.0 and 3.0 in separate debug directories. When `tracks.json` and `ocr_boxes.json` already exist, you can rerun only the matching refinement stages without decoding the video or rerunning PaddleOCR. OCR 3.0 remains experimental, so keep the 2.0 result for comparison.

### Subtitle refinement

1. Choose a subtitle in Assets and open **Subtitle editor**. The UI tries to locate the matching project video; you can also enter a video path manually.
2. Edit text and start/end timestamps directly, or use `±0.1s`, the current player time, and previous/next cue snapping.
3. Click **Play cue** to play exactly that interval, stop at its end, and render the edited sidecar text over the video.
4. Use the always-visible undo action after a mistake. Text, timing, insert/delete/merge, and batch cleanup changes share up to 50 undo steps.
5. Overwrite the source or save as `edited.srt`. Undo remains available after saving; restoring an older state marks it unsaved until you save again.

## Manual Commands

The Web UI does not require these files. Copy them only for YAML-driven or legacy CLI configuration:

```bash
cp configs/llm.example.yaml configs/llm.yaml
cp configs/run.example.yaml configs/run.yaml
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
- `configs/providers/*.yml` and `*.yaml` (commit only `*.yml.example` templates)
- `configs/local_runtime.yaml`
- `configs/app_settings.yaml`
- `.env*` (keep only the empty `.env.example` template)
- `configs/run.yaml`
- `configs/llm.yaml`
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
- **You cannot find the Conda environment**: run `conda info --envs` and `conda config --show envs_dirs`, or choose a path explicitly with `conda env create -p /path/to/envs/reibosub -f environment.yml`.
- **A CPU Paddle build cannot use the GPU**: select `cpu`/`auto`, or uninstall `paddlepaddle` and install a `paddlepaddle-gpu` build matching your CUDA version. Do not keep both packages.
- **Provider model discovery fails**: many compatible APIs do not expose `/models`; maintain static model IDs in Settings and continue normally.
- **YouTube cannot connect**: configure `YTDLP_PROXY` for downloads only instead of applying a global proxy to OCR/ASR.
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
