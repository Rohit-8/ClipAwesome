import { Download, History, PanelLeftClose, PanelLeftOpen, Scissors, Settings, WandSparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useApp } from "../lib/app-context";
import { cx } from "../lib/format";
import { IconButton, Logo } from "./ui";

const NAV = [
  { key: "studio", href: "#/", label: "Studio", icon: <WandSparkles className="size-[18px]" /> },
  { key: "download", href: "#/download", label: "Download", icon: <Download className="size-[18px]" /> },
  { key: "editor", href: "#/editor", label: "Editor", icon: <Scissors className="size-[18px]" /> },
  { key: "history", href: "#/history", label: "History", icon: <History className="size-[18px]" /> },
  { key: "settings", href: "#/settings", label: "Settings", icon: <Settings className="size-[18px]" /> },
];

function StatusRow({ ok, warn, label, detail }: { ok: boolean; warn?: boolean; label: string; detail: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <StatusDot ok={ok} warn={warn} className="mt-1.5" />
      <div className="min-w-0">
        <div className="text-[12px] text-fg-2">{label}</div>
        <div className="truncate text-[11.5px] text-fg-3">{detail}</div>
      </div>
    </div>
  );
}

function StatusDot({ ok, warn, className, title }: { ok: boolean; warn?: boolean; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cx("size-1.5 shrink-0 rounded-full", ok ? "bg-pos shadow-[0_0_8px] shadow-pos/60" : warn ? "bg-warn" : "bg-fg-3", className)}
    />
  );
}

/** Logo and name live here, outside the sidebar, so they never collapse. */
export function TopBar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <header className="hidden h-14 shrink-0 items-center gap-3 border-b border-white/[0.06] bg-ink-900 px-[18px] md:flex">
      <IconButton label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} onClick={onToggle} className="size-9">
        {collapsed ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
      </IconButton>
      <a href="#/" className="flex items-center gap-2.5">
        <Logo size={28} />
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight text-fg">ClipAwesome</div>
          <div className="text-[11px] text-fg-3">Moment finder</div>
        </div>
      </a>
    </header>
  );
}

export function Sidebar({ active, collapsed }: { active: string; collapsed: boolean }) {
  const { health, youtube } = useApp();
  const caps = health?.capabilities;
  const ai = caps?.ai_configured ? `${caps.ai_provider} · ${caps.ai_model}` : "Not configured";
  const yt = youtube === null ? "Checking…" : youtube.ok ? "Reachable" : "Blocked — set a proxy";
  const perf = caps?.performance ? `${caps.performance[0].toUpperCase()}${caps.performance.slice(1)}${caps.performance_auto ? " (auto)" : ""}` : "…";
  return (
    <aside
      className={cx(
        "hidden h-full shrink-0 flex-col overflow-y-auto overflow-x-hidden border-r border-white/[0.06] bg-ink-900 py-5 transition-[width] duration-200 md:flex",
        collapsed ? "w-[72px] px-3" : "w-[248px] px-4",
      )}
    >
      <nav className="space-y-1">
        {NAV.map((n) => {
          const on = n.key === active;
          return (
            <a
              key={n.key}
              href={n.href}
              title={collapsed ? n.label : undefined}
              aria-label={collapsed ? n.label : undefined}
              className={cx(
                "relative flex h-10 items-center gap-3 rounded-xl text-[13.5px] font-medium whitespace-nowrap transition-all duration-200",
                collapsed ? "justify-center" : "px-3",
                on ? "bg-white/[0.07] text-fg" : "text-fg-2 hover:bg-white/[0.04] hover:text-fg",
              )}
            >
              {on && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-accent" />}
              <span className={on ? "text-accent-soft" : ""}>{n.icon}</span>
              {!collapsed && n.label}
            </a>
          );
        })}
      </nav>

      {collapsed ? (
        <a
          href="#/settings"
          title={`Engine status\nAI mode: ${ai}\nLocal transcription: ${caps?.whisper ? "ready" : "not installed"}\nYouTube: ${yt}\nPerformance: ${perf}`}
          className="mt-auto flex flex-col items-center gap-2.5 rounded-xl border border-white/[0.06] bg-black/20 py-3"
        >
          <StatusDot ok={!!caps?.ai_configured} />
          <StatusDot ok={!!caps?.whisper} />
          <StatusDot ok={!!youtube?.ok} warn={youtube !== null && !youtube.ok} />
        </a>
      ) : (
        <div className="mt-auto space-y-3 rounded-2xl border border-white/[0.06] bg-black/20 p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-fg-3">Engine status</div>
          <StatusRow
            ok={!!caps?.ai_configured}
            label="AI mode"
            detail={caps?.ai_configured ? ai : <a href="#/settings" className="text-accent-soft hover:underline">Configure provider</a>}
          />
          <StatusRow ok={!!caps?.whisper} label="Local transcription" detail={caps?.whisper ? "faster-whisper ready" : "Not installed"} />
          <StatusRow
            ok={!!caps?.performance && caps.performance !== "low"}
            warn={caps?.performance === "low"}
            label="Performance"
            detail={
              <a href="#/settings" className="hover:text-fg" title="Change in Settings → Performance">
                {perf}
                {caps?.performance === "low" ? " · lighter, less accurate" : ""}
              </a>
            }
          />
          <StatusRow
            ok={!!youtube?.ok}
            warn={youtube !== null && !youtube.ok}
            label="YouTube"
            detail={youtube === null || youtube.ok ? yt : <a href="#/settings" className="text-warn hover:underline">Blocked — set proxy</a>}
          />
          {health && <div className="pt-1 text-[10.5px] text-fg-3">v{health.version}</div>}
        </div>
      )}
    </aside>
  );
}

export function MobileNav({ active }: { active: string }) {
  return (
    <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-white/[0.06] bg-ink-900/80 px-4 py-3 backdrop-blur-xl md:hidden">
      <Logo size={26} />
      <nav className="flex gap-1">
        {NAV.map((n) => (
          <a key={n.key} href={n.href} className={cx("rounded-lg px-3 py-1.5 text-[13px]", n.key === active ? "bg-white/[0.08] text-fg" : "text-fg-2")}>
            {n.label}
          </a>
        ))}
      </nav>
    </div>
  );
}
