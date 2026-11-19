# Feature Catalogue

Every deliverable feature, grouped by area. Each has an ID used in commits, tests and the [deliverables checklist](DELIVERABLES.md).

Scope rule: ClipAwesome **suggests** clip ranges. It does not render, cut, or publish clips.

---

## F1 — YouTube link analysis

| ID | Feature | Acceptance criteria |
|---|---|---|
| F1.1 | URL intake | Accepts `watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/` URLs and bare 11-char IDs. Anything else is rejected with a clear message (no arbitrary-site fetching). |
| F1.2 | Metadata | Title, channel, duration, thumbnail, views, upload date, language. |
| F1.3 | Captions transcript | Prefers manual captions in the video language, then original-language auto captions, then English. Parses `json3` (word timings) with `vtt` fallback. |
| F1.4 | Most-replayed heatmap | Uses the heatmap when YouTube exposes it; normalised and contrast-enhanced. |
| F1.5 | Chapters | Chapter titles attached to clips as context; chapter ticks on the timeline. |
| F1.6 | SponsorBlock | Community `poi_highlight` boosts a moment; sponsor / self-promo / interaction / intro / outro / preview / filler segments are penalised. |
| F1.7 | Comment timestamps | Top comments are mined for `m:ss` / `h:mm:ss` mentions, weighted by likes. Configurable (on/off, count). |
| F1.8 | Audience reactions | `[Laughter]`, `[Applause]`, `[Cheering]` tags in captions become reaction events. |
| F1.9 | Audio fallback | If no captions exist and Whisper is installed, the audio track is fetched temporarily, transcribed and measured for loudness, then deleted. Setting: never / when needed / always. |
| F1.10 | Graceful degradation | Any missing signal is skipped with a visible warning; weights re-normalise over the signals that exist. |

## F2 — Topic discovery

| ID | Feature | Acceptance criteria |
|---|---|---|
| F2.1 | Topic search | Searches YouTube for a free-text topic. Uses the YouTube Data API when a key is configured, otherwise yt-dlp search (no key needed). |
| F2.2 | Filters | Min/max duration, exclude live/upcoming, exclude Shorts (too short to clip), optional Creative-Commons-only (Data API only). |
| F2.3 | Video ranking | Deterministic: text relevance (BM25 on title + description) + popularity + clip-friendly length. AI mode: LLM re-ranks titles/descriptions for topical fit. |
| F2.4 | Deep analysis | The top *K* videos run through the full F1 pipeline with the topic as the focus query. |
| F2.5 | Cross-video ranking | One merged clip list ordered by clip score × video relevance, each clip tagged with its source video. |
| F2.6 | Other matches | Non-analysed search results are listed with a one-click "Analyse" action. |
| F2.7 | AI query expansion | In AI mode the LLM expands the topic into extra search queries and synonym keywords. |

## F3 — Local video analysis

| ID | Feature | Acceptance criteria |
|---|---|---|
| F3.1 | Upload | Drag-and-drop or browse; video and audio formats (`mp4 mkv mov webm avi m4v mp3 wav m4a flac ogg opus`). Optional sidecar subtitle (`srt`/`vtt`). |
| F3.2 | Local path | Analyse a file in place by absolute path (avoids copying multi-GB files). |
| F3.3 | Probe | Duration, resolution, fps, audio presence via PyAV. |
| F3.4 | Audio energy | Loudness (dB RMS) every 0.5 s, robust z-scored. |
| F3.5 | Scene cuts | Fast (key-frames) or full (sampled frames) visual change detection; used for timeline and boundary context. |
| F3.6 | Transcription | faster-whisper with word timestamps and VAD; model size and device configurable; sidecar subtitles take priority. |
| F3.7 | Playback | Analysed local media is streamed back to the UI with HTTP range support for seeking; formats the browser can't decode show a clear fallback. |

## F4 — Analysis modes

| ID | Feature | Acceptance criteria |
|---|---|---|
| F4.1 | Deterministic mode | No LLM, no network beyond the source itself. Identical input → identical output. Every clip has a numeric breakdown. |
| F4.2 | AI mode | Engine proposes top-N grounded candidates → LLM picks/re-scores, writes title, hook, reason and tags. Final score blends AI and engine scores (configurable). |
| F4.3 | Providers | All via the OpenAI chat-completions protocol: **Custom** (any OpenAI-compatible base URL, e.g. `https://llm.maqsoftware.net/v1` + `qwen-3.8-27b`), **Gemini**, **Groq**, **NVIDIA NIM**. Unsupported params (`response_format`, `temperature`, `max_tokens`) are relaxed automatically; `<think>` blocks from reasoning models are stripped. |
| F4.4 | Connection test | "Test connection" and "Load models" in Settings work with unsaved form values and return the provider's own error message. |
| F4.5 | Safe fallback | If the LLM fails, results fall back to deterministic with a warning — the job never fails because of AI. |
| F4.6 | Focus query | Optional "what should the clips be about?" text; boosts relevant moments in both modes. |

