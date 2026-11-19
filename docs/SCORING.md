# Scoring

The engine (`backend/clipawesome/engine`) is pure and deterministic. It turns a `SourceSignals` bundle into ranked, explained clip suggestions. AI mode re-ranks the engine's candidates; it never invents timestamps.

## 1. Signals → per-second series

The video is divided into 1-second bins. Each available signal becomes a series in `[0, 1]`. Missing signals are `None` and drop out of the weighting.

| Signal | Source | Normalisation |
|---|---|---|
| `heatmap` | YouTube "Most replayed" | Contrast-enhanced: `clip((v − median) / (1 − median), 0, 1)` |
| `audio` | Loudness (dB RMS, 0.5 s hop) | Robust z-score `z = (x − median) / (1.4826·MAD)`, mapped `clip((z + 0.5) / 3.5, 0, 1)` |
| `reactions` | `[Laughter]`, `[Applause]`, `[Cheering]`, `!` sentences, emphatic words | Events convolved with a peak-1 Gaussian (σ = 3 s), saturated `1 − e^{−x}` |
| `comments` | `m:ss` mentions in comments, weight `1 + ln(1 + likes)` | Gaussian σ = 6 s, divided by max, × `min(1, mentions / 5)` confidence |
| `highlight` | SponsorBlock `poi_highlight` | Gaussian σ = 8 s, clipped to 1 |
| `relevance` | BM25 of each sentence vs. focus query / topic (+ AI synonyms) | Sentence score / max, smoothed (σ = 2 s), rescaled to max 1 |
| `pace` | Words per second | 5 s box smoothing, robust z, `clip((z + 1) / 3, 0, 1)` |
| `visual` | Scene cuts | Gaussian σ = 2 s, saturated `1 − e^{−x}` |

Masks: **speech** (bins covered by a sentence) and **excluded** (SponsorBlock sponsor / selfpromo / interaction / intro / outro / preview / filler).

## 2. Units and candidates

- **Units** are sentences. Sentences end on `. ! ?`, on a pause ≥ 0.6 s, or after 15 s. Auto-captions without punctuation therefore segment on pauses.
- Without a transcript, units come from audio pauses (≥ 0.4 s at 10 dB below median) or a 5 s grid.
- **Candidates** are every span `units[i].start → units[j].end` whose duration fits the preset.

| Preset | Min | Target | Max |
|---|---|---|---|
| Shorts | 15 s | 35 s | 60 s |
| Standard | 30 s | 55 s | 90 s |
| Long | 60 s | 110 s | 180 s |

## 3. Window features

For each series: $f = 0.6\cdot\text{mean} + 0.4\cdot\text{peak}$ over the window's bins.

Window-level features (transcript required):

- **hook** — base 0.5; +0.25 if the first sentence is a question; +0.25 for a hook phrase (*"the secret"*, *"biggest mistake"*, *"here's why"*, …); −0.35 if it starts with a dangling conjunction or filler (*and, but, so, um*…); −0.1 if under 3 words.
- **completeness** — mean of *clean start* (previous sentence terminal or pause ≥ 0.6 s → 1, else 0.6) and *clean end* (terminal punctuation → 1, pause ≥ 0.8 s → 0.8, else 0.45).

## 4. Score

$$
\text{base} = \frac{\sum_k w_k f_k}{\sum_k w_k}\quad(\text{available features only})
$$

$$
\text{score} = 100 \cdot \text{base}\cdot(1 - 0.9\,e)\cdot(1 - 0.5\max(0, s - 0.25))\cdot(0.92 + 0.08\,\phi)
$$

- $e$ — excluded fraction of the window
- $s$ — silent fraction (only when a transcript exists)
- $\phi = \exp\!\left(-\left(\frac{d - \text{target}}{0.5(\max-\min)}\right)^2\right)$ — duration fit

Default weights (editable in Settings):

| heatmap | audio | reactions | relevance | comments | highlight | pace | visual | hook | completeness |
|---|---|---|---|---|---|---|---|---|---|
| 0.28 | 0.12 | 0.14 | 0.22 | 0.08 | 0.06 | 0.04 | 0.03 | 0.08 | 0.05 |

## 5. Selection

1. Sort candidates by score.
2. Greedy non-maximum suppression: accept a candidate only if its overlap with every accepted clip is ≤ 20 % of the shorter clip.
3. Stop at `max_clips`.
4. Pad: up to 0.3 s lead and 0.5 s tail, never crossing into neighbouring sentences.

## 6. Explanations

Each clip carries:

- **breakdown** — per feature: value, normalised weight, contribution (points out of 100).
- **reasons** — human sentences with polarity, e.g. *"Replayed more than 96% of the video"*, *"Laughter ×2"*, *"3 viewer comments point here: '12:31 I lost it'"*, *"Mentions 'pricing' ×4"*, *"Opens with a question"*, *"Overlaps a sponsor segment (18%)"*.
- **title** — deterministic: the hook sentence (≤ 80 chars) or chapter title; AI: generated.
- **tags** — top TF-IDF terms of the clip vs. the whole transcript.

## 7. AI re-ranking

1. Engine returns the top 18 non-overlapping candidates (pre-NMS limit raised).
2. The LLM receives video title/channel, focus query and each candidate's ID, time range, engine score and transcript (≤ 1 200 chars).
3. It returns JSON: `{clips: [{id, score, title, hook, reason, tags}]}` — only IDs from the input are accepted.
4. Final score $= \alpha\cdot\text{ai} + (1-\alpha)\cdot\text{engine}$, $\alpha$ = AI weight (default 0.6).
5. Any failure → deterministic result + warning.

Topic discovery in AI mode additionally asks the LLM for extra search queries and synonym keywords (fed into BM25 relevance), and re-ranks search results by topical fit.
