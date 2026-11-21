# Changelog

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
