import { CircleCheck, CircleX, Info } from "lucide-react";
import { createContext, useCallback, useContext, useState } from "react";
import type { ReactNode } from "react";
import { cx } from "../lib/format";

type Kind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: Kind;
  message: string;
}

const ToastContext = createContext<(message: string, kind?: Kind) => void>(() => {});

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((message: string, kind: Kind = "info") => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev.slice(-3), { id, kind, message }]);
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), kind === "error" ? 6000 : 3200);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[360px] max-w-[calc(100vw-2.5rem)] flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="glass-strong pointer-events-auto flex animate-fade-up items-start gap-3 rounded-xl px-4 py-3 text-[13px] shadow-2xl shadow-black/40">
            {t.kind === "success" ? (
              <CircleCheck className="mt-0.5 size-4 shrink-0 text-pos" />
            ) : t.kind === "error" ? (
              <CircleX className="mt-0.5 size-4 shrink-0 text-neg" />
            ) : (
              <Info className="mt-0.5 size-4 shrink-0 text-cyan" />
            )}
            <span className={cx("leading-relaxed", t.kind === "error" ? "text-[#fecaca]" : "text-fg")}>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
