import {
  ArrowDownWideNarrow,
  ArrowLeft,
  ChevronDown,
  Clock3,
  Cpu,
  Download,
  ExternalLink,
  FileJson,
  FileSpreadsheet,
  FileText,
  ListOrdered,
  Search,
  Sparkles,
  TriangleAlert,
  WandSparkles,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ClipCard } from "../components/ClipCard";
import type { PlayerHandle } from "../components/Player";
import { Player } from "../components/Player";
import { Thumb } from "../components/Thumb";
import { Timeline } from "../components/Timeline";
import { useToast } from "../components/Toast";
import { TranscriptPanel } from "../components/TranscriptPanel";
import { Badge, Button, Card, EmptyState, SectionTitle, Segmented } from "../components/ui";
import { api } from "../lib/api";
import { download, slug, toCSV, toJSON, toMarkdown } from "../lib/exporters";
import { cx, fmtCount, fmtDuration, relativeTime } from "../lib/format";
import { navigate } from "../lib/router";
import { formatLength } from "../lib/time";
import type { Analysis, Clip, Preset, SearchResult } from "../lib/types";

const SIGNAL_LABELS: Record<string, string> = {
  heatmap: "Most replayed",
  audio: "Audio energy",
  reactions: "Reactions",
  relevance: "Relevance",
  comments: "Comments",
  highlight: "SponsorBlock",
  pace: "Speech pace",
  visual: "Scene cuts",
  hook: "Hooks",
  completeness: "Boundaries",
};

const TRANSCRIPT_LABELS: Record<string, string> = {
  captions: "Creator captions",
  "auto-captions": "YouTube auto-captions",
  whisper: "Whisper transcription",
  subtitles: "Subtitle file",
};

