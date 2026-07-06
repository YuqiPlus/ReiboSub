# Video Translate

[中文说明](README.zh-CN.md)

Video Translate is a YouTube/video subtitle production assistant. It can download YouTube videos, subtitles, and thumbnails; extract embedded hard subtitles with OCR; transcribe speech with ASR; generate and review glossary drafts; translate subtitles with an OpenAI-compatible LLM; edit and convert subtitle files; and copy playable sidecar subtitles next to the video.

The project is designed for a human-in-the-loop workflow: the Agent can run multiple video flows at the same time, pause when it needs your decision, and continue after you review glossary terms.

## What It Can Do

- **Agent cockpit**: paste a YouTube URL or video ID, let the Agent probe subtitles, choose a route, and wait for confirmation when needed.
- **Project-based downloads**: each YouTube video is stored in its own folder with video, source subtitles, translated subtitles, thumbnail, and metadata.
- **YouTube subtitles**: detect manual and auto subtitles, download selected tracks, and prefer source-language/manual tracks for translation.
- **OCR subtitles**: extract hard subtitles from embedded video text with configurable crop regions and full-screen assist mode.
- **ASR subtitles**: transcribe speech with `faster-whisper`, then optionally correct ASR text with an LLM.
- **Hybrid workflows**: use a reliable uploaded subtitle timeline, such as English, while reconstructing original-language text from OCR when the embedded source subtitle is more accurate.
- **Glossary review**: generate draft terms, review names/nicknames/program titles in the UI, use romanization and blind candidates, then continue translation.
- **Subtitle editing**: edit, merge, delete, clean prefixes/trailing punctuation, and detect unmatched brackets/quotes.
- **Subtitle conversion**: convert to common formats including SRT, VTT, ASS/SSA, LRC, TXT, JSON, and Bilibili BCC.
- **Video overlay tool**: place watermark/logo masks on a video and export a new video without overwriting the original.
- **Generic LLM config**: one OpenAI-compatible configuration path; the examples use Volcengine Ark/Doubao, but the variable names are provider-neutral.

For the detailed YouTube Agent routing design, see [docs/youtube_agent_workflows.md](docs/youtube_agent_workflows.md).

## Quick Start

Clone and create a Python environment:

```bash
git clone https://github.com/YuqiPlus/Video_Translate.git
cd Video_Translate
conda create -n Video_Translate python=3.11 -y
conda activate Video_Translate
python -m pip install -e ".[dev]"
```

Optional ASR support:

```bash
python -m pip install -e ".[asr]"
```

Copy configuration templates:

```bash
cp .env.example .env
cp configs/llm.example.yaml configs/llm.yaml
cp configs/run.example.yaml configs/run.yaml
```

Edit `.env`:

```text
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
YTDLP_PROXY=
VIDEO_TRANSLATE_HOST=0.0.0.0
VIDEO_TRANSLATE_PORT=7860
VIDEO_TRANSLATE_DOWNLOAD_DIR=YoutubeDownloads
VIDEO_TRANSLATE_CACHE_DIR=models
VIDEO_TRANSLATE_OCR_DEVICE=auto
```

If YouTube needs a proxy on your network, set only `YTDLP_PROXY`, for example:

```text
YTDLP_PROXY=http://127.0.0.1:7890
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

On a remote server, use the server IP and configured port, for example:

```text
http://<server-ip>:7860
```

## Frontend Development

The Python server serves the built frontend from `frontend/dist`. After changing frontend code:

```bash
cd frontend
npm install
npm run build
cd ..
python run_agent_ui.py
```

## LLM Configuration

The project uses OpenAI-compatible chat-completions APIs. Provider switching should normally require only:

1. `.env`: update `LLM_API_KEY` and optionally `LLM_BASE_URL` / `LLM_MODEL`.
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

Task-specific model roles live under `tasks`. Model selection order is:

```text
explicit --model
> task-specific env var, e.g. ASR_CORRECTION_MODEL
> configs/llm.yaml tasks.<task>.model
> configs/llm.yaml tasks.<task>.model_role resolved through defaults.models
> .env global LLM_MODEL
> configs/llm.yaml defaults.model
> configs/llm.yaml defaults.models.default
```

Legacy `ARK_*` environment variables remain compatible for older local installs, but new setups should use `LLM_*`.

## GPU and Model Cache

Model caches default to the project-local `models/` directory. You can override the root in `.env`:

```text
VIDEO_TRANSLATE_CACHE_DIR=/data/models/video_translate
```

For PaddleOCR GPU support, install a PaddlePaddle GPU build that matches your CUDA runtime. Example for CUDA 12.6:

```bash
python -m pip uninstall -y paddlepaddle
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

Check CUDA visibility:

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

If `ocr.device` is `auto`, `.env` can choose the default device:

```text
VIDEO_TRANSLATE_OCR_DEVICE=gpu:0
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

## Manual Commands

Probe dependencies and cache paths:

```bash
python -m video_translate doctor
```

Run from `configs/run.yaml`:

```bash
python run_from_config.py
# or
video-translate run-config configs/run.yaml
```

Extract hard subtitles from a local video:

```bash
python -m video_translate extract "input.mp4" --lang korean --out "outputs/demo"
```

Extract with full-screen assist:

```bash
python -m video_translate extract "input.mp4" --lang korean --out "outputs/demo" --scan-full-frame
```

Translate an existing SRT with the configured OpenAI-compatible provider:

```bash
python -m video_translate translate-volcengine "outputs/demo/source.srt" \
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

- `.env`
- `configs/run.yaml`
- `configs/llm.yaml`
- `YoutubeDownloads/`
- `outputs/`
- `models/`
- generated media/subtitle files such as `*.mp4`, `*.srt`, `*.vtt`, `*.ass`, `*.bcc`

Keep reusable glossary examples under `configs/glossaries/examples/`. Per-task glossary drafts belong in `outputs/agent_tasks/<task-id>/` or another ignored working directory.

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
