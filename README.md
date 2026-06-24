# Video Translate

Video Translate is an early-stage hard-subtitle extraction and translation tool. It can OCR video frames, merge repeated OCR results into subtitle timelines, filter persistent overlays such as logos, translate subtitles with an OpenAI-compatible LLM provider, and export SRT files. The included examples use Volcengine Ark/Doubao.

## Features

- Extract hard subtitles from video frames with PaddleOCR.
- Merge frame-level OCR results into subtitle cues.
- Filter long-lived overlays such as logos, watermarks, and fixed title cards.
- Export `source.srt`, `zh.srt`, `tracks.json`, `ignored_tracks.json`, and `tracks_debug.csv`.
- Use a glossary to keep character names, show names, and terms consistent.
- Copy generated subtitles next to the source video for player debugging.

## Quick Start

Clone the project and create a Python environment:

```bash
git clone https://github.com/YuqiPlus/Video_Translate.git
cd Video_Translate
conda create -n Video_Translate python=3.11 -y
conda activate Video_Translate
python -m pip install -e ".[dev]"
```

Copy the environment template:

```bash
cp .env.example .env
```

Edit `.env` and at least fill the LLM settings. This example uses
Volcengine Ark, which exposes an OpenAI-compatible chat-completions API:

```text
LLM_API_KEY=your_openai_compatible_api_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
LLM_MODEL=doubao-seed-2.0-pro
```

For another provider, keep the `LLM_*` variable names and replace the API key,
base URL, and model name.

If YouTube needs a proxy on your network, set it explicitly:

```text
YTDLP_PROXY=http://127.0.0.1:7890
```

If you do not need a proxy, leave `YTDLP_PROXY=` empty. The project does not use
a proxy by default.

Run checks:

```bash
python -m video_translate doctor
python -m pytest
```

Start the Agent UI:

```bash
python run_agent_ui.py
```

Open:

```text
http://127.0.0.1:7860
```

## Installation Details

Create and activate a Conda environment:

```bash
conda create -n Video_Translate python=3.11 -y
conda activate Video_Translate
```

Install the project:

```bash
python -m pip install -e .
```

For development and tests:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Install optional ASR support:

```bash
python -m pip install -e ".[asr]"
```

The frontend source is under `frontend/`. The Python web server serves the built
frontend from `frontend/dist`. If you change frontend code:

```bash
cd frontend
npm install
npm run build
cd ..
python run_agent_ui.py
```

### GPU Setup

The default dependency can install CPU PaddlePaddle depending on your platform. If you want GPU OCR, install a GPU PaddlePaddle build that matches your CUDA runtime.

Example for CUDA 12.6:

```bash
python -m pip uninstall -y paddlepaddle
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

Check whether Paddle can see CUDA:

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

If CUDA is available, keep this in `configs/run.yaml`:

```yaml
ocr:
  device: "auto"
```

You can also force a device:

```yaml
ocr:
  device: "gpu:0"
