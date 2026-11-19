# Deliverables & Phase Plan

Checklist of what "done" means for each phase. Feature IDs refer to [FEATURES.md](FEATURES.md).

## Definition of done (applies to every item)

- Works end-to-end from the UI, not just the API.
- Failure paths produce a readable message (job error or warning), never a silent hang.
- Deterministic logic has unit tests; network-dependent code is isolated behind a source module.
- No secrets returned by the API; no arbitrary URL fetching.

## Status summary (2026-11-19)

| Area | Status | Evidence |
|---|---|---|
| Backend engine, sources, API | Done | `pytest` — 53 tests passing |
| Frontend | Done | `tsc` clean, `vite build` OK, verified in browser |
| Local file flow | Verified end-to-end in the UI | Demo file → job → ranked clips with reasons |
| AI providers | Done | Custom / Gemini / Groq / NVIDIA NIM; MAQ LiteLLM gateway reachable (needs an `sk-` key) |
| YouTube flows | Implemented, **not live-verified** | Dev machine's network blocks `youtube.com`; proxy setting added |

---

## Phase 0 — Foundations

- [x] Docs: README, features, deliverables, architecture, scoring, API, UI design, development guide
- [x] Repo layout: `backend/` (Python package `clipawesome`), `web/` (React app), `data/` (runtime, git-ignored)
- [x] Settings persistence + data directories
- [x] Health / capabilities endpoint (F9.2)

## Phase 1 — Deterministic engine

- [x] Transcript parsers: YouTube json3, WebVTT (incl. YouTube rolling auto-captions), SRT, Whisper words (F1.3, F3.6)
- [x] Sentence segmentation (punctuation + pause based) and reaction-tag extraction (F1.8)
- [x] Text relevance: tokeniser, stop-words, light stemming, BM25 (F4.6)
- [x] Signal series: heatmap, audio, reactions, comments, highlight, relevance, pace, visual (F1.4–F1.8, F3.4–F3.5)
- [x] Candidate windows, scoring, penalties, NMS, padding (F5.1–F5.4)
- [x] Reasons + breakdown + deterministic titles (F5.5–F5.7)
- [x] Unit tests for all of the above

## Phase 2 — Sources

- [x] YouTube metadata/captions/heatmap/chapters/comments via yt-dlp (F1.1–F1.7)
- [x] SponsorBlock client (F1.6)
- [x] Audio fallback download + Whisper (F1.9)
- [x] Local probe, loudness, scene cuts via PyAV (F3.3–F3.5)
- [x] faster-whisper transcription with model cache (F3.6)
- [x] Topic search via yt-dlp and YouTube Data API (F2.1–F2.2)
- [x] Outbound proxy + YouTube reachability check (F7.4)

## Phase 3 — Service layer

- [x] Background job manager with stages/progress (F9.1)
- [x] Analysis store + history (F8)
- [x] REST API: analyse YouTube / local upload / local path / discover, jobs, analyses, media streaming, settings, AI test & model list (F9)
- [x] Single-process static UI serving (F9.4)

## Phase 4 — AI mode

- [x] OpenAI-SDK client for custom gateway, Gemini, Groq, NVIDIA NIM with JSON output and param relaxation (F4.3)
- [x] Candidate re-ranking with grounded IDs + blended score (F4.2)
- [x] Topic query expansion + video re-rank (F2.3, F2.7)
- [x] Fallback to deterministic on any AI failure (F4.5)

## Phase 5 — Premium UI

- [x] Design system: dark glass theme, gradient accents, typography, components
- [x] Studio page: YouTube / Topic / Local tabs, mode + preset + focus query, advanced options
- [x] Job progress view with live stages
- [x] Results: player, signal timeline, clip cards, breakdown, transcript, multi-source switching, export (F6)
- [x] History page (F8)
- [x] Settings page incl. provider tiles, model list, weights sliders, network check (F7)

## Phase 6 — Deployment

- [x] Basic-auth gate (`CLIPAWESOME_AUTH_PASSWORD`), open `/api/healthz`, server-path analysis switch (tests in `test_deploy_security.py`)
- [x] Multi-stage `Dockerfile` (web build + Python runtime, non-root, Deno for yt-dlp, health check) and `compose.yaml`
- [x] GitHub Actions deploy on push to `main` (no tests): archive → VM → native build → health gate → rollback
- [x] Joins the nginx container's Docker network automatically; optional vhost install via `CLIPAWESOME_DOMAIN`
- [ ] First deploy to the VM + TLS for the domain

## Phase 7 — Next

- [ ] Live-verify YouTube link + topic flows on a network with YouTube access (or via proxy)
- [ ] Live-verify AI mode with a real key on the MAQ gateway
- [ ] Backlog items B1–B7 as prioritised
- [ ] Desktop packaging

---

## Milestone outputs

| Milestone | Output you can try | Status |
|---|---|---|
| M1 | `pytest` green on engine + parsers | Done |
| M2 | Paste a YouTube link → ranked clips in the UI (deterministic) | Built — needs YouTube network access |
| M3 | Upload a local video → ranked clips with player seeking | Done |
| M4 | Type a topic → clips across multiple videos | Built — needs YouTube network access |
| M5 | Switch to AI mode → titles, hooks, re-ranked results | Built — needs your API key |
