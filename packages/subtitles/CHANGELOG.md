# Changelog

## Unreleased

- Add optional, lazily initialized `ASR`/`FasterWhisperBackend` and
  `OCR`/`PaddleOCRBackend` Python interfaces, plus `ASRBackend`/`OCRBackend`
  extension contracts. No recognition framework is imported by default.
- Add independent `asr`, `ocr`, `ocr-cpu` and `video` extras. Models are not
  packaged; first use delegates download/cache to the upstream runtime.
- Add local/offline loading, explicit warmup, per-instance model reuse, image
  regions, basic crop/mask video OCR, progress and cooperative cancellation.
- Add optional per-instance OCR `cache_dir`, matching ASR's cache selection:
  default Hub user cache, lazy first download, cached-first reuse, explicit local
  model precedence and offline rejection. Do not mutate Paddle/global settings.
  Anchor relative OCR/ASR cache paths when constructing clients.
- Separate ordinary package installs, regular source installs and editable
  developer installs in the guides; document CPU and CUDA setup independently.
- Keep web OCR 3.0, ASR 2.2 and experimental Agents independent and unchanged.
  Runtime recognition never invokes pip or silently selects fallback models.
- These are source-only changes, not part of the already published 0.1.1 files.

## 0.1.1

- Publish only the independent `reibosub` subtitle toolkit, using its own source,
  tests, documentation and packaging configuration under `packages/subtitles`.
- Keep subtitle read/write, format conversion, Simplified/Traditional conversion,
  timing-locked translation, custom codecs and translation backends.
- Add reusable text script conversion, preserving inline subtitle tags.
- Exclude the website, local configuration, database migration, models, media and
  generated/test data from both the wheel and source distribution.

### Migration from 0.1.0

The early 0.x package was previously bundled with application compatibility code.
Starting with 0.1.1, `video_translate`, the `video-translate` command and the
`translate/download/video/ocr/ocr-cpu/asr/diarization/web/all-cpu` extras belong to
the separate **web application**, not this PyPI distribution. The library keeps
only lightweight runtime dependencies and the `dev` extra. The public HTTP
translator requires no additional extra.

`reibosub doctor/setup` now diagnoses/repairs only `core`. Use
`python -m video_translate.dependencies doctor/setup` in the web source project
for recognition/application setup. Legacy video commands use `video-translate`.

Use a fresh virtual environment for the standalone library. Do not replace a
package inside an environment used by a running website. For source development,
install both products as documented in the repository's web guide; the toolkit
does not read website keys or settings. Existing 0.1.0 artifacts are not changed.
