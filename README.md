# ClipAwesome

Find the moments worth clipping. ClipAwesome analyses a video and **suggests** the time ranges that would make the best short clips, with a transparent explanation of *why* each moment was picked. It never cuts or re-uploads media — it is a suggestion engine.

Three ways in:

| Input | What happens |
|---|---|
| **YouTube link** | Reads captions, "Most replayed" heatmap, chapters, SponsorBlock data and viewer comments, then ranks candidate clips. |
| **Topic** | Searches YouTube for the topic, ranks the videos, deep-analyses the best ones and returns one cross-video list of clip suggestions. |
| **Local file** | Measures audio energy, detects scene cuts, transcribes speech locally (Whisper) and ranks candidate clips. |

A separate **Download** page lists every resolution of a YouTube video with its file size and downloads the one you pick (video + audio merged, or audio only). Download only videos you own, that are Creative Commons, or that you have permission to save.

The **Editor** page trims and crops (9:16, 1:1, 4:5, 16:9, free), rotates/flips, resizes, removes audio and exports MP4, MP3 or GIF, with FFmpeg running on the same machine. Finished downloads open in it with one click.

Two analysis modes:

- **Deterministic** — no LLM, no cloud calls. A weighted, explainable scoring formula over measurable signals. Same input, same output.
- **AI** — the deterministic engine proposes grounded candidates, then an LLM re-ranks them, writes titles/hooks and explains its choice. Works with any OpenAI-compatible endpoint: a **custom gateway** (e.g. `https://llm.maqsoftware.net/v1`), **Gemini**, **Groq** or **NVIDIA NIM**. Timestamps always come from the engine, so they cannot be hallucinated.

## Quick start (Windows / PowerShell)

```powershell
# 1. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[transcribe,dev]"
python -m clipawesome            # API on http://127.0.0.1:8765

# 2. Frontend (new terminal)
cd web
npm install
npm run dev                      # UI on http://localhost:5173
```

Production-style single process: `cd web; npm run build` then `python -m clipawesome` serves the built UI at http://127.0.0.1:8765.

## Documentation

| Doc | Purpose |
|---|---|
| [docs/FEATURES.md](docs/FEATURES.md) | Complete feature catalogue with acceptance criteria |
| [docs/DELIVERABLES.md](docs/DELIVERABLES.md) | Phase plan, deliverables checklist, definition of done |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, module map |
| [docs/SCORING.md](docs/SCORING.md) | Deterministic scoring algorithm and AI re-ranking |
| [docs/API.md](docs/API.md) | REST API contract |
| [docs/UI_DESIGN.md](docs/UI_DESIGN.md) | Design system and screen inventory |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, commands, conventions, troubleshooting |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker image, GitHub Actions deploy to the VM, nginx wiring |

## Tech stack

- **Backend:** Python 3.11+, FastAPI, yt-dlp, PyAV (bundled FFmpeg libs — no system ffmpeg needed), NumPy, OpenAI SDK (for every OpenAI-compatible provider), faster-whisper (optional), httpx.
- **Frontend:** React + TypeScript + Vite + Tailwind CSS, lucide icons.
- **Storage:** local JSON files under `data/` (analyses, settings, uploads, models).
