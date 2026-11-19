import { fmtTime } from "./format";
import type { Analysis, Clip, SourceVideo } from "./types";

export function clipLink(source: SourceVideo | undefined, clip: Clip): string | null {
  if (!source || source.platform !== "youtube" || !source.video_id) return null;
  return `https://www.youtube.com/watch?v=${source.video_id}&t=${Math.floor(clip.start)}s`;
}

function sourceOf(a: Analysis, clip: Clip) {
  return a.sources.find((s) => s.id === clip.source_id);
}

function csvCell(value: unknown): string {
  const s = String(value ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCSV(a: Analysis): string {
  const header = ["rank", "video", "start", "end", "start_sec", "end_sec", "duration_sec", "score", "title", "link", "reasons"];
  const rows = a.clips.map((c) => {
    const src = sourceOf(a, c);
    return [
      c.rank,
      src?.title,
      fmtTime(c.start),
      fmtTime(c.end),
      c.start,
      c.end,
      Math.round(c.duration),
      c.score,
      c.title,
      clipLink(src, c) ?? "",
      c.reasons.map((r) => r.text).join(" | "),
    ].map(csvCell);
  });
  return [header.join(","), ...rows.map((r) => r.join(","))].join("\n");
}

export function toMarkdown(a: Analysis): string {
  const lines = [`# ${a.title}`, "", `_${a.clips.length} clip suggestions · ${a.mode} mode · ${new Date(a.created_at).toLocaleString()}_`, ""];
  for (const c of a.clips) {
    const src = sourceOf(a, c);
    const link = clipLink(src, c);
    const range = `${fmtTime(c.start)} – ${fmtTime(c.end)}`;
    lines.push(`## ${c.rank}. ${c.title}`);
    lines.push("");
    lines.push(`- **Range:** ${link ? `[${range}](${link})` : range} (${Math.round(c.duration)}s)`);
    lines.push(`- **Score:** ${c.score}`);
    if (a.sources.length > 1 && src) lines.push(`- **Video:** ${src.title}`);
    if (c.hook) lines.push(`- **Hook:** ${c.hook}`);
    for (const r of c.reasons) lines.push(`  - ${r.polarity === "neg" ? "⚠ " : ""}${r.text}`);
    lines.push("");
  }
  return lines.join("\n");
}

export function toJSON(a: Analysis): string {
  const rest: Partial<Analysis> = { ...a };
  delete rest.timelines;
  delete rest.transcripts;
  return JSON.stringify(rest, null, 2);
}

export function download(filename: string, text: string, mime: string) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "clips";
}
