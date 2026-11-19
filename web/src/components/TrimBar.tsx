import { useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { fmtTime } from "../lib/format";

const MIN_LEN = 0.1;

/** Trim range with draggable in/out handles, a playhead, and click-to-seek. */
export function TrimBar({
  duration,
  start,
  end,
  time,
  onChange,
  onSeek,
}: {
  duration: number;
  start: number;
  end: number;
  time: number;
  onChange: (start: number, end: number) => void;
  onSeek: (t: number) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const dragging = useRef<"start" | "end" | null>(null);
  const pct = (t: number) => `${(Math.min(duration, Math.max(0, t)) / duration) * 100}%`;

  const at = (clientX: number) => {
    const rect = track.current!.getBoundingClientRect();
    return Math.min(duration, Math.max(0, ((clientX - rect.left) / rect.width) * duration));
  };

  const grab = (which: "start" | "end") => (e: ReactPointerEvent) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    dragging.current = which;
  };

  const move = (e: ReactPointerEvent) => {
    if (!dragging.current) return;
    const t = at(e.clientX);
    if (dragging.current === "start") {
      const s = Math.min(t, end - MIN_LEN);
      onChange(s, end);
      onSeek(s);
    } else {
      const en = Math.max(t, start + MIN_LEN);
      onChange(start, en);
      onSeek(en);
    }
  };

  const handle = (which: "start" | "end") => (
    <div
      onPointerDown={grab(which)}
      onPointerMove={move}
      onPointerUp={() => (dragging.current = null)}
      className="absolute inset-y-0 z-10 flex w-3.5 -translate-x-1/2 cursor-ew-resize items-center justify-center rounded-md bg-accent shadow-[0_0_0_3px_rgba(9,9,11,0.6)]"
      style={{ left: pct(which === "start" ? start : end), touchAction: "none" }}
      role="slider"
      aria-label={which === "start" ? "Trim start" : "Trim end"}
      aria-valuenow={which === "start" ? start : end}
    >
      <span className="h-4 w-[3px] rounded-full bg-white/80" />
    </div>
  );

  return (
    <div className="select-none">
      <div
        ref={track}
        onPointerDown={(e) => onSeek(at(e.clientX))}
        className="relative h-11 cursor-pointer rounded-xl bg-white/[0.04] ring-1 ring-inset ring-white/[0.06]"
      >
        <div
          className="absolute inset-y-0 rounded-md border-y-2 border-accent bg-accent/15"
          style={{ left: pct(start), width: `${((end - start) / duration) * 100}%` }}
        />
        <div className="pointer-events-none absolute -inset-y-1 z-20 w-0.5 -translate-x-1/2 rounded-full bg-white" style={{ left: pct(time) }} />
        {handle("start")}
        {handle("end")}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] tabular text-fg-3">
        <span>0:00</span>
        <span>{fmtTime(duration / 2)}</span>
        <span>{fmtTime(duration)}</span>
      </div>
    </div>
  );
}
