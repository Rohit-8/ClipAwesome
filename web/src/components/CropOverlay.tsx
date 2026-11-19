import { useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { CropBox } from "../lib/types";

type Handle = "move" | "nw" | "ne" | "sw" | "se";
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
      onChange({ ...b, x: clamp(b.x + dx, 0, 1 - b.w), y: clamp(b.y + dy, 0, 1 - b.h) });
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
        <div className="pointer-events-none absolute left-1/2 top-2 -translate-x-1/2 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] font-medium tabular text-white">
          {even(box.w * frameWidth)}×{even(box.h * frameHeight)}
        </div>
        {corner("nw", "left-0 top-0 border-l-[3px] border-t-[3px]", "nwse-resize")}
        {corner("ne", "right-0 top-0 border-r-[3px] border-t-[3px]", "nesw-resize")}
        {corner("sw", "left-0 bottom-0 border-b-[3px] border-l-[3px]", "nesw-resize")}
        {corner("se", "right-0 bottom-0 border-b-[3px] border-r-[3px]", "nwse-resize")}
      </div>
    </div>
  );
}
