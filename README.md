# ReiboSub

[中文说明](README.zh-CN.md)

ReiboSub is a subtitle production assistant for YouTube, ordinary Bilibili uploads, and local videos. It can download videos, subtitles, and thumbnails; extract embedded hard subtitles with OCR; transcribe speech with ASR; generate and review glossary drafts; translate subtitles with an OpenAI-compatible LLM; edit and convert subtitle files; and copy playable sidecar subtitles next to the video.

The project is designed for a human-in-the-loop workflow: the Agent can run multiple video flows at the same time, pause when it needs your decision, and continue after you review glossary terms.

[Install and start](#quick-start) · [Bilibili and languages](#bilibili-and-multilingual-subtitles) · [Assets and glossary](#assets-and-glossary-review) · [Model settings](#llm-configuration) · [GPU and experiments](#gpu-and-model-cache) · [Troubleshooting](#troubleshooting)

For secondary development, the provisional [`reibosub` Python API](docs/python-api.md) provides immutable subtitle data, standalone read/write and conversion, Chinese script conversion, pluggable translation backends and custom format codecs. [Runnable examples](examples/python_api/) include offline implementations. It does not require the web service or discover its credentials. No PyPI release has been made; dependency splitting is a separate next step.

## What It Can Do

- **Agent cockpit**: paste a YouTube or ordinary Bilibili video URL/ID, let the Agent inspect sources, and review terms before translation.
- **Linked project assets**: each video or Bilibili part has its own media folder. Assets also lists associated task-owned source/target subtitles and archived versions without copying them beside the video.
- **Platform captions**: detect manual and automatic captions and download selected tracks; Bilibili danmaku is not used as a caption source.
- **OCR subtitles**: use the stabilized OCR 3.0 workflow for new Agent tasks while retaining isolated OCR 1.0 and 2.0 compatibility routes.
- **ASR subtitles**: transcribe speech with `faster-whisper`, then optionally correct ASR text with an LLM.
- **Video upload flow**: upload a local video from the browser and start an ASR-to-Chinese subtitle job directly.
- **Hybrid workflows**: use a reliable uploaded subtitle timeline, such as English, while reconstructing original-language text from OCR when the embedded source subtitle is more accurate.
- **Glossary review**: review names, nicknames and titles with romanization and context translations. Play evidence from the associated video/audio inside each term card, switch occurrences, slow down/repeat playback, and inspect adjacent source subtitles. Clips include 3 seconds on each side, expandable to 10; playback never confirms or edits a translation.
- **Reference translator**: translate between Chinese, English, Japanese and Korean within glossary review, with automatic source detection, direction swapping, original-sentence shortcuts and copy. Results never automatically confirm glossary terms.
- **Subtitle editing**: edit text and timing, keep 50 undo steps, preview one cue with a live sidecar overlay, and add/merge/delete/clean cues.
- **Subtitle conversion**: convert to common formats including SRT, VTT, ASS/SSA, LRC, TXT, JSON, and Bilibili BCC.
- **Video overlay tool**: place watermark/logo masks on a video and export a new video without overwriting the original.
- **Model provider settings**: manage providers and search for one shared model; optionally use a separate vision model and keep per-module overrides under advanced settings.

For Agent routing design notes, see [docs/youtube_agent_workflows.md](docs/youtube_agent_workflows.md). That document includes background and future ideas, so not every item is necessarily implemented.

### Independent goal-driven Agent experiment

Choose the experimental autonomous mode in the Agent cockpit and provide a YouTube or ordinary Bilibili video link. New sessions use an evidence-linked controller: the model chooses each next tool, revises a short plan after observations or failures, and selects delivery when artifact checks allow it. There is no mandatory run-through of every tool. The legacy workflow and saved older experimental sessions retain their existing protocols.

Tools include caption discovery and reuse, subtitle-context queries, frame sampling at model-selected times, vision/OCR trials, ASR, bounded 4–30 second audio checks, source comparison, and local translation review. Vision requires a configured image-capable model; local recognition requires its optional dependencies. The model cannot run arbitrary commands, select arbitrary files, change providers, bypass human glossary review for translation, or overwrite existing translated results. Usable existing target-language captions can be delivered after checks without glossary generation or retranslation, subject to the screen-inspection requirements below.

New autonomous tasks prioritize authored, burned-in subtitles. Before choosing a source, the Agent must analyze at least four frames spanning 60% of the video. If content subtitles are visible, OCR 3.0 supplies the primary text; external captions and localized audio checks are references, not substitutes. Whole-video ASR is available only after diverse sampled observations have not found burned-in subtitles, and this is not a claim about every frame. Conservative OCR crops preserve the full width and bottom edge rather than tightly cropping a few centered single-line samples. Saved experiments and explicitly scoped continuations keep their original protocols.

This experiment saves raw OCR separately, then performs bounded grouped review of candidate HUD/player-ID/object-text noise. Native-script text and adjacent name/number fragments are protected; uncertain groups remain evidence rather than being discarded solely for containing Latin letters or numbers. Native dialogue anchors the per-frame machine seed, so uncertain footer IDs cannot replace it. Raw tracks, quarantine audits and final subtitles remain separate. A dedicated subprocess reuses the existing V3 final refiners with bounded requests/timeouts/output and non-thinking Doubao 2.1 generation; OCR Lab and its stable defaults are unchanged.

Normal new tasks must save both the video and the selected target-language subtitles. The Agent may inspect captions and decide its approach before scheduling the download, and reuses an existing project video when available. Missing video prevents completion even when subtitles are ready. The UI shows saved-video status and a download link. Explicit verification-only, local-review and source-reuse continuations retain their original narrower scope.

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
| Downloads, conversion and subtitle editing | FFmpeg/ffprobe; YouTube also needs Node.js 22.12+ and network access |
| Translation and glossary | Your own OpenAI-compatible model service and quota |
| OCR 1.0 / 2.0 / 3.0 | CPU or GPU PaddlePaddle engine and recognition weights; LLM cleanup requires a model service |
| Web ASR 2.2 | faster-whisper, Whisper weights and NVIDIA CUDA; the current UI submits CUDA/float16, while basic CPU transcription is available through the CLI below |
| Agent visual inspection | An image-capable model, which may be the shared model |

The standard public setup stores tasks and subtitles in files; no database or maintainer's `.env` is required. Qwen/multi-model ASR experiments have separate requirements below.

### 1. Install the recommended CPU starter environment

Install Git and Conda/Miniforge first, then run the following. If GitHub requires authentication or returns 404, verify repository access first; authorized SSH users can also use `git clone git@github.com:YuqiPlus/ReiboSub.git`. Installation does not change repository visibility.

```bash
git clone https://github.com/YuqiPlus/ReiboSub.git
cd ReiboSub
conda create -n reibosub --override-channels -c conda-forge python=3.11 pip ffmpeg "nodejs>=22.12" -y
conda activate reibosub
python -m pip install -r requirements.txt
```

Keep `--override-channels -c conda-forge`: this command uses only conda-forge rather than appending globally configured channels. No global `.condarc` changes or Anaconda-defaults terms acceptance are needed for this project. The restriction applies to **Conda channels**: Python dependencies still install from PyPI through pip; GPU Paddle uses its official index below.

An `environment.yml` containing `conda-forge` / `nodefaults` remains available for manifest-based installs. `nodefaults` prevents the solver from appending default channels, but some Anaconda terms plugins check global channels before reading the manifest. If affected, use the explicit create command above. The project never automatically accepts terms or changes global configuration. See the [official Conda environment format](https://conda.org/learn/specifications/exchange/environment-yml/) for the format semantics.

This installs Python 3.11, FFmpeg/ffprobe, Node.js 22.12+, CPU OCR and faster-whisper. Installation and initial model loading require network access; long videos may be slow on CPU. **For GPU OCR, skip this CPU environment and follow [GPU and Model Cache](#gpu-and-model-cache).**

If you already have a suitable Python environment, skip environment creation and install as follows. You must separately install FFmpeg/ffprobe and Node.js 22.12+ in `PATH`:

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

None of the three tool paths should be `None`; Node should be version 22.12 or newer. Start the server from the same activated terminal. Calling a Python executable by absolute path does not automatically add its environment's `bin` directory to `PATH`. `reibosub doctor` checks some Python imports/cache paths, not every external tool, CUDA library, model download or API connection.

### 3. Build the frontend

```bash
cd frontend
npm ci --include=dev
npm run build
cd ..
```

Do not skip this step. The server reads `frontend/dist`, not the source files directly; rebuild after pulling frontend changes as well.

The frontend requires Node.js **at least 22.12**; use the latest patch of a supported LTS branch rather than pinning an old 22.12 release. Vite and its Vue plugin are development dependencies but are required to build, so the command explicitly uses `--include=dev`. Python serves the resulting static files without a running Vite process; an `npm ci --omit=dev` installation cannot build the frontend.

### 4. Optional machine-local settings

Optionally copy the single machine-local startup template. The defaults already start safely; create this file to change the media directory, platform proxies, Bilibili cookie path, listen address or port.

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
3. Once recognition and your API work, provide a full YouTube or ordinary Bilibili link in the subtitle assistant and check source/target languages. Formal translation pauses for human glossary review: fill or confirm names and terms, then save to continue.
4. Download the SRT or open it from Assets for editing. Task history provides stage states, artifacts and reruns. Deleting a task removes its task-directory artifacts but preserves downloaded video; download any subtitles you want to keep first.

Automatic checks are not a word-for-word human audit. Test short inputs before long videos to avoid wasting processing time and API quota on setup errors.

## Bilibili and Multilingual Subtitles

The UI currently uses Chinese labels; the labels below are included to help you find the controls.

### Supported links and parts

Both **Downloads & Links (下载与链接)** and **Subtitle Assistant (字幕助手)** accept YouTube URLs/IDs, ordinary Bilibili BV/av IDs, full video links and `b23.tv` short links. Replace the placeholder `BVxxxxxxxxxx` below with a real video you are authorized to process:

```text
BVxxxxxxxxxx
https://www.bilibili.com/video/BVxxxxxxxxxx
https://www.bilibili.com/video/BVxxxxxxxxxx?p=2
```

One task handles one part: no `p` means P1; `?p=2` means P2. Each part has a distinct task key and media directory; similar titles do not permit cross-part OCR reuse. Create a separate task for each part. Bangumi, live streams, whole collections and automatic all-part batches are not supported. Danmaku is not CC dialogue. If a short link fails, paste the full BV URL from your browser's address bar.

### Download without translation

1. Open **下载与链接** and paste a link. Available video formats load automatically; **刷新画质** refreshes them.
2. Choose an actual format, or keep the compatibility preset (up to 1080p, H.264/MP4 preferred), then click **下载视频**. A subtitle probe and LLM credentials are not required first.
3. For CC captions, separately click **查看字幕与视频信息**, select the language/manual or automatic track, and download it. No CC tracks does not mean there are no burned-in subtitles.
4. Find the video in **Assets (素材库)** for preview or further processing. Thumbnail download is under **封面与下载说明**.

Maximum quality is limited to the formats accessible to the current session. MP4 is a container; H.264, HEVC and AV1 are codecs. The highest-quality option does not guarantee H.264; use the compatibility preset when browser/OCR playback matters.

### Generate subtitles from a link

1. Click **新建字幕任务** in the sidebar and paste the full URL, retaining `?p=N` for the selected Bilibili part.
2. Check source language (**音源语言**), target (**译成**) and mode (**处理模式**). **自主 Agent · 实验** selects tools from evidence; no test range is required.
3. Click **开始制作字幕**. The Agent saves the local video and checks sampled frames. Burned-in dialogue/captions take priority through OCR 3.0; external captions or ASR become primary only after sufficient observations find no content subtitles. Configure model services and local recognition dependencies first, as described in Quick Start.
4. When translation is needed, **Glossary Review (术语审核)** opens. Fill and confirm names, titles and fixed terms, then click **全部已确认，保存并开始翻译**. This returns to the Agent and continues without a second confirmation. Usable existing target captions may instead be delivered after checks, without forced retranslation or glossary generation.
5. Download source and target SRTs on completion, or edit them from **素材库**. **所有任务** contains artifacts and rerun controls; do not restart the entire translation solely because a target file has not appeared yet.

Defaults for new tasks:

| Platform | Source language | Target language |
| --- | --- | --- |
| Bilibili | Chinese | English |
| YouTube | Saved source setting, initially Korean | Chinese |

Both sides can be changed manually. Targets are Chinese, English, Japanese and Korean. Manual choices persist within the current draft even if you replace its link; click **新建字幕任务** to reset platform defaults. Saved tasks retain their saved language pair. Check the real spoken language: a Bilibili video is not necessarily Chinese.

### Existing subtitles and language-specific outputs

In **字幕工具 → 翻译与转换**, select/enter a subtitle path and choose **原文语言** and **译成**. Optionally generate and review a glossary first. Unlike the Agent translation route, this manual tool allows translation without a glossary. Format conversion does not call a translation model.

Glossary translations, context references and verification follow the task target, with no Chinese-character requirement for non-Chinese targets. Generate/review a new target-specific glossary when changing direction. A legacy glossary without `target_language` still means Chinese; historical `zh` / `suggested_zh` field names remain compatible but hold the selected target's text.

Language codes are `zh` (Chinese), `en` (English), `ja` (Japanese) and `ko` (Korean). Common outputs include `en.srt` / `<title>.en.srt`; isolated Agent versions may use `en.review_<marker>.srt` with `source.review_<marker>.srt`. Use the task download buttons or asset paths rather than searching only for `zh.srt`.

### Bilibili login, proxy and access

Bilibili uses a direct connection by default, not `youtube_proxy`. Some videos, qualities and CC tracks require login or account entitlements. If needed, add these optional settings to your own `configs/reibosub.yaml` and restart:

```yaml
bilibili_proxy: ""  # only if Bilibili needs its own proxy
bilibili_cookie_file: /private/path/bilibili.cookies.txt
```

Replace the cookie path with a real, server-readable file exported from your own account in Netscape cookie format. Store it outside the repository; it is sensitive login information and must not be shared, screenshotted or committed. The integration does not bypass paid, membership or geographic restrictions. Existing `video_translate.youtube.*` command names remain compatible with ordinary Bilibili videos and selected parts.

## Assets and Glossary Review

### Find subtitles and archived versions

1. Open **素材库**, search by title/filename, or filter by video, audio or subtitle.
2. Click **文件与更多** on a project card. Its **字幕** section lists source/target files and available versions. Task outputs display a run number (**第 N 轮**); archived ones add **历史版本**.
3. Download a file with **下载**, or open its **精修字幕** editor. The associated project video is passed to the editor. The card's quick-edit button prefers a current translation over an archive with a newer copy timestamp.
4. Click **刷新** if a new result is missing. Completed OCR/ASR source text may appear before translation; target files publish once translation completes. Running or failed translation drafts are not published as final results.

Association uses the exact project/video path recorded by a task, not fuzzy title matching. It neither copies nor overwrites subtitles. Media stays in the media folder; independent subtitles stay under `outputs/agent_tasks/<task-id>/` or that task's archived run. Existing tasks with correct bindings and surviving files are included too. Unbound outputs may still need to be opened from task history or independent processing results.

**Visibility in Assets does not mean a player has loaded the subtitle.** Autonomous results are commonly task-owned, with no automatic sidecar copy beside the video. Manually load the downloaded SRT in your player, or place/name it beside the video as your player requires. Do not back up only the media folder if you need task subtitles. Deleting a task removes its task directory and independent subtitles; download or back them up first.

### Review terms with original evidence

The Agent opens its glossary automatically when human review is needed. You can also load one through **字幕工具 → 术语审核 → 术语文件与高级编辑**. Fill translations in the target language and click **确认** per term; edits autosave. **播放证据片段** shows the original audio/video and neighboring subtitles, with occurrence selection, slower playback and repeat. Recognition, romanization and reference translations are clues, not verified official names.

An Agent translation waits until every pending term is confirmed and you click **全部已确认，保存并开始翻译**. A manually opened glossary uses **保存审核结果**. Playing evidence or copying a reference does not confirm a term.

### Use the reference translator

1. Open **随手翻译** at the top of **术语审核**; no glossary file is required. If collapsed, click **展开**.
2. Select a source language on the left or keep **自动识别**. Choose Chinese, English, Japanese or Korean on the right. Its initial target follows the current glossary; changing it affects only this scratchpad, not the task's language pair.
3. Enter up to 4000 characters and click **翻译**, or press `Ctrl+Enter` / `⌘+Enter` in the input. **放入翻译器** on a term card inserts its evidence sentence and resets source detection to automatic.
4. Choose an explicit source to enable **⇄**. Swapping moves a current valid translation into the input when available; click translate again afterward. Swapping is disabled with automatic detection or while a request is active.
5. Use **复制译文** or select text manually. Changing input/languages marks an old result as stale; late replies cannot replace the result for new input. Translate again to refresh it.

The translator reuses the configured subtitle-translation model, normally inherited from the shared model unless overridden. No extra provider/key is required. Text is sent to that provider and consumes its quota. It translates only this text, not the whole video, and never fills, saves or confirms a glossary term automatically. Copy the desired name into its glossary field and confirm it yourself. Copy any result you need before leaving the page. Check model settings/access/quota after service errors; manually select/copy text if clipboard access is blocked.

### Toolbox: use individual tools without a full Agent task

Open **Toolbox (工具箱)** in the workspace sidebar:

- **Text translation**: choose source and target languages and translate up to 4,000 characters with the configured translation model. This uses the provider's quota and does not change the glossary.
- **Subtitle tools**: upload/drop a subtitle directly, then switch between translation, format conversion and Simplified/Traditional conversion with the same file. No video project or Agent task is required. SRT/VTT/ASS/SSA/BCC/JSON/LRC/TXT are supported, up to 10 MB and 20,000 cues. Select UTF-8, UTF-16, GB18030/GBK or Big5 under the encoding disclosure and re-upload if needed. Translation uses the configured model, defaults to locked timing, supports Chinese/English/Japanese/Korean targets and extra fixed-name instructions, and outputs SRT without mandatory glossary review. Mechanical conversions do not call a model. Script conversion retains the native format, timecodes and ASS/SSA style definitions; cross-format conversion can lose styles/effects, and timing synthesized for TXT input is not actual synchronization. Each run saves a separate result: download it, open SRT in the editor, or reuse the result for the next operation. Navigation does not interrupt work; refresh attempts to restore the latest file/job. Original pages and their full glossary-review features remain available.
- **Extract dialogue**: choose library media or upload audio/video. Stable ASR 2.2 produces original-language text, TXT and SRT, with an entry to subtitle editing/playback. It does not translate or require glossary approval. Advanced options include the model, CPU/GPU, hotwords and optional speaker separation. ASR/FFmpeg and device dependencies are still required; speaker separation needs additional dependencies and weights. Extraction continues when navigating away, and a refresh attempts to restore the latest extraction. Each run retains its own job outputs, while the source subtitle sidecar beside the media may be updated.
- **Subtitle to plain text**: open or paste SRT/WebVTT, optionally retain time ranges, and copy/download TXT. This runs entirely in the browser without an upload or model request.

Shortcuts link to downloads, subtitle translation/conversion, screen-text extraction and video processing. Existing pages and experimental versions remain available.

Enable **Separate speakers (区分说话人)** in the dialogue tool's main controls to set the known speaker count to automatic or 1–20. This labels speakers as Speaker 1, 2, etc.; it does not identify real names and still requires speaker-separation dependencies and weights.

**Chinese ASR output**: the dialogue tool and stable ASR Lab expose Simplified (default), Traditional and original-as-recognized output when the input language is Chinese or automatic. Automatic detection applies conversion only to Chinese. Copied text, TXT, SRT and sidecars use the same script; raw recognition evidence remains intact, and subsequent gap review retains the selected script. Conversion uses local [OpenCC](https://github.com/yichen0831/opencc-python), not an LLM; it changes neither timing nor recognition mistakes. Existing tasks are not rewritten, and Korean-only experiments are unchanged. Existing installations should run `python -m pip install -e ".[asr]"` to install the new dependency, then restart the web service.

## Frontend Development

The Python service reads `frontend/dist`. Use `npm ci --include=dev && npm run build` for a production-style local build. For development, run the backend and Vite separately:

```bash
# terminal 1
python run_agent_ui.py

# terminal 2
cd frontend
npm ci --include=dev
npm run dev
```

Vite defaults to `http://127.0.0.1:5173` and proxies `/api` to port `7860`. Still run `npm run build` before committing.

A successful build does not imply vulnerability-free dependencies. Run `npm run audit:deps` from `frontend` to audit the entire locked tree, including development dependencies, and `npm test` for frontend tests. This update uses the maintained Vite 7.3 patch line and patched Vue 3.5; Node requirements align with the [official Vite 7 migration guide](https://v7.vite.dev/guide/migration#node-js-support). Advisories change over time: re-audit, test and build when updating, rather than using `--omit=dev` to hide build-tool advisories. Do not expose the Vite development server publicly or apply untested major upgrades with `npm audit fix --force`.

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
conda create -n reibosub --override-channels -c conda-forge python=3.11 pip ffmpeg "nodejs>=22.12" -y
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
npm ci --include=dev
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
Paste a YouTube or ordinary Bilibili video link; no test interval is required. A bounded controller chooses
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
accuracy. Downloadable source/target-language SRT files remain drafts for user review.

Select **经典工作流** to keep using the original guided route below. Its processing
steps and the ASR 2.2 baseline are unchanged.

Typical guided UI flow:

1. Paste a YouTube / ordinary Bilibili URL or video ID in **字幕助手**, and check the source/target languages.
2. Tell the Agent whether embedded subtitles are present if you know.
3. Let it probe metadata and subtitle tracks, then show the route choice without waiting for a full video download.
4. Choose the recommended route or manually switch to OCR/ASR/downloaded subtitles. After the route is chosen, the Agent downloads the project video or reuses an existing one before continuing.
5. If OCR is needed, preview a frame and tune the crop region immediately.
6. Generate a glossary draft and review terms in the glossary UI.
7. Save the glossary; the Agent continues translation for that specific flow.
8. Review the generated subtitle or convert it to another format.

Multiple Agent flows can run in parallel. Running sessions are polled independently; when a flow waits for confirmation or glossary review, click its card in the Agent task list and handle it without stopping other flows.

Common routes:

- **Existing target-language subtitle**: inspect and reuse, optionally convert/rename.
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

Platform-download and subtitle helpers (replace example URLs/paths with your own):

```bash
python -m video_translate.youtube.download_subtitles "https://www.youtube.com/watch?v=..." --sub-langs ko,en
python -m video_translate.youtube.download_video "https://www.youtube.com/watch?v=..."
python -m video_translate.tools.generate_glossary "YoutubeDownloads/example.ko.srt" --out "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.translate_subtitles "YoutubeDownloads/example.ko.srt" --glossary "outputs/example/glossary.draft.yaml"
python -m video_translate.tools.convert_subtitle "YoutubeDownloads/example.zh.srt" --format bcc
```

For example, with an existing `source.zh.srt`, generate a Chinese → English glossary and translation using the same configured model service:

```bash
python -m video_translate.tools.generate_glossary "source.zh.srt" \
  --source-language chinese --target-language english \
  --out "outputs/demo/glossary.en.yaml"
# Load this glossary in the UI, fill/review and save names before continuing:
python -m video_translate.tools.translate_subtitles "source.zh.srt" \
  --target-language english --glossary "outputs/demo/glossary.en.yaml" \
  --out "outputs/demo/en.srt"
```

To download Bilibili P2, use `python -m video_translate.youtube.download_video "https://www.bilibili.com/video/BVxxxxxxxxxx?p=2"`, replacing the placeholder BV ID. The `youtube` module name is retained for script compatibility, not a restriction on the source platform.

Script wrappers under `scripts/` provide equivalent manual entry points.

## Output Layout

Downloaded YouTube/Bilibili projects are stored under `YoutubeDownloads/<video-title>/` by default. Possible files:

```text
<video-title>.mp4
<video-title>.jpg
<video-title>.source.srt
<video-title>.zh.srt
<video-title>.en.srt
project.yaml
```

These are possible sidecar copies, not files guaranteed for every task. Bilibili titles/directories include a `[BV-ID Pn]` suffix to distinguish parts. `media_dir` can change the media root; its historical default name `YoutubeDownloads` is also used for Bilibili and need not be renamed.

Agent task state and intermediate artifacts live under:

```text
outputs/agent_tasks/<task-id>/
outputs/agent_jobs/<job-id>/
```

Isolated autonomous deliveries commonly use task-owned `source.review_<marker>.srt` and `en.review_<marker>.srt`. Archived generations may live under the task's `runs/generation_*/`. Assets links these records without overwriting sidecars in the video folder.

Common pipeline outputs:

- `source.srt`: source-language subtitle from OCR/ASR/downloaded track.
- `zh.srt` / `en.srt` / `ja.srt` / `ko.srt`: subtitles in the selected target language; isolated filenames may retain review markers.
- `tracks.json`: OCR text tracks with boxes and metadata.
- `ignored_tracks.json`: tracks filtered as persistent overlays/noise.
- `tracks_debug.csv`: spreadsheet-friendly OCR/debug table.
- `*.bcc`: Bilibili subtitle JSON output.

Only workflows with sidecar copying enabled copy subtitles beside the video for player loading. Isolated autonomous results do not guarantee such a copy; use the task result or Assets to locate/download the actual final file.

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

- **The page says the frontend is not built**: run `cd frontend && npm ci --include=dev && npm run build`, then refresh.
- **FFmpeg is installed but the service cannot find it**: activate the project environment, verify the actual Python/ffmpeg/ffprobe paths and launch from that terminal. Installing Python packages does not install a system FFmpeg executable.
- **YouTube reports no JS runtime or challenge solver**: ensure Node.js 22.12+ is in the service's `PATH`, run `python -m pip install -U "yt-dlp[default]"`, and restart. Proxies, login requirements and geographic restrictions may still affect access separately.
- **`libGL.so.1` / `libgomp.so.1` is missing**: this is a system-library issue, not an API-key or model issue. On Ubuntu/Debian an administrator can install `libgl1 libglib2.0-0 libgomp1`; use corresponding packages on other distributions.
- **You cannot find the Conda environment**: run `conda info --envs` and `conda config --show envs_dirs`. To choose a path, replace `-n reibosub` with `-p /path/to/envs/reibosub` in the create command, retaining `--override-channels -c conda-forge`, then activate that path.
- **Conda asks to accept Anaconda defaults-channel terms**: use the explicit `conda create ... --override-channels -c conda-forge ...` command above, followed by pip installation. Some pre-command plugins still intercept `conda env create` even with `nodefaults`; accepting terms or changing global channels is unnecessary. Do not pass `nodefaults` as a download channel with `-c`.
- **Vite reports unsupported Node or a crypto error during build**: check `node --version` in the activated environment; it must be at least 22.12. Node 22.0–22.11 is insufficient. After updating, rerun `npm ci --include=dev` and build; an existing `dist` does not prove dependencies are ready.
- **A CPU Paddle build cannot use the GPU**: select `cpu`/`auto`, or uninstall `paddlepaddle` and install a `paddlepaddle-gpu` build matching your CUDA version. Do not keep both packages.
- **Provider model discovery fails**: many compatible APIs do not expose `/models`; maintain static model IDs in Settings and continue normally.
- **A model list loads but translation fails**: check API base URL, key permissions, quota and model access. Listing models does not prove inference requests will succeed.
- **ASR fails with CUDA or float16 errors on CPU**: the current UI uses CUDA/float16. Use explicit `--device cpu --compute-type int8` with the basic CLI, or configure NVIDIA CUDA before using Web ASR.
- **YouTube cannot connect**: set `youtube_proxy` in `configs/reibosub.yaml`; it applies only to downloads and does not proxy OCR/ASR.
- **Bilibili qualities/CC tracks are missing or require login**: check account entitlements and `bilibili_cookie_file`, then restart after changes. Bilibili does not use the YouTube proxy. Burned-in captions need OCR and speech-only material needs ASR; danmaku is not dialogue captions.
- **Replacing a link does not reset languages**: explicit choices take priority in the current draft. Click **新建字幕任务** to restore platform defaults. Saved tasks retain their own language pair.
- **A completed task has no subtitles beside its video**: autonomous results are often task-owned. Open **素材库 → 文件与更多 → 字幕** or download them from the task. Refresh Assets first if the list is stale instead of reprocessing the whole video.
- **The glossary translator fails or shows stale text**: check the subtitle/shared model's configuration, access and quota. Click translate again after editing input/languages. Update and restart the backend as well as rebuilding the frontend; copying only UI build files is insufficient.
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

Alternatively run `npm test`. Run `npm run audit:deps` for an audit including development dependencies; it exits nonzero when vulnerabilities are reported.

Frontend build:

```bash
cd frontend
npm run build
```

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
