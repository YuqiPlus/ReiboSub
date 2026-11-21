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

Only the `dev` extra belongs to this library. Website, download and recognition
extras belong to the root `reibosub-web` source project. They are not public
OCR/ASR engine APIs. See the [web guide](https://github.com/YuqiPlus/ReiboSub/blob/main/docs/web-application.md).

This repository reorganization is **unreleased**. The existing PyPI 0.1.0 remains
unchanged; a future release must use a new version. From a source checkout, use
the editable install above to test these changes rather than assuming the
published wheel already has this new layout.

[API and extensions](https://github.com/YuqiPlus/ReiboSub/blob/main/packages/subtitles/docs/python-api.md) · [Examples](https://github.com/YuqiPlus/ReiboSub/tree/main/packages/subtitles/examples/python_api)
