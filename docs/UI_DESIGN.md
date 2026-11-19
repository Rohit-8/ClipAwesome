# UI Design

Goal: a calm, premium, focused tool. Dark canvas, glass surfaces, one vivid gradient accent used sparingly for primary actions and scores.

## Design tokens

| Token | Value | Use |
|---|---|---|
| `--color-ink-950` | `#07080c` | App background |
| `--color-ink-900` | `#0c0e14` | Sidebar |
| `--color-ink-800` | `#12151d` | Raised surfaces |
| Surface glass | `white / 3%` + `border white / 7%` + blur | Cards, panels |
| Text primary | `#eef0f6` | |
| Text secondary | `#9aa1b4` | |
| Text muted | `#5e6578` | |
| Accent gradient | `#8b5cf6 → #6366f1 → #22d3ee` | Primary button, score ring, brand mark |
| Positive | `#34d399` | Positive reasons |
| Negative | `#f87171` | Penalties |
| Warning | `#fbbf24` | Warnings |
| Radius | 10 / 14 / 20 px | Inputs / cards / hero |
| Font | Inter, system fallback; tabular numerals for times & scores | |

Motion: 150–250 ms ease-out on hover/focus; progress shimmer on running jobs; no gratuitous animation.

## Layout

```
┌──────────┬──────────────────────────────────────────────┐
│ Sidebar  │  Page header (title · context actions)       │
│  brand   │                                              │
│  Studio  │  Content                                     │
│  History │                                              │
│  Settings│                                              │
│          │                                              │
│ status   │                                              │
└──────────┴──────────────────────────────────────────────┘
```

## Screens

1. **Studio** — hero headline, segmented source tabs (YouTube link · Topic · Local file), mode switch (Deterministic / AI), preset chips, optional focus query, collapsible advanced options, primary "Find clips" button. Topic tab adds search size, deep-analyse count, duration range, Creative-Commons toggle. Local tab has a drag-and-drop zone + optional subtitle + "use file path" alternative.
2. **Job progress** — source title, animated progress bar, stage checklist with timestamps, cancel-safe (job continues server-side), auto-navigates on success, readable error on failure.
3. **Results** —
   - Header: thumbnail, title, channel, duration, mode badge, signal chips, warnings, export menu.
   - Left column: player → signal timeline (composite area + heatmap line + clip regions + chapter ticks + excluded hatching + playhead) → transcript panel.
   - Right column: ranked clip cards (score ring, title, time range, duration, top reasons, tags; expand → breakdown bars + transcript; actions: play clip, copy link, copy range).
   - Discovery: "Analysed videos" strip with relevance; clip cards show source thumbnail; "Other matches" list with Analyse buttons.
4. **History** — cards grid with thumbnail, kind icon, title, date, clip count, top score; open / delete.
5. **Settings** — sections: AI provider (with Test connection), Analysis defaults, Transcription, YouTube, Scoring weights (sliders + reset). Sticky save bar when dirty.

## Components

`Button` (primary gradient / secondary / ghost / danger), `SegmentedControl`, `Chip`, `Toggle`, `Slider`, `Field` + `Input` / `Select` / `Textarea`, `Card`, `Badge`, `ScoreRing`, `ProgressBar`, `Dropzone`, `Timeline`, `ClipCard`, `TranscriptPanel`, `Player` (YouTube / HTML5 behind one imperative handle), `Toast`, `EmptyState`.

## Accessibility

Visible focus rings, ≥ 4.5:1 contrast for body text, keyboard-operable controls, `aria-label` on icon-only buttons, reduced-motion respected.
