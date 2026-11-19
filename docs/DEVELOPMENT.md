# Development Guide

## Prerequisites

- Python 3.11+ (developed on 3.13)
- Node.js 20+ (developed on 24)
- No system ffmpeg required (PyAV bundles FFmpeg libraries).
- Optional: Deno or Node on `PATH` — yt-dlp uses a JS runtime for full YouTube support. Node is enabled automatically when Deno is absent.

## Setup

```powershell
# backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[transcribe,dev]"

# frontend
cd ..\web
npm install
```

`transcribe` extra installs faster-whisper (local speech-to-text). Without it, local files need a sidecar subtitle and YouTube videos need captions.

## Run

| Task | Command (from repo root) |
|---|---|
| API (dev, auto-reload) | `cd backend; .\.venv\Scripts\python -m clipawesome --reload` |
| UI (dev, proxies `/api` → 8765) | `cd web; npm run dev` |
| Build UI | `cd web; npm run build` |
| Single process (serves built UI) | `cd backend; .\.venv\Scripts\python -m clipawesome` → http://127.0.0.1:8765 |
| Backend tests | `cd backend; .\.venv\Scripts\python -m pytest -q` |
| Type-check UI | `cd web; npx tsc -b` |

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `CLIPAWESOME_DATA` | `<repo>/data` | Data directory |
| `CLIPAWESOME_HOST` | `127.0.0.1` | Bind host |
| `CLIPAWESOME_PORT` | `8765` | Bind port |

## Conventions

- Engine code (`engine/`, `transcript.py`, `text.py`) must stay pure: no network, no file I/O.
- Every new signal: add to `engine/signals.py`, default weight in `config.ScoringWeights`, label in `engine/scoring.py`, slider label in `web/src/pages/Settings.tsx`, and a row in [SCORING.md](SCORING.md).
- Network/source failures become `warnings`, not exceptions, unless the source itself is unusable.
- Keep API models in `models.py` and mirror them in `web/src/lib/types.ts`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Could not connect to YouTube (the network may block it)` | Corporate networks often block `youtube.com` / `youtubei.googleapis.com` at the TLS handshake. Set **Settings → YouTube & network → Proxy** and press *Check YouTube connection*, or use local files. |
| `Sign in to confirm you're not a bot` / 403 from YouTube | Update yt-dlp: `pip install -U "yt-dlp[default]"`. Running from a home network works better than cloud IPs. |
| Captions missing | Video may have none; enable *YouTube audio fallback* and install the `transcribe` extra. |
| First local transcription slow | Whisper model downloads once into `data/models`. Choose `base` or `small` on CPU. |
| AI mode disabled in UI | Configure a provider in Settings and press *Test connection*. For a LiteLLM gateway the key must start with `sk-`. |
| Local video shows "codec can't be previewed" | The browser can't decode that codec (e.g. MPEG-4 Part 2, some MKV/AVI). Suggestions are still valid; MP4/H.264 and WebM preview inline. |
