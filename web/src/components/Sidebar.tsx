import { History, Settings, WandSparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useApp } from "../lib/app-context";
import { cx } from "../lib/format";
import { Logo } from "./ui";

const NAV = [
  { key: "studio", href: "#/", label: "Studio", icon: <WandSparkles className="size-[18px]" /> },
  { key: "history", href: "#/history", label: "History", icon: <History className="size-[18px]" /> },
  { key: "settings", href: "#/settings", label: "Settings", icon: <Settings className="size-[18px]" /> },
];

function StatusRow({ ok, warn, label, detail }: { ok: boolean; warn?: boolean; label: string; detail: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className={cx("mt-1.5 size-1.5 shrink-0 rounded-full", ok ? "bg-pos shadow-[0_0_8px] shadow-pos/60" : warn ? "bg-warn" : "bg-fg-3")} />
      <div className="min-w-0">
        <div className="text-[12px] text-fg-2">{label}</div>
        <div className="truncate text-[11.5px] text-fg-3">{detail}</div>
      </div>
    </div>
  );
}

export function Sidebar({ active }: { active: string }) {
  const { health, youtube } = useApp();
  const caps = health?.capabilities;
  return (
    <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col border-r border-white/[0.06] bg-ink-900 px-4 py-5 md:flex">
      <a href="#/" className="flex items-center gap-2.5 px-2">
        <Logo size={30} />
        <div>
          <div className="text-[15px] font-semibold tracking-tight text-fg">ClipAwesome</div>
          <div className="text-[11px] text-fg-3">Moment finder</div>
        </div>
      </a>

      <nav className="mt-8 space-y-1">
        {NAV.map((n) => {
          const on = n.key === active;
          return (
            <a
              key={n.key}
              href={n.href}
              className={cx(
                "relative flex h-10 items-center gap-3 rounded-xl px-3 text-[13.5px] font-medium transition-all duration-200",
                on ? "bg-white/[0.07] text-fg" : "text-fg-2 hover:bg-white/[0.04] hover:text-fg",
              )}
            >
              {on && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-accent" />}
              <span className={on ? "text-accent-soft" : ""}>{n.icon}</span>
              {n.label}
            </a>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 rounded-2xl border border-white/[0.06] bg-black/20 p-4">
        <div className="text-[11px] font-medium uppercase tracking-wider text-fg-3">Engine status</div>
        <StatusRow
          ok={!!caps?.ai_configured}
          label="AI mode"
          detail={caps?.ai_configured ? `${caps.ai_provider} · ${caps.ai_model}` : <a href="#/settings" className="text-accent-soft hover:underline">Configure provider</a>}
        />
        <StatusRow ok={!!caps?.whisper} label="Local transcription" detail={caps?.whisper ? "faster-whisper ready" : "Not installed"} />
        <StatusRow
          ok={!!youtube?.ok}
          warn={youtube !== null && !youtube.ok}
          label="YouTube"
          detail={youtube === null ? "Checking…" : youtube.ok ? "Reachable" : <a href="#/settings" className="text-warn hover:underline">Blocked — set proxy</a>}
        />
        {health && <div className="pt-1 text-[10.5px] text-fg-3">v{health.version}</div>}
      </div>
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
