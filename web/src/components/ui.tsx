import { ChevronDown, LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useId } from "react";
import { cx } from "../lib/format";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const BTN_BASE =
  "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-200 select-none whitespace-nowrap disabled:opacity-45 disabled:pointer-events-none";
const BTN_SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-[15px]",
};
const BTN_VARIANT: Record<Variant, string> = {
  primary:
    "bg-accent text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.18),0_1px_2px_rgba(0,0,0,0.5)] hover:bg-accent-hover active:scale-[0.98]",
  secondary: "bg-white/[0.05] text-fg border border-white/[0.08] hover:bg-white/[0.09] hover:border-white/[0.14]",
  ghost: "text-fg-2 hover:text-fg hover:bg-white/[0.06]",
  danger: "text-neg bg-neg/10 border border-neg/20 hover:bg-neg/15",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  icon,
  children,
  className,
  disabled,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean; icon?: ReactNode }) {
  return (
    <button type={type} className={cx(BTN_BASE, BTN_SIZE[size], BTN_VARIANT[variant], className)} disabled={disabled || loading} {...rest}>
      {loading ? <LoaderCircle className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  children,
  className,
  active,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex size-8 items-center justify-center rounded-lg transition-colors disabled:opacity-40",
        active ? "bg-white/[0.1] text-fg" : "text-fg-2 hover:bg-white/[0.07] hover:text-fg",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("glass rounded-2xl", className)} {...rest}>
      {children}
    </div>
  );
}

export function SectionTitle({ icon, title, subtitle, action }: { icon?: ReactNode; title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        {icon && <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.05] text-fg-2 ring-1 ring-white/[0.06]">{icon}</div>}
        <div>
          <h3 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h3>
          {subtitle && <p className="mt-0.5 text-[13px] leading-relaxed text-fg-3">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

export interface SegOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  hint?: string;
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = "md",
  full,
}: {
  value: T;
  onChange: (v: T) => void;
  options: SegOption<T>[];
  size?: "sm" | "md";
  full?: boolean;
}) {
  return (
    <div role="tablist" className={cx("inline-flex gap-1 rounded-xl border border-white/[0.06] bg-black/20 p-1", full && "w-full")}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            type="button"
            aria-selected={active}
            title={o.hint}
            disabled={o.disabled}
            onClick={() => onChange(o.value)}
            className={cx(
              "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-40",
              size === "sm" ? "h-7 px-3 text-[12.5px]" : "h-9 px-4 text-[13.5px]",
              full && "flex-1",
              active ? "bg-white/[0.09] text-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]" : "text-fg-2 hover:text-fg",
            )}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Chip({
  active,
  children,
  icon,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean; icon?: ReactNode }) {
  return (
    <button
      type="button"
      className={cx(
        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-all duration-200",
        active ? "border-accent/60 bg-accent/15 text-fg" : "border-white/[0.08] text-fg-2 hover:border-white/20 hover:text-fg",
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className={cx("flex cursor-pointer items-start justify-between gap-4", disabled && "cursor-not-allowed opacity-50")}>
      {(label || description) && (
        <span>
          {label && <span className="block text-sm text-fg">{label}</span>}
          {description && <span className="mt-0.5 block text-[12.5px] text-fg-3">{description}</span>}
        </span>
      )}
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full transition-colors duration-200",
          checked ? "bg-accent" : "bg-white/[0.12]",
        )}
      >
        <span className={cx("inline-block size-4 rounded-full bg-white shadow transition-transform duration-200", checked ? "translate-x-[19px]" : "translate-x-[3px]")} />
      </button>
    </label>
  );
}

export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cx("space-y-1.5", className)}>
      <div className="text-[12.5px] font-medium text-fg-2">{label}</div>
      {children}
      {hint && <div className="text-[12px] leading-relaxed text-fg-3">{hint}</div>}
    </div>
  );
}

export const inputClass =
  "w-full h-10 rounded-xl bg-ink-900/70 border border-white/[0.08] px-3.5 text-sm text-fg placeholder:text-fg-3 outline-none transition duration-200 focus:border-violet/60 focus:ring-4 focus:ring-violet/15 disabled:opacity-50";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(inputClass, className)} {...rest} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx(inputClass, "h-auto py-2.5", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select className={cx(inputClass, "appearance-none pr-9", className)} {...rest}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-fg-3" />
    </div>
  );
}

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  format = (v) => String(v),
  label,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
  label?: ReactNode;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className="space-y-2">
      {label !== undefined && (
        <div className="flex items-center justify-between text-[13px]">
          <span className="text-fg-2">{label}</span>
          <span className="tabular font-medium text-fg">{format(value)}</span>
        </div>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full"
        style={{ background: `linear-gradient(90deg, var(--color-accent) ${pct}%, rgba(255,255,255,0.1) ${pct}%)` }}
      />
    </div>
  );
}

type Tone = "violet" | "cyan" | "pos" | "neg" | "warn" | "neutral";
const TONES: Record<Tone, string> = {
  violet: "bg-accent/12 text-accent-soft ring-accent/25",
  cyan: "bg-cyan/10 text-[#67e8f9] ring-cyan/20",
  pos: "bg-pos/10 text-pos ring-pos/20",
  neg: "bg-neg/10 text-neg ring-neg/20",
  warn: "bg-warn/10 text-warn ring-warn/20",
  neutral: "bg-white/[0.05] text-fg-2 ring-white/[0.08]",
};

export function Badge({ tone = "neutral", icon, children, className }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex h-6 items-center gap-1 rounded-md px-2 text-[11.5px] font-medium ring-1 ring-inset", TONES[tone], className)}>
      {icon}
      {children}
    </span>
  );
}

export function ProgressBar({ value, active }: { value: number; active?: boolean }) {
  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <div
        className={cx("h-full rounded-full bg-accent transition-[width] duration-500 ease-out", active && "animate-pulse")}
        style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

export function EmptyState({ icon, title, body, action }: { icon: ReactNode; title: ReactNode; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-white/[0.04] text-fg-2 ring-1 ring-white/[0.07]">{icon}</div>
      <div className="text-[15px] font-semibold text-fg">{title}</div>
      {body && <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-fg-3">{body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Notice({ tone = "warn", icon, children, action }: { tone?: "warn" | "neg" | "info"; icon?: ReactNode; children: ReactNode; action?: ReactNode }) {
  const styles = {
    warn: "border-warn/20 bg-warn/[0.06] text-[#fde68a]",
    neg: "border-neg/25 bg-neg/[0.07] text-[#fecaca]",
    info: "border-cyan/20 bg-cyan/[0.05] text-[#a5f3fc]",
  }[tone];
  return (
    <div className={cx("flex items-start gap-3 rounded-xl border px-4 py-3 text-[13px] leading-relaxed", styles)}>
      {icon && <div className="mt-0.5 shrink-0">{icon}</div>}
      <div className="flex-1">{children}</div>
      {action}
    </div>
  );
}

export function YouTubeMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 28 20" className={className} aria-hidden>
      <rect width="28" height="20" rx="5.5" fill="#FF0033" />
      <path d="M11.2 5.8v8.4l7-4.2z" fill="#fff" />
    </svg>
  );
}

export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="9" fill="#7c66ff" />
      <path d="M8 21.5h3.2V10.5H8zM12.8 21.5H16V7.5h-3.2zM17.6 21.5h3.2v-8h-3.2zM22.4 21.5H24V15h-1.6z" fill="#fff" opacity=".95" />
    </svg>
  );
}
