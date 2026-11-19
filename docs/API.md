# REST API

Base URL: `http://127.0.0.1:8765/api`. All bodies are JSON unless noted. Long-running work returns `202 {"job_id": "..."}`; poll the job.

## Common analysis options (`AnalyzeOptions`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `mode` | `"deterministic" \| "ai"` | settings default | AI requires a configured provider |
| `preset` | `"shorts" \| "standard" \| "long" \| "custom"` | settings default | |
| `min_len`, `max_len` | number (s, ≥ 0) | from preset | Used when `preset = custom`. No upper limit; swapped if reversed, widened to a 5 s gap, and fitted to each video's duration (the range actually used is returned on the `Analysis`). |
| `query` | string | `null` | Focus: "what should clips be about?" |
| `max_clips` | int 1–30 | settings default | |
| `include_comments` | bool | settings default | YouTube only |

## Endpoints

### System

| Method | Path | Response |
|---|---|---|
| GET | `/health` | `{status, version, capabilities: {pyav, whisper, js_runtime, ai_configured, youtube_api_key}}` |
| GET | `/settings` | `Settings` with secrets masked (`"••••abcd"`) and `has_*` flags |
| GET | `/settings/defaults` | Default `Settings` |
| PUT | `/settings` | Saves and returns masked `Settings`. A masked or empty secret keeps the stored value; send `"__clear__"` to delete it. |
| POST | `/ai/test` | `{ok, message, model}` — sends a tiny JSON prompt. Body may carry unsaved AI settings (`provider`, `base_url`, `model`, `api_key`…); a masked key uses the stored one. |
| POST | `/ai/models` | `{ok, models, message?}` — lists models from the endpoint's `/models` (same body as `/ai/test`) |
| GET | `/ai/providers` | `{custom|gemini|groq|nvidia: {base_url, model}}` defaults |
| POST | `/network/youtube` | `{ok, message}` — checks YouTube reachability; optional body `{proxy}` to test an unsaved proxy |

### Analysis jobs

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/analyze/youtube` | `{url, ...AnalyzeOptions}` | URL must be a YouTube video URL or ID |
| POST | `/analyze/local` | multipart: `file`, optional `subtitle`, `options` (JSON string of `AnalyzeOptions`) | Upload |
| POST | `/analyze/local-path` | `{path, subtitle_path?, ...AnalyzeOptions}` | Absolute path to an existing media file |
| POST | `/discover` | `{topic, search_limit=15, analyze_top=3, min_duration=180, max_duration=7200, creative_commons=false, ...AnalyzeOptions}` | |
| GET | `/jobs/{job_id}` | — | `Job` |
| GET | `/jobs` | — | Recent jobs |

`Job`:

```json
{
  "id": "j_…", "kind": "youtube", "status": "running",
  "progress": 0.42, "stage": "Fetching captions",
  "stages": [{"name": "Reading video metadata", "at": "…"}],
  "error": null, "result_id": null, "created_at": "…", "title": "…"
}
```

`status`: `queued | running | done | error`.

### Results

| Method | Path | Response |
|---|---|---|
| GET | `/analyses` | `[AnalysisSummary]` newest first |
| GET | `/analyses/{id}` | `Analysis` |
| DELETE | `/analyses/{id}` | `204` |
| GET | `/media/{media_id}` | Media stream (supports `Range`) for local sources |

`Analysis` (abridged):

```json
{
  "id": "a_…", "kind": "youtube|local|discover", "mode": "deterministic|ai",
  "preset": "standard", "min_len": 30, "max_len": 90, "query": null,
  "created_at": "…", "elapsed_sec": 12.4,
  "sources": [{
    "id": "s1", "platform": "youtube", "video_id": "…", "url": "…", "title": "…",
    "channel": "…", "duration": 1834.0, "thumbnail": "…", "view_count": 123,
    "media_id": null, "transcript_source": "auto-captions",
    "signals": ["heatmap", "reactions", "comments", "relevance"],
    "chapters": [{"start": 0, "end": 120, "title": "Intro"}],
    "relevance": 0.81
  }],
  "clips": [{
    "id": "c1", "rank": 1, "source_id": "s1",
    "start": 731.2, "end": 778.9, "duration": 47.7, "score": 82.4,
    "engine_score": 78.1, "ai_score": 85.0,
    "title": "…", "hook": "…", "transcript": "…", "chapter": "…", "tags": ["…"],
    "reasons": [{"text": "Replayed more than 96% of the video", "signal": "heatmap", "polarity": "pos"}],
    "breakdown": [{"signal": "heatmap", "label": "Most replayed", "value": 0.93, "weight": 0.26, "contribution": 24.2}]
  }],
  "timelines": {"s1": {"bin_sec": 3, "series": {"composite": [], "heatmap": []}, "markers": {"excluded": [], "highlights": [], "reactions": [], "scene_cuts": []}}},
  "transcripts": {"s1": [{"start": 0.0, "end": 3.2, "text": "…"}]},
  "other_results": [],
  "warnings": ["No 'Most replayed' data for this video"]
}
```

## Errors

`4xx` → `{"detail": "human readable message"}`. Job failures surface as `status: "error"` with `error` text.
