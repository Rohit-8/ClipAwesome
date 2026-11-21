import { BadgeCheck, CircleX, Clapperboard, Download, LoaderCircle, PackageCheck, Scissors } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { cx, fmtBytes } from "../lib/format";
import { navigate } from "../lib/router";
import type { Analysis, BatchOptions, Clip, DownloadTask, ExportBatch, ExportTask, SourceVideo } from "../lib/types";
import { useToast } from "./Toast";
import { Button, Field, Modal, Notice, ProgressBar, Segmented, Select, Toggle } from "./ui";

const QUALITIES = [360, 480, 720, 1080, 1440, 2160];

function save(task: ExportTask) {
  const a = document.createElement("a");
  a.href = api.exportFileUrl(task.id);
  a.download = task.file_name ?? "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function QualityPicker({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <Field
      label="Video quality for editing"
      hint="The YouTube video is downloaded once at this quality (a download you already have at this quality or better is reused). Higher looks better but takes longer and uses more disk."
    >
      <Select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {QUALITIES.map((q) => (
          <option key={q} value={q}>
            {q}p{q === 720 ? " (recommended)" : q === 360 ? " (fastest)" : ""}
          </option>
        ))}
      </Select>
    </Field>
  );
}

/** Wait for the source to be editable (downloading it if needed), reporting the download's progress. */
async function prepareSource(analysisId: string, sourceId: string, quality: number, onDownload: (d: DownloadTask) => void, cancelled: () => boolean) {
  for (;;) {
    const res = await api.editSource(analysisId, sourceId, quality);
    if (res.status === "ready") return res.source;
    let task = res.download;
    while (task.status !== "done") {
      if (cancelled()) throw new Error("cancelled");
      if (task.status === "error" || task.status === "cancelled") throw new Error(task.error || "The download didn't finish.");
      onDownload(task);
      await new Promise((r) => window.setTimeout(r, 1000));
      task = await api.download(task.id);
    }
  }
}

export function OpenInEditorDialog({ analysis, clip, source, onClose }: { analysis: Analysis; clip: Clip; source: SourceVideo; onClose: () => void }) {
  const toast = useToast();
  const [quality, setQuality] = useState(720);
  const [download, setDownload] = useState<DownloadTask | null>(null);
  const [busy, setBusy] = useState(false);
  const stop = useRef(false);
  const youtube = source.platform === "youtube";

  const open = async () => {
    setBusy(true);
    try {
      const src = await prepareSource(analysis.id, source.id, quality, setDownload, () => stop.current);
      if (stop.current) return;
      const params = new URLSearchParams({
        source: src.id,
        start: String(clip.start),
        end: String(clip.end),
        title: clip.title,
        analysis: analysis.id,
        asrc: source.id,
      });
      navigate(`editor?${params.toString()}`);
    } catch (e) {
      if ((e as Error).message !== "cancelled") toast((e as Error).message, "error");
      setBusy(false);
      setDownload(null);
    }
  };

  // Local files are ready immediately, so there is nothing to choose.
  useEffect(() => {
    if (!youtube) void open();
  }, []);

  return (
    <Modal
      title="Edit & export this clip"
      subtitle={`“${clip.title}” opens in the editor with its start and end already set. Crop it for Shorts, add captions and export.`}
      onClose={() => {
        stop.current = true;
        onClose();
      }}
    >
      <div className="space-y-5">
        {youtube && !busy && <QualityPicker value={quality} onChange={setQuality} />}
        {busy && (
          <div className="space-y-2 rounded-xl border border-white/[0.06] bg-black/20 p-4">
            <div className="flex items-center gap-2 text-[13px] text-fg">
              <LoaderCircle className="size-4 animate-spin text-accent-soft" />
              {download ? `Downloading the video (${download.label})…` : "Getting the video ready…"}
            </div>
            {download && (
              <>
                <ProgressBar value={download.progress} active={download.progress <= 0} />
                <div className="tabular text-[12px] text-fg-3">
                  {Math.round(download.progress * 100)}%{download.total_bytes ? ` of ${fmtBytes(download.total_bytes)}` : ""} · it also appears under Downloads
                </div>
              </>
            )}
          </div>
        )}
        {youtube && !busy && (
          <Button variant="primary" className="w-full" icon={<Scissors className="size-4" />} onClick={open}>
            Open in editor
          </Button>
        )}
      </div>
    </Modal>
  );
}