function ExportMenu({ a }: { a: Analysis }) {
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const name = slug(a.title);
  const items = [
    { icon: <FileText className="size-4" />, label: "Markdown", run: () => download(`${name}.md`, toMarkdown(a), "text/markdown") },
    { icon: <FileSpreadsheet className="size-4" />, label: "CSV (spreadsheet)", run: () => download(`${name}.csv`, toCSV(a), "text/csv") },
    { icon: <FileJson className="size-4" />, label: "JSON", run: () => download(`${name}.json`, toJSON(a), "application/json") },
    {
      icon: <ListOrdered className="size-4" />,
      label: "Copy as text",
      run: () =>
        navigator.clipboard.writeText(toMarkdown(a)).then(
          () => toast("Suggestions copied", "success"),
          () => toast("Clipboard is not available", "error"),
        ),
    },
  ];
  return (
    <div ref={ref} className="relative">
      <Button icon={<Download className="size-4" />} onClick={() => setOpen((v) => !v)}>
        Export <ChevronDown className="size-3.5" />
      </Button>
      {open && (
        <div className="glass-strong absolute right-0 z-20 mt-2 w-52 animate-fade-up rounded-xl p-1.5 shadow-2xl shadow-black/50">
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              onClick={() => {
                it.run();
                setOpen(false);
              }}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-fg-2 transition hover:bg-white/[0.06] hover:text-fg"
            >
              {it.icon}
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function OtherMatches({ a, items }: { a: Analysis; items: SearchResult[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();
  const analyse = async (r: SearchResult) => {
    setBusy(r.video_id);
    try {
      const res = await api.analyzeYouTube(r.url, {
        mode: a.mode,
        preset: a.preset as Preset,
        min_len: a.min_len,
        max_len: a.max_len,
        query: a.query,
      });
      navigate(`job/${res.job_id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(null);
    }
  };
  return (
    <Card className="p-4">
      <SectionTitle icon={<Search className="size-4" />} title="Other matches" subtitle="Found for this topic but not deep-analysed." />
      <div className="mt-4 space-y-2">
        {items.map((r) => (
          <div key={r.video_id} className="flex items-center gap-3 rounded-xl p-1.5 transition hover:bg-white/[0.03]">
            <Thumb src={r.thumbnail} kind="youtube" className="aspect-video w-24 shrink-0 rounded-lg" />
            <div className="min-w-0 flex-1">
              <a href={r.url} target="_blank" rel="noreferrer" className="line-clamp-2 text-[13px] leading-snug text-fg hover:underline">
                {r.title}
              </a>
              <div className="mt-0.5 truncate text-[11.5px] text-fg-3">
                {r.channel} · {r.duration ? fmtDuration(r.duration) : "?"} · {Math.round(r.relevance * 100)}% match
              </div>
            </div>
            <Button size="sm" variant="secondary" loading={busy === r.video_id} disabled={!!busy} onClick={() => analyse(r)}>
              Analyse
            </Button>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function Results({ id }: { id: string }) {
  const [a, setA] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [activeClip, setActiveClip] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [sort, setSort] = useState<"score" | "time">("score");
  const [showWarnings, setShowWarnings] = useState(false);
  const player = useRef<PlayerHandle>(null);
  const pendingPlay = useRef<Clip | null>(null);

  useEffect(() => {
    api
      .analysis(id)
      .then((x) => {
        setA(x);
        setSourceId(x.sources[0]?.id ?? "");
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    const c = pendingPlay.current;
    if (c && c.source_id === sourceId) {
      pendingPlay.current = null;
      const t = window.setTimeout(() => player.current?.playRange(c.start, c.end), 60);
      return () => window.clearTimeout(t);
    }
  }, [sourceId]);

  const source = a?.sources.find((s) => s.id === sourceId);
  const sourceClips = useMemo(() => (a ? a.clips.filter((c) => c.source_id === sourceId) : []), [a, sourceId]);
  const listClips = useMemo(() => {
    if (!a) return [];
    return sort === "score" ? a.clips : [...a.clips].sort((x, y) => x.source_id.localeCompare(y.source_id) || x.start - y.start);
  }, [a, sort]);

  const playClip = useCallback(
    (c: Clip) => {
      setActiveClip(c.id);
      if (c.source_id !== sourceId) {
        pendingPlay.current = c;
        setTime(0);
        setSourceId(c.source_id);
      } else player.current?.playRange(c.start, c.end);
    },
    [sourceId],
  );

  const seek = useCallback((t: number) => {
    player.current?.seek(t);
    setTime(t);
  }, []);

  if (error) {
    return (
      <div className="mx-auto max-w-xl px-5 py-20">
        <Card>
          <EmptyState
            icon={<TriangleAlert className="size-5" />}
            title="Couldn't open this analysis"
            body={error}
            action={
              <Button icon={<ArrowLeft className="size-4" />} onClick={() => navigate("history")}>
                Back to History
              </Button>
            }
          />
        </Card>
      </div>
    );
  }
  if (!a || !source) {
    return (
      <div className="mx-auto max-w-[1440px] px-6 py-8">
        <div className="h-24 animate-pulse rounded-2xl bg-white/[0.03]" />
        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_440px]">
          <div className="aspect-video animate-pulse rounded-2xl bg-white/[0.03]" />
          <div className="h-[480px] animate-pulse rounded-2xl bg-white/[0.03]" />
        </div>
      </div>
    );
  }

  const multi = a.sources.length > 1;
  const lines = a.transcripts[sourceId] ?? [];

  return (
    <div className="mx-auto max-w-[1440px] px-5 pb-16 pt-6 md:px-8">
      <header className="flex animate-fade-up flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <Thumb src={multi ? null : source.thumbnail} kind={a.kind} className="hidden aspect-video w-36 shrink-0 rounded-xl ring-1 ring-white/[0.08] sm:flex" />
          <div className="min-w-0">
            <a href="#/" className="mb-1.5 inline-flex items-center gap-1 text-[12px] text-fg-3 hover:text-fg">
              <ArrowLeft className="size-3.5" /> Studio
            </a>
            <h1 className="line-clamp-2 text-[22px] font-semibold leading-tight tracking-tight text-fg md:text-[26px]">{a.title}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-fg-3">
              {!multi && source.channel && <span className="text-fg-2">{source.channel}</span>}
              {!multi && <span>{fmtDuration(source.duration)}</span>}
              {!multi && source.view_count != null && <span>· {fmtCount(source.view_count)} views</span>}
              {multi && <span className="text-fg-2">{a.sources.length} videos analysed</span>}
              <span>· {relativeTime(a.created_at)}</span>
              <span className="inline-flex items-center gap-1">
                · <Clock3 className="size-3" /> {a.elapsed_sec}s
              </span>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {a.mode === "ai" ? (
                <Badge tone="violet" icon={<Sparkles className="size-3" />}>
                  AI re-ranked
                </Badge>
              ) : (
                <Badge icon={<Cpu className="size-3" />}>Deterministic</Badge>
              )}
              <Badge>
                {a.preset} · {formatLength(a.min_len)} – {formatLength(a.max_len)}
              </Badge>
              {a.query && <Badge tone="cyan">Focus: {a.query}</Badge>}
              {source.signals.map((s) => (
                <Badge key={s} tone="neutral" className="bg-transparent">
                  {SIGNAL_LABELS[s] ?? s}
                </Badge>
              ))}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {source.platform === "youtube" && source.url && (
            <a href={source.url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm text-fg-2 transition hover:bg-white/[0.06] hover:text-fg">
              YouTube <ExternalLink className="size-3.5" />
            </a>
          )}
          <ExportMenu a={a} />
        </div>
      </header>

      {a.warnings.length > 0 && (
        <div className="mt-5 rounded-xl border border-warn/15 bg-warn/[0.04]">
          <button type="button" onClick={() => setShowWarnings((v) => !v)} className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-[12.5px] text-[#fde68a]">
            <TriangleAlert className="size-4" />
            {a.warnings.length} note{a.warnings.length > 1 ? "s" : ""} about available signals
            <ChevronDown className={cx("ml-auto size-4 transition-transform", showWarnings && "rotate-180")} />
          </button>
          {showWarnings && (
            <ul className="space-y-1 px-4 pb-3 pl-11 text-[12.5px] text-fg-2">
              {a.warnings.map((w, i) => (
                <li key={i} className="list-disc">
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {multi && (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {a.sources.map((s) => {
            const n = a.clips.filter((c) => c.source_id === s.id).length;
            const on = s.id === sourceId;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setSourceId(s.id)}
                className={cx(
                  "flex items-center gap-3 rounded-2xl border p-2.5 text-left transition-all duration-200",
                  on ? "border-violet/45 bg-white/[0.05]" : "border-white/[0.07] bg-white/[0.02] hover:border-white/15",
                )}
              >
                <Thumb src={s.thumbnail} kind="youtube" className="aspect-video w-24 shrink-0 rounded-lg" />
                <div className="min-w-0">
                  <div className="line-clamp-2 text-[12.5px] font-medium leading-snug text-fg">{s.title}</div>
                  <div className="mt-1 text-[11.5px] text-fg-3">
                    {n} clip{n === 1 ? "" : "s"} · {Math.round((s.relevance ?? 0) * 100)}% match
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_440px]">
        <div className="min-w-0 space-y-6">
          <Card className="p-2.5">
            <Player ref={player} source={source} onTime={setTime} />
          </Card>
          <Card className="p-5">
            <SectionTitle title="Signal timeline" subtitle="Where the evidence is. Click anywhere to seek, click a region to play that clip." />
            <div className="mt-4">
              <Timeline
                key={sourceId}
                data={a.timelines[sourceId]}
                duration={source.duration}
                clips={sourceClips}
                chapters={source.chapters}
                activeClipId={activeClip}
                time={time}
                onSeek={seek}
                onSelectClip={playClip}
              />
            </div>
          </Card>
          <Card className="flex h-[480px] flex-col p-5">
            <SectionTitle
              title="Transcript"
              subtitle={source.transcript_source ? `${TRANSCRIPT_LABELS[source.transcript_source] ?? source.transcript_source}${source.language ? ` · ${source.language}` : ""}` : "Not available"}
            />
            <div className="mt-4 min-h-0 flex-1">
              <TranscriptPanel lines={lines} clips={sourceClips} time={time} onSeek={seek} />
            </div>
          </Card>
        </div>

        <aside className="min-w-0">
          <div className="space-y-4 xl:sticky xl:top-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[15px] font-semibold text-fg">{a.clips.length} clip suggestions</h2>
                <p className="text-[12px] text-fg-3">{multi ? "Ranked across all analysed videos" : "Best first"}</p>
              </div>
              <Segmented
                size="sm"
                value={sort}
                onChange={setSort}
                options={[
                  { value: "score", label: "Score", icon: <ArrowDownWideNarrow className="size-3.5" /> },
                  { value: "time", label: "Time", icon: <Clock3 className="size-3.5" /> },
                ]}
              />
            </div>
            {a.clips.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<WandSparkles className="size-5" />}
                  title="No clips found"
                  body="The video may be shorter than the chosen clip length, or no usable signals were available. Check the notes above and try a shorter preset."
                />
              </Card>
            ) : (
              <div className="space-y-3 xl:max-h-[calc(100vh-130px)] xl:overflow-y-auto xl:pr-1">
                {listClips.map((c) => (
                  <ClipCard
                    key={c.id}
                    clip={c}
                    source={a.sources.find((s) => s.id === c.source_id)}
                    active={c.id === activeClip}
                    showSource={multi}
                    onPlay={() => playClip(c)}
                  />
                ))}
                {a.other_results.length > 0 && <OtherMatches a={a} items={a.other_results} />}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
