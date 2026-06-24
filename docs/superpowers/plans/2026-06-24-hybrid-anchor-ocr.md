# Hybrid Anchor OCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a workflow that uses trusted uploaded subtitle timing as the anchor while extracting Korean burned-in subtitles with OCR for higher-fidelity translation.

**Architecture:** The hybrid workflow creates an intermediate `.srt` whose cue timing is copied from the uploaded subtitle and whose text contains Korean OCR plus the uploaded English reference. The existing glossary and subtitle translation jobs then run on that intermediate file with an extra prompt telling the LLM to translate from Korean first and use English only as context/fallback.

**Tech Stack:** Python, yt-dlp, PaddleOCR, existing job runner in `video_translate/web_agent.py`, Vue Agent UI.

---

### Task 1: Hybrid Source Builder

**Files:**
- Create: `video_translate/subtitle/hybrid_ocr.py`
- Create: `hybrid_anchor_ocr_subtitles.py`
- Test: `tests/test_hybrid_anchor_ocr.py`

- [ ] Build an intermediate source SRT from anchor cues and OCR boxes.
- [ ] Preserve cue start/end exactly from the anchor SRT.
- [ ] Write a debug JSON with OCR text, English reference, confidence, and fallback reason.
- [ ] Add a CLI that extracts OCR boxes from an input video and writes `hybrid.source.srt`, `hybrid.debug.json`, and `hybrid.ocr_boxes.json`.

### Task 2: Agent Routing

**Files:**
- Modify: `video_translate/agent_planner.py`
- Modify: `video_translate/web_agent.py`
- Test: `tests/test_agent_planner.py`
- Test: `tests/test_web_agent.py`

- [ ] If there is no target/source subtitle but English manual subtitles exist and the user says embedded subtitles exist, recommend `hybrid_anchor_ocr`.
- [ ] Add an Agent action that downloads the English subtitle and video, runs the hybrid source job, generates glossary, and waits for review.
- [ ] Pass a hybrid translation prompt when translating the intermediate SRT.

### Task 3: UI Labels

**Files:**
- Modify: `frontend/src/components/AgentSessionPanel.vue`

- [ ] Display `hybrid_anchor_ocr` as “英文定轴 + 韩文 OCR”.
- [ ] Make the recommended action label clear that it is slower than pure subtitle translation but more faithful than English-only translation.

### Task 4: Verification

**Commands:**
- `python -m pytest tests/test_hybrid_anchor_ocr.py tests/test_agent_planner.py tests/test_web_agent.py -q`
- `python -m pytest -q`
- `cd frontend && npm run build`