```

## Configuration

Copy the example files:

```bash
cp .env.example .env
cp configs/run.example.yaml configs/run.yaml
cp configs/llm.example.yaml configs/llm.yaml
```

On Windows PowerShell:

```powershell
copy .env.example .env
copy configs\run.example.yaml configs\run.yaml
copy configs\llm.example.yaml configs\llm.yaml
```

Edit `.env`. The template uses Volcengine Ark as the example provider:

```text
LLM_API_KEY=your_openai_compatible_api_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
LLM_MODEL=doubao-seed-2.0-pro
```

For a different OpenAI-compatible provider, change only the values. Keep the
`LLM_*` names.

Do not commit `.env`. It is ignored by Git.

### Environment Variables

Most machine-specific settings should live in `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_API_KEY` | empty | API key for an OpenAI-compatible chat/completions provider. Required for title translation, glossary, ASR correction, hybrid reconstruction, and subtitle translation. |
| `LLM_BASE_URL` | `https://ark.cn-beijing.volces.com/api/coding/v3` in `.env.example` | OpenAI-compatible endpoint base URL. |
| `LLM_MODEL` | `doubao-seed-2.0-pro` in `.env.example` | Global default model. A task-specific model in `configs/llm.yaml` overrides it. |
| `LLM_REQUEST_TIMEOUT` | `240` | HTTP timeout in seconds for LLM calls. Increase this for long subtitle batches. |
| `LLM_REQUEST_RETRIES` | `3` | Retry count for LLM requests. |
| `ASR_CORRECTION_MODEL` | empty | Optional override for ASR source-text correction. |
| `YTDLP_PROXY` | empty | Proxy used only by YouTube download/probe paths. Example: `http://127.0.0.1:7890`. |
| `YTDLP_OUTPUT_DIR` | `YoutubeDownloads` | Default output directory for direct YouTube download scripts. Relative paths are resolved from the project root. |
| `YTDLP_SUB_LANGS` | `ko,en.*` in code, expanded in `.env.example` | Default subtitle language list for direct subtitle downloads. |
| `VIDEO_TRANSLATE_HOST` | `0.0.0.0` | Agent UI bind host. |
| `VIDEO_TRANSLATE_PORT` | `7860` | Agent UI port. |
| `VIDEO_TRANSLATE_DOWNLOAD_DIR` | `YoutubeDownloads` | Download/media directory used by the Agent UI. |
| `VIDEO_TRANSLATE_CACHE_DIR` | `models` in Agent child processes | Local model cache root for PaddleOCR/faster-whisper. |
| `HF_HOME` | `${VIDEO_TRANSLATE_CACHE_DIR}/huggingface` | Optional Hugging Face cache override. |
| `PADDLE_HOME` | `${VIDEO_TRANSLATE_CACHE_DIR}/paddle` | Optional Paddle cache override. |
| `PADDLE_PDX_CACHE_HOME` | `${VIDEO_TRANSLATE_CACHE_DIR}/paddlex` | Optional PaddleX model cache override. |

Proxy note: generic `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` are removed
from Agent child processes so local OCR/ASR/LLM work does not accidentally go
through a YouTube proxy. Use `YTDLP_PROXY` for YouTube only.

Task-specific model choices live in `configs/llm.yaml`.

Model selection order:

```text
explicit --model
> task-specific env var, e.g. ASR_CORRECTION_MODEL
> configs/llm.yaml tasks.<task>.model
> .env global default LLM_MODEL
> configs/llm.yaml defaults.model
```

In practice, put your strong default model in `.env` as `LLM_MODEL`. Then put
cheaper/faster models in `configs/llm.yaml` only for small tasks such as title
translation, ASR correction, or hybrid source reconstruction.

Older local installs that still use `ARK_API_KEY`, `ARK_BASE_URL`,
`ARK_MODEL`, `ARK_REQUEST_TIMEOUT`, or `ARK_REQUEST_RETRIES` remain compatible,
but new setups should use the provider-neutral `LLM_*` names.

Edit `configs/run.yaml`:

```yaml
mode: full
input_video: "/path/to/video.mp4"
source_srt: "outputs/demo/source.srt"
output_dir: "outputs/demo"

source_language: "korean"
target_language: "简体中文"
glossary: "configs/glossaries/examples/glossary.example.yaml"

ocr:
  device: "auto"
  sample_fps: 3.0
  bottom_ratio: 0.42
  scan_full_frame: false

translation:
  provider: "volcengine"
  batch_size: 40
  model: null
  base_url: null

sidecar:
  enabled: true
  copy_source: true
  copy_translated: true
  source_suffix: ".source"
  translated_suffix: ".zh"
```

Modes:

- `extract`: OCR only.
- `translate`: translate an existing `source_srt`.
- `full`: OCR, then translate.

## Usage

Check dependencies and cache paths:

```bash
python -m video_translate doctor
```

Run from `configs/run.yaml`:

```bash
python run_from_config.py
```

Run the Agent UI:

```bash
python run_agent_ui.py --host 0.0.0.0 --port 7860
```

Or via `.env`:

```text
VIDEO_TRANSLATE_HOST=0.0.0.0
VIDEO_TRANSLATE_PORT=7860
```

Extract subtitles from a video:

```bash
python -m video_translate extract "input.mp4" --lang korean --out "outputs/demo"
```

Use full-frame OCR when screen text outside the lower subtitle area matters:

```bash
python -m video_translate extract "input.mp4" --lang korean --out "outputs/demo" --scan-full-frame
```

Translate an extracted SRT with Volcengine Ark/Doubao:

```bash
python -m video_translate translate-volcengine "outputs/demo/source.srt" --glossary "configs/glossaries/examples/glossary.example.yaml" --out "outputs/demo/zh.srt"
```

Reprocess an existing `tracks.json` after changing filtering logic:

```bash
python -m video_translate reprocess-tracks "outputs/demo/tracks.json" --out "outputs/demo"
```

Prepare a JSON translation batch without calling an LLM:

```bash
python -m video_translate prepare-translation "outputs/demo/source.srt" --glossary "configs/glossaries/examples/glossary.example.yaml" --out "outputs/demo/translation_batch.json"
```

Apply a translated JSON result back to SRT:

```bash
python -m video_translate apply-translation "outputs/demo/source.srt" "outputs/demo/translated.json" --out "outputs/demo/zh.srt"
```

## Command-Line Tools

Tool implementations live under `video_translate.youtube` and `video_translate.tools`.
Prefer module commands for new automation:

```bash
python -m video_translate.youtube.download_subtitles "https://www.youtube.com/watch?v=..." --sub-langs ko,en
python -m video_translate.youtube.download_video "https://www.youtube.com/watch?v=..."
python -m video_translate.tools.generate_glossary "YoutubeDownloads/example.ko.srt" --out "configs/glossaries/example.draft.yaml"
python -m video_translate.tools.translate_subtitles "YoutubeDownloads/example.ko.srt" --glossary "configs/glossaries/examples/glossary.example.yaml"
python -m video_translate.tools.convert_subtitle "YoutubeDownloads/example.zh.srt" --format bcc
python run_agent_ui.py --host 0.0.0.0 --port 7860
```

Thin script wrappers are kept under `scripts/` for manual use, for example:

```bash
python scripts/download_youtube_video.py "https://www.youtube.com/watch?v=..."
python scripts/translate_downloaded_subtitles.py "YoutubeDownloads/example.ko.srt"
```

Downloaded videos and subtitles are ignored by Git. Agent-created per-task glossary drafts live under `outputs/agent_jobs/<job_id>/` with the rest of that task's logs and artifacts. Keep only reusable glossary files under `configs/glossaries/`; the tracked starter example is `configs/glossaries/examples/glossary.example.yaml`.

## Outputs

Typical output files:

- `source.srt`: OCR source-language subtitles.
- `zh.srt`: translated subtitles.
- `tracks.json`: full OCR text tracks with boxes and metadata.
- `ignored_tracks.json`: tracks filtered as persistent overlays.
- `tracks_debug.csv`: spreadsheet-friendly debug table with bbox positions and filter reasons.

If `sidecar.enabled` is `true`, generated subtitles are also copied next to the input video. For `demo.mp4`, the sidecar files are:

```text
demo.source.srt
demo.zh.srt
```

Existing sidecar files are overwritten on each run.

## Cache

By default, model caches are stored in the project directory:

```text
.cache/
```

To put model caches elsewhere:

```bash
export VIDEO_TRANSLATE_CACHE_DIR="/path/to/model-cache"
```

On Windows PowerShell:

```powershell
$env:VIDEO_TRANSLATE_CACHE_DIR="C:\path\to\Video_Translate\.cache"
```

## Notes

- Start with `mode: extract` and `sample_fps: 1.0` when tuning OCR.
- Use `tracks_debug.csv` to inspect text positions and filter reasons.
- `scan_full_frame: true` catches more screen text, but also increases logo, watermark, and UI noise.
- Keep personal paths in `configs/run.yaml`; it is ignored by Git.
