import {
  ArrowLeftRight,
  ArrowUpDown,
  AudioWaveform,
  BadgeCheck,
  Captions,
  CircleX,
  Clock,
  CloudUpload,
  Download,
  Film,
  ImagePlay,
  LoaderCircle,
  Merge,
  Pause,
  Play,
  Repeat,
  RotateCcw,
  RotateCw,
  Scissors,
  Trash2,
  Undo2,
  Volume2,
  VolumeX,
  X,
  Zap,
} from "lucide-react";
import type { DragEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CropOverlay, fitCrop } from "../components/CropOverlay";
import { MergeWorkspace, encoderText, useGpuStatus } from "../components/MergeWorkspace";
import { Thumb } from "../components/Thumb";
import { TimeInput } from "../components/TimeInput";
import { useToast } from "../components/Toast";
import { TrimBar } from "../components/TrimBar";
import { Badge, Button, Card, Chip, Field, IconButton, Input, Notice, ProgressBar, Segmented, Select, Toggle, ToolSection } from "../components/ui";
import { api } from "../lib/api";
import { useApp } from "../lib/app-context";
import { browserDecodes, useCompatAudio } from "../lib/compat-audio";
import { cx, fmtBytes, fmtDuration, relativeTime } from "../lib/format";
import { navigate, useRoute } from "../lib/router";
import { formatLength } from "../lib/time";
import type { CaptionStyle, CropBox, DownloadTask, EditSource, ExportFormat, ExportTask } from "../lib/types";

const MEDIA_ACCEPT = ".mp4,.mkv,.mov,.webm,.avi,.m4v,.wmv,.flv,.mpg,.mpeg,.ts,.mp3,.wav,.m4a,.flac,.ogg,.opus,.aac";
const ACTIVE = new Set(["queued", "running"]);
const ASPECTS: { key: string; label: string; value: number | null; hint?: string }[] = [
  { key: "off", label: "Off", value: null },
  { key: "free", label: "Free", value: null },
  { key: "9:16", label: "9:16", value: 9 / 16, hint: "Shorts · Reels · TikTok" },
  { key: "1:1", label: "1:1", value: 1, hint: "Square posts" },
  { key: "4:5", label: "4:5", value: 4 / 5, hint: "Instagram portrait" },
  { key: "16:9", label: "16:9", value: 16 / 9, hint: "YouTube, widescreen" },
  { key: "4:3", label: "4:3", value: 4 / 3 },
];
const HEIGHTS = [2160, 1440, 1080, 720, 480, 360];
const even = (n: number) => Math.max(2, Math.floor(n / 2 + 0.01) * 2);