type Pick = "approved" | "top" | "all";

export function ExportClipsDialog({ analysis, onClose }: { analysis: Analysis; onClose: () => void }) {
  const toast = useToast();
  const approved = analysis.clips.filter((c) => c.review === "approved");
  const [pick, setPick] = useState<Pick>(approved.length ? "approved" : "top");
  const [top, setTop] = useState(Math.min(5, analysis.clips.length));
  const [frame, setFrame] = useState<BatchOptions["frame"]>("9:16");
  const [captions, setCaptions] = useState<BatchOptions["captions"]>("bold");
  const [normalize, setNormalize] = useState(true);
  const [quality, setQuality] = useState<BatchOptions["quality"]>("balanced");
  const [downloadQuality, setDownloadQuality] = useState(720);
  const [batch, setBatch] = useState<ExportBatch | null>(null);
  const [tasks, setTasks] = useState<ExportTask[]>([]);
  const [busy, setBusy] = useState(false);
  const hasYouTube = analysis.sources.some((s) => s.platform === "youtube");

  const chosen = useMemo(() => {
    if (pick === "approved") return approved;
    const ranked = [...analysis.clips].filter((c) => c.review !== "rejected").sort((a, b) => a.rank - b.rank);
    return pick === "top" ? ranked.slice(0, top) : ranked;
  }, [pick, top, analysis.clips, approved]);

  const batchId = batch?.id;
  useEffect(() => {
    if (!batchId) return;
    let stopped = false;
    let timer = 0;
    const tick = async () => {
      try {
        const b = await api.exportBatch(batchId);
        const all = b.export_ids.length ? await api.exports() : [];
        if (stopped) return;
        const mine = b.export_ids.map((id) => all.find((t) => t.id === id)).filter((t): t is ExportTask => !!t);
        setBatch(b);
        setTasks(mine);
        if (b.status !== "preparing" && mine.every((t) => t.status !== "queued" && t.status !== "running")) return;
      } catch {
        /* keep polling */
      }
      if (!stopped) timer = window.setTimeout(tick, 1000);
    };
    timer = window.setTimeout(tick, 500);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [batchId]);

  const start = async () => {
    setBusy(true);
    try {
      setBatch(
        await api.exportClips(analysis.id, {
          clip_ids: chosen.map((c) => c.id),
          download_quality: downloadQuality,
          frame,
          captions,
          normalize,
          quality,
        }),
      );
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const ready = tasks.filter((t) => t.status === "done");
  const running = batch?.status === "preparing" || tasks.some((t) => t.status === "queued" || t.status === "running");
  const saveAll = () => ready.forEach((t, i) => window.setTimeout(() => save(t), i * 400));

  if (batch) {
    return (
      <Modal title={`Exporting ${batch.total} clip${batch.total === 1 ? "" : "s"}`} subtitle={batch.stage} onClose={onClose} wide>
        <div className="space-y-3">
          {batch.errors.map((e, i) => (
            <Notice key={i} tone="neg">
              {e}
            </Notice>
          ))}
          {tasks.length === 0 && batch.status === "preparing" && <ProgressBar value={0} active />}
          {tasks.map((t) => (
            <div key={t.id} className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-black/20 p-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-fg" title={t.file_name ?? t.source_name}>
                  {t.file_name ?? t.source_name}
                </div>
                <div
                  className={cx(
                    "mt-0.5 flex items-center gap-1.5 text-[12px]",
                    t.status === "error" ? "text-neg" : t.status === "done" ? "text-pos" : "text-fg-3",
                  )}
                >
                  {t.status === "done" && <BadgeCheck className="size-3.5" />}
                  {t.status === "error" && <CircleX className="size-3.5" />}
                  {t.status === "done"
                    ? `Ready · ${fmtBytes(t.file_size)}`
                    : t.status === "error"
                      ? t.error
                      : t.stage || (t.status === "queued" ? "Waiting…" : `${Math.round(t.progress * 100)}%${t.encoder ? ` · ${t.encoder}` : ""}`)}
                </div>
                {(t.status === "queued" || t.status === "running") && (
                  <div className="mt-2">
                    <ProgressBar value={t.progress} active={t.status === "queued"} />
                  </div>
                )}
              </div>
              {t.status === "done" && (
                <Button size="sm" icon={<Download className="size-3.5" />} onClick={() => save(t)}>
                  Save
                </Button>
              )}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2 pt-2">
            <Button variant="primary" icon={<PackageCheck className="size-4" />} disabled={!ready.length} onClick={saveAll}>
              Save all ready ({ready.length})
            </Button>
            <Button variant="ghost" icon={<Clapperboard className="size-4" />} onClick={() => navigate("editor")}>
              Open the editor
            </Button>
            {running && <span className="text-[12px] text-fg-3">You can close this; exports keep running and appear in the editor.</span>}
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Export clips" subtitle="Turns suggestions into ready-to-post video files. Each clip becomes its own MP4." onClose={onClose} wide>
      <div className="space-y-5">
        <Field label="Which clips">
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              value={pick}
              onChange={setPick}
              options={[
                { value: "approved", label: `Approved (${approved.length})`, disabled: !approved.length },
                { value: "top", label: "Top" },
                { value: "all", label: "All not rejected" },
              ]}
            />
            {pick === "top" && (
              <Select value={top} onChange={(e) => setTop(Number(e.target.value))} className="w-24">
                {Array.from({ length: analysis.clips.length }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </Select>
            )}
          </div>
        </Field>
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="Frame" hint={frame === "original" ? "Keeps the video's shape." : "Crops the centre of the video to this shape."}>
            <Segmented
              value={frame}
              onChange={setFrame}
              options={[
                { value: "9:16", label: "9:16 Shorts" },
                { value: "1:1", label: "1:1" },
                { value: "original", label: "Original" },
              ]}
            />
          </Field>
          <Field label="Captions" hint={captions === "off" ? "No text on the video." : "Burned into the video from the transcript (clips outside it are transcribed now)."}>
            <Segmented
              value={captions}
              onChange={setCaptions}
              options={[
                { value: "bold", label: "Bold" },
                { value: "classic", label: "Classic" },
                { value: "boxed", label: "Boxed" },
                { value: "off", label: "Off" },
              ]}
            />
          </Field>
          <Field label="Quality" hint="Smaller files lose a little detail.">
            <Segmented
              value={quality}
              onChange={setQuality}
              options={[
                { value: "high", label: "High" },
                { value: "balanced", label: "Balanced" },
                { value: "small", label: "Small" },
              ]}
            />
          </Field>
          {hasYouTube && (
            <Field label="Download quality" hint="YouTube videos are downloaded once at this quality (existing downloads are reused).">
              <Select value={downloadQuality} onChange={(e) => setDownloadQuality(Number(e.target.value))}>
                {QUALITIES.map((q) => (
                  <option key={q} value={q}>
                    {q}p{q === 720 ? " (recommended)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>
        <Toggle
          checked={normalize}
          onChange={setNormalize}
          label="Even out the volume (−14 LUFS)"
          description="Every clip plays at the same loudness that YouTube, Instagram and TikTok expect, so none is too quiet or too loud."
        />
        <Button variant="primary" size="lg" className="w-full" loading={busy} disabled={!chosen.length} onClick={start}>
          Export {chosen.length} clip{chosen.length === 1 ? "" : "s"}
        </Button>
      </div>
    </Modal>
  );
}
