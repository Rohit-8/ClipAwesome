import { ExternalLink, FileWarning, LoaderCircle, Music, RotateCw, Server } from "lucide-react";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Ref } from "react";
import { api } from "../lib/api";
import { browserDecodes, useCompatAudio } from "../lib/compat-audio";
import { fmtTime } from "../lib/format";
import type { PreviewStatus, SourceVideo } from "../lib/types";
import { Button, ProgressBar, YouTubeMark } from "./ui";

const EMBED_KEY = "clipawesome.youtube-embed";
const EMBED_READY_MS = 8000;

type Request = { start: number; end: number | null };

export interface PlayerHandle {
  playRange(start: number, end: number): void;
  seek(t: number): void;
}

interface YTPlayer {
  seekTo(t: number, allowSeekAhead: boolean): void;
  playVideo(): void;
  pauseVideo(): void;
  getCurrentTime(): number;
  destroy(): void;
}

interface YTNamespace {
  Player: new (el: HTMLElement, opts: Record<string, unknown>) => YTPlayer;
}

declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

let ytPromise: Promise<YTNamespace> | null = null;

function loadYouTubeApi(): Promise<YTNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (!ytPromise) {
    ytPromise = new Promise<YTNamespace>((resolve, reject) => {
      const fail = () => {
        ytPromise = null;
        reject(new Error("YouTube player unavailable"));
      };
      const prev = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        prev?.();
        if (window.YT) resolve(window.YT);
      };
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.async = true;
      script.onerror = fail;
      document.head.appendChild(script);
      window.setTimeout(() => !window.YT?.Player && fail(), 12000);
    });
  }
  return ytPromise;
}

function YouTubeEmbed({
  source,
  onTime,
  initial,
  onUnavailable,
  ref,
}: {
  source: SourceVideo;
  onTime: (t: number) => void;
  initial: Request | null;
  onUnavailable: () => void;
  ref?: Ref<PlayerHandle>;
}) {
  const host = useRef<HTMLDivElement>(null);
  const player = useRef<YTPlayer | null>(null);
  const ready = useRef(false);
  const rangeEnd = useRef<number | null>(null);
  const pending = useRef<Request | null>(initial);
  const onTimeRef = useRef(onTime);
  const giveUp = useRef(onUnavailable);
  onTimeRef.current = onTime;
  giveUp.current = onUnavailable;

  useEffect(() => {
    let disposed = false;
    let timer = 0;
    // Some browsers (e.g. VS Code's) never load third-party iframes, so onReady/onError would never fire.
    const watchdog = window.setTimeout(() => !disposed && !ready.current && giveUp.current(), EMBED_READY_MS);
    ready.current = false;
    loadYouTubeApi()
      .then((YT) => {
        if (disposed || !host.current) return;
        const el = document.createElement("div");
        host.current.replaceChildren(el);
        player.current = new YT.Player(el, {
          videoId: source.video_id,
          host: "https://www.youtube-nocookie.com",
          width: "100%",
          height: "100%",
          playerVars: { rel: 0, modestbranding: 1, playsinline: 1, origin: window.location.origin },
          events: {
            onReady: () => {
              ready.current = true;
              const p = pending.current;
              if (p && player.current) {
                rangeEnd.current = p.end;
                player.current.seekTo(p.start, true);
                if (p.end !== null) player.current.playVideo();
                pending.current = null;
              }
            },
            onError: () => !disposed && giveUp.current(),
          },
        });
        timer = window.setInterval(() => {
          const p = player.current;
          if (!p || !ready.current) return;
          const t = p.getCurrentTime();
          onTimeRef.current(t);
          if (rangeEnd.current !== null && t >= rangeEnd.current) {
            p.pauseVideo();
            rangeEnd.current = null;
          }
        }, 250);
      })
      .catch(() => !disposed && giveUp.current());
    return () => {
      disposed = true;
      window.clearTimeout(watchdog);
      window.clearInterval(timer);
      try {
        player.current?.destroy();
      } catch {
        /* player already torn down */
      }
      player.current = null;
    };
  }, [source.video_id]);

  useImperativeHandle(
    ref,
    () => ({
      playRange(start, end) {
        rangeEnd.current = end;
        if (player.current && ready.current) {
          player.current.seekTo(start, true);
          player.current.playVideo();
        } else pending.current = { start, end };
      },
      seek(t) {
        rangeEnd.current = null;
        if (player.current && ready.current) player.current.seekTo(t, true);
        else pending.current = { start: t, end: null };
      },
    }),
    [],
  );

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black ring-1 ring-white/[0.06]">
      <div ref={host} className="absolute inset-0 [&_iframe]:size-full" />
    </div>
  );
}

