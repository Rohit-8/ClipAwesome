# REST API

Base URL: `http://127.0.0.1:8765/api`. All bodies are JSON unless noted. Long-running work returns `202 {"job_id": "..."}`; poll the job.

**Auth:** when `CLIPAWESOME_AUTH_PASSWORD` is set (always, in deployments) every route except `GET /api/healthz` requires HTTP Basic auth (`CLIPAWESOME_AUTH_USER`, default `admin`); otherwise `401`.

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
| GET | `/healthz` | `{status: "ok"}` — unauthenticated liveness probe (container health check) |
| GET | `/health` | `{status, version, capabilities: {pyav, whisper, js_runtime, ai_configured, youtube_api_key, local_path, performance: low\|balanced\|high, performance_auto}}` |
| GET | `/settings` | `Settings` with secrets masked (`"••••abcd"`, and the proxy password as `user:••••@host`) and `has_*` flags |
| GET | `/settings/defaults` | Default `Settings` |
| PUT | `/settings` | Saves and returns masked `Settings`. A masked or empty secret keeps the stored value (a masked proxy keeps its stored password); send `"__clear__"` to delete it. New fields: `performance: auto\|low\|balanced\|high`, `focused_transcription: auto\|on\|off`, `cleanup_days` (1–90), `cache_limit_gb`. |
| POST | `/ai/test` | `{ok, message, model}` — sends a tiny JSON prompt. Body may carry unsaved AI settings (`provider`, `base_url`, `model`, `api_key`…); a masked key uses the stored one. |
| POST | `/ai/models` | `{ok, models, message?}` — lists models from the endpoint's `/models` (same body as `/ai/test`) |
| GET | `/ai/providers` | `{custom|gemini|groq|nvidia: {base_url, model}}` defaults |
| POST | `/network/youtube` | `{ok, message}` — checks YouTube reachability; optional body `{proxy}` to test an unsaved proxy (a masked password uses the stored one) |
| GET | `/system` | `{cpus, ram_gb, available_ram_gb, recommended, setting, active: Profile, profiles: {low, balanced, high}}`. `Profile` = `{name, heavy_slots, threads, whisper_model, visual_analysis, x264_preset, chunk_sec, focused_over_sec}` (`null` = use the user's setting; `focused_over_sec: 0` = always focused, `null` = never). |
| GET | `/storage` | `{categories: [{key, label, bytes, files, auto_cleanup}], total_bytes, disk_free_bytes, disk_total_bytes, cleanup_days, cache_limit_gb, data_dir}` |
| POST | `/storage/cleanup` | `{freed: {category: bytes}, freed_bytes, usage}` — removes temporary files, finished exports, audio preview copies and YouTube playback copies now. Downloads and editor sources are never removed. |
| GET | `/diagnostics` | `{ok, checks: [{key, label, status: ok\|info\|warn\|fail, detail, hint}]}` — FFmpeg, GPU encoder, captions (libass + fonts test render), Whisper, yt-dlp, JS runtime, YouTube reachability, AI provider, disk space, machine/profile, data folder. |

### Analysis jobs

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/analyze/youtube` | `{url, ...AnalyzeOptions}` | URL must be a YouTube video URL or ID |
| POST | `/analyze/local` | multipart: `file`, optional `subtitle`, `options` (JSON string of `AnalyzeOptions`) | Upload |
| POST | `/analyze/local-path` | `{path, subtitle_path?, ...AnalyzeOptions}` | Absolute path to an existing media file. `403` when `CLIPAWESOME_ALLOW_LOCAL_PATH=false` (default in Docker). |
| POST | `/discover` | `{topic, search_limit=15, analyze_top=3, min_duration=180, max_duration=7200, creative_commons=false, ...AnalyzeOptions}` | |
| GET | `/jobs/{job_id}` | — | `Job` |
| GET | `/jobs` | — | Recent jobs |
| POST | `/jobs/{job_id}/retry` | — | `202 Job` — a new job with the same request. `409` while the original is still active or when it has no saved request, `410` when its uploaded file is gone. |

`Job`:

```json
{
  "id": "j_…", "kind": "youtube", "status": "running",
  "progress": 0.42, "stage": "Fetching captions",
  "stages": [{"name": "Reading video metadata", "at": "…"}],
  "error": null, "result_id": null, "created_at": "…", "title": "…", "retryable": true
}
```

`status`: `queued | running | done | error | interrupted`. Jobs are saved to `data/jobs/`; jobs that were running when the server stopped come back as `interrupted` and can be retried.

### Results

| Method | Path | Response |
|---|---|---|
| GET | `/analyses` | `[AnalysisSummary]` newest first |
| GET | `/analyses/{id}` | `Analysis` |
| DELETE | `/analyses/{id}` | `204` |
| PATCH | `/analyses/{id}/clips/{clip_id}` | Body `{review: "approved"\|"rejected"\|null}` → `{id, review}`; saved on the clip (`clip.review`). |
| POST | `/analyses/{id}/sources/{source_id}/edit-source` | Body `{quality: 360\|480\|720\|1080\|1440\|2160}` (default 720) → `{status: "ready", source: EditSource}` or `{status: "downloading", download: DownloadTask}` (poll `/downloads/{id}`, then call again). Local files are ready at once; a YouTube download at this quality or better is reused. |
| POST | `/analyses/{id}/export` | `BatchOptions` — `{clip_ids: […], download_quality: 720, frame: original\|9:16\|1:1, captions: off\|bold\|classic\|boxed, normalize: true, quality: high\|balanced\|small}` → `202 Batch` |
| GET | `/export-batches/{id}` | `Batch` — `{id, analysis_id, status: preparing\|done\|error, stage, total, export_ids, errors}`. Each clip becomes a normal editor export (`/editor/exports/{id}`) named `NN title [start to end].mp4`. Kept in memory only. |
| GET | `/media/{media_id}` | Media stream (supports `Range`) for local sources |
| GET | `/media/{media_id}/preview-audio` | Cached MP3 copy of the audio for browsers that can't decode the original codec |
| GET / POST | `/youtube/{video_id}/preview` | `PreviewStatus` — `{video_id, status: none\|downloading\|ready\|error, progress, size, audio_codec, reused_download, error}`. POST starts fetching a 360p playable copy through the server (proxy); a finished MP4/WebM download of the same video is reused. Used when YouTube's embedded player can't load in the browser. |
| GET | `/youtube/{video_id}/preview/media` / `/preview/audio` | The playable copy (supports `Range`) / its cached MP3 audio |

### YouTube downloads

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/download/formats` | `{url}` | `DownloadInfo` — `{video_id, url, title, channel, duration, thumbnail, license, creative_commons, ffmpeg, options: [{id, kind: video\|audio, label, quality, width, height, fps, hdr, ext, codec, bitrate_kbps, size, approx, available, reason}]}`. `502` with a readable message when YouTube fails. |
| POST | `/downloads` | `{url, option_id}` | `202 DownloadTask` |
| GET | `/downloads` | — | `[DownloadTask]` newest first |
| GET | `/downloads/{id}` | — | `DownloadTask` — `{id, title, label, ext, status: queued\|downloading\|merging\|done\|error\|cancelled, stage, progress, downloaded_bytes, total_bytes, speed, eta, file_name, file_size, error, …}` |
| POST | `/downloads/{id}/cancel` | — | `DownloadTask` |
| DELETE | `/downloads/{id}` | — | `204`; `409` while still active |
| GET | `/downloads/{id}/file` | — | The file as an attachment |

### Editor

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/editor/sources/upload` | multipart `file` | `EditSource` — `{id, name, kind: upload\|download, download_id, duration, has_video, has_audio, width, height, rotation: 0\|90\|180\|270, fps, size, created_at}` |
| POST | `/editor/sources/from-download` | `{download_id}` | `EditSource` (re-uses the downloaded file) |
| GET | `/editor/sources` | — | `[EditSource]` newest first |
| GET | `/editor/sources/{id}` | — | `EditSource` |
| GET | `/editor/sources/{id}/media` | — | Media stream (supports `Range`) for the preview |
| GET | `/editor/sources/{id}/preview-audio` | — | MP3 copy of the audio (generated once, cached) for browsers that can't decode the original codec |
| DELETE | `/editor/sources/{id}` | — | `204`; `409` while an export from it runs |
| POST | `/editor/exports` | `{source_id, start, end, crop?: {x,y,w,h} (0–1), rotate: 0\|90\|180\|270, flip_h, flip_v, height?: 2160\|1440\|1080\|720\|480\|360, mute, format: mp4\|mp3\|gif, quality: high\|balanced\|small, fast, normalize?: bool, captions?: {style: bold\|classic\|boxed, position: bottom\|center, analysis_id?, analysis_source?}, title?}` | `202 ExportTask`; `400` with a readable reason (e.g. GIF > 60 s, fast cut with crop/captions/normalize, captions on non-MP4). Captions use the analysis transcript when `analysis_id` is given, otherwise Whisper transcribes the range. `normalize` = EBU R128 loudness to −14 LUFS, true peak −1.5 dB. `title` names the file. |
| POST | `/editor/merges` | `{clips: [{source_id, start, end}] (2–20), frame: first\|16:9\|9:16\|1:1, fit: pad\|crop, resolution?: short side 2160…360, mute, format: mp4\|mp3, quality, fast, normalize?}` | `202 ExportTask`; `400` with a readable reason (e.g. fast merge of clips in different formats, fast merge with normalize) |
| GET | `/editor/gpu` | — | `{enabled, ffmpeg, encoder: {codec, name} \| null, tried: [{codec, name, ok, detail}]}` — detects on first call when GPU acceleration is on |
| POST | `/editor/gpu/detect` | — | Same, re-running the test encodes |
| GET | `/editor/exports` / `/editor/exports/{id}` | — | `ExportTask` — `{id, source_ids, source_name, label, format, encoder: "GPU · …"\|"CPU · x264"\|null, status: queued\|running\|done\|error\|cancelled, stage (e.g. "Transcribing the clip for captions…", "Waiting for another heavy task…"), progress, speed, eta, file_name, file_size, error, …}` |
| POST | `/editor/exports/{id}/cancel` | — | `ExportTask` |
| DELETE | `/editor/exports/{id}` | — | `204`; `409` while running |
| GET | `/editor/exports/{id}/file` | — | The file as an attachment |

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
