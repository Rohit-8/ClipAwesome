import { Star } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { cx, fmtTime } from "../lib/format";
import type { Chapter, Clip, Timeline as TimelineData } from "../lib/types";

const SERIES: Record<string, { label: string; color: string }> = {
  heatmap: { label: "Most replayed", color: "#22d3ee" },
  relevance: { label: "Topic relevance", color: "#fbbf24" },
  reactions: { label: "Reactions", color: "#34d399" },
  audio: { label: "Audio energy", color: "#c4b5fd" },
  comments: { label: "Comments", color: "#f472b6" },
  highlight: { label: "Highlight", color: "#fde68a" },
  pace: { label: "Speech pace", color: "#93c5fd" },
  visual: { label: "Visual activity", color: "#fca5a5" },
};

const H = 120;
const BASE = 112;
const AMP = 100;

function linePath(values: number[]): string {
  const n = values.length;
  if (n < 2) return "";
  return values.map((v, i) => `${i === 0 ? "M" : "L"}${((i / (n - 1)) * 1000).toFixed(2)},${(BASE - v * AMP).toFixed(2)}`).join(" ");
}

export function Timeline({
  data,
  duration,
  clips,
  chapters,
  activeClipId,
  time,
  onSeek,
  onSelectClip,
}: {
  data: TimelineData | undefined;
  duration: number;
  clips: Clip[];
  chapters: Chapter[];
  activeClipId: string | null;
  time: number;
  onSeek: (t: number) => void;
  onSelectClip: (c: Clip) => void;
}) {
  const available = useMemo(() => Object.keys(SERIES).filter((k) => data?.series[k]?.length), [data]);
  const [shown, setShown] = useState<Set<string>>(() => {
    const preferred = available.filter((k) => k === "heatmap" || k === "relevance");
    return new Set(preferred.length ? preferred : available.slice(0, 1));
  });
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const composite = data?.series.composite ?? [];
  const area = composite.length > 1 ? `${linePath(composite)} L1000,${BASE} L0,${BASE} Z` : "";
  const pct = (t: number) => `${Math.max(0, Math.min(100, (t / Math.max(1, duration)) * 100))}%`;

  const timeAt = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return 0;
    return Math.max(0, Math.min(duration, ((clientX - rect.left) / rect.width) * duration));
  };

  const toggle = (k: string) =>
    setShown((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-[12px] text-fg-2">
          <span className="h-2.5 w-4 rounded-sm bg-gradient-to-r from-violet/70 to-cyan/50" /> Composite score
        </span>
        <span className="mx-1 h-3 w-px bg-white/10" />
        {available.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => toggle(k)}
            className={cx(
              "inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[11.5px] ring-1 transition",
              shown.has(k) ? "bg-white/[0.06] text-fg ring-white/15" : "text-fg-3 ring-white/[0.06] hover:text-fg-2",
            )}
          >
            <span className="size-2 rounded-full" style={{ background: SERIES[k].color, opacity: shown.has(k) ? 1 : 0.4 }} />
            {SERIES[k].label}
          </button>
        ))}
      </div>

      <div
        ref={box}
        className="relative h-[120px] cursor-crosshair select-none overflow-hidden rounded-xl bg-black/25 ring-1 ring-white/[0.06]"
        onMouseMove={(e) => setHover(timeAt(e.clientX))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => onSeek(timeAt(e.clientX))}
      >
        <svg viewBox={`0 0 1000 ${H}`} preserveAspectRatio="none" className="absolute inset-0 size-full">
          <defs>
            <linearGradient id="tl-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#8b5cf6" stopOpacity="0.55" />
              <stop offset="1" stopColor="#22d3ee" stopOpacity="0.04" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((g) => (
            <line key={g} x1="0" x2="1000" y1={BASE - g * AMP} y2={BASE - g * AMP} stroke="rgba(255,255,255,0.04)" vectorEffect="non-scaling-stroke" />
          ))}
          {(data?.markers.excluded ?? []).map((m, i) => (
            <rect key={i} x={(m.start / duration) * 1000} width={Math.max(1, ((m.end - m.start) / duration) * 1000)} y="0" height={H} fill="rgba(248,113,113,0.10)">
              <title>{`Excluded: ${m.label} (${fmtTime(m.start)}–${fmtTime(m.end)})`}</title>
            </rect>
          ))}
          {area && <path d={area} fill="url(#tl-area)" />}
          {composite.length > 1 && <path d={linePath(composite)} fill="none" stroke="#a78bfa" strokeWidth="1.25" strokeOpacity="0.8" vectorEffect="non-scaling-stroke" />}
          {available
            .filter((k) => shown.has(k))
            .map((k) => (
              <path key={k} d={linePath(data!.series[k])} fill="none" stroke={SERIES[k].color} strokeWidth="1.5" strokeOpacity="0.9" vectorEffect="non-scaling-stroke" />
            ))}
        </svg>

        {clips.map((c) => {
          const active = c.id === activeClipId;
          return (
            <button
              key={c.id}
              type="button"
              title={`#${c.rank} ${c.title} (${fmtTime(c.start)}–${fmtTime(c.end)})`}
              onClick={(e) => {
                e.stopPropagation();
                onSelectClip(c);
              }}
              className={cx(
                "absolute inset-y-0 border-x transition-colors",
                active ? "border-white/70 bg-violet/30" : "border-violet/50 bg-violet/[0.13] hover:bg-violet/25",
              )}
              style={{ left: pct(c.start), width: `max(3px, calc(${pct(c.end)} - ${pct(c.start)}))` }}
            >
              <span
                className={cx(
                  "absolute left-1 top-1 rounded px-1 text-[10px] font-semibold leading-4 tabular",
                  active ? "bg-white text-ink-950" : "bg-violet/80 text-white",
                )}
              >
                {c.rank}
              </span>
            </button>
          );
        })}

        {(data?.markers.highlights ?? []).map((h, i) => (
          <Star key={i} className="pointer-events-none absolute top-1 size-3 -translate-x-1/2 fill-warn text-warn" style={{ left: pct(h.t) }} />
        ))}
        {(data?.markers.reactions ?? []).slice(0, 150).map((r, i) => (
          <span key={i} className="pointer-events-none absolute bottom-1 size-1.5 -translate-x-1/2 rounded-full bg-pos/80" style={{ left: pct(r.t) }} title={r.label} />
        ))}

        <div className="pointer-events-none absolute inset-y-0 w-px bg-white shadow-[0_0_8px_rgba(255,255,255,0.6)]" style={{ left: pct(time) }}>
          <span className="absolute -left-[3px] -top-[1px] size-[7px] rounded-full bg-white" />
        </div>
        {hover !== null && (
          <div className="pointer-events-none absolute inset-y-0 w-px bg-white/30" style={{ left: pct(hover) }}>
            <span className="absolute -translate-x-1/2 rounded-md bg-ink-950/90 px-1.5 py-0.5 text-[10.5px] tabular text-fg ring-1 ring-white/10" style={{ top: 4 }}>
              {fmtTime(hover)}
            </span>
          </div>
        )}
      </div>

      {chapters.length > 0 && (
        <div className="relative h-6 overflow-hidden rounded-md bg-white/[0.02]">
          {chapters.map((ch, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onSeek(ch.start)}
              title={`${fmtTime(ch.start)} · ${ch.title}`}
              className="absolute inset-y-0 truncate border-l border-white/15 px-1.5 text-left text-[10.5px] leading-6 text-fg-3 transition hover:bg-white/[0.04] hover:text-fg-2"
              style={{ left: pct(ch.start), width: `calc(${pct(ch.end)} - ${pct(ch.start)})` }}
            >
              {ch.title}
            </button>
          ))}
        </div>
      )}

      <div className="flex justify-between text-[10.5px] tabular text-fg-3">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <span key={f}>{fmtTime(duration * f)}</span>
        ))}
      </div>
    </div>
  );
}
