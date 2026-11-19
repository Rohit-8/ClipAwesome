import {
  Bot,
  CircleCheck,
  CircleX,
  Cpu,
  Globe,
  KeyRound,
  ListRestart,
  Mic,
  RefreshCw,
  RotateCcw,
  Save,
  Server,
  SlidersHorizontal,
  Sparkles,
  Wifi,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useToast } from "../components/Toast";
import { Button, Card, Field, Input, Notice, SectionTitle, Segmented, Select, Slider, Toggle } from "../components/ui";
import { api } from "../lib/api";
import { useApp } from "../lib/app-context";
import { cx } from "../lib/format";
import type { AISettings, CheckResult, Provider, Settings, Weights } from "../lib/types";

const PROVIDERS: { value: Provider; name: string; blurb: string; icon: ReactNode; keyUrl?: string }[] = [
  { value: "custom", name: "Custom", blurb: "Any OpenAI-compatible endpoint", icon: <Server className="size-4" /> },
  { value: "gemini", name: "Gemini", blurb: "Google AI Studio", icon: <Sparkles className="size-4" />, keyUrl: "https://aistudio.google.com/apikey" },
  { value: "groq", name: "Groq", blurb: "Low-latency inference", icon: <Zap className="size-4" />, keyUrl: "https://console.groq.com/keys" },
  { value: "nvidia", name: "NVIDIA NIM", blurb: "build.nvidia.com", icon: <Cpu className="size-4" />, keyUrl: "https://build.nvidia.com" },
];

const CUSTOM_EXAMPLE = { base_url: "https://llm.maqsoftware.net/v1", model: "qwen-3.8-27b" };

const WEIGHTS: { key: keyof Weights; label: string; help: string }[] = [
  { key: "heatmap", label: "Most replayed", help: "YouTube's replay heatmap — the strongest audience signal." },
  { key: "relevance", label: "Topic relevance", help: "How strongly the transcript matches your focus or topic." },
  { key: "reactions", label: "Audience reactions", help: "Laughter, applause, exclamations and emphatic language." },
  { key: "audio", label: "Audio energy", help: "Loudness spikes relative to the rest of the video." },
  { key: "comments", label: "Viewer comments", help: "Timestamps viewers mention in comments, weighted by likes." },
  { key: "hook", label: "Opening hook", help: "Clips that open with a question or hook phrase." },
  { key: "highlight", label: "Community highlight", help: "SponsorBlock's crowd-marked highlight point." },
  { key: "completeness", label: "Clean boundaries", help: "Starts and ends on complete sentences." },
  { key: "pace", label: "Speech pace", help: "Faster, denser speech than usual." },
  { key: "visual", label: "Visual activity", help: "Density of scene cuts (local files)." },
];

const SECTIONS = [
  { id: "ai", label: "AI provider", icon: <Bot className="size-4" /> },
  { id: "analysis", label: "Analysis defaults", icon: <SlidersHorizontal className="size-4" /> },
  { id: "transcription", label: "Transcription", icon: <Mic className="size-4" /> },
  { id: "network", label: "YouTube & network", icon: <Globe className="size-4" /> },
  { id: "weights", label: "Scoring weights", icon: <ListRestart className="size-4" /> },
];

function Result({ r }: { r: CheckResult | null }) {
  if (!r) return null;
  return (
    <div className={cx("flex items-start gap-2 rounded-xl px-3.5 py-2.5 text-[12.5px] leading-relaxed", r.ok ? "bg-pos/[0.07] text-[#a7f3d0]" : "bg-neg/[0.07] text-[#fecaca]")}>
      {r.ok ? <CircleCheck className="mt-0.5 size-4 shrink-0" /> : <CircleX className="mt-0.5 size-4 shrink-0" />}
      <span className="break-words">{r.message}</span>
    </div>
  );
}