## F5 — Clip suggestions

| ID | Feature | Acceptance criteria |
|---|---|---|
| F5.1 | Length presets | Shorts 15–60 s, Standard 30–90 s, Long 60–180 s, Custom. Custom takes free-form times of any size (`90`, `1:30`, `2m 30s`, `1h 15m`). An invalid range is never rejected: the edited value snaps to the nearest valid one (min ≤ max − 5 s), ranges longer than the media are fitted to it, and if no sentence-aligned window fits exactly the nearest lengths are used — each adjustment is shown to the user. |
| F5.2 | Clean boundaries | Clips start at a sentence start and end at a sentence end (or a pause when no transcript), with small lead/tail padding that never bleeds into the neighbouring sentence. |
| F5.3 | No overlaps | Non-maximum suppression keeps suggestions distinct. |
| F5.4 | Score 0–100 | Plus per-signal breakdown (value, weight, contribution). |
| F5.5 | Human reasons | e.g. "Replayed more than 94% of the video", "Laughter ×2", "4 viewer comments point here", "Opens with a question". |
| F5.6 | Titles & hooks | Deterministic: first sentence + key terms. AI: generated title and hook line. |
| F5.7 | Transcript excerpt | Full text of the clip range. |

## F6 — Results experience

| ID | Feature | Acceptance criteria |
|---|---|---|
| F6.1 | Player | YouTube embed (IFrame API) or HTML5 video for local media; "Play clip" plays exactly the range and stops. |
| F6.2 | Signal timeline | Composite score area, heatmap line, clip regions, chapter ticks, excluded segments, live playhead; click to seek. |
| F6.3 | Clip list | Ranked cards with score ring, time range, duration, reasons, expandable breakdown and transcript. |
| F6.4 | Transcript panel | Searchable, highlights clip ranges and current sentence, click to seek. |
| F6.5 | Multi-source | Discovery results switch the player to the clip's source video. |
| F6.6 | Export | JSON, CSV, Markdown (with timestamped YouTube links), copy-to-clipboard. |

## F7 — Settings

| ID | Feature | Acceptance criteria |
|---|---|---|
| F7.1 | AI provider config | Provider (custom / gemini / groq / nvidia), base URL, model (with model list from the endpoint), API key (write-only, masked on read), AI weight, temperature, timeout. |
| F7.2 | Analysis defaults | Default mode, preset, max clips, comment mining, visual analysis level. |
| F7.3 | Transcription | Whisper model size, device, compute type, YouTube audio fallback policy. |
| F7.4 | YouTube & network | Optional Data API key, preferred caption languages, outbound **proxy** (http/https/socks5) for restricted networks, and a "Check YouTube connection" button. |
| F7.5 | Scoring weights | Sliders for every signal weight; reset to defaults. |

## F8 — History

| ID | Feature | Acceptance criteria |
|---|---|---|
| F8.1 | Saved analyses | Every completed analysis persists locally and is listed newest-first with thumbnail, type, clip count. |
| F8.2 | Reopen / delete | Open any past result instantly; delete removes it. |

## F9 — Platform

| ID | Feature | Acceptance criteria |
|---|---|---|
| F9.1 | Background jobs | Long work runs off the request thread; UI polls job status with stage + progress. |
| F9.2 | Capabilities | `/api/health` reports what is available (Whisper, AI configured, JS runtime for yt-dlp) and the UI checks YouTube reachability, so it can warn before a job fails. |
| F9.3 | Local-only by default | API binds to `127.0.0.1`; strict CORS; secrets never returned to the browser. |
| F9.4 | Single-process mode | Backend serves the built UI. |

---

## Backlog (post-MVP)

| ID | Idea |
|---|---|
| B1 | Live-chat replay density for streams (YouTube / Twitch VODs). |
| B2 | Semantic (embedding) search for focus queries in deterministic mode with a local embedding model. |
| B3 | Speaker diarization (pyannote) — "clips where guest speaks". |
| B4 | Multimodal AI pass (Gemini video input) for visual-only content (sports, gaming). |
| B5 | Channel watch — auto-analyse new uploads. |
| B6 | Desktop packaging (Tauri) with bundled Python runtime. |
| B7 | Optional export of EDL / Premiere / Resolve XML of the suggested ranges. |
