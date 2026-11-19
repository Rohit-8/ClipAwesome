const UNIT_SECONDS: Record<string, number> = {
  h: 3600, hr: 3600, hrs: 3600, hour: 3600, hours: 3600,
  m: 60, min: 60, mins: 60, minute: 60, minutes: 60,
  s: 1, sec: 1, secs: 1, second: 1, seconds: 1,
};

/** Parses "90", "90.5", "1:30", "1:02:03", "2m 30s", "1.5m", "1h 20m", "2 hours" into seconds; null if unreadable. */
export function parseTime(raw: string): number | null {
  const s = raw.trim().toLowerCase();
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) return Number(s);
  if (/^\d+(:\d{1,2}){1,2}(\.\d+)?$/.test(s)) {
    const parts = s.split(":").map(Number);
    if (parts.slice(1).some((p) => p >= 60)) return null;
    return parts.reduce((acc, p) => acc * 60 + p, 0);
  }
  const unitRe = /(\d+(?:\.\d+)?)\s*(hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)(?![a-z])/g;
  let total = 0;
  let matched = false;
  const rest = s.replace(unitRe, (_, n: string, unit: string) => {
    total += Number(n) * UNIT_SECONDS[unit];
    matched = true;
    return " ";
  });
  if (!matched || rest.replace(/[\s,]|and/g, "") !== "") return null;
  return total;
}

/** Human length that parseTime can read back: 90 → "1m 30s", 3600 → "1h", 12.5 → "12.5s". */
export function formatLength(sec: number): string {
  const total = Math.round(Math.max(0, sec) * 10) / 10;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.round((total % 60) * 10) / 10;
  const parts: string[] = [];
  if (h) parts.push(`${h}h`);
  if (m) parts.push(`${m}m`);
  if (s || !parts.length) parts.push(`${s}s`);
  return parts.join(" ");
}

export const MIN_GAP = 5;

/**
 * Keeps a min/max clip-length pair valid. The value just edited is moved to the nearest valid value
 * (same rule the old sliders used); `limit` caps both to the media length when it is known.
 */
export function snapRange(
  min: number,
  max: number,
  edited: "min" | "max",
  limit: number | null,
): { min: number; max: number; note: string | null } {
  let lo = Math.max(0, min);
  let hi = Math.max(0, max);
  const notes: string[] = [];
  if (limit && limit > 0) {
    if (hi > limit) {
      hi = limit;
      notes.push(`maximum capped to the media length (${formatLength(limit)})`);
    }
    if (lo > Math.max(0, limit - MIN_GAP)) {
      lo = Math.max(0, limit - MIN_GAP);
      notes.push(`minimum lowered to ${formatLength(lo)} to fit the media length`);
    }
  }
  if (hi - lo < MIN_GAP) {
    if (edited === "min" && hi >= MIN_GAP) {
      lo = hi - MIN_GAP;
      notes.push(`minimum set to ${formatLength(lo)} — it must be at least ${MIN_GAP}s below the maximum`);
    } else {
      hi = lo + MIN_GAP;
      notes.push(`maximum set to ${formatLength(hi)} — it must be at least ${MIN_GAP}s above the minimum`);
    }
  }
  const note = notes.length ? notes.join("; ").replace(/^./, (c) => c.toUpperCase()) + "." : null;
  return { min: lo, max: hi, note };
}
