import { ArrowRight, ChevronDown, Cpu, FileVideo, FolderOpen, Gauge, Info, ListChecks, ShieldCheck, Sparkles, Telescope, WandSparkles } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AnalysisTile } from "../components/AnalysisTile";
import { Dropzone } from "../components/Dropzone";
import { TimeInput } from "../components/TimeInput";
import { Badge, Button, Card, Chip, Field, Input, Notice, Segmented, Select, Slider, Toggle, YouTubeMark } from "../components/ui";
import { api } from "../lib/api";
import { useApp } from "../lib/app-context";
import { cx } from "../lib/format";
import { navigate, useRoute } from "../lib/router";
import { formatLength, snapRange } from "../lib/time";
import type { AnalysisSummary, AnalyzeOptions, Mode, Preset } from "../lib/types";

type Tab = "youtube" | "topic" | "local";

const PRESETS: { value: Preset; label: string; range: string }[] = [
  { value: "shorts", label: "Shorts", range: "15–60s" },
  { value: "standard", label: "Standard", range: "30–90s" },
  { value: "long", label: "Long", range: "1–3 min" },
  { value: "custom", label: "Custom", range: "" },
];

const DURATIONS = {
  any: { label: "Any length", min: 60, max: 14400 },
  short: { label: "1–15 min", min: 60, max: 900 },
  medium: { label: "3–60 min", min: 180, max: 3600 },
  long: { label: "20 min+", min: 1200, max: 14400 },
} as const;

const YT_LIKE = /(youtube\.com\/(watch|shorts|live|embed)|youtu\.be\/)|^[A-Za-z0-9_-]{11}$/;

function Feature({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
      <div className="mb-2.5 flex size-8 items-center justify-center rounded-lg bg-white/[0.05] text-accent-soft ring-1 ring-white/[0.06]">{icon}</div>
      <div className="text-[13.5px] font-medium text-fg">{title}</div>
      <p className="mt-1 text-[12.5px] leading-relaxed text-fg-3">{body}</p>
    </div>
  );
}

