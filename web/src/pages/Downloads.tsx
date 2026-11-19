import { AudioLines, BadgeCheck, CircleX, Clock, Download, ExternalLink, Film, Info, Scissors, Search, ShieldCheck, Trash2, X } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Thumb } from "../components/Thumb";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, IconButton, Notice, ProgressBar, YouTubeMark } from "../components/ui";
import { api } from "../lib/api";
import { useApp } from "../lib/app-context";
import { navigate } from "../lib/router";
import { cx, fmtBytes, fmtDuration, relativeTime } from "../lib/format";
import type { DownloadInfo, DownloadOption, DownloadTask } from "../lib/types";

const ACTIVE = new Set(["queued", "downloading", "merging"]);

function saveFile(task: DownloadTask) {
  const a = document.createElement("a");
  a.href = api.downloadFileUrl(task.id);
  a.download = task.file_name ?? "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function OptionRow({ option, top, busy, disabled, onPick }: { option: DownloadOption; top: boolean; busy: boolean; disabled: boolean; onPick: () => void }) {
  const isVideo = option.kind === "video";
  return (
    <div
      className={cx(
        "flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border px-4 py-3 transition-colors duration-200",
        option.available ? "border-white/[0.06] bg-black/20 hover:border-white/[0.14]" : "border-white/[0.04] bg-black/10 opacity-60",
      )}
    >
      <div className="flex w-[118px] shrink-0 items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">
          {isVideo ? <Film className="size-4" /> : <AudioLines className="size-4" />}
        </div>
        <div className="min-w-0">
          <div className="tabular text-[15px] font-semibold leading-tight text-fg">{isVideo ? option.label : option.label.replace("Audio · ", "")}</div>
          <div className="text-[11.5px] text-fg-3">{option.quality}</div>
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        <Badge>
          {option.ext.toUpperCase()} · {option.codec}
        </Badge>
        {option.fps && option.fps > 30 && <Badge tone="violet">{Math.round(option.fps)} fps</Badge>}
        {option.hdr && <Badge tone="warn">HDR</Badge>}
        {top && isVideo && <Badge tone="pos">Highest</Badge>}
        {option.width && option.height && <span className="ml-1 tabular text-[12px] text-fg-3">{option.width}×{option.height}</span>}
        {!option.available && option.reason && <span className="ml-1 text-[12px] text-warn">{option.reason}</span>}
      </div>

      <div className="w-[92px] text-right">
        <div className="tabular text-[14px] font-medium text-fg">
          {option.size ? `${option.approx ? "≈ " : ""}${fmtBytes(option.size)}` : "Size unknown"}
        </div>
        {isVideo && option.bitrate_kbps && <div className="tabular text-[11px] text-fg-3">{Math.round(option.bitrate_kbps)} kbps</div>}
      </div>

      <Button
        size="sm"
        variant={top ? "primary" : "secondary"}
        icon={<Download className="size-3.5" />}
        loading={busy}
        disabled={disabled || !option.available}
        onClick={onPick}
      >
        Download
      </Button>
    </div>
  );
}

function TaskRow({ task, onCancel, onDelete }: { task: DownloadTask; onCancel: () => void; onDelete: () => void }) {
  const active = ACTIVE.has(task.status);
  let detail: ReactNode;
  if (task.status === "queued") detail = "Waiting for a free download slot…";
  else if (task.status === "downloading") {
    const parts = [
      task.total_bytes ? `${fmtBytes(task.downloaded_bytes)} of ${fmtBytes(task.total_bytes)}` : fmtBytes(task.downloaded_bytes),
      task.speed ? `${fmtBytes(task.speed)}/s` : null,
      task.eta != null ? `${fmtDuration(task.eta)} left` : null,
    ].filter(Boolean);
    detail = `${task.stage} · ${parts.join(" · ")}`;
  } else if (task.status === "merging") detail = "Merging video and audio into one file…";
  else if (task.status === "done") detail = `Ready · ${fmtBytes(task.file_size)} · ${relativeTime(task.finished_at ?? task.created_at)}`;
  else if (task.status === "cancelled") detail = "Cancelled";
  else detail = task.error || "Download failed";

  return (
    <div className="flex items-center gap-4 rounded-xl border border-white/[0.06] bg-black/20 p-3">
      <Thumb src={task.thumbnail} kind="youtube" className="aspect-video w-[104px] shrink-0 rounded-lg" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <div className="truncate text-[13.5px] font-medium text-fg" title={task.title}>
            {task.title}
          </div>
          <Badge className="shrink-0">{task.label}</Badge>
        </div>
        {active && (
          <div className="mt-2">
            <ProgressBar value={task.progress} active={task.status !== "downloading"} />
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
          <IconButton label="Edit in Editor" onClick={() => navigate(`editor?download=${task.id}`)}>
            <Scissors className="size-4" />
          </IconButton>
        )}
        {task.status === "done" && (
          <Button size="sm" variant="primary" icon={<Download className="size-3.5" />} onClick={() => saveFile(task)}>
            Save
          </Button>
        )}
        {active ? (
          <IconButton label="Cancel download" onClick={onCancel}>
            <X className="size-4" />
          </IconButton>
        ) : (
          <IconButton label="Delete download" onClick={onDelete}>
            <Trash2 className="size-4" />
          </IconButton>
        )}
      </div>
    </div>
  );
}

