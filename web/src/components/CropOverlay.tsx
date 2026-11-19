import { useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { CropBox } from "../lib/types";

type Handle = "move" | "nw" | "ne" | "sw" | "se" | "n" | "s" | "e" | "w";
const MIN = 0.05;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
// Matches the server: H.264 needs even dimensions.
const even = (n: number) => Math.max(2, Math.floor(n / 2 + 0.01) * 2);

/** Largest centred box with pixel aspect `aspect` inside a frame whose pixel aspect is `frameAspect`. */
export function fitCrop(aspect: number | null, frameAspect: number): CropBox {
  if (!aspect) return { x: 0.1, y: 0.1, w: 0.8, h: 0.8 };
  const r = aspect / frameAspect;
  const w = r >= 1 ? 1 : r;
  const h = r >= 1 ? 1 / r : 1;
  return { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
}

/**
 * Draggable crop rectangle over a media element. Coordinates are normalised (0–1) to the displayed frame;
 * `aspect` is the locked pixel aspect (w/h) or null for free-form.
 */
export function CropOverlay({
  box,
  aspect,
  frameWidth,
  frameHeight,
  onChange,
}: {
  box: CropBox;
  aspect: number | null;
  frameWidth: number;
  frameHeight: number;
  onChange: (box: CropBox) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const drag = useRef<{ handle: Handle; px: number; py: number; box: CropBox } | null>(null);
  const ratio = aspect ? aspect / (frameWidth / frameHeight) : null;

  const begin = (handle: Handle) => (e: ReactPointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { handle, px: e.clientX, py: e.clientY, box };
  };

  const move = (e: ReactPointerEvent) => {
    const d = drag.current;
    const rect = root.current?.getBoundingClientRect();
    if (!d || !rect) return;
    const dx = (e.clientX - d.px) / rect.width;
    const dy = (e.clientY - d.py) / rect.height;
    const b = d.box;

    if (d.handle === "move") {
      // Shift locks the move to the dominant axis.
      const horizontal = Math.abs(e.clientX - d.px) >= Math.abs(e.clientY - d.py);
      const mx = e.shiftKey && !horizontal ? 0 : dx;
      const my = e.shiftKey && horizontal ? 0 : dy;
      onChange({ ...b, x: clamp(b.x + mx, 0, 1 - b.w), y: clamp(b.y + my, 0, 1 - b.h) });
      return;
    }
    if (d.handle === "e" || d.handle === "w") {
      const east = d.handle === "e";
      const ax = east ? b.x : b.x + b.w;
      let w = clamp(east ? b.x + b.w + dx - ax : ax - (b.x + dx), MIN, east ? 1 - ax : ax);
      let h = b.h;
      let y = b.y;
      if (ratio) {
        w = Math.min(w, ratio);
        h = w / ratio;
        y = clamp(b.y + b.h / 2 - h / 2, 0, 1 - h);
      }
      onChange({ x: east ? ax : ax - w, y, w, h });
      return;
    }
    if (d.handle === "n" || d.handle === "s") {
      const south = d.handle === "s";
      const ay = south ? b.y : b.y + b.h;
      let h = clamp(south ? b.y + b.h + dy - ay : ay - (b.y + dy), MIN, south ? 1 - ay : ay);
      let w = b.w;
      let x = b.x;
      if (ratio) {
        h = Math.min(h, 1 / ratio);
        w = h * ratio;
        x = clamp(b.x + b.w / 2 - w / 2, 0, 1 - w);
      }
      onChange({ x, y: south ? ay : ay - h, w, h });
      return;
    }
    const east = d.handle.endsWith("e");
    const south = d.handle.startsWith("s");
    const ax = east ? b.x : b.x + b.w;
    const ay = south ? b.y : b.y + b.h;
    const px = clamp((east ? b.x + b.w : b.x) + dx, 0, 1);
    const py = clamp((south ? b.y + b.h : b.y) + dy, 0, 1);
    let w = Math.max(MIN, east ? px - ax : ax - px);
    let h = Math.max(MIN, south ? py - ay : ay - py);
    w = Math.min(w, east ? 1 - ax : ax);
    h = Math.min(h, south ? 1 - ay : ay);
    if (ratio) {
      if (w / h > ratio) w = h * ratio;
      else h = w / ratio;
    }
    onChange({ x: east ? ax : ax - w, y: south ? ay : ay - h, w, h });
  };

  const end = () => {
    drag.current = null;
  };

  const corner = (handle: Handle, pos: string, cursor: string) => (
    <div
      onPointerDown={begin(handle)}
      onPointerMove={move}
      onPointerUp={end}
      className={`absolute ${pos} z-10 size-5 border-white`}
      style={{ cursor, touchAction: "none" }}
    />
  );

  const edge = (handle: Handle, pos: string, bar: string, cursor: string) => (
    <div
      onPointerDown={begin(handle)}
      onPointerMove={move}
      onPointerUp={end}
      className={`absolute ${pos} z-10 flex items-center justify-center`}
      style={{ cursor, touchAction: "none" }}
    >
      <span className={`pointer-events-none rounded-full bg-white shadow ${bar}`} />
    </div>
  );

  return (
    <div ref={root} className="absolute inset-0 overflow-hidden">
      <div
        onPointerDown={begin("move")}
        onPointerMove={move}
        onPointerUp={end}
        className="absolute cursor-move outline outline-2 outline-white/90"
        style={{
          left: `${box.x * 100}%`,
          top: `${box.y * 100}%`,
          width: `${box.w * 100}%`,
          height: `${box.h * 100}%`,
          boxShadow: "0 0 0 9999px rgba(0,0,0,0.58)",
          touchAction: "none",
        }}
      >
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute inset-y-0 left-1/3 w-px bg-white/25" />
          <div className="absolute inset-y-0 left-2/3 w-px bg-white/25" />
          <div className="absolute inset-x-0 top-1/3 h-px bg-white/25" />
          <div className="absolute inset-x-0 top-2/3 h-px bg-white/25" />
        </div>
        <div className="pointer-events-none absolute left-1/2 top-6 -translate-x-1/2 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] font-medium tabular text-white">
          {even(box.w * frameWidth)}×{even(box.h * frameHeight)}
        </div>
        {corner("nw", "left-0 top-0 border-l-[3px] border-t-[3px]", "nwse-resize")}
        {corner("ne", "right-0 top-0 border-r-[3px] border-t-[3px]", "nesw-resize")}
        {corner("sw", "left-0 bottom-0 border-b-[3px] border-l-[3px]", "nesw-resize")}
        {corner("se", "right-0 bottom-0 border-b-[3px] border-r-[3px]", "nwse-resize")}
        {edge("n", "left-1/2 top-0 h-4 w-10 -translate-x-1/2", "h-[4px] w-7", "ns-resize")}
        {edge("s", "left-1/2 bottom-0 h-4 w-10 -translate-x-1/2", "h-[4px] w-7", "ns-resize")}
        {edge("w", "left-0 top-1/2 h-10 w-4 -translate-y-1/2", "h-7 w-[4px]", "ew-resize")}
        {edge("e", "right-0 top-1/2 h-10 w-4 -translate-y-1/2", "h-7 w-[4px]", "ew-resize")}
      </div>
    </div>
  );
}
