# ReiboSub

A lightweight Python subtitle toolkit with read/write, format conversion, Chinese
Simplified/Traditional conversion, pluggable timing-locked LLM translation,
and optional lazy OCR/ASR interfaces.
Python 3.10+ · Apache-2.0 · early 0.x API.

## Install

```bash
python -m pip install reibosub
```

The default installation needs only OpenCC and packaging. It does **not** install
OCR/ASR frameworks, models, CUDA, FFmpeg, Node, or a running website.

## Read, write and convert

```python
from reibosub import Cue, Subtitle, convert

subtitle = Subtitle((Cue(1, 0.5, 2.0, "繁體字幕"),), language="zh-Hant")
subtitle.save("input.srt")
loaded = Subtitle.load("input.srt")
loaded.save("output.vtt")
loaded.to_simplified().save("simplified.srt")
loaded.to_traditional().save("traditional.srt")
convert("input.srt", "output.json")
print(loaded.to_text())
```

Times use seconds. Operations return new objects. Saving refuses to overwrite an
existing file unless `overwrite=True` is explicit. Supported formats: SRT, VTT,
ASS/SSA, JSON, BCC, LRC and TXT. Conversions do not preserve all ASS styles,
effects or VTT positioning; TXT creates synthetic timings when read.

## Translate with your own provider

```python
from getpass import getpass
from reibosub import Subtitle, Translator

client = Translator(
    base_url="https://your-provider.example/v1",  # replace with your endpoint
    api_key=getpass("API key: "),
    model="your-model-id",  # replace with an available compatible model
    glossary={"ReiboSub": "ReiboSub"},
)
client.translate(
    Subtitle.load("input.srt"), source_language="ko", target_language="zh",
).save("output.zh.srt")
```

Requires a Chat Completions-compatible service and may incur provider charges.
Credentials must be supplied explicitly; no website configuration is read. Cue
counts, indexes and timing are locked; semantic accuracy still needs review.
Implement `TranslationBackend.translate_batch()` to use a local model or another
SDK. The default install already includes the public HTTP translator.

## Independent development

This directory is the standalone library product. Its implementation is under
`src/reibosub`; tests, examples and packaging configuration belong to this
product. It never imports the web application, reads its settings or discovers
its credentials.

```bash
# From the repository root:
python -m pip install -e "./packages/subtitles[dev]"
cd packages/subtitles
python -m pytest tests -q
python -m pip install "build>=1.2,<2"
python -m build
reibosub doctor core
reibosub setup core --dry-run
```

