# ReiboSub

A lightweight Python subtitle toolkit with read/write, format conversion, Chinese
Simplified/Traditional conversion, and pluggable, timing-locked LLM translation.
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

## Optional features and diagnostics

```bash
python -m pip install 'reibosub[download]'
python -m pip install 'reibosub[asr]'
reibosub doctor core
reibosub setup asr --dry-run
```

Extras: `translate` (legacy translation dependencies), `download`, `video`, `ocr`,
`ocr-cpu`, `asr`, `diarization`, `web`, `all-cpu`, `dev`. Recognition engines,
device compatibility, external tools and model authorization require separate
setup. `ocr` does not choose a CPU/GPU Paddle engine. Do not install `ocr-cpu`
over GPU Paddle. Package diagnosis never installs anything; installation needs
explicit consent, e.g. `reibosub setup asr --yes`, in an isolated environment.
Do not modify an environment used by a running service.

The web application, frontend build and complete video workflows use a **source
checkout**, not just this wheel. OCR/ASR extras install dependencies; they are not
new stable public Python engine APIs.

- [Python API and extension guide](https://github.com/YuqiPlus/ReiboSub/blob/main/docs/python-api.md)
- [Runnable development examples](https://github.com/YuqiPlus/ReiboSub/tree/main/examples/python_api)
- [Website setup / 中文说明](https://github.com/YuqiPlus/ReiboSub/blob/main/README.zh-CN.md)
- [Source and issues](https://github.com/YuqiPlus/ReiboSub)
