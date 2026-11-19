import { Crosshair, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { cx, fmtTime } from "../lib/format";
import type { Clip, TranscriptLine } from "../lib/types";
import { IconButton } from "./ui";

function highlight(text: string, q: string): ReactNode {
  if (!q) return text;
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
  return parts.map((p, i) => (i % 2 ? <mark key={i} className="rounded bg-warn/25 px-0.5 text-fg">{p}</mark> : p));
}

export function TranscriptPanel({
  lines,
  clips,
  time,
  onSeek,
}: {
  lines: TranscriptLine[];
  clips: Clip[];
  time: number;
  onSeek: (t: number) => void;
}) {
  const [q, setQ] = useState("");
  const [follow, setFollow] = useState(true);
  const list = useRef<HTMLDivElement>(null);
  const rows = useRef<Map<number, HTMLButtonElement>>(new Map());

  const activeIdx = useMemo(() => {
    let lo = 0;
    let hi = lines.length - 1;
    let ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (lines[mid].start <= time) {
        ans = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return ans;
  }, [lines, time]);

  const query = q.trim().toLowerCase();
  const visible = useMemo(
    () => lines.map((l, i) => ({ l, i })).filter(({ l }) => !query || l.text.toLowerCase().includes(query)),
    [lines, query],
  );

  useEffect(() => {
    if (!follow || query || activeIdx < 0) return;
    const el = rows.current.get(activeIdx);
    const box = list.current;
    if (el && box) {
      const top = el.offsetTop - box.clientHeight / 3;
      if (Math.abs(box.scrollTop - top) > 40) box.scrollTo({ top, behavior: "smooth" });
    }
  }, [activeIdx, follow, query]);

  const inClip = (l: TranscriptLine) => clips.some((c) => l.start < c.end && l.end > c.start);

  if (!lines.length) {
    return <div className="py-10 text-center text-[13px] text-fg-3">No transcript was available for this source.</div>;
  }
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Search ${lines.length} lines…`}
            className="h-9 w-full rounded-lg border border-white/[0.07] bg-black/20 pl-9 pr-3 text-[13px] text-fg outline-none transition placeholder:text-fg-3 focus:border-violet/50"
          />
        </div>
        <IconButton label={follow ? "Following playback" : "Follow playback"} active={follow} onClick={() => setFollow((v) => !v)}>
          <Crosshair className="size-4" />
        </IconButton>
      </div>
      <div ref={list} className="relative min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
        {visible.map(({ l, i }) => (
          <button
            key={i}
            ref={(el) => {
              if (el) rows.current.set(i, el);
              else rows.current.delete(i);
            }}
            type="button"
            onClick={() => onSeek(l.start)}
            className={cx(
              "flex w-full gap-3 rounded-lg border-l-2 px-3 py-1.5 text-left text-[13px] leading-relaxed transition",
              i === activeIdx ? "bg-white/[0.07] text-fg" : "text-fg-2 hover:bg-white/[0.04] hover:text-fg",
              inClip(l) ? "border-violet/60" : "border-transparent",
            )}
          >
            <span className="w-12 shrink-0 pt-px font-mono text-[11.5px] tabular text-fg-3">{fmtTime(l.start)}</span>
            <span>{highlight(l.text, query)}</span>
          </button>
        ))}
        {!visible.length && <div className="py-8 text-center text-[13px] text-fg-3">No lines match “{q}”.</div>}
      </div>
    </div>
  );
}