export function DownloadsPage() {
  const { youtube } = useApp();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [fetching, setFetching] = useState(false);
  const [info, setInfo] = useState<DownloadInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tasks, setTasks] = useState<DownloadTask[] | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const autoSave = useRef(new Set<string>());

  const apply = useCallback(
    (next: DownloadTask[]) => {
      for (const t of next) {
        if (!autoSave.current.has(t.id) || ACTIVE.has(t.status)) continue;
        autoSave.current.delete(t.id);
        if (t.status === "done") {
          saveFile(t);
          toast(`Saved “${t.title}” (${t.label})`, "success");
        } else if (t.status === "error") toast(t.error || "Download failed", "error");
      }
      setTasks(next);
    },
    [toast],
  );

  useEffect(() => {
    api
      .downloads()
      .then(setTasks)
      .catch((e: Error) => {
        setTasks([]);
        toast(e.message, "error");
      });
  }, [toast]);

  const anyActive = !!tasks?.some((t) => ACTIVE.has(t.status));
  useEffect(() => {
    if (!anyActive) return;
    const timer = window.setInterval(() => {
      api.downloads().then(apply).catch(() => {});
    }, 1000);
    return () => window.clearInterval(timer);
  }, [anyActive, apply]);

  const fetchFormats = async () => {
    if (!url.trim() || fetching) return;
    setFetching(true);
    setError(null);
    setInfo(null);
    try {
      setInfo(await api.downloadFormats(url.trim()));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setFetching(false);
    }
  };

  const start = async (option: DownloadOption) => {
    if (!info) return;
    setStarting(option.id);
    try {
      const task = await api.startDownload(info.url, option.id);
      autoSave.current.add(task.id);
      setTasks((prev) => [task, ...(prev ?? []).filter((t) => t.id !== task.id)]);
      toast(`Downloading ${option.kind === "video" ? option.label : option.label.toLowerCase()} — it will save automatically when ready`, "info");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setStarting(null);
    }
  };

  const cancel = async (task: DownloadTask) => {
    autoSave.current.delete(task.id);
    try {
      const updated = await api.cancelDownload(task.id);
      setTasks((prev) => (prev ?? []).map((t) => (t.id === updated.id ? updated : t)));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const remove = async (task: DownloadTask) => {
    try {
      await api.deleteDownload(task.id);
      setTasks((prev) => (prev ?? []).filter((t) => t.id !== task.id));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const clearFinished = async () => {
    const finished = (tasks ?? []).filter((t) => !ACTIVE.has(t.status));
    await Promise.allSettled(finished.map((t) => api.deleteDownload(t.id)));
    setTasks((prev) => (prev ?? []).filter((t) => ACTIVE.has(t.status)));
  };

  const videos = info?.options.filter((o) => o.kind === "video") ?? [];
  const audios = info?.options.filter((o) => o.kind === "audio") ?? [];
  const finishedCount = (tasks ?? []).filter((t) => !ACTIVE.has(t.status)).length;

  return (
    <div className="mx-auto max-w-[940px] px-5 pb-16 pt-10 md:px-8">
      <div className="mb-8">
        <h1 className="text-[28px] font-semibold tracking-tight text-fg">Download</h1>
        <p className="mt-1 text-[14px] text-fg-2">Paste a YouTube link to see every available resolution with its file size, then save the one you need.</p>
      </div>

      {youtube && !youtube.ok && (
        <div className="mb-4">
          <Notice
            action={
              <a href="#/settings" className="shrink-0 text-[12.5px] font-medium text-warn hover:underline">
                Network settings
              </a>
            }
          >
            YouTube isn't reachable from this machine right now. Set a proxy in Settings to fetch formats.
          </Notice>
        </div>
      )}

      <Card className="animate-fade-up p-4 md:p-5">
        <div className="flex flex-col gap-3 md:flex-row">
          <div className="relative flex-1">
            <YouTubeMark className="pointer-events-none absolute left-4 top-1/2 h-4 w-6 -translate-y-1/2" />
            <input
              autoFocus
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchFormats()}
              placeholder="Paste a YouTube link — youtube.com/watch?v=…, youtu.be/…, /shorts/…"
              className="h-12 w-full rounded-xl border border-white/[0.09] bg-black/25 pl-14 pr-4 text-[15px] text-fg outline-none transition placeholder:text-fg-3 focus:border-violet/60 focus:ring-4 focus:ring-violet/15"
            />
          </div>
          <Button variant="primary" size="lg" icon={<Search className="size-4" />} loading={fetching} disabled={!url.trim()} onClick={fetchFormats}>
            Get formats
          </Button>
        </div>
        {error && (
          <div className="mt-3">
            <Notice tone="neg">{error}</Notice>
          </div>
        )}
      </Card>

      {fetching && (
        <Card className="mt-5 space-y-3 p-5">
          <div className="flex gap-4">
            <div className="aspect-video w-[220px] animate-pulse rounded-xl bg-white/[0.04]" />
            <div className="flex-1 space-y-2 pt-1">
              <div className="h-5 w-3/4 animate-pulse rounded bg-white/[0.05]" />
              <div className="h-4 w-1/3 animate-pulse rounded bg-white/[0.04]" />
            </div>
          </div>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-[62px] animate-pulse rounded-xl bg-white/[0.03]" />
          ))}
        </Card>
      )}

      {info && !fetching && (
        <Card className="mt-5 animate-fade-up p-5">
          <div className="flex flex-col gap-5 md:flex-row">
            <Thumb src={info.thumbnail} kind="youtube" className="aspect-video w-full shrink-0 rounded-xl md:w-[240px]" />
            <div className="min-w-0 flex-1">
              <h2 className="text-[17px] font-semibold leading-snug tracking-tight text-fg">{info.title}</h2>
              <div className="mt-1 text-[13px] text-fg-2">
                {[info.channel, info.duration ? fmtDuration(info.duration) : null].filter(Boolean).join(" · ")}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {info.creative_commons ? (
                  <Badge tone="pos" icon={<ShieldCheck className="size-3.5" />}>
                    Creative Commons
                  </Badge>
                ) : (
                  <Badge icon={<Info className="size-3.5" />}>Standard YouTube licence</Badge>
                )}
                <Badge>{videos.length} resolutions</Badge>
                <a
                  href={info.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[12.5px] font-medium text-accent-soft hover:text-white"
                >
                  Open on YouTube <ExternalLink className="size-3.5" />
                </a>
              </div>
              {!info.ffmpeg && (
                <div className="mt-3">
                  <Notice>FFmpeg isn't available, so only formats that already contain audio can be downloaded.</Notice>
                </div>
              )}
            </div>
          </div>

          {videos.length > 0 && (
            <div className="mt-6">
              <div className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-fg-3">Video + audio</div>
              <div className="space-y-2">
                {videos.map((o, i) => (
                  <OptionRow key={o.id} option={o} top={i === 0} busy={starting === o.id} disabled={starting !== null} onPick={() => start(o)} />
                ))}
              </div>
            </div>
          )}

          {audios.length > 0 && (
            <div className="mt-6">
              <div className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-fg-3">Audio only</div>
              <div className="space-y-2">
                {audios.map((o) => (
                  <OptionRow key={o.id} option={o} top={false} busy={starting === o.id} disabled={starting !== null} onPick={() => start(o)} />
                ))}
              </div>
            </div>
          )}

          <p className="mt-5 flex items-start gap-2 text-[12px] leading-relaxed text-fg-3">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            Sizes come from YouTube; “≈” marks an estimate. Only download videos you own, that carry a Creative Commons licence, or that you have
            permission to save, and follow YouTube's Terms of Service.
          </p>
        </Card>
      )}

      <div className="mb-3 mt-10 flex items-center justify-between">
        <h3 className="text-[15px] font-semibold tracking-tight text-fg">
          Your downloads{tasks && tasks.length > 0 && <span className="ml-2 text-fg-3">{tasks.length}</span>}
        </h3>
        {finishedCount > 0 && (
          <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={clearFinished}>
            Clear finished
          </Button>
        )}
      </div>

      {tasks === null ? (
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="h-[84px] animate-pulse rounded-xl bg-white/[0.03]" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Download className="size-5" />}
            title="No downloads yet"
            body="Fetch the formats for a video above and pick a resolution. Finished files save to your device automatically."
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {tasks.map((t) => (
            <TaskRow key={t.id} task={t} onCancel={() => cancel(t)} onDelete={() => remove(t)} />
          ))}
        </div>
      )}
    </div>
  );
}