export function SettingsPage() {
  const { refresh } = useApp();
  const toast = useToast();
  const [saved, setSaved] = useState<Settings | null>(null);
  const [form, setForm] = useState<Settings | null>(null);
  const [providers, setProviders] = useState<Record<string, { base_url: string; model: string }>>({});
  const [models, setModels] = useState<string[]>([]);
  const [aiResult, setAiResult] = useState<CheckResult | null>(null);
  const [ytResult, setYtResult] = useState<CheckResult | null>(null);
  const [busy, setBusy] = useState<"" | "save" | "test" | "models" | "yt">("");

  useEffect(() => {
    Promise.all([api.settings(), api.providers()])
      .then(([s, p]) => {
        setSaved(s);
        setForm(s);
        setProviders(p);
      })
      .catch((e: Error) => toast(e.message, "error"));
  }, [toast]);

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(saved), [form, saved]);

  if (!form || !saved) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4 px-8 py-10">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-48 animate-pulse rounded-2xl bg-white/[0.03]" />
        ))}
      </div>
    );
  }

  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const setAI = <K extends keyof AISettings>(k: K, v: AISettings[K]) => setForm((f) => (f ? { ...f, ai: { ...f.ai, [k]: v } } : f));
  const setWeight = (k: keyof Weights, v: number) => setForm((f) => (f ? { ...f, weights: { ...f.weights, [k]: v } } : f));

  const ai = form.ai;
  const defaults = providers[ai.provider] ?? { base_url: "", model: "" };
  const urlPlaceholder = defaults.base_url || CUSTOM_EXAMPLE.base_url;
  const modelPlaceholder = defaults.model || CUSTOM_EXAMPLE.model;
  const effectiveUrl = ai.base_url || defaults.base_url || "<base_url>";
  const effectiveModel = ai.model || defaults.model || "<model>";
  const keyMasked = ai.api_key.startsWith("••••");
  const keyCleared = ai.api_key === "__clear__";
  const providerInfo = PROVIDERS.find((p) => p.value === ai.provider)!;

  const save = async () => {
    setBusy("save");
    try {
      const res = await api.saveSettings(form);
      setSaved(res);
      setForm(res);
      refresh();
      toast("Settings saved", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  };

  const testAI = async () => {
    setBusy("test");
    setAiResult(null);
    try {
      setAiResult(await api.testAI(ai));
    } catch (e) {
      setAiResult({ ok: false, message: (e as Error).message });
    } finally {
      setBusy("");
    }
  };

  const loadModels = async () => {
    setBusy("models");
    try {
      const res = await api.listModels(ai);
      if (res.ok) {
        setModels(res.models);
        toast(`${res.models.length} models available`, "success");
      } else toast(res.message ?? "Could not list models", "error");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  };

  const checkYouTube = async () => {
    setBusy("yt");
    setYtResult(null);
    try {
      setYtResult(await api.checkYouTube(form.proxy));
    } catch (e) {
      setYtResult({ ok: false, message: (e as Error).message });
    } finally {
      setBusy("");
    }
  };

  const resetWeights = async () => {
    const d = await api.defaults();
    set("weights", d.weights);
  };

  return (
    <div className="mx-auto max-w-[1100px] px-5 pb-28 pt-10 md:px-8">
      <div className="mb-8">
        <h1 className="text-[28px] font-semibold tracking-tight text-fg">Settings</h1>
        <p className="mt-1 text-[14px] text-fg-2">Configure AI, transcription, network access and how clips are scored. Stored locally in <code className="text-fg">data/settings.json</code>.</p>
      </div>

      <div className="grid gap-8 lg:grid-cols-[200px_minmax(0,1fr)]">
        <nav className="hidden lg:block">
          <div className="sticky top-8 space-y-1">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => document.getElementById(`set-${s.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-fg-2 transition hover:bg-white/[0.04] hover:text-fg"
              >
                {s.icon}
                {s.label}
              </button>
            ))}
          </div>
        </nav>

        <div className="min-w-0 space-y-6">
          <Card id="set-ai" className="scroll-mt-6 p-6">
            <SectionTitle
              icon={<Bot className="size-4" />}
              title="AI provider"
              subtitle="Every provider is called through the OpenAI chat-completions protocol, so any compatible gateway works."
              action={ai.configured ? <span className="text-[12px] text-pos">● Configured</span> : <span className="text-[12px] text-fg-3">Not configured</span>}
            />

            <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => {
                    setAI("provider", p.value);
                    setModels([]);
                    setAiResult(null);
                  }}
                  className={cx(
                    "rounded-xl border p-3 text-left transition-all duration-200",
                    ai.provider === p.value ? "border-violet/50 bg-violet/[0.08] shadow-[0_0_0_3px_rgba(139,92,246,0.08)]" : "border-white/[0.07] hover:border-white/15 hover:bg-white/[0.02]",
                  )}
                >
                  <div className={cx("flex items-center gap-2 text-[13.5px] font-medium", ai.provider === p.value ? "text-fg" : "text-fg-2")}>
                    {p.icon}
                    {p.name}
                  </div>
                  <div className="mt-1 text-[11.5px] text-fg-3">{p.blurb}</div>
                </button>
              ))}
            </div>

            <div className="mt-6 grid gap-5 md:grid-cols-2">
              <Field label="Base URL" hint={ai.provider === "custom" ? "Ends with /v1 — e.g. your company gateway or a local server." : "Leave empty to use the provider default."}>
                <Input value={ai.base_url} onChange={(e) => setAI("base_url", e.target.value)} placeholder={urlPlaceholder} spellCheck={false} />
              </Field>
              <Field
                label="Model"
                hint={
                  <button type="button" onClick={loadModels} disabled={busy === "models"} className="inline-flex items-center gap-1 text-[#c4b5fd] hover:text-white disabled:opacity-50">
                    <RefreshCw className={cx("size-3", busy === "models" && "animate-spin")} /> Load models from endpoint
                  </button>
                }
              >
                <Input value={ai.model} onChange={(e) => setAI("model", e.target.value)} placeholder={modelPlaceholder} list="ai-models" spellCheck={false} />
                <datalist id="ai-models">
                  {models.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </Field>
              <Field
                label="API key"
                className="md:col-span-2"
                hint={
                  keyCleared ? (
                    <span className="text-warn">The saved key will be removed when you save.</span>
                  ) : ai.has_api_key ? (
                    <span>
                      A key is saved ({ai.api_key}). Type a new one to replace it, or{" "}
                      <button type="button" className="text-neg hover:underline" onClick={() => setAI("api_key", "__clear__")}>
                        remove it
                      </button>
                      .
                    </span>
                  ) : providerInfo.keyUrl ? (
                    <span>
                      Get a key at{" "}
                      <a href={providerInfo.keyUrl} target="_blank" rel="noreferrer" className="text-[#c4b5fd] hover:underline">
                        {providerInfo.keyUrl.replace("https://", "")}
                      </a>
                      . Stored only on this machine and never sent back to the browser.
                    </span>
                  ) : (
                    "Optional for local gateways. Stored only on this machine and never sent back to the browser."
                  )
                }
              >
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-fg-3" />
                  <Input
                    type="password"
                    autoComplete="off"
                    className="pl-10 font-mono"
                    value={keyMasked || keyCleared ? "" : ai.api_key}
                    placeholder={keyMasked ? ai.api_key : "sk-…"}
                    onChange={(e) => setAI("api_key", e.target.value || saved.ai.api_key)}
                  />
                </div>
              </Field>
            </div>

            <div className="mt-6 grid gap-6 md:grid-cols-3">
              <Slider label="AI weight in final score" value={ai.ai_weight} min={0} max={1} step={0.05} onChange={(v) => setAI("ai_weight", v)} format={(v) => `${Math.round(v * 100)}%`} />
              <Slider label="Temperature" value={ai.temperature} min={0} max={1.5} step={0.05} onChange={(v) => setAI("temperature", v)} format={(v) => v.toFixed(2)} />
              <Slider label="Timeout" value={ai.timeout_sec} min={15} max={300} step={5} onChange={(v) => setAI("timeout_sec", v)} format={(v) => `${v}s`} />
            </div>

            <div className="mt-6 overflow-hidden rounded-xl border border-white/[0.06] bg-black/30">
              <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2 text-[11.5px] text-fg-3">
                <span>Equivalent request</span>
                <span>OpenAI SDK</span>
              </div>
              <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-relaxed text-fg-2">
                <span className="text-[#c4b5fd]">client</span> = OpenAI(base_url=<span className="text-[#86efac]">"{effectiveUrl}"</span>, api_key=
                <span className="text-[#86efac]">"{ai.has_api_key || (!keyMasked && ai.api_key) ? "sk-…" : "not-needed"}"</span>){"\n"}
                <span className="text-[#c4b5fd]">client</span>.chat.completions.create(model=<span className="text-[#86efac]">"{effectiveModel}"</span>, messages=[…])
              </pre>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button onClick={testAI} loading={busy === "test"} icon={<Zap className="size-4" />}>
                Test connection
              </Button>
              <span className="text-[12px] text-fg-3">Uses the values above, even before saving.</span>
            </div>
            {aiResult && (
              <div className="mt-3">
                <Result r={aiResult} />
              </div>
            )}
          </Card>

          <Card id="set-analysis" className="scroll-mt-6 p-6">
            <SectionTitle icon={<SlidersHorizontal className="size-4" />} title="Analysis defaults" subtitle="Pre-selected options in the Studio." />
            <div className="mt-5 grid gap-5 md:grid-cols-2">
              <Field label="Default mode">
                <Segmented
                  value={form.default_mode}
                  onChange={(v) => set("default_mode", v)}
                  options={[
                    { value: "deterministic", label: "Deterministic", icon: <Cpu className="size-4" /> },
                    { value: "ai", label: "AI", icon: <Sparkles className="size-4" /> },
                  ]}
                />
              </Field>
              <Field label="Default clip length">
                <Select value={form.default_preset} onChange={(e) => set("default_preset", e.target.value as Settings["default_preset"])}>
                  <option value="shorts">Shorts · 15–60s</option>
                  <option value="standard">Standard · 30–90s</option>
                  <option value="long">Long · 1–3 min</option>
                </Select>
              </Field>
              <Slider label="Default number of suggestions" value={form.default_max_clips} min={1} max={20} onChange={(v) => set("default_max_clips", v)} />
              <Field label="Visual analysis (local files)" hint="Fast reads key-frames only; Full samples ~5 frames/s and is slower on long videos.">
                <Segmented
                  value={form.visual_analysis}
                  onChange={(v) => set("visual_analysis", v)}
                  options={[
                    { value: "off", label: "Off" },
                    { value: "fast", label: "Fast" },
                    { value: "full", label: "Full" },
                  ]}
                />
              </Field>
              <Toggle checked={form.include_comments} onChange={(v) => set("include_comments", v)} label="Mine viewer comments" description="Look for timestamps people mention in YouTube comments." />
              <Slider label="Comments to scan" value={form.max_comments} min={50} max={1000} step={50} onChange={(v) => set("max_comments", v)} />
            </div>
          </Card>

          <Card id="set-transcription" className="scroll-mt-6 p-6">
            <SectionTitle icon={<Mic className="size-4" />} title="Transcription" subtitle="Local speech-to-text with faster-whisper for files and caption-less videos." />
            <div className="mt-5 grid gap-5 md:grid-cols-3">
              <Field label="Whisper model" hint="base is fast on CPU; small is more accurate.">
                <Select value={form.whisper_model} onChange={(e) => set("whisper_model", e.target.value)}>
                  {["tiny", "base", "small", "medium", "large-v3", "turbo", "distil-large-v3"].map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Device">
                <Select value={form.whisper_device} onChange={(e) => set("whisper_device", e.target.value as Settings["whisper_device"])}>
                  <option value="cpu">CPU</option>
                  <option value="cuda">NVIDIA GPU (CUDA)</option>
                  <option value="auto">Auto</option>
                </Select>
              </Field>
              <Field label="Compute type">
                <Select value={form.whisper_compute_type} onChange={(e) => set("whisper_compute_type", e.target.value)}>
                  {["int8", "int8_float16", "float16", "float32"].map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="YouTube audio analysis" className="md:col-span-2" hint="Downloads the audio temporarily to measure energy and transcribe; deleted right after.">
                <Segmented
                  value={form.youtube_audio}
                  onChange={(v) => set("youtube_audio", v)}
                  options={[
                    { value: "never", label: "Never" },
                    { value: "when_needed", label: "When no captions" },
                    { value: "always", label: "Always" },
                  ]}
                />
              </Field>
              <Field label="Preferred caption languages" hint="Comma-separated, e.g. en, hi">
                <Input
                  value={form.caption_languages.join(", ")}
                  onChange={(e) =>
                    set(
                      "caption_languages",
                      e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    )
                  }
                />
              </Field>
            </div>
          </Card>

          <Card id="set-network" className="scroll-mt-6 p-6">
            <SectionTitle icon={<Globe className="size-4" />} title="YouTube & network" subtitle="Optional API key for official search, and a proxy for restricted networks." />
            <div className="mt-5 grid gap-5 md:grid-cols-2">
              <Field
                label="YouTube Data API key (optional)"
                hint={form.has_youtube_api_key ? "A key is saved. Type to replace it." : "Enables official search and the Creative-Commons filter. Without it, search uses yt-dlp."}
              >
                <Input
                  type="password"
                  autoComplete="off"
                  className="font-mono"
                  value={form.youtube_api_key.startsWith("••••") ? "" : form.youtube_api_key}
                  placeholder={form.youtube_api_key.startsWith("••••") ? form.youtube_api_key : "AIza…"}
                  onChange={(e) => set("youtube_api_key", e.target.value || saved.youtube_api_key)}
                />
              </Field>
              <Field label="Proxy" hint="Used for YouTube, SponsorBlock and search. http://, https:// or socks5://">
                <Input value={form.proxy} onChange={(e) => set("proxy", e.target.value)} placeholder="http://proxy.company.com:8080" spellCheck={false} />
              </Field>
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button onClick={checkYouTube} loading={busy === "yt"} icon={<Wifi className="size-4" />}>
                Check YouTube connection
              </Button>
            </div>
            {ytResult && (
              <div className="mt-3">
                <Result r={ytResult} />
              </div>
            )}
          </Card>

          <Card id="set-weights" className="scroll-mt-6 p-6">
            <SectionTitle
              icon={<ListRestart className="size-4" />}
              title="Scoring weights"
              subtitle="How much each signal counts. Weights are normalised over the signals a video actually has."
              action={
                <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={resetWeights}>
                  Reset
                </Button>
              }
            />
            <div className="mt-6 grid gap-x-8 gap-y-6 md:grid-cols-2">
              {WEIGHTS.map((w) => (
                <div key={w.key}>
                  <Slider label={w.label} value={form.weights[w.key]} min={0} max={0.5} step={0.01} onChange={(v) => setWeight(w.key, v)} format={(v) => v.toFixed(2)} />
                  <p className="mt-1.5 text-[11.5px] leading-relaxed text-fg-3">{w.help}</p>
                </div>
              ))}
            </div>
          </Card>

          {!ai.configured && form.default_mode === "ai" && <Notice>Default mode is AI but no provider is configured yet — the Studio will fall back to Deterministic.</Notice>}
        </div>
      </div>

      <div
        className={cx(
          "pointer-events-none fixed inset-x-0 bottom-5 z-40 flex justify-center px-5 transition-all duration-300 md:pl-[248px]",
          dirty ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0",
        )}
      >
        <div className="glass-strong pointer-events-auto flex w-full max-w-[640px] items-center justify-between gap-4 rounded-2xl px-5 py-3 shadow-2xl shadow-black/50">
          <span className="text-[13px] text-fg-2">You have unsaved changes</span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => setForm(saved)}>
              Discard
            </Button>
            <Button variant="primary" size="sm" loading={busy === "save"} icon={<Save className="size-3.5" />} onClick={save}>
              Save changes
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
