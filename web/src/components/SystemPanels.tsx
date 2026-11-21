import { CircleCheck, CircleX, Gauge, HardDrive, Info, RefreshCw, Stethoscope, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import { cx, fmtBytes } from "../lib/format";
import type { DiagnosticCheck, PerformanceName, PerformanceProfile, Settings, StorageUsage, SystemInfo } from "../lib/types";
import { useToast } from "./Toast";
import { Badge, Button, Card, Field, SectionTitle, Segmented, Slider } from "./ui";

type SetSetting = <K extends keyof Settings>(k: K, v: Settings[K]) => void;

const NAMES: Record<PerformanceName, string> = { low: "Low", balanced: "Balanced", high: "High" };

const SUMMARY: Record<PerformanceName, string> = {
  low: "For laptops with 4 or fewer CPU threads or under 8 GB RAM. Analyses and exports use far less CPU and memory; transcripts and some signals are less complete.",
  balanced: "For typical laptops and desktops. Full quality, with long videos transcribed only where the best moments are likely.",
  high: "For strong machines (12+ CPU threads, 16 GB+ RAM). Everything in full, two heavy tasks at once, slightly smaller export files.",
};

function focusText(p: PerformanceProfile): string {
  if (p.focused_over_sec === null) return "Never (full transcripts)";
  if (p.focused_over_sec === 0) return "Always";
  return `Videos longer than ${Math.round(p.focused_over_sec / 60)} min`;
}

function presetEffect(preset: string): string {
  if (preset === "superfast") return "Fastest encoding; same visual quality, files about 10–20% larger";
  if (preset === "faster") return "Slower encoding; files about 10% smaller at the same quality";
  return "Good balance of speed and file size";
}

function EffectRow({ what, value, effect, warn }: { what: string; value: ReactNode; effect: string; warn?: boolean }) {
  return (
    <div className="grid gap-1 border-t border-white/[0.05] py-2.5 first:border-t-0 sm:grid-cols-[170px_150px_minmax(0,1fr)] sm:gap-3">
      <span className="text-[12.5px] text-fg-3">{what}</span>
      <span className="text-[12.5px] font-medium text-fg">{value}</span>
      <span className={cx("text-[12.5px]", warn ? "text-warn" : "text-fg-2")}>{effect}</span>
    </div>
  );
}

export function PerformanceCard({ form, set }: { form: Settings; set: SetSetting }) {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  useEffect(() => {
    api
      .systemInfo()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

  const name: PerformanceName = form.performance === "auto" ? (info?.recommended ?? "balanced") : form.performance;
  const p = info?.profiles[name];
  const focusedMode =
    form.focused_transcription === "auto" ? (p ? focusText(p) : "follows the profile") : form.focused_transcription === "on" ? "Always (your choice)" : "Never (your choice)";

  return (
    <Card id="set-performance" className="scroll-mt-6 p-6">
      <SectionTitle
        icon={<Gauge className="size-4" />}
        title="Performance"
        subtitle="How hard ClipAwesome works this machine. Lighter settings are faster and use less memory, but can reduce accuracy and file efficiency. Applies to new analyses and exports."
      />
      <div className="mt-5 space-y-5">
        <div className="rounded-xl border border-white/[0.06] bg-black/20 px-4 py-3 text-[13px] text-fg-2">
          {info ? (
            <>
              This machine: <span className="text-fg">{info.cpus} CPU threads</span> ·{" "}
              <span className="text-fg">{info.ram_gb ?? "?"} GB RAM</span>
              {info.available_ram_gb !== null && <span className="text-fg-3"> ({info.available_ram_gb} GB free now)</span>} · recommended:{" "}
              <span className="font-medium text-accent-soft">{NAMES[info.recommended]}</span>
            </>
          ) : (
            <span className="text-fg-3">Reading machine details…</span>
          )}
        </div>

        <Field label="Performance profile">
          <Segmented
            value={form.performance}
            onChange={(v) => set("performance", v)}
            options={[
              { value: "auto", label: `Auto${info ? ` (${NAMES[info.recommended]})` : ""}`, hint: "Detects CPU and memory and picks a profile" },
              { value: "low", label: "Low" },
              { value: "balanced", label: "Balanced" },
              { value: "high", label: "High" },
            ]}
          />
        </Field>

        {p && (
          <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-semibold text-fg">What {NAMES[name]} does</span>
              {name === "low" && <Badge tone="warn">Lower accuracy</Badge>}
            </div>
            <p className="mb-3 text-[12.5px] text-fg-3">{SUMMARY[name]}</p>
            <EffectRow
              what="Speech-to-text model"
              value={p.whisper_model ? `${p.whisper_model} (forced)` : `${form.whisper_model} (your choice)`}
              effect={p.whisper_model ? "About 3× faster than base, but more transcription mistakes in titles, hooks and topic matching" : "Uses the model chosen under Transcription"}
              warn={!!p.whisper_model}
            />
            <EffectRow
              what="Focused transcription"
              value={form.focused_transcription === "auto" ? focusText(p) : focusedMode}
              effect="Only the most replayed, commented and loud stretches are transcribed; moments elsewhere get no transcript"
              warn={form.focused_transcription === "on" || (form.focused_transcription === "auto" && p.focused_over_sec !== null)}
            />
            <EffectRow
              what="Scene-cut detection"
              value={p.visual_analysis === "off" ? "Off (forced)" : "Your choice"}
              effect={p.visual_analysis === "off" ? "Local files lose the visual-activity signal; other signals are unaffected" : "Uses the setting under Analysis defaults"}
              warn={p.visual_analysis === "off"}
            />
            <EffectRow what="Heavy tasks at once" value={p.heavy_slots} effect="Transcriptions and exports beyond this wait in a queue instead of slowing everything down" />
            <EffectRow what="CPU threads per task" value={`${p.threads} of ${info?.cpus ?? "?"}`} effect="The rest stays free so the computer remains responsive" />
            <EffectRow what="Video export (CPU)" value={`x264 ${p.x264_preset}`} effect={presetEffect(p.x264_preset)} warn={p.x264_preset === "superfast"} />
            <EffectRow what="Audio kept in memory" value={`${p.chunk_sec / 60} min at a time`} effect="Long videos are transcribed piece by piece, so memory stays low" />
          </div>
        )}

        <Field
          label="Focused transcription"
          hint={`Applies to videos without captions. Auto follows the profile: currently ${focusedMode.toLowerCase()}. Each analysis notes how much was transcribed.`}
        >
          <Segmented
            value={form.focused_transcription}
            onChange={(v) => set("focused_transcription", v)}
            options={[
              { value: "auto", label: "Auto" },
              { value: "on", label: "Always", hint: "Fastest: transcribe only the likely moments" },
              { value: "off", label: "Never", hint: "Complete transcripts; slowest on long videos" },
            ]}
          />
        </Field>
      </div>
    </Card>
  );
}

export function StorageCard({ form, set }: { form: Settings; set: SetSetting }) {
  const toast = useToast();
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .storage()
      .then(setUsage)
      .catch(() => setUsage(null));
  }, []);

  const clean = async () => {
    setBusy(true);
    try {
      const res = await api.cleanupStorage();
      setUsage(res.usage);
      toast(res.freed_bytes ? `Freed ${fmtBytes(res.freed_bytes)}` : "Nothing to clean up", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const lowDisk = !!usage && usage.disk_free_bytes < 5 * 1024 ** 3;

  return (
    <Card id="set-storage" className="scroll-mt-6 p-6">
      <SectionTitle
        icon={<HardDrive className="size-4" />}
        title="Storage"
        subtitle="Caches and finished exports are cleaned up automatically. Your downloads and the files you opened are never deleted automatically."
      />
      <div className="mt-5 space-y-5">
        {usage ? (
          <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[13px]">
              <span className="text-fg-2">
                Using <span className="font-medium text-fg">{fmtBytes(usage.total_bytes)}</span> ·{" "}
                <span className={cx(lowDisk ? "text-warn" : "text-fg")}>{fmtBytes(usage.disk_free_bytes)} free</span> of {fmtBytes(usage.disk_total_bytes)}
              </span>
              {lowDisk && <Badge tone="warn">Low disk space</Badge>}
            </div>
            <div className="space-y-1.5">
              {usage.categories.map((c) => (
                <div key={c.key} className="flex items-center gap-3 text-[12.5px]">
                  <span className="min-w-0 flex-1 truncate text-fg-2">{c.label}</span>
                  {c.auto_cleanup && <span className="text-[11px] text-fg-3">auto-cleaned</span>}
                  <span className="w-20 text-right tabular text-fg">{fmtBytes(c.bytes)}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="h-32 animate-pulse rounded-xl bg-white/[0.03]" />
        )}
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <Slider
              label="Keep caches and finished exports for"
              value={form.cleanup_days}
              min={0}
              max={60}
              onChange={(v) => set("cleanup_days", v)}
              format={(v) => (v === 0 ? "Forever" : `${v} days`)}
            />
            <p className="mt-1.5 text-[11.5px] text-fg-3">Exports are saved to your computer when they finish; this only removes the server's copy.</p>
          </div>
          <div>
            <Slider
              label="YouTube playback copies limit"
              value={form.cache_limit_gb}
              min={0}
              max={50}
              onChange={(v) => set("cache_limit_gb", v)}
              format={(v) => (v === 0 ? "No limit" : `${v} GB`)}
            />
            <p className="mt-1.5 text-[11.5px] text-fg-3">Oldest copies are removed first when the limit is reached.</p>
          </div>
        </div>
        <Button icon={<Trash2 className="size-4" />} loading={busy} onClick={clean}>
          Clean up now
        </Button>
        <p className="-mt-3 text-[12px] text-fg-3">Removes YouTube playback copies, audio preview copies, temporary files and finished exports right away.</p>
      </div>
    </Card>
  );
}

const STATUS_ICON: Record<DiagnosticCheck["status"], ReactNode> = {
  ok: <CircleCheck className="size-4 text-pos" />,
  warn: <TriangleAlert className="size-4 text-warn" />,
  fail: <CircleX className="size-4 text-neg" />,
  info: <Info className="size-4 text-cyan" />,
};

export function DiagnoseCard() {
  const [checks, setChecks] = useState<DiagnosticCheck[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setChecks((await api.diagnostics()).checks);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const problems = (checks ?? []).filter((c) => c.status === "fail" || c.status === "warn").length;

  return (
    <Card id="set-diagnose" className="scroll-mt-6 p-6">
      <SectionTitle
        icon={<Stethoscope className="size-4" />}
        title="Diagnose"
        subtitle="Checks FFmpeg, GPU encoding, speech-to-text, yt-dlp, YouTube access, disk space and memory, with a fix for each problem."
        action={
          <Button size="sm" icon={<RefreshCw className="size-3.5" />} loading={busy} onClick={run}>
            {checks ? "Run again" : "Run checks"}
          </Button>
        }
      />
      {error && <p className="mt-4 text-[13px] text-neg">{error}</p>}
      {checks && (
        <div className="mt-5 space-y-3">
          <div className={cx("text-[13px] font-medium", problems ? "text-warn" : "text-pos")}>
            {problems ? `${problems} item${problems === 1 ? "" : "s"} need attention` : "Everything looks good"}
          </div>
          <ul className="space-y-2">
            {checks.map((c) => (
              <li key={c.key} className="flex items-start gap-3 rounded-xl border border-white/[0.06] bg-black/20 px-3.5 py-2.5">
                <span className="mt-0.5 shrink-0">{STATUS_ICON[c.status]}</span>
                <div className="min-w-0">
                  <div className="text-[13px] font-medium text-fg">{c.label}</div>
                  <div className="break-words text-[12.5px] text-fg-2">{c.detail}</div>
                  {c.hint && <div className="mt-0.5 text-[12px] text-accent-soft">Fix: {c.hint}</div>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