function fmtPrecise(sec: number): string {
  const s = Math.max(0, sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = (s % 60).toFixed(1).padStart(4, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

function saveExport(task: ExportTask) {
  const a = document.createElement("a");
  a.href = api.exportFileUrl(task.id);
  a.download = task.file_name ?? "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ------------------------------------------------------------------ source picker

function SourcePicker() {
  const toast = useToast();
  const [sources, setSources] = useState<EditSource[] | null>(null);
  const [downloads, setDownloads] = useState<DownloadTask[] | null>(null);
  const [upload, setUpload] = useState<{ name: string; progress: number } | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.editorSources().then(setSources).catch(() => setSources([]));
    api
      .downloads()
      .then((all) => setDownloads(all.filter((d) => d.status === "done")))
      .catch(() => setDownloads([]));
  }, []);

  const send = async (file: File | undefined) => {
    if (!file || upload) return;
    const ctrl = new AbortController();
    abort.current = ctrl;
    setUpload({ name: file.name, progress: 0 });
    try {
      const src = await api.editorUpload(file, (p) => setUpload({ name: file.name, progress: p }), ctrl.signal);
      navigate(`editor?source=${src.id}`);
    } catch (e) {
      if (!ctrl.signal.aborted) toast((e as Error).message, "error");
    } finally {
      setUpload(null);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    void send(e.dataTransfer.files[0]);
  };

  const removeSource = async (src: EditSource) => {
    try {
      await api.deleteEditorSource(src.id);
      setSources((prev) => (prev ?? []).filter((s) => s.id !== src.id));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <div className="grid animate-fade-up gap-5 lg:grid-cols-[1.15fr_1fr]">
      <Card className="p-2">
        <div
          role="button"
          tabIndex={0}
          onClick={() => !upload && input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !upload && input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={cx(
            "flex h-full min-h-[300px] cursor-pointer flex-col items-center justify-center rounded-[14px] border border-dashed px-8 py-12 text-center transition-all duration-200",
            drag ? "border-accent/70 bg-accent/[0.07]" : "border-white/[0.12] bg-black/15 hover:border-white/25 hover:bg-white/[0.02]",
          )}
        >
          <input ref={input} type="file" accept={MEDIA_ACCEPT} className="hidden" onChange={(e) => void send(e.target.files?.[0])} />
          {upload ? (
            <div className="w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
              <div className="mb-3 truncate text-sm font-medium text-fg">{upload.name}</div>
              <ProgressBar value={upload.progress} active={upload.progress >= 1} />
              <div className="mt-2 flex items-center justify-between text-[12px] text-fg-3">
                <span className="tabular">{upload.progress >= 1 ? "Reading the file…" : `Uploading · ${Math.round(upload.progress * 100)}%`}</span>
                {upload.progress < 1 && (
                  <button type="button" onClick={() => abort.current?.abort()} className="font-medium text-fg-2 hover:text-fg">
                    Cancel
                  </button>
                )}
              </div>
            </div>
          ) : (
            <>
              <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-accent text-white">
                <CloudUpload className="size-6" />
              </div>
              <div className="text-[16px] font-semibold text-fg">Drop a video or audio file</div>
              <div className="mt-1.5 text-[13px] text-fg-3">or click to browse · MP4, MOV, MKV, WebM, MP3, WAV… up to 20 GB</div>
            </>
          )}
        </div>
      </Card>

      <div className="space-y-5">
        <Card className="p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-[14px] font-semibold text-fg">From your downloads</h3>
            <a href="#/download" className="text-[12.5px] font-medium text-accent-soft hover:text-white">
              Download a video
            </a>
          </div>
          {downloads === null ? (
            <div className="h-16 animate-pulse rounded-xl bg-white/[0.03]" />
          ) : downloads.length === 0 ? (
            <p className="text-[13px] text-fg-3">Videos you download from YouTube show up here, ready to trim and crop.</p>
          ) : (
            <div className="space-y-2">
              {downloads.slice(0, 5).map((d) => (
                <div key={d.id} className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-black/20 p-2.5">
                  <Thumb src={d.thumbnail} kind="youtube" className="aspect-video w-[72px] shrink-0 rounded-md" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium text-fg">{d.title}</div>
                    <div className="text-[11.5px] text-fg-3">
                      {d.label} · {fmtBytes(d.file_size)}
                    </div>
                  </div>
                  <Button size="sm" icon={<Scissors className="size-3.5" />} onClick={() => navigate(`editor?download=${d.id}`)}>
                    Edit
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>

        {sources && sources.length > 0 && (
          <Card className="p-5">
            <h3 className="mb-3 text-[14px] font-semibold text-fg">Recent in the editor</h3>
            <div className="space-y-2">
              {sources.slice(0, 6).map((s) => (
                <div key={s.id} className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-black/20 p-2.5">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">
                    {s.has_video ? <Film className="size-4" /> : <AudioWaveform className="size-4" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium text-fg">{s.name}</div>
                    <div className="text-[11.5px] text-fg-3">
                      {fmtDuration(s.duration)} · {fmtBytes(s.size)}
                      {s.width && s.height ? ` · ${s.width}×${s.height}` : ""}
                    </div>
                  </div>
                  <Button size="sm" onClick={() => navigate(`editor?source=${s.id}`)}>
                    Open
                  </Button>
                  <IconButton label="Remove from editor" onClick={() => removeSource(s)}>
                    <Trash2 className="size-4" />
                  </IconButton>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ workspace

/** A clip handed over from the Results page: its range, title and the analysis whose transcript feeds captions. */
interface ClipPreset {
  start: number;
  end: number;
  title: string;
  analysis: string | null;
  asrc: string | null;
}

function Workspace({ source, preset, onStarted }: { source: EditSource; preset: ClipPreset | null; onStarted: (task: ExportTask) => void }) {
  const toast = useToast();
  const gpu = useGpuStatus();
  const { health } = useApp();
  const video = useRef<HTMLVideoElement>(null);
  const [dims, setDims] = useState({ w: source.width || 1920, h: source.height || 1080 });
  const [duration, setDuration] = useState(source.duration);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loopSel, setLoopSel] = useState(!!preset);
  const [mediaError, setMediaError] = useState(false);
  const [range, setRange] = useState(() => {
    if (!preset) return { start: 0, end: source.duration };
    const end = Math.min(source.duration, Math.max(preset.end, 0.1));
    return { start: Math.max(0, Math.min(preset.start, end - 0.1)), end };
  });
  const [title, setTitle] = useState(preset?.title ?? "");
  const [captions, setCaptions] = useState<"off" | CaptionStyle>("off");
  const [captionPos, setCaptionPos] = useState<"bottom" | "center">("bottom");
  const [normalize, setNormalize] = useState(false);
  const [aspect, setAspect] = useState("off");
  const [crop, setCrop] = useState<CropBox>(() => fitCrop(null, 16 / 9));
  const [rotate, setRotate] = useState<0 | 90 | 180 | 270>(0);
  const [flipH, setFlipH] = useState(false);
  const [flipV, setFlipV] = useState(false);
  const [height, setHeight] = useState<number | null>(null);
  const [mute, setMute] = useState(false);
  const [format, setFormat] = useState<ExportFormat>(source.has_video ? "mp4" : "mp3");
  const [quality, setQuality] = useState<"high" | "balanced" | "small">("balanced");
  const [fast, setFast] = useState(false);
  const [busy, setBusy] = useState(false);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);

  const previewUrl = source.has_audio ? api.editorPreviewAudioUrl(source.id) : null;
  const [mediaSrc, setMediaSrc] = useState(() =>
    !source.has_video && previewUrl && browserDecodes(source.audio_codec) !== true ? previewUrl : api.editorMediaUrl(source.id),
  );
  const compat = useCompatAudio(video, previewUrl, { codec: source.audio_codec, enabled: source.has_video && source.has_audio });

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    v.volume = volume;
    v.muted = muted;
  }, [volume, muted]);

  const visual = source.has_video && format !== "mp3";
  const cropOn = visual && aspect !== "off";
  const transforms = visual && (cropOn || rotate !== 0 || flipH || flipV || height !== null);
  const captionsOn = format === "mp4" && source.has_video && captions !== "off";
  const canNormalize = format !== "gif" && source.has_audio && !(format === "mp4" && mute);
  const normalizeOn = canNormalize && normalize;
  const useFast = fast && format === "mp4" && !transforms && !captionsOn && !normalizeOn;
  const captionsNeedWhisper = !preset?.analysis && health?.capabilities.whisper === false;
  const selLength = range.end - range.start;

  // Smooth playhead while playing; loop the selection when asked.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const v = video.current;
      if (v) {
        if (loopSel && v.currentTime >= range.end) v.currentTime = range.start;
        setTime(v.currentTime);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, loopSel, range.start, range.end]);

  const seek = useCallback((t: number) => {
    const v = video.current;
    if (v) v.currentTime = t;
    setTime(t);
  }, []);

  const togglePlay = useCallback(() => {
    const v = video.current;
    if (!v) return;
    if (v.paused) {
      if (loopSel && (v.currentTime < range.start || v.currentTime >= range.end)) v.currentTime = range.start;
      void v.play();
    } else v.pause();
  }, [loopSel, range.start, range.end]);

  const markIn = useCallback(() => setRange((r) => ({ start: Math.min(time, r.end - 0.1), end: r.end })), [time]);
  const markOut = useCallback(() => setRange((r) => ({ start: r.start, end: Math.max(time, r.start + 0.1) })), [time]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === " ") {
        e.preventDefault();
        togglePlay();
      } else if (e.key === "i" || e.key === "I") markIn();
      else if (e.key === "o" || e.key === "O") markOut();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePlay, markIn, markOut]);

  const pickAspect = (key: string) => {
    setAspect(key);
    const a = ASPECTS.find((x) => x.key === key);
    if (key !== "off") setCrop(fitCrop(a?.value ?? null, dims.w / dims.h));
    if (key !== "off") setFast(false);
  };

  const aspectValue = ASPECTS.find((a) => a.key === aspect)?.value ?? null;

  const out = useMemo(() => {
    let w = cropOn ? even(crop.w * dims.w) : dims.w;
    let h = cropOn ? even(crop.h * dims.h) : dims.h;
    if (rotate === 90 || rotate === 270) [w, h] = [h, w];
    const preScaleH = h;
    if (height && h > height) {
      w = even((w * height) / h);
      h = height;
    }
    if (format === "gif" && !height && w > 480) {
      h = even((h * 480) / w);
      w = 480;
    }
    return { w, h, preScaleH };
  }, [cropOn, crop, dims, rotate, height, format]);

  const heightChoices = HEIGHTS.filter((h) => h < out.preScaleH);

  const doExport = async () => {
    setBusy(true);
    try {
      const task = await api.startExport({
        source_id: source.id,
        start: Math.round(range.start * 1000) / 1000,
        end: Math.round(range.end * 1000) / 1000,
        crop: cropOn ? crop : null,
        rotate: visual ? rotate : 0,
        flip_h: visual && flipH,
        flip_v: visual && flipV,
        height: visual ? height : null,
        mute: format === "mp4" && mute,
        format,
        quality,
        fast: useFast,
        normalize: normalizeOn,
        captions: captionsOn
          ? { style: captions as CaptionStyle, position: captionPos, analysis_id: preset?.analysis ?? null, analysis_source: preset?.asrc ?? null }
          : null,
        title: title.trim() || null,
      });
      onStarted(task);
      toast("Export started. It will save automatically when ready.", "info");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const gifTooLong = format === "gif" && selLength > 60;

  return (
    <div className="grid animate-fade-up gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Card className="p-4 md:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">
            {source.has_video ? <Film className="size-4" /> : <AudioWaveform className="size-4" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-semibold text-fg" title={source.name}>
              {source.name}
            </div>
            <div className="text-[12px] text-fg-3">
              {fmtDuration(source.duration)} · {fmtBytes(source.size)}
              {source.has_video ? ` · ${dims.w}×${dims.h}` : " · audio"}
              {source.fps ? ` · ${Math.round(source.fps)} fps` : ""}
            </div>
          </div>
          <Button size="sm" variant="ghost" icon={<Merge className="size-3.5" />} onClick={() => navigate(`editor?mode=merge&add=${source.id}`)}>
            Merge with other clips
          </Button>
          <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} onClick={() => navigate("editor")}>
            Change file
          </Button>
        </div>

        <div className="flex justify-center rounded-2xl bg-black/40 p-3 ring-1 ring-inset ring-white/[0.04]">
          <div
            className="relative overflow-hidden rounded-lg bg-black"
            style={
              source.has_video
                ? { aspectRatio: `${dims.w} / ${dims.h}`, width: `min(100%, calc(56vh * ${dims.w / dims.h}))` }
                : { width: "100%", height: 180 }
            }
          >
            <video
              ref={video}
              src={mediaSrc}
              preload="auto"
              playsInline
              onLoadedMetadata={(e) => {
                const v = e.currentTarget;
                if (v.videoWidth && v.videoHeight) setDims({ w: v.videoWidth, h: v.videoHeight });
                if (Number.isFinite(v.duration) && v.duration > 0) setDuration(v.duration);
                if (preset && v.currentTime === 0) {
                  v.currentTime = range.start;
                  setTime(range.start);
                }
              }}
              onPlay={() => setPlaying(true)}
              onPause={() => {
                setPlaying(false);
                setTime(video.current?.currentTime ?? 0);
              }}
              onSeeked={(e) => setTime(e.currentTarget.currentTime)}
              onError={() => {
                if (!source.has_video && previewUrl && mediaSrc !== previewUrl) setMediaSrc(previewUrl);
                else setMediaError(true);
              }}
              onClick={() => !cropOn && togglePlay()}
              className="absolute inset-0 size-full object-contain"
            />
            {!source.has_video && (
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-fg-3">
                <AudioWaveform className="size-10" />
                <span className="text-[12px]">Audio file</span>
              </div>
            )}
            {cropOn && <CropOverlay box={crop} aspect={aspectValue} frameWidth={dims.w} frameHeight={dims.h} onChange={setCrop} />}
          </div>
        </div>

        {mediaError && (
          <div className="mt-3">
            <Notice>
              Your browser can't preview this file's codec. You can still type trim times and export. The export is converted to a format that
              plays everywhere.
            </Notice>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant="primary" size="sm" icon={playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} onClick={togglePlay}>
            {playing ? "Pause" : "Play"}
          </Button>
          <span className="tabular text-[13px] text-fg-2">
            {fmtPrecise(time)} <span className="text-fg-3">/ {fmtPrecise(duration)}</span>
          </span>
          {source.has_audio && (
            <div className="flex items-center gap-1.5">
              <IconButton label={muted ? "Unmute" : "Mute"} onClick={() => setMuted((m) => !m)}>
                {muted || volume === 0 ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
              </IconButton>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={muted ? 0 : volume}
                aria-label="Volume"
                onChange={(e) => {
                  setVolume(Number(e.target.value));
                  setMuted(false);
                }}
                className="h-1.5 w-20 cursor-pointer appearance-none rounded-full"
                style={{ background: `linear-gradient(90deg, var(--color-accent) ${(muted ? 0 : volume) * 100}%, rgba(255,255,255,0.12) ${(muted ? 0 : volume) * 100}%)` }}
              />
              {compat === "loading" && (
                <Badge tone="warn" icon={<LoaderCircle className="size-3 animate-spin" />}>
                  Preparing audio…
                </Badge>
              )}
              {compat === "ready" && (
                <span title="This browser can't decode the file's audio codec, so an MP3 copy plays in sync. Exports keep the original audio.">
                  <Badge tone="neutral">Audio via MP3 preview</Badge>
                </span>
              )}
              {compat === "error" && <Badge tone="neg">Audio preview failed</Badge>}
            </div>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Chip active={loopSel} icon={<Repeat className="size-3.5" />} onClick={() => setLoopSel((v) => !v)}>
              Loop selection
            </Chip>
            <Button size="sm" onClick={markIn} title="Shortcut: I">
              Set start <kbd className="ml-1 rounded bg-white/[0.08] px-1 text-[10.5px] text-fg-3">I</kbd>
            </Button>
            <Button size="sm" onClick={markOut} title="Shortcut: O">
              Set end <kbd className="ml-1 rounded bg-white/[0.08] px-1 text-[10.5px] text-fg-3">O</kbd>
            </Button>
          </div>
        </div>

        <div className="mt-4">
          <TrimBar
            duration={duration}
            start={range.start}
            end={range.end}
            time={time}
            onChange={(start, end) => setRange({ start, end })}
            onSeek={seek}
          />
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <TimeInput
            label="Start"
            value={range.start}
            placeholder="e.g. 1:05 or 65"
            onCommit={(v) => {
              const s = Math.min(Math.max(0, v), range.end - 0.1);
              setRange((r) => ({ start: s, end: r.end }));
              seek(s);
            }}
          />
          <TimeInput
            label="End"
            value={range.end}
            placeholder="e.g. 2:30"
            onCommit={(v) => {
              const en = Math.min(duration, Math.max(v, range.start + 0.1));
              setRange((r) => ({ start: r.start, end: en }));
              seek(en);
            }}
          />
          <Field label="Selection">
            <div className="flex h-10 items-center justify-between rounded-xl border border-white/[0.06] bg-black/20 px-3.5">
              <span className="tabular text-sm font-medium text-fg">{formatLength(selLength)}</span>
              {(range.start > 0 || range.end < duration) && (
                <button type="button" className="text-[12px] text-fg-3 hover:text-fg" onClick={() => setRange({ start: 0, end: duration })}>
                  Reset
                </button>
              )}
            </div>
          </Field>
        </div>
        <p className="mt-3 text-[12px] text-fg-3">
          Drag the purple handles or press <kbd className="rounded bg-white/[0.08] px-1">I</kbd> /{" "}
          <kbd className="rounded bg-white/[0.08] px-1">O</kbd> at the playhead. <kbd className="rounded bg-white/[0.08] px-1">Space</kbd> plays.
        </p>
      </Card>

      <Card className="h-fit space-y-6 p-5 lg:sticky lg:top-6">
        <ToolSection title="Export as">
          <Segmented
            full
            size="sm"
            value={format}
            onChange={(v) => {
              setFormat(v);
              if (v !== "mp4") setFast(false);
            }}
            options={[
              { value: "mp4", label: "Video", icon: <Film className="size-3.5" />, disabled: !source.has_video },
              { value: "mp3", label: "MP3", icon: <AudioWaveform className="size-3.5" />, disabled: !source.has_audio },
              { value: "gif", label: "GIF", icon: <ImagePlay className="size-3.5" />, disabled: !source.has_video },
            ]}
          />
        </ToolSection>

        {visual && (
          <ToolSection title="Crop" hint={cropOn ? "Drag inside to move (hold Shift for a straight line). Side bars resize one direction; corners resize both." : "Pick a shape to crop the frame."}>
            <div className="flex flex-wrap gap-1.5">
              {ASPECTS.map((a) => (
                <Chip key={a.key} active={aspect === a.key} title={a.hint} onClick={() => pickAspect(a.key)} className="h-7 px-2.5 text-[12.5px]">
                  {a.label}
                </Chip>
              ))}
            </div>
          </ToolSection>
        )}

        {visual && (
          <ToolSection title="Rotate & flip" hint={rotate || flipH || flipV ? "Applied when you export." : undefined}>
            <div className="flex items-center gap-1.5">
              <IconButton label="Rotate left" onClick={() => setRotate((r) => ((r + 270) % 360) as 0 | 90 | 180 | 270)} className="size-9 bg-white/[0.04]">
                <RotateCcw className="size-4" />
              </IconButton>
              <IconButton label="Rotate right" onClick={() => setRotate((r) => ((r + 90) % 360) as 0 | 90 | 180 | 270)} className="size-9 bg-white/[0.04]">
                <RotateCw className="size-4" />
              </IconButton>
              <IconButton label="Flip horizontally" active={flipH} onClick={() => setFlipH((v) => !v)} className="size-9 bg-white/[0.04]">
                <ArrowLeftRight className="size-4" />
              </IconButton>
              <IconButton label="Flip vertically" active={flipV} onClick={() => setFlipV((v) => !v)} className="size-9 bg-white/[0.04]">
                <ArrowUpDown className="size-4" />
              </IconButton>
              <span className="ml-2 tabular text-[12.5px] text-fg-2">{rotate}°</span>
            </div>
          </ToolSection>
        )}

        {visual && (
          <ToolSection title="Resize">
            <Select value={height ?? ""} onChange={(e) => setHeight(e.target.value ? Number(e.target.value) : null)}>
              <option value="">{format === "gif" ? "Auto (max 480 px wide)" : "Original size"}</option>
              {heightChoices.map((h) => (
                <option key={h} value={h}>
                  {h}p
                </option>
              ))}
            </Select>
          </ToolSection>
        )}

        {format === "mp4" && source.has_video && (
          <ToolSection
            title="Captions"
            hint={
              captions === "off"
                ? "Burn the spoken words into the video, a few words at a time, like Shorts and Reels."
                : preset?.analysis
                  ? "Words come from this clip’s analysis transcript. If it has no transcript here, the clip is transcribed with Whisper first."
                  : "The clip is transcribed with Whisper on this server first, which adds some time before the export starts."
            }
          >
            <div className="space-y-2.5">
              <Segmented
                full
                size="sm"
                value={captions}
                onChange={(v) => {
                  setCaptions(v);
                  if (v !== "off") setFast(false);
                }}
                options={[
                  { value: "off", label: "Off" },
                  { value: "bold", label: "Bold", icon: <Captions className="size-3.5" /> },
                  { value: "classic", label: "Classic" },
                  { value: "boxed", label: "Boxed" },
                ]}
              />
              {captions !== "off" && (
                <Segmented
                  full
                  size="sm"
                  value={captionPos}
                  onChange={setCaptionPos}
                  options={[
                    { value: "bottom", label: "Bottom" },
                    { value: "center", label: "Middle" },
                  ]}
                />
              )}
              {captions !== "off" && captionsNeedWhisper && (
                <Notice tone="warn">Whisper is not installed, so captions only work for clips opened from an analysis that has a transcript.</Notice>
              )}
            </div>
          </ToolSection>
        )}

        {format === "mp4" && (
          <ToolSection title="Options">
            <div className="space-y-4">
              {source.has_audio && <Toggle checked={mute} onChange={setMute} label="Remove audio" />}
              {canNormalize && (
                <Toggle
                  checked={normalizeOn}
                  onChange={(v) => {
                    setNormalize(v);
                    if (v) setFast(false);
                  }}
                  label="Even out the volume"
                  description="Sets loudness to −14 LUFS, the level YouTube, TikTok and Instagram play at, so quiet clips are not drowned out. Re-encodes the audio."
                />
              )}
              <Toggle
                checked={useFast}
                disabled={transforms || captionsOn || normalizeOn}
                onChange={setFast}
                label={
                  <span className="inline-flex items-center gap-1.5">
                    <Zap className="size-3.5 text-warn" /> Fast cut
                  </span>
                }
                description={
                  transforms || captionsOn || normalizeOn
                    ? "Only for plain trims, so turn crop, rotate, resize, captions and volume levelling off first."
                    : "No re-encoding: instant and keeps the original quality. Cuts snap to the nearest keyframe."
                }
              />
            </div>
          </ToolSection>
        )}

        {format === "mp3" && canNormalize && (
          <ToolSection title="Options">
            <Toggle
              checked={normalizeOn}
              onChange={setNormalize}
              label="Even out the volume"
              description="Sets loudness to −14 LUFS, the level streaming apps play at."
            />
          </ToolSection>
        )}

        <ToolSection title="File name" hint="Optional. Leave empty to name it after the source and the time range.">
          <Input value={title} maxLength={120} placeholder={source.name.replace(/\.[^.]+$/, "")} onChange={(e) => setTitle(e.target.value)} />
        </ToolSection>

        {format === "mp4" && !useFast && (
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
            <span className="tabular font-medium text-fg">
              {format === "mp3" ? "Audio only" : useFast ? "Original frame" : `${out.w}×${out.h}`}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-3">Length</span>
            <span className={cx("tabular font-medium", gifTooLong ? "text-neg" : "text-fg")}>{formatLength(selLength)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-3">File</span>
            <span className="font-medium text-fg">
              {useFast ? "Same as source" : format === "mp4" ? "MP4 · H.264" : format === "mp3" ? "MP3" : "Animated GIF"}
            </span>
          </div>
          {format === "mp4" && !useFast && (
            <div className="flex justify-between gap-3">
              <span className="text-fg-3">Encoder</span>
              <span className="truncate font-medium text-fg">{encoderText(gpu)}</span>
            </div>
          )}
          {(captionsOn || normalizeOn) && (
            <div className="flex justify-between gap-3">
              <span className="text-fg-3">Extras</span>
              <span className="truncate font-medium text-fg">
                {[captionsOn ? `${captions} captions` : null, normalizeOn ? "−14 LUFS" : null].filter(Boolean).join(" · ")}
              </span>
            </div>
          )}
        </div>
        {gifTooLong && <Notice tone="neg">GIFs are limited to 60 seconds. Shorten the selection.</Notice>}

        <Button variant="primary" size="lg" className="w-full" icon={<Scissors className="size-4" />} loading={busy} disabled={gifTooLong} onClick={doExport}>
          Export {format === "mp4" ? (useFast ? "clip" : "video") : format.toUpperCase()}
        </Button>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ exports list

function ExportRow({ task, onCancel, onDelete }: { task: ExportTask; onCancel: () => void; onDelete: () => void }) {
  const active = ACTIVE.has(task.status);
  let detail: string;
  if (task.status === "queued") detail = task.stage || "Waiting for the previous export to finish…";
  else if (task.status === "running" && task.stage) detail = task.stage;
  else if (task.status === "running")
    detail = [
      `${Math.round(task.progress * 100)}%`,
      task.speed ? `${task.speed.toFixed(1)}× realtime` : null,
      task.eta != null ? `${fmtDuration(task.eta)} left` : null,
      task.encoder,
    ]
      .filter(Boolean)
      .join(" · ");
  else if (task.status === "done")
    detail = [`Ready · ${fmtBytes(task.file_size)} · ${relativeTime(task.finished_at ?? task.created_at)}`, task.encoder].filter(Boolean).join(" · ");
  else if (task.status === "cancelled") detail = "Cancelled";
  else detail = task.error || "Export failed";

  return (
    <div className="flex items-center gap-4 rounded-xl border border-white/[0.06] bg-black/20 p-3">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">
        {task.label.startsWith("Merge") ? (
          <Merge className="size-4" />
        ) : task.format === "mp3" ? (
          <AudioWaveform className="size-4" />
        ) : task.format === "gif" ? (
          <ImagePlay className="size-4" />
        ) : (
          <Film className="size-4" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <div className="truncate text-[13.5px] font-medium text-fg" title={task.file_name ?? task.source_name}>
            {task.file_name ?? task.source_name}
          </div>
          <Badge className="shrink-0">{task.label}</Badge>
        </div>
        {active && (
          <div className="mt-2">
            <ProgressBar value={task.progress} active={task.status === "queued"} />
          </div>
        )}
        <div
          className={cx(
            "mt-1.5 flex items-center gap-1.5 truncate text-[12px]",
            task.status === "error" ? "text-neg" : task.status === "done" ? "text-pos" : "text-fg-3",
          )}
        >
          {task.status === "done" && <BadgeCheck className="size-3.5 shrink-0" />}
          {task.status === "error" && <CircleX className="size-3.5 shrink-0" />}
          {task.status === "queued" && <Clock className="size-3.5 shrink-0" />}
          <span className="truncate tabular">{detail}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {task.status === "done" && (
          <Button size="sm" variant="primary" icon={<Download className="size-3.5" />} onClick={() => saveExport(task)}>
            Save
          </Button>
        )}
        {active ? (
          <IconButton label="Cancel export" onClick={onCancel}>
            <X className="size-4" />
          </IconButton>
        ) : (
          <IconButton label="Delete export" onClick={onDelete}>
            <Trash2 className="size-4" />
          </IconButton>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ page

export function EditorPage() {
  const { params } = useRoute();
  const sourceId = params.get("source");
  const downloadId = params.get("download");
  const merging = params.get("mode") === "merge";
  const startParam = params.get("start");
  const endParam = params.get("end");
  const titleParam = params.get("title");
  const analysisParam = params.get("analysis");
  const asrcParam = params.get("asrc");
  const preset = useMemo<ClipPreset | null>(() => {
    const start = Number(startParam);
    const end = Number(endParam);
    if (startParam == null || endParam == null || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
    return { start, end, title: titleParam ?? "", analysis: analysisParam, asrc: asrcParam };
  }, [startParam, endParam, titleParam, analysisParam, asrcParam]);
  const toast = useToast();
  const [source, setSource] = useState<EditSource | null>(null);
  const [opening, setOpening] = useState(false);
  const [tasks, setTasks] = useState<ExportTask[] | null>(null);
  const autoSave = useRef(new Set<string>());

  useEffect(() => {
    let stale = false;
    if (downloadId) {
      setOpening(true);
      api
        .editorFromDownload(downloadId)
        .then((s) => !stale && navigate(`editor?source=${s.id}`, true))
        .catch((e: Error) => {
          if (stale) return;
          toast(e.message, "error");
          navigate("editor", true);
        })
        .finally(() => !stale && setOpening(false));
    } else if (!sourceId) {
      setSource(null);
    } else {
      setOpening(true);
      api
        .editorSource(sourceId)
        .then((s) => !stale && setSource(s))
        .catch((e: Error) => {
          if (stale) return;
          toast(e.message, "error");
          navigate("editor", true);
        })
        .finally(() => !stale && setOpening(false));
    }
    return () => {
      stale = true;
    };
  }, [sourceId, downloadId, toast]);

  const apply = useCallback(
    (next: ExportTask[]) => {
      for (const t of next) {
        if (!autoSave.current.has(t.id) || ACTIVE.has(t.status)) continue;
        autoSave.current.delete(t.id);
        if (t.status === "done") {
          saveExport(t);
          toast(`Exported “${t.file_name}”`, "success");
        } else if (t.status === "error") toast(t.error || "Export failed", "error");
      }
      setTasks(next);
    },
    [toast],
  );

  useEffect(() => {
    api
      .exports()
      .then(setTasks)
      .catch(() => setTasks([]));
  }, []);

  const anyActive = !!tasks?.some((t) => ACTIVE.has(t.status));
  useEffect(() => {
    if (!anyActive) return;
    const timer = window.setInterval(() => {
      api.exports().then(apply).catch(() => {});
    }, 700);
    return () => window.clearInterval(timer);
  }, [anyActive, apply]);

  const started = (task: ExportTask) => {
    autoSave.current.add(task.id);
    setTasks((prev) => [task, ...(prev ?? [])]);
  };

  const cancel = async (task: ExportTask) => {
    autoSave.current.delete(task.id);
    try {
      const updated = await api.cancelExport(task.id);
      setTasks((prev) => (prev ?? []).map((t) => (t.id === updated.id ? updated : t)));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const remove = async (task: ExportTask) => {
    try {
      await api.deleteExport(task.id);
      setTasks((prev) => (prev ?? []).filter((t) => t.id !== task.id));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const clearFinished = async () => {
    const finished = (tasks ?? []).filter((t) => !ACTIVE.has(t.status));
    await Promise.allSettled(finished.map((t) => api.deleteExport(t.id)));
    setTasks((prev) => (prev ?? []).filter((t) => ACTIVE.has(t.status)));
  };

  const finishedCount = (tasks ?? []).filter((t) => !ACTIVE.has(t.status)).length;

  return (
    <div className="mx-auto max-w-[1240px] px-5 pb-16 pt-10 md:px-8">
      <div className="mb-7 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight text-fg">Editor</h1>
          <p className="mt-1 text-[14px] text-fg-2">Trim, crop, convert and merge videos with FFmpeg on this server. Nothing is sent anywhere else.</p>
        </div>
        <div className="shrink-0">
          <Segmented
            value={merging ? "merge" : "edit"}
            onChange={(v) => navigate(v === "merge" ? (source ? `editor?mode=merge&add=${source.id}` : "editor?mode=merge") : "editor")}
            options={[
              { value: "edit", label: "Edit a video", icon: <Scissors className="size-3.5" /> },
              { value: "merge", label: "Merge videos", icon: <Merge className="size-3.5" /> },
            ]}
          />
        </div>
      </div>

      {merging ? (
        <MergeWorkspace seed={params.get("add")} onStarted={started} />
      ) : opening && !source ? (
        <Card className="h-[420px] animate-pulse bg-white/[0.02]" />
      ) : source && source.id === sourceId ? (
        <Workspace key={`${source.id}:${startParam ?? ""}:${endParam ?? ""}`} source={source} preset={preset} onStarted={started} />
      ) : (
        <SourcePicker />
      )}

      {tasks && tasks.length > 0 && (
        <>
          <div className="mb-3 mt-10 flex items-center justify-between">
            <h3 className="text-[15px] font-semibold tracking-tight text-fg">
              Exports<span className="ml-2 text-fg-3">{tasks.length}</span>
            </h3>
            {finishedCount > 0 && (
              <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={clearFinished}>
                Clear finished
              </Button>
            )}
          </div>
          <div className="space-y-2">
            {tasks.map((t) => (
              <ExportRow key={t.id} task={t} onCancel={() => cancel(t)} onDelete={() => remove(t)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
