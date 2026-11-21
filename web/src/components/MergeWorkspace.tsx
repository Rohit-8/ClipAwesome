import { ArrowDown, ArrowUp, AudioWaveform, CloudUpload, Film, GripVertical, Merge, MonitorPlay, Pause, Play, Plus, Scissors, Trash2, Zap } from "lucide-react";
import type { DragEvent, PointerEvent as ReactPointerEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { browserDecodes, useCompatAudio } from "../lib/compat-audio";
import { cx, fmtBytes, fmtDuration } from "../lib/format";
import { navigate } from "../lib/router";
import { formatLength } from "../lib/time";
import type { DownloadTask, EditSource, ExportTask, GpuStatus, MergeFrame, MergeRequest } from "../lib/types";
import { TimeInput } from "./TimeInput";
import { useToast } from "./Toast";
import { TrimBar } from "./TrimBar";
import { Badge, Button, Card, IconButton, Notice, ProgressBar, Segmented, Select, Toggle, ToolSection } from "./ui";

const MAX_CLIPS = 20;
const STORE_KEY = "clipawesome.merge";
const MEDIA_ACCEPT = ".mp4,.mkv,.mov,.webm,.avi,.m4v,.wmv,.flv,.mpg,.mpeg,.ts,.mp3,.wav,.m4a,.flac,.ogg,.opus,.aac";
const FRAMES: { value: MergeFrame; label: string; hint: string }[] = [
  { value: "first", label: "Match first clip", hint: "Same shape as the first video clip" },
  { value: "16:9", label: "16:9", hint: "YouTube, widescreen" },
  { value: "9:16", label: "9:16", hint: "Shorts · Reels · TikTok" },
  { value: "1:1", label: "1:1", hint: "Square posts" },
];
const RATIOS: Partial<Record<MergeFrame, number>> = { "16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1 };
const RESOLUTIONS = [2160, 1440, 1080, 720, 480, 360];
const even = (n: number) => Math.max(2, Math.round(n / 2) * 2);
const round3 = (n: number) => Math.round(n * 1000) / 1000;

interface Clip {
  key: string;
  source: EditSource;
  start: number;
  end: number;
}

let keySeq = 0;
const newKey = () => `c${Date.now().toString(36)}${(keySeq++).toString(36)}`;

function displaySize(s: EditSource): [number, number] {
  const w = s.width || 1920;
  const h = s.height || 1080;
  return s.rotation % 180 === 90 ? [h, w] : [w, h];
}

/** Mirrors editor.merge_canvas on the server: `resolution` is the short side. */
function mergeCanvas(first: EditSource, frame: MergeFrame, resolution: number | null): [number, number] {
  const [w, h] = displaySize(first);
  const ratio = RATIOS[frame] ?? w / h;
  const short = resolution ?? Math.min(w, h);
  return ratio >= 1 ? [even(short * ratio), even(short)] : [even(short), even(short / ratio)];
}

export function useGpuStatus(): GpuStatus | null {
  const [status, setStatus] = useState<GpuStatus | null>(null);
  useEffect(() => {
    api
      .gpuStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  return status;
}

export function encoderText(status: GpuStatus | null): string {
  if (!status) return "Checking…";
  if (!status.enabled) return "CPU (GPU turned off)";
  return status.encoder ? `GPU · ${status.encoder.name}` : "CPU · x264";
}

// ------------------------------------------------------------------ clip preview

function ClipPreview({ clip, index, onChange }: { clip: Clip; index: number; onChange: (start: number, end: number) => void }) {
  const { source } = clip;
  const video = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(clip.start);
  const [playing, setPlaying] = useState(false);
  const previewUrl = source.has_audio ? api.editorPreviewAudioUrl(source.id) : null;
  const [mediaSrc, setMediaSrc] = useState(() =>
    !source.has_video && previewUrl && browserDecodes(source.audio_codec) !== true ? previewUrl : api.editorMediaUrl(source.id),
  );
  const compat = useCompatAudio(video, previewUrl, { codec: source.audio_codec, enabled: source.has_video && source.has_audio });
  const [w, h] = displaySize(source);

  // Play only the selected part of the clip.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const v = video.current;
      if (v) {
        if (v.currentTime >= clip.end) {
          v.pause();
          v.currentTime = clip.end;
        }
        setTime(v.currentTime);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, clip.end]);

  const seek = useCallback((t: number) => {
    const v = video.current;
    if (v) v.currentTime = t;
    setTime(t);
  }, []);

  const toggle = () => {
    const v = video.current;
    if (!v) return;
    if (v.paused) {
      if (v.currentTime < clip.start || v.currentTime >= clip.end - 0.05) v.currentTime = clip.start;
      void v.play();
    } else v.pause();
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-center rounded-2xl bg-black/40 p-3 ring-1 ring-inset ring-white/[0.04]">
        <div
          className="relative overflow-hidden rounded-lg bg-black"
          style={source.has_video ? { aspectRatio: `${w} / ${h}`, width: `min(100%, calc(42vh * ${w / h}))` } : { width: "100%", height: 140 }}
        >
          <video
            ref={video}
            src={mediaSrc}
            preload="auto"
            playsInline
            onLoadedMetadata={(e) => {
              e.currentTarget.currentTime = clip.start;
            }}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onSeeked={(e) => setTime(e.currentTarget.currentTime)}
            onError={() => {
              if (!source.has_video && previewUrl && mediaSrc !== previewUrl) setMediaSrc(previewUrl);
            }}
            onClick={toggle}
            className="absolute inset-0 size-full object-contain"
          />
          {!source.has_video && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-fg-3">
              <AudioWaveform className="size-9" />
              <span className="text-[12px]">Audio only · shown as a black frame in the video</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" icon={playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} onClick={toggle}>
          {playing ? "Pause" : `Play clip ${index + 1}`}
        </Button>
        <span className="tabular text-[13px] text-fg-2">
          {fmtDuration(time)} <span className="text-fg-3">/ {fmtDuration(source.duration)}</span>
        </span>
        {compat === "ready" && <Badge tone="neutral">Audio via MP3 preview</Badge>}
        <div className="ml-auto flex gap-1.5">
          <Button size="sm" onClick={() => onChange(Math.min(time, clip.end - 0.1), clip.end)}>
            Start here
          </Button>
          <Button size="sm" onClick={() => onChange(clip.start, Math.max(time, clip.start + 0.1))}>
            End here
          </Button>
        </div>
      </div>

      <TrimBar duration={source.duration} start={clip.start} end={clip.end} time={time} onChange={onChange} onSeek={seek} />

      <div className="grid gap-3 sm:grid-cols-2">
        <TimeInput
          label="Clip start"
          value={clip.start}
          placeholder="e.g. 1:05"
          onCommit={(v) => {
            const s = Math.min(Math.max(0, v), clip.end - 0.1);
            onChange(s, clip.end);
            seek(s);
          }}
        />
        <TimeInput
          label="Clip end"
          value={clip.end}
          placeholder="e.g. 2:30"
          onCommit={(v) => {
            const e = Math.min(source.duration, Math.max(v, clip.start + 0.1));
            onChange(clip.start, e);
            seek(e);
          }}
        />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ merged preview

function mediaSrc(s: EditSource): string {
  return !s.has_video && s.has_audio && browserDecodes(s.audio_codec) !== true ? api.editorPreviewAudioUrl(s.id) : api.editorMediaUrl(s.id);
}

/**
 * Plays every clip's selected range back to back inside the output frame. Two video elements take turns:
 * one plays while the other is already loaded at the next clip's start, so cuts are near-seamless.
 */
function MergedPreview({ clips, frame, fit, mute }: { clips: Clip[]; frame: [number, number] | null; fit: "pad" | "crop"; mute: boolean }) {
  const a = useRef<HTMLVideoElement>(null);
  const b = useRef<HTMLVideoElement>(null);
  const slots = useMemo(() => [a, b], []);
  const bar = useRef<HTMLDivElement>(null);
  const initial = [0, clips.length > 1 ? 1 : -1];
  const rt = useRef({ front: 0, assign: [...initial], pending: [null, null] as (number | null)[] });
  const [assign, setAssign] = useState(initial);
  const [front, setFront] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);

  const offsets = useMemo(() => {
    let acc = 0;
    return clips.map((c) => {
      const at = acc;
      acc += c.end - c.start;
      return at;
    });
  }, [clips]);
  const total = clips.reduce((sum, c) => sum + (c.end - c.start), 0);

  const srcA = clips[assign[0]]?.source;
  const srcB = clips[assign[1]]?.source;
  useCompatAudio(a, srcA?.has_audio ? api.editorPreviewAudioUrl(srcA.id) : null, { codec: srcA?.audio_codec, enabled: !!srcA?.has_video && !!srcA.has_audio });
  useCompatAudio(b, srcB?.has_audio ? api.editorPreviewAudioUrl(srcB.id) : null, { codec: srcB?.audio_codec, enabled: !!srcB?.has_video && !!srcB.has_audio });

  const load = useCallback(
    (slot: number, index: number, offset: number) => {
      const v = slots[slot].current;
      const c = clips[index];
      if (!v || !c) return;
      const url = mediaSrc(c.source);
      const t = c.start + Math.max(0, offset);
      if (v.getAttribute("src") !== url) {
        rt.current.pending[slot] = t;
        v.src = url;
      } else if (v.readyState >= 1) v.currentTime = t;
      else rt.current.pending[slot] = t;
      rt.current.assign[slot] = index;
      setAssign([...rt.current.assign]);
    },
    [clips, slots],
  );

  useEffect(() => {
    load(0, 0, 0);
    if (clips.length > 1) load(1, 1, 0);
  }, [load, clips.length]);

  useEffect(() => {
    for (const s of slots) if (s.current) s.current.muted = mute;
  }, [mute, slots]);

  const onMeta = (slot: number) => () => {
    const v = slots[slot].current;
    const t = rt.current.pending[slot];
    if (v && t != null) {
      v.currentTime = t;
      rt.current.pending[slot] = null;
    }
  };

  const advance = useCallback(
    (next: number) => {
      const r = rt.current;
      const f = r.front;
      const back = 1 - f;
      slots[f].current?.pause();
      if (r.assign[back] !== next) load(back, next, 0);
      r.front = back;
      setFront(back);
      void slots[back].current?.play().catch(() => {});
      if (next + 1 < clips.length) load(f, next + 1, 0);
    },
    [clips.length, load, slots],
  );

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const r = rt.current;
      const v = slots[r.front].current;
      const i = r.assign[r.front];
      const c = clips[i];
      if (v && c && r.pending[r.front] == null) {
        if (v.currentTime >= c.end - 0.03 || v.ended) {
          if (i + 1 >= clips.length) {
            v.pause();
            setPlaying(false);
            setTime(total);
            return;
          }
          advance(i + 1);
        } else setTime(offsets[i] + Math.max(0, v.currentTime - c.start));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, clips, offsets, total, advance, slots]);

  const seek = (t: number) => {
    const target = Math.min(Math.max(0, t), Math.max(0, total - 0.05));
    let i = 0;
    while (i + 1 < offsets.length && offsets[i + 1] <= target) i++;
    const r = rt.current;
    if (r.assign[r.front] !== i && r.assign[1 - r.front] === i) {
      slots[r.front].current?.pause();
      r.front = 1 - r.front;
      setFront(r.front);
    }
    load(r.front, i, target - offsets[i]);
    const other = 1 - r.front;
    if (i + 1 < clips.length && r.assign[other] !== i + 1) load(other, i + 1, 0);
    if (playing) void slots[r.front].current?.play().catch(() => {});
    setTime(target);
  };

  const toggle = () => {
    const v = slots[rt.current.front].current;
    if (!v) return;
    if (playing) {
      v.pause();
      setPlaying(false);
      return;
    }
    if (time >= total - 0.06) seek(0);
    void slots[rt.current.front].current?.play().catch(() => {});
    setPlaying(true);
  };

  const scrub = (e: ReactPointerEvent<HTMLDivElement>) => {
    const rect = bar.current!.getBoundingClientRect();
    seek(((e.clientX - rect.left) / rect.width) * total);
  };

  const index = Math.max(0, assign[front]);
  const cur = clips[index];
  const [w, h] = frame ?? [16, 9];

  return (
    <div className="space-y-4">
      <div className="flex justify-center rounded-2xl bg-black/40 p-3 ring-1 ring-inset ring-white/[0.04]">
        <div
          className="relative overflow-hidden rounded-lg bg-black"
          style={frame ? { aspectRatio: `${w} / ${h}`, width: `min(100%, calc(44vh * ${w / h}))` } : { width: "100%", height: 150 }}
        >
          {slots.map((ref, slot) => (
            <video
              key={slot}
              ref={ref}
              preload="auto"
              playsInline
              onLoadedMetadata={onMeta(slot)}
              onClick={toggle}
              className={cx(
                "absolute inset-0 size-full",
                fit === "crop" ? "object-cover" : "object-contain",
                frame && slot === front ? "opacity-100" : "pointer-events-none opacity-0",
              )}
            />
          ))}
          {frame && cur && !cur.source.has_video && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[12px] text-fg-3">Black frame · audio-only clip</div>
          )}
          {!frame && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-fg-3">
              <AudioWaveform className="size-9" />
              <span className="text-[12px]">MP3 · audio only</span>
            </div>
          )}
          <div className="pointer-events-none absolute left-2 top-2 rounded-md bg-black/65 px-1.5 py-0.5 text-[11px] font-medium text-white tabular">
            Clip {index + 1} / {clips.length}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" icon={playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} onClick={toggle}>
          {playing ? "Pause" : "Play merged"}
        </Button>
        <span className="tabular text-[13px] text-fg-2">
          {fmtDuration(time)} <span className="text-fg-3">/ {fmtDuration(total)}</span>
        </span>
        {mute && frame && <Badge tone="neutral">Audio removed</Badge>}
        <span className="ml-auto min-w-0 truncate text-[12px] text-fg-3" title={cur?.source.name}>
          {cur?.source.name}
        </span>
      </div>

      <div
        ref={bar}
        role="slider"
        aria-label="Merged video position"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={time}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          scrub(e);
        }}
        onPointerMove={(e) => e.buttons === 1 && scrub(e)}
        className="relative flex h-9 cursor-pointer overflow-hidden rounded-lg ring-1 ring-inset ring-white/[0.06]"
        style={{ touchAction: "none" }}
      >
        {clips.map((c, i) => (
          <div
            key={c.key}
            className={cx(
              "flex items-center truncate border-l border-black/60 px-1.5 text-[11px] font-medium first:border-l-0",
              i === index ? "bg-accent/30 text-white" : i % 2 ? "bg-white/[0.08] text-fg-2" : "bg-white/[0.04] text-fg-2",
            )}
            style={{ flexGrow: c.end - c.start, flexBasis: 0, minWidth: 0 }}
          >
            {i + 1}
          </div>
        ))}
        <div className="pointer-events-none absolute -inset-y-0.5 w-0.5 -translate-x-1/2 rounded-full bg-white" style={{ left: `${total ? (time / total) * 100 : 0}%` }} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ workspace

export function MergeWorkspace({ seed, onStarted }: { seed: string | null; onStarted: (task: ExportTask) => void }) {
  const toast = useToast();
  const gpu = useGpuStatus();
  const [library, setLibrary] = useState<EditSource[] | null>(null);
  const [downloads, setDownloads] = useState<DownloadTask[]>([]);
  const [clips, setClips] = useState<Clip[]>([]);
  const [restored, setRestored] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"merged" | "clip">("merged");
  const [upload, setUpload] = useState<{ name: string; progress: number } | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [format, setFormat] = useState<"mp4" | "mp3">("mp4");
  const [frame, setFrame] = useState<MergeFrame>("first");
  const [fit, setFit] = useState<"pad" | "crop">("pad");
  const [resolution, setResolution] = useState<number | null>(null);
  const [quality, setQuality] = useState<"high" | "balanced" | "small">("balanced");
  const [mute, setMute] = useState(false);
  const [fast, setFast] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const loadLibrary = useCallback(() => api.editorSources().then(setLibrary), []);

  useEffect(() => {
    loadLibrary().catch(() => setLibrary([]));
    api
      .downloads()
      .then((all) => setDownloads(all.filter((d) => d.status === "done")))
      .catch(() => setDownloads([]));
  }, [loadLibrary]);

  // Restore the clip list from this tab's session, then add the clip the user came from.
  useEffect(() => {
    if (!library || restored) return;
    const byId = new Map(library.map((s) => [s.id, s]));
    let saved: { source_id: string; start: number; end: number }[] = [];
    try {
      saved = JSON.parse(sessionStorage.getItem(STORE_KEY) ?? "[]");
    } catch {
      saved = [];
    }
    const next: Clip[] = saved.flatMap((c) => {
      const source = byId.get(c.source_id);
      return source ? [{ key: newKey(), source, start: Math.min(c.start, source.duration - 0.1), end: Math.min(c.end, source.duration) }] : [];
    });
    const seeded = seed ? byId.get(seed) : undefined;
    if (seeded && !next.some((c) => c.source.id === seeded.id)) next.push({ key: newKey(), source: seeded, start: 0, end: seeded.duration });
    setClips(next.slice(0, MAX_CLIPS));
    setSelected(next.at(-1)?.key ?? null);
    setRestored(true);
    if (seed) navigate("editor?mode=merge", true);
  }, [library, restored, seed]);

  useEffect(() => {
    if (restored) sessionStorage.setItem(STORE_KEY, JSON.stringify(clips.map((c) => ({ source_id: c.source.id, start: c.start, end: c.end }))));
  }, [clips, restored]);

  const addSource = (source: EditSource) => {
    if (clips.length >= MAX_CLIPS) {
      toast(`A merge can have up to ${MAX_CLIPS} clips.`, "error");
      return;
    }
    const clip = { key: newKey(), source, start: 0, end: source.duration };
    setClips((prev) => [...prev, clip]);
    setSelected(clip.key);
    setView("clip");
  };

  const addDownload = async (d: DownloadTask) => {
    setAdding(d.id);
    try {
      const source = await api.editorFromDownload(d.id);
      addSource(source);
      await loadLibrary();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setAdding(null);
    }
  };

  const uploadFiles = async (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      setUpload({ name: file.name, progress: 0 });
      try {
        addSource(await api.editorUpload(file, (p) => setUpload({ name: file.name, progress: p })));
      } catch (e) {
        toast(`${file.name}: ${(e as Error).message}`, "error");
      }
    }
    setUpload(null);
    if (input.current) input.current.value = "";
    loadLibrary().catch(() => {});
  };

  const update = (key: string, start: number, end: number) => setClips((prev) => prev.map((c) => (c.key === key ? { ...c, start, end } : c)));

  const move = (from: number, to: number) =>
    setClips((prev) => {
      if (to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });

  const remove = (key: string) => {
    setClips((prev) => prev.filter((c) => c.key !== key));
    if (selected === key) setSelected(null);
  };

  const onDropRow = (e: DragEvent, target: number) => {
    e.preventDefault();
    const from = clips.findIndex((c) => c.key === dragKey);
    if (from >= 0) move(from, target);
    setDragKey(null);
  };

  const hasVideo = clips.some((c) => c.source.has_video);
  const hasAudio = clips.some((c) => c.source.has_audio);
  const fmt = hasVideo || clips.length === 0 ? format : "mp3";
  const useFast = fast && fmt === "mp4";
  const firstVideo = clips.find((c) => c.source.has_video)?.source;
  const canvas = firstVideo && fmt === "mp4" && !useFast ? mergeCanvas(firstVideo, frame, resolution) : null;
  const total = clips.reduce((sum, c) => sum + (c.end - c.start), 0);
  const current = clips.find((c) => c.key === selected) ?? null;
  const autoShort = firstVideo ? Math.min(...displaySize(firstVideo)) : null;
  const previewFrame: [number, number] | null = fmt === "mp3" ? null : (canvas ?? (firstVideo ? displaySize(firstVideo) : null));
  const previewKey = clips.map((c) => `${c.key}:${c.start}:${c.end}`).join("|");
  const showClip = view === "clip" && current !== null;
  const pick = (key: string) => {
    setSelected(key);
    setView("clip");
  };

  // Joining without re-encoding only works for identical streams; flag obvious mismatches before the server does.
  const fastMismatch = useMemo(() => {
    if (clips.length < 2) return false;
    const sig = (s: EditSource) => [s.has_video, s.width, s.height, s.rotation, Math.round(s.fps ?? 0), s.audio_codec, s.name.split(".").pop()?.toLowerCase()].join("|");
    return clips.some((c) => !c.source.has_video || sig(c.source) !== sig(clips[0].source));
  }, [clips]);

  const imported = new Set((library ?? []).map((s) => s.download_id).filter(Boolean));
  const freshDownloads = downloads.filter((d) => !imported.has(d.id));

  const doMerge = async () => {
    const req: MergeRequest = {
      clips: clips.map((c) => ({ source_id: c.source.id, start: round3(c.start), end: round3(c.end) })),
      frame,
      fit,
      resolution: useFast ? null : resolution,
      mute: fmt === "mp4" && mute,
      format: fmt,
      quality,
      fast: useFast,
    };
    setBusy(true);
    try {
      onStarted(await api.startMerge(req));
      toast("Merge started. It will save automatically when ready.", "info");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid animate-fade-up gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-5">
        {clips.length > 0 && (
          <Card className="p-4 md:p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <Segmented
                size="sm"
                value={showClip ? "clip" : "merged"}
                onChange={setView}
                options={[
                  { value: "merged", label: "Merged result", icon: <MonitorPlay className="size-3.5" /> },
                  {
                    value: "clip",
                    label: current ? `Trim clip ${clips.findIndex((c) => c.key === current.key) + 1}` : "Trim a clip",
                    icon: <Scissors className="size-3.5" />,
                    disabled: !current,
                  },
                ]}
              />
              <span className="text-[12px] text-fg-3">
                {showClip
                  ? "Set where this clip starts and ends."
                  : `All clips in order, framed like the export${previewFrame ? ` · ${previewFrame[0]}×${previewFrame[1]}` : ""} · ${formatLength(total)}`}
              </span>
            </div>
            {showClip && current ? (
              <ClipPreview
                key={current.key}
                clip={current}
                index={clips.findIndex((c) => c.key === current.key)}
                onChange={(s, e) => update(current.key, s, e)}
              />
            ) : (
              <MergedPreview key={previewKey} clips={clips} frame={previewFrame} fit={useFast ? "pad" : fit} mute={fmt === "mp4" && mute} />
            )}
          </Card>
        )}

        <Card className="p-4 md:p-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-[14px] font-semibold text-fg">
                Clips<span className="ml-2 text-fg-3">{clips.length}</span>
              </h3>
              <p className="text-[12px] text-fg-3">Drag to reorder. Select a clip to trim it; “Merged result” plays them all in order.</p>
            </div>
            {clips.length > 0 && (
              <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => setClips([])}>
                Clear
              </Button>
            )}
          </div>

          {!restored ? (
            <div className="h-24 animate-pulse rounded-xl bg-white/[0.03]" />
          ) : clips.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/[0.1] px-6 py-10 text-center text-[13px] text-fg-3">
              Add two or more videos below. They play one after another in the order shown here.
            </div>
          ) : (
            <>
              <div className="mb-3 flex h-8 gap-0.5 overflow-hidden rounded-lg" aria-hidden>
                {clips.map((c, i) => (
                  <button
                    key={c.key}
                    type="button"
                    tabIndex={-1}
                    onClick={() => pick(c.key)}
                    className={cx(
                      "min-w-[22px] truncate px-1.5 text-[11px] font-medium transition-colors",
                      c.key === selected ? "bg-accent text-white" : i % 2 ? "bg-white/[0.09] text-fg-2" : "bg-white/[0.05] text-fg-2",
                    )}
                    style={{ flexGrow: Math.max(0.1, c.end - c.start) }}
                    title={`${i + 1}. ${c.source.name} · ${formatLength(c.end - c.start)}`}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
              <div className="space-y-1.5">
                {clips.map((c, i) => (
                  <div
                    key={c.key}
                    draggable
                    onDragStart={() => setDragKey(c.key)}
                    onDragEnd={() => setDragKey(null)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => onDropRow(e, i)}
                    onClick={() => pick(c.key)}
                    className={cx(
                      "flex cursor-pointer items-center gap-2.5 rounded-xl border p-2 pr-1.5 transition-colors",
                      c.key === selected ? "border-accent/50 bg-accent/[0.08]" : "border-white/[0.06] bg-black/20 hover:border-white/[0.12]",
                      dragKey === c.key && "opacity-50",
                    )}
                  >
                    <GripVertical className="size-4 shrink-0 cursor-grab text-fg-3" />
                    <span className="tabular w-5 shrink-0 text-center text-[12px] font-semibold text-fg-2">{i + 1}</span>
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">
                      {c.source.has_video ? <Film className="size-3.5" /> : <AudioWaveform className="size-3.5" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium text-fg" title={c.source.name}>
                        {c.source.name}
                      </div>
                      <div className="tabular text-[11.5px] text-fg-3">
                        {fmtDuration(c.start)} → {fmtDuration(c.end)} · {formatLength(c.end - c.start)}
                        {c.source.has_video ? ` · ${displaySize(c.source).join("×")}` : " · audio"}
                        {!c.source.has_audio && c.source.has_video ? " · no sound" : ""}
                      </div>
                    </div>
                    <IconButton
                      label="Move up"
                      disabled={i === 0}
                      onClick={(e) => {
                        e.stopPropagation();
                        move(i, i - 1);
                      }}
                    >
                      <ArrowUp className="size-4" />
                    </IconButton>
                    <IconButton
                      label="Move down"
                      disabled={i === clips.length - 1}
                      onClick={(e) => {
                        e.stopPropagation();
                        move(i, i + 1);
                      }}
                    >
                      <ArrowDown className="size-4" />
                    </IconButton>
                    <IconButton
                      label="Remove clip"
                      onClick={(e) => {
                        e.stopPropagation();
                        remove(c.key);
                      }}
                    >
                      <Trash2 className="size-4" />
                    </IconButton>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>

        <Card className="p-4 md:p-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-[14px] font-semibold text-fg">Add clips</h3>
            <input ref={input} type="file" multiple accept={MEDIA_ACCEPT} className="hidden" onChange={(e) => void uploadFiles(e.target.files)} />
            <Button size="sm" icon={<CloudUpload className="size-3.5" />} disabled={!!upload} onClick={() => input.current?.click()}>
              Upload files
            </Button>
          </div>
          {upload && (
            <div className="mb-3 rounded-xl border border-white/[0.06] bg-black/20 p-3">
              <div className="mb-2 truncate text-[12.5px] text-fg-2">{upload.name}</div>
              <ProgressBar value={upload.progress} active={upload.progress >= 1} />
            </div>
          )}
          {library === null ? (
            <div className="h-16 animate-pulse rounded-xl bg-white/[0.03]" />
          ) : library.length === 0 && freshDownloads.length === 0 ? (
            <p className="text-[13px] text-fg-3">
              Upload files, or <a href="#/download" className="text-accent-soft hover:text-white">download a video</a> first.
            </p>
          ) : (
            <div className="max-h-[320px] space-y-1.5 overflow-y-auto pr-1">
              {library.map((s) => (
                <div key={s.id} className="flex items-center gap-2.5 rounded-xl border border-white/[0.06] bg-black/20 p-2">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">
                    {s.has_video ? <Film className="size-3.5" /> : <AudioWaveform className="size-3.5" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] text-fg" title={s.name}>
                      {s.name}
                    </div>
                    <div className="text-[11.5px] text-fg-3">
                      {fmtDuration(s.duration)} · {fmtBytes(s.size)}
                      {s.has_video ? ` · ${displaySize(s).join("×")}` : " · audio"}
                    </div>
                  </div>
                  <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => addSource(s)}>
                    Add
                  </Button>
                </div>
              ))}
              {freshDownloads.map((d) => (
                <div key={d.id} className="flex items-center gap-2.5 rounded-xl border border-white/[0.06] bg-black/20 p-2">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">
                    <Film className="size-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] text-fg" title={d.title}>
                      {d.title}
                    </div>
                    <div className="text-[11.5px] text-fg-3">
                      Download · {d.label} · {fmtBytes(d.file_size)}
                    </div>
                  </div>
                  <Button size="sm" icon={<Plus className="size-3.5" />} loading={adding === d.id} onClick={() => void addDownload(d)}>
                    Add
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card className="h-fit space-y-6 p-5 lg:sticky lg:top-6">
        <ToolSection title="Export as">
          <Segmented
            full
            size="sm"
            value={fmt}
            onChange={setFormat}
            options={[
              { value: "mp4", label: "Video", icon: <Film className="size-3.5" />, disabled: clips.length > 0 && !hasVideo },
              { value: "mp3", label: "MP3", icon: <AudioWaveform className="size-3.5" />, disabled: clips.length > 0 && !hasAudio },
            ]}
          />
        </ToolSection>

        {fmt === "mp4" && !useFast && (
          <>
            <ToolSection title="Frame" hint="Every clip is fitted into this frame.">
              <div className="flex flex-wrap gap-1.5">
                {FRAMES.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    title={f.hint}
                    onClick={() => setFrame(f.value)}
                    className={cx(
                      "inline-flex h-7 items-center rounded-full border px-2.5 text-[12.5px] transition-all",
                      frame === f.value ? "border-accent/60 bg-accent/15 text-fg" : "border-white/[0.08] text-fg-2 hover:border-white/20 hover:text-fg",
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </ToolSection>

            <ToolSection title="Clips with a different shape">
              <Segmented
                full
                size="sm"
                value={fit}
                onChange={setFit}
                options={[
                  { value: "pad", label: "Black bars", hint: "Show the whole picture, with bars where it doesn't fill the frame" },
                  { value: "crop", label: "Fill & crop", hint: "Fill the frame and cut off the edges that don't fit" },
                ]}
              />
            </ToolSection>

            <ToolSection title="Resolution">
              <Select value={resolution ?? ""} onChange={(e) => setResolution(e.target.value ? Number(e.target.value) : null)}>
                <option value="">{autoShort ? `Auto (${autoShort}p, from the first clip)` : "Auto (from the first clip)"}</option>
                {RESOLUTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}p
                  </option>
                ))}
              </Select>
            </ToolSection>
          </>
        )}

        {fmt === "mp4" && (
          <ToolSection title="Options">
            <div className="space-y-4">
              {hasAudio && <Toggle checked={mute} onChange={setMute} label="Remove audio" />}
              <Toggle
                checked={useFast}
                onChange={setFast}
                label={
                  <span className="inline-flex items-center gap-1.5">
                    <Zap className="size-3.5 text-warn" /> Fast merge
                  </span>
                }
                description={
                  fastMismatch
                    ? "These clips differ in size, frame rate or format, so a fast merge would be refused. Leave it off to re-encode."
                    : "No re-encoding: instant and keeps the original quality. Needs clips in the same format (e.g. parts of one video). Cuts snap to keyframes."
                }
              />
            </div>
          </ToolSection>
        )}

        {fmt === "mp4" && !useFast && (
          <ToolSection title="Quality">
            <Segmented
              full
              size="sm"
              value={quality}
              onChange={setQuality}
              options={[
                { value: "high", label: "High" },
                { value: "balanced", label: "Balanced" },
                { value: "small", label: "Small file" },
              ]}
            />
          </ToolSection>
        )}

        <div className="space-y-2 rounded-xl border border-white/[0.06] bg-black/25 p-3.5 text-[12.5px]">
          <div className="flex justify-between">
            <span className="text-fg-3">Output</span>
            <span className="tabular font-medium text-fg">{fmt === "mp3" ? "Audio only" : useFast ? "Same as the clips" : canvas ? `${canvas[0]}×${canvas[1]}` : "—"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-3">Clips</span>
            <span className="tabular font-medium text-fg">{clips.length}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-3">Length</span>
            <span className="tabular font-medium text-fg">{formatLength(total)}</span>
          </div>
          {fmt === "mp4" && !useFast && (
            <div className="flex justify-between gap-3">
              <span className="text-fg-3">Encoder</span>
              <span className="truncate font-medium text-fg">{encoderText(gpu)}</span>
            </div>
          )}
        </div>
        {clips.length === 1 && <Notice tone="info">Add at least one more clip to merge.</Notice>}

        <Button
          variant="primary"
          size="lg"
          className="w-full"
          icon={<Merge className="size-4" />}
          loading={busy}
          disabled={clips.length < 2 || !!upload}
          onClick={doMerge}
        >
          Merge {clips.length >= 2 ? `${clips.length} clips` : "clips"}
        </Button>
      </Card>
    </div>
  );
}
