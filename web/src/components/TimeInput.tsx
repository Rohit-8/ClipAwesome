import { Clock3 } from "lucide-react";
import { useEffect, useState } from "react";
import { cx } from "../lib/format";
import { formatLength, parseTime } from "../lib/time";
import { inputClass } from "./ui";

export function TimeInput({
  label,
  value,
  onCommit,
  placeholder = "e.g. 45 · 1:30 · 2m 30s · 1h",
}: {
  label: string;
  value: number;
  onCommit: (seconds: number) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(() => formatLength(value));
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(formatLength(value));
  }, [value, editing]);

  const parsed = parseTime(draft);
  const invalid = draft.trim() !== "" && parsed === null;

  const commit = () => {
    setEditing(false);
    // Unreadable input is discarded and the last valid value is restored.
    if (parsed === null) setDraft(formatLength(value));
    else onCommit(parsed);
  };

  return (
    <div className="space-y-1.5">
      <div className="text-[12.5px] font-medium text-fg-2">{label}</div>
      <div className="relative">
        <Clock3 className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-fg-3" />
        <input
          value={draft}
          inputMode="text"
          spellCheck={false}
          placeholder={placeholder}
          onFocus={() => setEditing(true)}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") {
              setDraft(formatLength(value));
              e.currentTarget.blur();
            }
          }}
          className={cx(inputClass, "pl-10 pr-24 tabular", invalid && "border-neg/60 focus:border-neg/60 focus:ring-neg/15")}
        />
        {editing && draft.trim() && (
          <span className={cx("pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[12px] tabular", invalid ? "text-neg" : "text-fg-3")}>
            {invalid ? "can't read" : `= ${formatLength(parsed!)}`}
          </span>
        )}
      </div>
    </div>
  );
}