Website and download extras belong to the root `reibosub-web` source project.
Version 0.1.2 also provides independent recognition extras described
below. These do not install or run the website. See the [web guide](https://github.com/YuqiPlus/ReiboSub/blob/main/docs/web-application.md).

Version **0.1.1** is the first toolkit-only distribution. It retains the subtitle
API while removing the bundled `video_translate` application, recognition/web
extras and legacy video command forwarding. Install/develop the website from the
repository root instead; see [migration notes](https://github.com/YuqiPlus/ReiboSub/blob/main/packages/subtitles/CHANGELOG.md).
The published 0.1.0 files remain unchanged. Do not upgrade an environment used by
a running website; test the package in its own environment first.

[API and extensions](https://github.com/YuqiPlus/ReiboSub/blob/main/packages/subtitles/docs/python-api.md) · [Examples](https://github.com/YuqiPlus/ReiboSub/tree/main/packages/subtitles/examples/python_api)

## Optional OCR and ASR

**Available starting with 0.1.2.** Ordinary package users do not need to clone
the repository or know its internal source directory:

```bash
python -m pip install "reibosub[asr]>=0.1.2,<0.2"
python -m pip install "reibosub[ocr-cpu,video]>=0.1.2,<0.2" # CPU
python -m pip install "reibosub[ocr,video]>=0.1.2,<0.2"     # CUDA: separately install matching GPU Paddle
```

Source users/developers can instead install a checkout in an independent environment:

```bash
# From the repository root, regular source installation:
python -m pip install "./packages/subtitles[ocr-cpu,video]"
# Only developers who want source edits to take effect immediately need -e:
python -m pip install -e "./packages/subtitles[asr,ocr-cpu,video,dev]"
# CUDA source installation: use ./packages/subtitles[ocr,video], not [ocr-cpu].
```

`./packages/subtitles` selects the source product, not the model directory;
`[ocr,video]` selects dependencies. Do not modify a running website's environment.
Do not install CPU and GPU Paddle together. Follow the [Paddle installation guide](https://www.paddleocr.ai/latest/en/version3.x/installation.html)
to select GPU Paddle for your platform/driver/CUDA combination.

```python
from reibosub import ASR, OCR

asr = ASR(model="small", device="cpu", compute_type="int8", cache_dir="./models/asr")
# Construction performs no imports/downloads. First recognition loads/downloads;
# the same instance reuses weights in memory. Later processes reuse disk cache.
asr.transcribe("speech.wav", language="ko").save("speech.ko.srt")

ocr = OCR(language="korean", device="cpu")
# Optional custom cache: OCR(language="korean", cache_dir="./models/ocr")
# CUDA: OCR(language="korean", device="gpu:0", cache_dir="./models/ocr")
for region in ocr.read_image("frame.png"):
    print(region.text, region.confidence, region.polygon)
ocr.extract_subtitles(
    "video.mp4", crop=(0, 0.65, 1, 1), exclude=((0.8, 0, 1, 0.15),),
    sample_fps=3, language="ko",
).save("screen.ko.srt")
```

PaddleOCR uses its own language codes (`korean`, `japan`, `ch`, `chinese_cht`,
`en`), while ASR uses ISO codes such as `ko`, `ja`, `zh`, `en`. ASR can auto-detect
with `language=None`; OCR language selection is explicit. Simplified/Traditional
ASR output can be chosen with `.to_simplified()` / `.to_traditional()` afterward.

### Model cache is optional and separate from installation

Both OCR and ASR accept `cache_dir=None` (the default): use the standard Hugging
Face user cache, normally `~/.cache/huggingface/hub`, respecting upstream cache
environment settings. Nothing needs to be filled in. OCR weights come from the
official `PaddlePaddle` model repositories; only inference assets are fetched.

Pass `cache_dir="./models/ocr"` to choose a different OCR cache. Relative paths
are anchored to the working directory when the object is created; `~` expands
to the user's home. Construction creates no directory, loads no runtime and
downloads nothing. First recognition checks the cache before accessing the
network; missing models download into that cache. Later calls reuse the loaded
instance, and new instances/processes reuse the on-disk snapshot. A failed or
unwritable selected cache raises an error, not a silent fallback elsewhere.

Explicit `detection_model_dir` / `recognition_model_dir` override the cache for
that model. They must contain complete local inference assets; invalid explicit
paths never trigger replacement downloads. The cache uses Hugging Face's
versioned layout; do not assume the root itself is a single model directory.
Paddle may still maintain its own auxiliary runtime cache, but this library never
changes global `HOME`, Paddle cache paths or website configuration.

Use `ASR(..., local_files_only=True)` or
`OCR(cache_dir="./models/ocr", local_files_only=True)` to reject missing weights
instead of downloading. For offline OCR, start Python with
`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` to disable the upstream connectivity
probe; explicit detection/recognition paths remain supported. See the API guide.
Model downloads may use your upstream network/proxy environment. Downloaded
model licenses are separate from the Python package's license.

Missing Python dependencies produce an installation hint; recognition never
runs pip. `reibosub doctor asr/ocr/ocr-cpu/video` checks dependencies without
loading weights; use one feature name per command. Recognition extras/platform
support and GPU libraries depend on third-party wheels, independently of the
lightweight toolkit's Python support.

Video OCR is a **basic sampled extractor** with exact adjacent-text merging and
sample-resolution timing (video timestamps decoded by PyAV), not the web OCR 3.0 LLM refinement or ASR Agent. No
speaker diarization, autonomous verification or hidden translation is performed.
Implement `ASRBackend` or `OCRBackend` to substitute a local model/cloud API.