export function Studio() {
  const { health, youtube } = useApp();
  const { params } = useRoute();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "youtube");
  const [mode, setMode] = useState<Mode>("deterministic");
  const [preset, setPreset] = useState<Preset>("standard");
  const [minLen, setMinLen] = useState(20);
  const [maxLen, setMaxLen] = useState(75);
  const [lenNote, setLenNote] = useState<string | null>(null);
  const [fileLength, setFileLength] = useState<number | null>(null);
  const [maxClips, setMaxClips] = useState(8);
  const [includeComments, setIncludeComments] = useState(true);
  const [query, setQuery] = useState("");
  const [url, setUrl] = useState(params.get("url") ?? "");
  const [topic, setTopic] = useState("");
  const [searchLimit, setSearchLimit] = useState(15);
  const [analyzeTop, setAnalyzeTop] = useState(3);
  const [durations, setDurations] = useState<keyof typeof DURATIONS>("medium");
  const [creativeCommons, setCreativeCommons] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [subtitle, setSubtitle] = useState<File | null>(null);
  const [usePathChoice, setUsePath] = useState(false);
  const [path, setPath] = useState("");
  const [subPath, setSubPath] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<AnalysisSummary[]>([]);

  const aiReady = !!health?.capabilities.ai_configured;
  const hasApiKey = !!health?.capabilities.youtube_api_key;
  const pathAllowed = health?.capabilities.local_path !== false;
  const usePath = usePathChoice && pathAllowed;

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setMode(s.default_mode === "ai" && s.ai.configured ? "ai" : "deterministic");
        setPreset(s.default_preset);
        setMaxClips(s.default_max_clips);
        setIncludeComments(s.include_comments);
      })
      .catch(() => {});
    api
      .analyses()
      .then((r) => setRecent(r.slice(0, 4)))
      .catch(() => {});
  }, []);

  useEffect(() => setError(null), [tab]);

  // Read the length of a picked local file in the browser so custom ranges can be capped before upload.
  useEffect(() => {
    setFileLength(null);
    if (!file) return;
    const url = URL.createObjectURL(file);
    const el = document.createElement(file.type.startsWith("audio") ? "audio" : "video");
    el.preload = "metadata";
    el.onloadedmetadata = () => Number.isFinite(el.duration) && el.duration > 0 && setFileLength(el.duration);
    el.src = url;
    return () => {
      el.removeAttribute("src");
      URL.revokeObjectURL(url);
    };
  }, [file]);

  const mediaLength = tab === "local" && !usePath ? fileLength : null;

  const applyRange = (min: number, max: number, edited: "min" | "max") => {
    const r = snapRange(min, max, edited, mediaLength);
    setMinLen(r.min);
    setMaxLen(r.max);
    setLenNote(r.note);
  };

  useEffect(() => {
    if (mediaLength && maxLen > mediaLength) applyRange(minLen, maxLen, "max");
  }, [mediaLength]);

  const canSubmit =
    tab === "youtube" ? YT_LIKE.test(url.trim()) : tab === "topic" ? topic.trim().length >= 2 : usePath ? path.trim().length > 3 : !!file;

  const submit = async () => {
    if (!canSubmit || busy) return;
    setBusy(true);
    setError(null);
    const opts: AnalyzeOptions = {
      mode,
      preset,
      max_clips: maxClips,
      include_comments: includeComments,
      query: tab !== "topic" && query.trim() ? query.trim() : null,
      ...(preset === "custom" ? { min_len: minLen, max_len: maxLen } : {}),
    };
    try {
      let res: { job_id: string };
      if (tab === "youtube") res = await api.analyzeYouTube(url.trim(), opts);
      else if (tab === "topic")
        res = await api.discover({
          ...opts,
          topic: topic.trim(),
          search_limit: searchLimit,
          analyze_top: analyzeTop,
          min_duration: DURATIONS[durations].min,
          max_duration: DURATIONS[durations].max,
          creative_commons: creativeCommons,
        });
      else if (usePath) res = await api.analyzeLocalPath(path.trim(), subPath.trim() || null, opts);
      else res = await api.analyzeLocal(file!, subtitle, opts);
      navigate(`job/${res.job_id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const tabs = [
    { value: "youtube" as const, label: "YouTube link", icon: <YouTubeMark className="h-3.5 w-5" /> },
    { value: "topic" as const, label: "Topic", icon: <Telescope className="size-4" /> },
    { value: "local" as const, label: "Local file", icon: <FileVideo className="size-4" /> },
  ];

  return (
    <div className="mx-auto max-w-[940px] px-5 pb-16 pt-10 md:px-8 md:pt-14">
      <header className="mb-9 animate-fade-up text-center">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1 text-[12px] text-fg-2">
          <span className="size-1.5 rounded-full bg-accent" /> Explainable clip discovery · Deterministic + AI
        </div>
        <h1 className="text-[34px] font-semibold leading-[1.1] tracking-tight text-fg md:text-[46px]">
          Find the moments <span className="text-accent-soft">worth clipping.</span>
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-[15px] leading-relaxed text-fg-2">
          Paste a YouTube link, describe a topic, or drop a local file. ClipAwesome ranks the best clip ranges and shows exactly why each one works.
        </p>
      </header>

      {youtube && !youtube.ok && tab !== "local" && (
        <div className="mb-4">
          <Notice
            action={
              <a href="#/settings" className="shrink-0 text-[12.5px] font-medium text-warn hover:underline">
                Network settings
              </a>
            }
          >
            YouTube isn't reachable from this machine right now. Analyses of links and topics will fail until it is — set a proxy in Settings, or use a local file.
          </Notice>
        </div>
      )}

      <Card className="animate-fade-up p-2 shadow-[0_30px_80px_-40px_rgba(0,0,0,0.8)]">
        <div className="p-1">
          <Segmented full value={tab} onChange={setTab} options={tabs} />
        </div>

        <div className="space-y-6 p-4 md:p-6">
          {tab === "youtube" && (
            <div className="relative">
              <YouTubeMark className="pointer-events-none absolute left-4 top-1/2 h-4 w-6 -translate-y-1/2" />
              <input
                autoFocus
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="Paste a YouTube link — youtube.com/watch?v=…, youtu.be/…, /shorts/…"
                className="h-14 w-full rounded-2xl border border-white/[0.09] bg-black/25 pl-14 pr-4 text-[15px] text-fg outline-none transition placeholder:text-fg-3 focus:border-violet/60 focus:ring-4 focus:ring-violet/15"
              />
            </div>
          )}

          {tab === "topic" && (
            <div className="space-y-5">
              <div className="relative">
                <Telescope className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-fg-3" />
                <input
                  autoFocus
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submit()}
                  placeholder="What do you want clips about? e.g. “startup pricing mistakes”"
                  className="h-14 w-full rounded-2xl border border-white/[0.09] bg-black/25 pl-12 pr-4 text-[15px] text-fg outline-none transition placeholder:text-fg-3 focus:border-violet/60 focus:ring-4 focus:ring-violet/15"
                />
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                <Field label="Videos to search">
                  <Select value={searchLimit} onChange={(e) => setSearchLimit(Number(e.target.value))}>
                    {[10, 15, 25, 40].map((n) => (
                      <option key={n} value={n}>
                        {n} results
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Deep-analyse the best">
                  <Select value={analyzeTop} onChange={(e) => setAnalyzeTop(Number(e.target.value))}>
                    {[1, 2, 3, 4, 5, 6].map((n) => (
                      <option key={n} value={n}>
                        {n} video{n > 1 ? "s" : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Video length">
                  <Select value={durations} onChange={(e) => setDurations(e.target.value as keyof typeof DURATIONS)}>
                    {Object.entries(DURATIONS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v.label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <Toggle
                checked={creativeCommons}
                onChange={setCreativeCommons}
                disabled={!hasApiKey}
                label="Creative Commons videos only"
                description={hasApiKey ? "Only suggest videos licensed for reuse." : "Requires a YouTube Data API key (Settings → YouTube)."}
              />
            </div>
          )}

          {tab === "local" && (
            <div className="space-y-4">
              {usePath ? (
                <div className="grid gap-4">
                  <Field label="Media file path" hint="Absolute path on this machine. The file is analysed in place — nothing is copied.">
                    <div className="relative">
                      <FolderOpen className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-fg-3" />
                      <Input className="pl-10" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\Videos\podcast-episode-42.mp4" />
                    </div>
                  </Field>
                  <Field label="Subtitle path (optional)">
                    <Input value={subPath} onChange={(e) => setSubPath(e.target.value)} placeholder="C:\Videos\podcast-episode-42.srt" />
                  </Field>
                </div>
              ) : (
                <Dropzone file={file} subtitle={subtitle} onFile={setFile} onSubtitle={setSubtitle} />
              )}
              {pathAllowed && (
                <button type="button" onClick={() => setUsePath((v) => !v)} className="text-[12.5px] font-medium text-accent-soft hover:text-white">
                  {usePath ? "Upload a file instead" : "Large file? Use a file path instead"}
                </button>
              )}
              {!health?.capabilities.whisper && (
                <Notice tone="info">Local transcription isn't installed — add a subtitle file for speech-aware results, or install the <code>transcribe</code> extra.</Notice>
              )}
            </div>
          )}

          <div className="h-px bg-white/[0.06]" />

          <div className="grid gap-6 md:grid-cols-2">
            <Field
              label="Analysis mode"
              hint={
                mode === "ai"
                  ? "Engine proposes grounded candidates; your LLM re-ranks them and writes titles & hooks."
                  : "Pure signal scoring. No LLM, fully repeatable, every score explained."
              }
            >
              <Segmented
                value={mode}
                onChange={setMode}
                options={[
                  { value: "deterministic", label: "Deterministic", icon: <Cpu className="size-4" /> },
                  {
                    value: "ai",
                    label: "AI",
                    icon: <Sparkles className="size-4" />,
                    disabled: !aiReady,
                    hint: aiReady ? undefined : "Configure an AI provider in Settings",
                  },
                ]}
              />
              {!aiReady && (
                <a href="#/settings" className="ml-3 text-[12px] text-accent-soft hover:underline">
                  Set up AI →
                </a>
              )}
            </Field>
            <Field label="Clip length">
              <div className="flex flex-wrap gap-2">
                {PRESETS.map((p) => (
                  <Chip key={p.value} active={preset === p.value} onClick={() => setPreset(p.value)}>
                    {p.label}
                    {p.range && <span className="text-fg-3">{p.range}</span>}
                  </Chip>
                ))}
              </div>
            </Field>
          </div>

          {preset === "custom" && (
            <div className="animate-fade-up space-y-3 rounded-xl border border-white/[0.06] bg-ink-900 p-4">
              <div className="grid gap-4 md:grid-cols-2">
                <TimeInput label="Minimum clip length" value={minLen} onCommit={(v) => applyRange(v, maxLen, "min")} />
                <TimeInput label="Maximum clip length" value={maxLen} onCommit={(v) => applyRange(minLen, v, "max")} />
              </div>
              <p className="text-[12px] leading-relaxed text-fg-3">
                Any length works — plain numbers are seconds, or write <span className="text-fg-2">1:30</span>, <span className="text-fg-2">2m 30s</span>,{" "}
                <span className="text-fg-2">1h 15m</span>. {mediaLength ? `This file is ${formatLength(mediaLength)} long, so lengths are capped to it.` : "Ranges longer than the video are fitted to it automatically."}
              </p>
              {lenNote && (
                <Notice tone="info" icon={<Info className="size-4" />}>
                  {lenNote}
                </Notice>
              )}
            </div>
          )}

          {tab !== "topic" && (
            <Field label="Focus (optional)" hint="Boost moments about something specific. Leave empty to find the most engaging moments overall.">
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. pricing advice · the product demo · funniest moments" />
            </Field>
          )}

          <div>
            <button type="button" onClick={() => setAdvanced((v) => !v)} className="inline-flex items-center gap-1.5 text-[13px] text-fg-2 hover:text-fg">
              <ChevronDown className={cx("size-4 transition-transform", advanced && "rotate-180")} /> Advanced options
            </button>
            {advanced && (
              <div className="mt-4 grid animate-fade-up gap-6 rounded-xl border border-white/[0.06] bg-black/15 p-4 md:grid-cols-2">
                <Slider label="Maximum suggestions" value={maxClips} min={1} max={20} onChange={setMaxClips} />
                {tab !== "local" && (
                  <Toggle checked={includeComments} onChange={setIncludeComments} label="Mine viewer comments" description="Timestamps people mention (e.g. “12:31 😂”) become evidence." />
                )}
              </div>
            )}
          </div>

          {error && <Notice tone="neg">{error}</Notice>}

          <div className="flex flex-col-reverse items-stretch justify-between gap-4 md:flex-row md:items-center">
            <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-3">
              <Badge tone={mode === "ai" ? "violet" : "neutral"} icon={mode === "ai" ? <Sparkles className="size-3" /> : <Cpu className="size-3" />}>
                {mode === "ai" ? "AI re-ranking" : "Deterministic"}
              </Badge>
              <span>
                up to {maxClips} clips · {preset === "custom" ? `${formatLength(minLen)} – ${formatLength(maxLen)}` : PRESETS.find((p) => p.value === preset)?.range}
              </span>
            </div>
            <Button variant="primary" size="lg" loading={busy} disabled={!canSubmit} onClick={submit} icon={<WandSparkles className="size-[18px]" />}>
              Find clips <ArrowRight className="size-4" />
            </Button>
          </div>
        </div>
      </Card>

      {recent.length > 0 && (
        <section className="mt-12">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold text-fg">Recent analyses</h2>
            <a href="#/history" className="text-[12.5px] text-fg-2 hover:text-fg">
              View all →
            </a>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {recent.map((r) => (
              <AnalysisTile key={r.id} item={r} />
            ))}
          </div>
        </section>
      )}

      <section className="mt-12 grid gap-3 md:grid-cols-3">
        <Feature icon={<Gauge className="size-4" />} title="Signals, not guesses" body="Most-replayed heatmap, reactions, comment timestamps, audio energy, scene cuts and topic relevance." />
        <Feature icon={<ListChecks className="size-4" />} title="Every score explained" body="Each suggestion shows its evidence and a point-by-point breakdown you can tune in Settings." />
        <Feature icon={<ShieldCheck className="size-4" />} title="AI that can't invent timestamps" body="The LLM only chooses among engine candidates, so every range is grounded in real sentence boundaries." />
      </section>
    </div>
  );
}
