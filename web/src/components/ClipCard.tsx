import { Check, ChevronDown, Clock, Copy, Info, Link2, Play, Sparkles, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { clipLink } from "../lib/exporters";
import { cx, fmtDuration, fmtTime } from "../lib/format";
import type { Clip, Reason, SourceVideo } from "../lib/types";
import { ScoreRing } from "./ScoreRing";
import { useToast } from "./Toast";
import { Badge, IconButton } from "./ui";

function ReasonRow({ r }: { r: Reason }) {
  const icon =
    r.signal === "ai" ? (
      <Sparkles className="size-3.5 text-[#c4b5fd]" />
    ) : r.polarity === "neg" ? (
      <TriangleAlert className="size-3.5 text-neg" />
    ) : r.polarity === "info" ? (
      <Info className="size-3.5 text-cyan" />
    ) : (
      <Check className="size-3.5 text-pos" />
    );
  return (
    <li className="flex items-start gap-2 text-[12.5px] leading-relaxed text-fg-2">
      <span className="mt-[3px] shrink-0">{icon}</span>
      <span className={cx(r.signal === "ai" && "text-fg")}>{r.text}</span>
    </li>
  );
}

export function ClipCard({
  clip,
  source,
  active,
  showSource,
  onPlay,
}: {
  clip: Clip;
  source: SourceVideo | undefined;
  active: boolean;
  showSource: boolean;
  onPlay: () => void;
}) {
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const link = clipLink(source, clip);
  const visibleReasons = open ? clip.reasons : clip.reasons.slice(0, 3);

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} copied`, "success");
    } catch {
      toast("Clipboard is not available", "error");
    }
  };

  return (
    <article
      className={cx(
        "group relative overflow-hidden rounded-2xl border p-4 transition-all duration-200",
        active ? "border-violet/45 bg-white/[0.05] shadow-[0_0_0_1px_rgba(139,92,246,0.25),0_20px_50px_-25px_rgba(139,92,246,0.6)]" : "border-white/[0.07] bg-white/[0.025] hover:border-white/[0.13] hover:bg-white/[0.04]",
      )}
    >
      {active && <span className="absolute inset-y-0 left-0 w-[3px] bg-accent" />}
      <div className="flex gap-3.5">
        <ScoreRing score={clip.score} size={50} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] font-semibold tabular text-fg-3">#{clip.rank}</span>
            {clip.ai_score !== null && (
              <Badge tone="violet" icon={<Sparkles className="size-3" />}>
                AI {Math.round(clip.ai_score)}
              </Badge>
            )}
            {clip.chapter && <span className="truncate text-[11.5px] text-fg-3">· {clip.chapter}</span>}
          </div>
          <h4 className="mt-1 line-clamp-2 text-[14.5px] font-medium leading-snug text-fg">{clip.title}</h4>
          <div className="mt-1.5 flex items-center gap-1.5 text-[12px] text-fg-2">
            <Clock className="size-3.5 text-fg-3" />
            <span className="font-mono tabular">
              {fmtTime(clip.start)} → {fmtTime(clip.end)}
            </span>
            <span className="text-fg-3">· {fmtDuration(clip.duration)}</span>
          </div>
        </div>
      </div>

      {showSource && source && (
        <div className="mt-3 flex items-center gap-2.5 rounded-lg bg-black/20 p-1.5 pr-3">
          {source.thumbnail ? (
            <img src={source.thumbnail} alt="" className="h-8 w-14 rounded object-cover" loading="lazy" onError={(e) => (e.currentTarget.style.display = "none")} />
          ) : (
            <span className="h-8 w-14 rounded bg-white/[0.05]" />
          )}
          <span className="truncate text-[12px] text-fg-2">{source.title}</span>
        </div>
      )}

      {visibleReasons.length > 0 && (
        <ul className="mt-3 space-y-1">
          {visibleReasons.map((r, i) => (
            <ReasonRow key={i} r={r} />
          ))}
        </ul>
      )}

      {open && (
        <div className="mt-4 space-y-4 border-t border-white/[0.06] pt-4">
          {clip.hook && (
            <blockquote className="rounded-lg border-l-2 border-violet/60 bg-violet/[0.06] px-3 py-2 text-[13px] italic leading-relaxed text-fg">“{clip.hook}”</blockquote>
          )}
          <div>
            <div className="mb-2 flex items-center justify-between text-[11.5px] uppercase tracking-wider text-fg-3">
              <span>Score breakdown</span>
              <span className="normal-case tracking-normal">
                Engine {Math.round(clip.engine_score)}
                {clip.ai_score !== null && <> · AI {Math.round(clip.ai_score)}</>}
              </span>
            </div>
            <div className="space-y-1.5">
              {clip.breakdown.map((b) => (
                <div key={b.signal} className="grid grid-cols-[130px_1fr_44px] items-center gap-2 text-[12px]">
                  <span className="truncate text-fg-2">{b.label}</span>
                  {b.signal === "penalties" ? (
                    <span className="h-1.5 rounded-full bg-neg/40" style={{ width: `${Math.min(100, Math.abs(b.contribution) * 3)}%` }} />
                  ) : (
                    <span className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                      <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(b.value * 100)}%` }} />
                    </span>
                  )}
                  <span className={cx("text-right tabular", b.contribution < 0 ? "text-neg" : "text-fg-2")}>
                    {b.contribution > 0 ? "+" : ""}
                    {b.contribution.toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
          </div>
          {clip.transcript && (
            <div>
              <div className="mb-1.5 text-[11.5px] uppercase tracking-wider text-fg-3">Transcript</div>
              <p className="max-h-44 overflow-auto pr-1 text-[13px] leading-relaxed text-fg-2">{clip.transcript}</p>
            </div>
          )}
          {clip.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {clip.tags.map((t) => (
                <span key={t} className="rounded-md bg-white/[0.05] px-2 py-0.5 text-[11.5px] text-fg-2">
                  #{t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mt-3.5 flex items-center gap-1">
        <button
          type="button"
          onClick={onPlay}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/[0.07] px-3 text-[12.5px] font-medium text-fg ring-1 ring-white/[0.08] transition hover:bg-white/[0.12]"
        >
          <Play className="size-3.5 fill-current" /> Play clip
        </button>
        {link && (
          <IconButton label="Copy YouTube link at this moment" onClick={() => copy(link, "Link")}>
            <Link2 className="size-4" />
          </IconButton>
        )}
        <IconButton label="Copy time range" onClick={() => copy(`${fmtTime(clip.start)} - ${fmtTime(clip.end)}`, "Time range")}>
          <Copy className="size-4" />
        </IconButton>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="ml-auto inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-[12.5px] text-fg-2 transition hover:bg-white/[0.06] hover:text-fg"
          aria-expanded={open}
        >
          {open ? "Less" : "Details"}
          <ChevronDown className={cx("size-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>
    </article>
  );
}
