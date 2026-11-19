import { ExternalLink, FileWarning, Music } from "lucide-react";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Ref } from "react";
import { api } from "../lib/api";
import { fmtTime } from "../lib/format";
import type { SourceVideo } from "../lib/types";
import { YouTubeMark } from "./ui";

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

function YouTubePlayer({ source, onTime, ref }: { source: SourceVideo; onTime: (t: number) => void; ref?: Ref<PlayerHandle> }) {
  const host = useRef<HTMLDivElement>(null);
  const player = useRef<YTPlayer | null>(null);
  const ready = useRef(false);
  const rangeEnd = useRef<number | null>(null);
  const pending = useRef<{ start: number; end: number | null } | null>(null);
  const onTimeRef = useRef(onTime);
  const [failed, setFailed] = useState(false);
  const [lastStart, setLastStart] = useState(0);
  onTimeRef.current = onTime;

  useEffect(() => {
    let disposed = false;
    let timer = 0;
    ready.current = false;
    setFailed(false);
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
                player.current.seekTo(p.start, true);
                player.current.playVideo();
                pending.current = null;
              }
            },
            onError: () => setFailed(true),
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
      .catch(() => !disposed && setFailed(true));
    return () => {
      disposed = true;
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
        setLastStart(start);
        rangeEnd.current = end;
        if (player.current && ready.current) {
          player.current.seekTo(start, true);
          player.current.playVideo();
        } else pending.current = { start, end };
      },
      seek(t) {
        setLastStart(t);
        rangeEnd.current = null;
        if (player.current && ready.current) player.current.seekTo(t, true);
      },
    }),
    [],
  );

  if (failed) {
    const link = `https://www.youtube.com/watch?v=${source.video_id}&t=${Math.floor(lastStart)}s`;
    return (
      <div className="relative flex aspect-video w-full flex-col items-center justify-center gap-4 overflow-hidden rounded-xl bg-ink-850 text-center ring-1 ring-white/[0.06]">
        <YouTubeMark className="h-9 w-12" />
        <div>
          <div className="text-sm font-medium text-fg">Embedded player unavailable on this network</div>
          <div className="mt-1 text-[12.5px] text-fg-3">Clip timings are still accurate — open the moment directly.</div>
        </div>
        <a href={link} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-2 rounded-xl bg-white/[0.07] px-4 text-[13px] font-medium text-fg ring-1 ring-white/10 transition hover:bg-white/[0.12]">
          Open at {fmtTime(lastStart)} on YouTube <ExternalLink className="size-3.5" />
        </a>
      </div>
    );
  }
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black ring-1 ring-white/[0.06]">
      <div ref={host} className="absolute inset-0 [&_iframe]:size-full" />
    </div>
  );
}

function LocalPlayer({ source, onTime, ref }: { source: SourceVideo; onTime: (t: number) => void; ref?: Ref<PlayerHandle> }) {
  const media = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const rangeEnd = useRef<number | null>(null);
  const [unsupported, setUnsupported] = useState(false);
  const src = source.media_id ? api.mediaUrl(source.media_id) : undefined;

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

  if (source.media_kind === "audio") {
    return (
      <div className="flex aspect-video w-full flex-col justify-end gap-6 overflow-hidden rounded-xl bg-ink-850 p-6 ring-1 ring-white/[0.06]">
        <div className="flex flex-1 items-center justify-center">
          <div className="flex size-16 items-center justify-center rounded-2xl bg-white/[0.06] ring-1 ring-white/10">
            <Music className="size-7 text-fg-2" />
          </div>
        </div>
        <audio ref={(el) => void (media.current = el)} src={src} controls preload="metadata" onTimeUpdate={onTimeUpdate} className="w-full" />
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
  return source.platform === "youtube" ? (
    <YouTubePlayer key={source.id} source={source} onTime={onTime} ref={ref} />
  ) : (
    <LocalPlayer key={source.id} source={source} onTime={onTime} ref={ref} />
  );
}
