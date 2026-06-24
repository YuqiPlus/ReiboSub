# YouTube Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable Agent layer for YouTube links: clean URLs, recommend subtitle/OCR/ASR route, and show the recommendation in the existing UI.

**Architecture:** Add small pure modules for URL normalization and workflow planning, then wire them into `/api/probe` and the Vue new-task screen. Long-running OCR/ASR diagnosis and format conversion remain follow-up tasks after the planner surface is stable.

**Tech Stack:** Python stdlib + pytest for backend planning logic; Vue 3 + existing Vite app for UI.

---

### Task 1: URL Normalization

**Files:**
- Create: `video_translate/youtube_url.py`
- Modify: `download_youtube_video.py`
- Modify: `download_youtube_subtitles.py`
- Test: `tests/test_youtube_url.py`

- [ ] Write tests for watch, youtu.be, shorts, embed, and URLs with `t/list/si` noise.
- [ ] Implement `normalize_youtube_url()` and `extract_youtube_video_id()`.
- [ ] Reuse normalization in video/subtitle download scripts.
- [ ] Run `pytest tests/test_youtube_url.py tests/test_youtube_download.py`.

### Task 2: Agent Route Planner

**Files:**
- Create: `video_translate/agent_planner.py`
- Test: `tests/test_agent_planner.py`

- [ ] Write tests for direct Chinese subtitle, source-language manual subtitle, auto subtitle, embedded-subtitle hint OCR, no-embedded hint ASR, and unknown hint diagnosis.
- [ ] Implement `build_agent_plan()` returning route, confidence, reasons, actions, and selected subtitle.
- [ ] Run `pytest tests/test_agent_planner.py`.

### Task 3: Probe API Integration

**Files:**
- Modify: `video_translate/web_agent.py`
- Test: `tests/test_web_agent.py`

- [ ] Extend `probe_video()` to normalize URL and include `normalized_url` plus `agent_plan`.
- [ ] Accept optional `embedded_subtitle_hint` and `target_language` in `/api/probe` payload.
- [ ] Run `pytest tests/test_web_agent.py`.

### Task 4: Frontend Agent Card

**Files:**
- Modify: `frontend/src/components/VideoInputPanel.vue`
- Modify: `frontend/src/components/VideoInfoPanel.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles.css`

- [ ] Add three-state embedded subtitle hint control: yes/no/unknown.
- [ ] Show Agent recommendation card after probe.
- [ ] Route buttons reuse existing download subtitle/video/OCR/ASR actions where possible.
- [ ] Run `npm run build`.

### Task 5: Verification

**Files:**
- No new files.

- [ ] Run full `pytest`.
- [ ] Run frontend build.
- [ ] Restart `run_agent_ui.py` on port 7860.
