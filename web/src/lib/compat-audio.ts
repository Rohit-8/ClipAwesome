import { useEffect, useState } from "react";
import type { RefObject } from "react";

const CODEC_MIME: Record<string, string> = {
  aac: 'audio/mp4; codecs="mp4a.40.2"',
  mp3: "audio/mpeg",
  opus: 'audio/webm; codecs="opus"',
  vorbis: 'audio/webm; codecs="vorbis"',
  flac: "audio/flac",
  alac: 'audio/mp4; codecs="alac"',
  ac3: 'audio/mp4; codecs="ac-3"',
  eac3: 'audio/mp4; codecs="ec-3"',
};

/** true/false when the codec is known, null when it isn't (then playback is watched instead). */
export function browserDecodes(codec: string | null | undefined): boolean | null {
  if (!codec) return null;
  const probe = document.createElement("audio");
  if (codec.startsWith("pcm_")) return probe.canPlayType("audio/wav") !== "";
  const mime = CODEC_MIME[codec];
  return mime ? probe.canPlayType(mime) !== "" : false;
}

export type CompatState = "native" | "loading" | "ready" | "error";

/**
 * Some browsers (e.g. the VS Code / Electron browser) play H.264 video but can't decode AAC audio, so the
 * picture plays silently. When that happens this plays the server's MP3 copy of the audio in sync with `media`.
 */
export function useCompatAudio(
  media: RefObject<HTMLMediaElement | null>,
  previewUrl: string | null,
  { codec, enabled }: { codec?: string | null; enabled: boolean },
): CompatState {
  const [active, setActive] = useState(() => enabled && !!previewUrl && browserDecodes(codec) === false);
  const [state, setState] = useState<CompatState>("loading");

  // Unknown codec: Chromium exposes how many audio bytes it decoded; zero after a second of playback means silence.
  useEffect(() => {
    const v = media.current as (HTMLMediaElement & { webkitAudioDecodedByteCount?: number }) | null;
    if (!v || active || !enabled || !previewUrl || !("webkitAudioDecodedByteCount" in v)) return;
    let from: number | null = null;
    const check = () => {
      if (v.paused) {
        from = null;
        return;
      }
      if (from === null) from = v.currentTime;
      else if (v.currentTime - from > 1) {
        v.removeEventListener("timeupdate", check);
        if (v.webkitAudioDecodedByteCount === 0) setActive(true);
      }
    };
    v.addEventListener("timeupdate", check);
    return () => v.removeEventListener("timeupdate", check);
  }, [media, active, enabled, previewUrl]);

  useEffect(() => {
    const v = media.current;
    if (!active || !v || !previewUrl) return;
    const a = new Audio();
    a.preload = "auto";
    a.src = previewUrl;
    setState("loading");

    const mirror = () => {
      a.volume = v.volume;
      a.muted = v.muted;
      a.playbackRate = v.playbackRate;
    };
    const align = () => {
      const drift = a.currentTime - v.currentTime;
      if (Math.abs(drift) > 0.3) {
        a.currentTime = v.currentTime;
        a.playbackRate = v.playbackRate;
      } else if (Math.abs(drift) > 0.03) {
        // Small drift: nudge speed instead of seeking, which would click.
        a.playbackRate = v.playbackRate * (drift > 0 ? 0.97 : 1.03);
      } else {
        a.playbackRate = v.playbackRate;
      }
    };
    const play = () => {
      mirror();
      align();
      if (a.paused) void a.play().catch(() => {});
    };
    const pause = () => a.pause();
    const seek = () => {
      a.currentTime = v.currentTime;
    };
    const ready = () => setState("ready");
    const failed = () => setState("error");

    const events: [string, () => void][] = [
      ["play", play],
      ["playing", play],
      ["pause", pause],
      ["waiting", pause],
      ["seeking", seek],
      ["seeked", seek],
      ["volumechange", mirror],
      ["ratechange", mirror],
    ];
    for (const [name, fn] of events) v.addEventListener(name, fn);
    a.addEventListener("canplay", ready);
    a.addEventListener("error", failed);
    const timer = window.setInterval(() => {
      if (v.paused) return;
      if (a.paused && a.readyState >= 2) play();
      else align();
    }, 200);
    if (!v.paused) play();

    return () => {
      window.clearInterval(timer);
      for (const [name, fn] of events) v.removeEventListener(name, fn);
      a.removeEventListener("canplay", ready);
      a.removeEventListener("error", failed);
      a.pause();
      a.removeAttribute("src");
      a.load();
    };
  }, [media, active, previewUrl]);

  return active ? state : "native";
}
