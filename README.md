# Video Translate

Video Translate is an early-stage hard-subtitle extraction and translation tool. It can OCR video frames, merge repeated OCR results into subtitle timelines, filter persistent overlays such as logos, translate subtitles with Volcengine Ark/Doubao, and export SRT files.

## Features

- Extract hard subtitles from video frames with PaddleOCR.
- Merge frame-level OCR results into subtitle cues.
- Filter long-lived overlays such as logos, watermarks, and fixed title cards.
- Export `source.srt`, `zh.srt`, `tracks.json`, `ignored_tracks.json`, and `tracks_debug.csv`.
- Use a glossary to keep character names, show names, and terms consistent.
- Copy generated subtitles next to the source video for player debugging.

## Environment

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
```

On Windows PowerShell:

```powershell
copy .env.example .env
copy configs\run.example.yaml configs\run.yaml
```

Edit `.env`:

```text
ARK_API_KEY=your_volcengine_ark_api_key
ARK_MODEL=your_model_or_endpoint_id
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

Do not commit `.env`. It is ignored by Git.

Edit `configs/run.yaml`:

```yaml
mode: full
input_video: "/path/to/video.mp4"
source_srt: "outputs/demo/source.srt"
output_dir: "outputs/demo"

source_language: "korean"
target_language: "简体中文"
glossary: "configs/glossary.example.yaml"

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
python -m video_translate translate-volcengine "outputs/demo/source.srt" --glossary "configs/glossary.example.yaml" --out "outputs/demo/zh.srt"
```

Reprocess an existing `tracks.json` after changing filtering logic:

```bash
python -m video_translate reprocess-tracks "outputs/demo/tracks.json" --out "outputs/demo"
```

Prepare a JSON translation batch without calling an LLM:

```bash
python -m video_translate prepare-translation "outputs/demo/source.srt" --glossary "configs/glossary.example.yaml" --out "outputs/demo/translation_batch.json"
```

Apply a translated JSON result back to SRT:

```bash
python -m video_translate apply-translation "outputs/demo/source.srt" "outputs/demo/translated.json" --out "outputs/demo/zh.srt"
```

## YouTube Helper Scripts

The top-level helper scripts use stable command-style names:

```bash
python download_youtube_subtitles.py "https://www.youtube.com/watch?v=..." --sub-langs ko,en
python download_youtube_video.py "https://www.youtube.com/watch?v=..."
python generate_glossary_from_subtitles.py "YoutubeDownloads/example.ko.srt" --out "configs/glossaries/example.draft.yaml"
python translate_downloaded_subtitles.py "YoutubeDownloads/example.ko.srt" --glossary "configs/glossary.example.yaml"
python run_agent_ui.py --host 0.0.0.0 --port 7860
```

Downloaded videos and subtitles are ignored by Git. Per-task glossary drafts under `configs/glossaries/` are also ignored; keep reusable examples in `configs/glossary.example.yaml`.

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