/** Plays a 360p copy fetched by the server (through its proxy), for when YouTube's own player can't load here. */
function ServerCopyPlayer({ source, onTime, initial, ref }: { source: SourceVideo; onTime: (t: number) => void; initial: Request | null; ref?: Ref<PlayerHandle> }) {
  const media = useRef<PlayerHandle>(null);
  const pending = useRef<Request | null>(initial);
  const [status, setStatus] = useState<PreviewStatus | null>(null);
  const [attempt, setAttempt] = useState(0);
  const videoId = source.video_id ?? "";

  useEffect(() => {
    let stale = false;
    let timer = 0;
    const poll = () =>
      api
        .youtubePreview(videoId)
        .then((s) => {
          if (stale) return;
          setStatus(s);
          if (s.status === "downloading") timer = window.setTimeout(poll, 1000);
        })
        .catch((e: Error) => !stale && setStatus({ video_id: videoId, status: "error", progress: 0, size: null, audio_codec: null, reused_download: false, error: e.message }));
    api
      .startYoutubePreview(videoId)
      .then((s) => {
        if (stale) return;
        setStatus(s);
        if (s.status === "downloading") timer = window.setTimeout(poll, 1000);
      })
      .catch((e: Error) => !stale && setStatus({ video_id: videoId, status: "error", progress: 0, size: null, audio_codec: null, reused_download: false, error: e.message }));
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [videoId, attempt]);

  const ready = status?.status === "ready";
  useEffect(() => {
    const p = pending.current;
    if (!ready || !p || !media.current) return;
    pending.current = null;
    if (p.end === null) media.current.seek(p.start);
    else media.current.playRange(p.start, p.end);
  }, [ready]);

  useImperativeHandle(
    ref,
    () => ({
      playRange(start, end) {
        if (media.current) media.current.playRange(start, end);
        else pending.current = { start, end };
      },
      seek(t) {
        if (media.current) media.current.seek(t);
        else pending.current = { start: t, end: null };
      },
    }),
    [],
  );

  if (ready && status) {
    return (
      <MediaPlayer
        ref={media}
        url={api.youtubePreviewMediaUrl(videoId)}
        previewUrl={api.youtubePreviewAudioUrl(videoId)}
        codec={status.audio_codec}
        audioOnly={false}
        onTime={onTime}
      />
    );
  }

  const failed = status?.status === "error";
  const at = pending.current?.start ?? 0;
  return (
    <div className="relative flex aspect-video w-full flex-col items-center justify-center gap-4 overflow-hidden rounded-xl bg-ink-850 px-8 text-center ring-1 ring-white/[0.06]">
      {source.thumbnail && <img src={source.thumbnail} alt="" className="absolute inset-0 size-full object-cover opacity-20 blur-sm" />}
      <div className="relative flex size-12 items-center justify-center rounded-2xl bg-white/[0.06] ring-1 ring-white/10">
        {failed ? <YouTubeMark className="h-6 w-8" /> : <LoaderCircle className="size-5 animate-spin text-fg-2" />}
      </div>
      {failed ? (
        <div className="relative space-y-3">
          <div>
            <div className="text-sm font-medium text-fg">Couldn't get a playable copy of this video</div>
            <div className="mt-1 max-w-md text-[12.5px] text-fg-3">{status?.error}</div>
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            <Button size="sm" icon={<RotateCw className="size-3.5" />} onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </Button>
            <a
              href={`https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(at)}s`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 items-center gap-2 rounded-xl bg-white/[0.07] px-3 text-[13px] font-medium text-fg ring-1 ring-white/10 transition hover:bg-white/[0.12]"
            >
              Open at {fmtTime(at)} on YouTube <ExternalLink className="size-3.5" />
            </a>
          </div>
        </div>
      ) : (
        <div className="relative w-full max-w-sm space-y-3">
          <div>
            <div className="text-sm font-medium text-fg">Preparing the video on the server…</div>
            <div className="mt-1 text-[12.5px] text-fg-3">YouTube's player can't load in this browser, so the server fetches a 360p copy once. It's kept for next time.</div>
          </div>
          <ProgressBar value={status?.progress ?? 0} active={!status || status.progress <= 0} />
          <div className="tabular text-[12px] text-fg-3">{status && status.progress > 0 ? `${Math.round(status.progress * 100)}%` : "Starting…"}</div>
        </div>
      )}
    </div>
  );
}

function YouTubePlayer({ source, onTime, ref }: { source: SourceVideo; onTime: (t: number) => void; ref?: Ref<PlayerHandle> }) {
  const [mode, setMode] = useState<"embed" | "server">(() => (localStorage.getItem(EMBED_KEY) === "blocked" ? "server" : "embed"));
  const inner = useRef<PlayerHandle>(null);
  const last = useRef<Request | null>(null);

  useImperativeHandle(
    ref,
    () => ({
      playRange(start, end) {
        last.current = { start, end };
        inner.current?.playRange(start, end);
      },
      seek(t) {
        last.current = { start: t, end: null };
        inner.current?.seek(t);
      },
    }),
    [],
  );

  const toServer = () => {
    localStorage.setItem(EMBED_KEY, "blocked");
    setMode("server");
  };
  const toEmbed = () => {
    localStorage.removeItem(EMBED_KEY);
    setMode("embed");
  };

  return (
    <div className="space-y-2">
      {mode === "embed" ? (
        <YouTubeEmbed ref={inner} source={source} onTime={onTime} initial={last.current} onUnavailable={toServer} />
      ) : (
        <ServerCopyPlayer ref={inner} source={source} onTime={onTime} initial={last.current} />
      )}
      <div className="flex justify-end">
        <button type="button" onClick={mode === "embed" ? toServer : toEmbed} className="inline-flex items-center gap-1.5 text-[12px] text-fg-3 transition hover:text-fg">
          {mode === "embed" ? (
            <>
              <Server className="size-3.5" /> Video not showing? Play it through the server
            </>
          ) : (
            <>
              <YouTubeMark className="h-3 w-4" /> Try YouTube's player instead
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function MediaPlayer({
  url,
  previewUrl,
  codec,
  audioOnly,
  onTime,
  ref,
}: {
  url: string | undefined;
  previewUrl: string | null;
  codec: string | null | undefined;
  audioOnly: boolean;
  onTime: (t: number) => void;
  ref?: Ref<PlayerHandle>;
}) {
  const media = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const rangeEnd = useRef<number | null>(null);
  const [unsupported, setUnsupported] = useState(false);
  const [src, setSrc] = useState(() => (audioOnly && previewUrl && browserDecodes(codec) === false ? previewUrl : url));
  useCompatAudio(media, previewUrl, { codec, enabled: !audioOnly });

  useImperativeHandle(
    ref,
    () => ({
      playRange(start, end) {
        const m = media.current;
        if (!m) return;
        rangeEnd.current = end;
        m.currentTime = start;
        void m.play().catch(() => {});
      },
      seek(t) {
        rangeEnd.current = null;
        if (media.current) media.current.currentTime = t;
      },
    }),
    [],
  );

  const onTimeUpdate = () => {
    const m = media.current;
    if (!m) return;
    onTime(m.currentTime);
    if (rangeEnd.current !== null && m.currentTime >= rangeEnd.current) {
      m.pause();
      rangeEnd.current = null;
    }
  };

  // Browsers report codec problems either as an error or as a video with no decodable frames.
  const checkDecodable = () => {
    const m = media.current;
    if (m instanceof HTMLVideoElement && m.videoWidth === 0 && m.readyState >= 1) setUnsupported(true);
  };

  if (unsupported) {
    return (
      <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-xl bg-ink-850 px-8 text-center ring-1 ring-white/[0.06]">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-white/[0.05] ring-1 ring-white/10">
          <FileWarning className="size-5 text-warn" />
        </div>
        <div className="text-sm font-medium text-fg">This file's codec can't be previewed in the browser</div>
        <div className="max-w-md text-[12.5px] leading-relaxed text-fg-3">
          Clip suggestions and timings are unaffected — open the file in your video player and jump to the ranges. MP4 (H.264) or WebM files preview inline.
        </div>
      </div>
    );
  }

  if (audioOnly) {
    return (
      <div className="flex aspect-video w-full flex-col justify-end gap-6 overflow-hidden rounded-xl bg-ink-850 p-6 ring-1 ring-white/[0.06]">
        <div className="flex flex-1 items-center justify-center">
          <div className="flex size-16 items-center justify-center rounded-2xl bg-white/[0.06] ring-1 ring-white/10">
            <Music className="size-7 text-fg-2" />
          </div>
        </div>
        <audio
          ref={(el) => void (media.current = el)}
          src={src}
          controls
          preload="metadata"
          onTimeUpdate={onTimeUpdate}
          onError={() => previewUrl && src !== previewUrl && setSrc(previewUrl)}
          className="w-full"
        />
      </div>
    );
  }
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black ring-1 ring-white/[0.06]">
      <video
        ref={(el) => void (media.current = el)}
        src={src}
        controls
        preload="metadata"
        onTimeUpdate={onTimeUpdate}
        onLoadedMetadata={checkDecodable}
        onError={() => setUnsupported(true)}
        className="size-full"
      />
    </div>
  );
}

export function Player({ source, onTime, ref }: { source: SourceVideo; onTime: (t: number) => void; ref?: Ref<PlayerHandle> }) {
  if (source.platform === "youtube") return <YouTubePlayer key={source.id} source={source} onTime={onTime} ref={ref} />;
  return (
    <MediaPlayer
      key={source.id}
      ref={ref}
      url={source.media_id ? api.mediaUrl(source.media_id) : undefined}
      previewUrl={source.media_id ? api.mediaPreviewAudioUrl(source.media_id) : null}
      codec={source.audio_codec}
      audioOnly={source.media_kind === "audio"}
      onTime={onTime}
    />
  );
}
