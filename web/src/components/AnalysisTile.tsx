import { Sparkles, Trash2 } from "lucide-react";
import { relativeTime } from "../lib/format";
import type { AnalysisSummary } from "../lib/types";
import { Thumb } from "./Thumb";
import { Badge } from "./ui";

const KIND_LABEL = { youtube: "YouTube", local: "Local file", discover: "Topic" } as const;

export function AnalysisTile({ item, onDelete }: { item: AnalysisSummary; onDelete?: () => void }) {
  return (
    <a
      href={`#/analysis/${item.id}`}
      className="group relative flex gap-4 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-white/[0.14] hover:bg-white/[0.045]"
    >
      <Thumb src={item.thumbnail} kind={item.kind} className="aspect-video w-36 shrink-0 rounded-xl" />
      <div className="min-w-0 flex-1 py-0.5">
        <div className="flex items-center gap-1.5">
          <Badge>{KIND_LABEL[item.kind]}</Badge>
          {item.mode === "ai" && (
            <Badge tone="violet" icon={<Sparkles className="size-3" />}>
              AI
            </Badge>
          )}
        </div>
        <div className="mt-1.5 line-clamp-2 text-[14px] font-medium leading-snug text-fg">{item.title}</div>
        <div className="mt-1.5 flex items-center gap-2 text-[12px] text-fg-3">
          <span>{relativeTime(item.created_at)}</span>
          <span>·</span>
          <span>{item.clip_count} clips</span>
          {item.top_score !== null && (
            <>
              <span>·</span>
              <span className="tabular text-fg-2">top {Math.round(item.top_score)}</span>
            </>
          )}
        </div>
      </div>
      {onDelete && (
        <button
          type="button"
          aria-label="Delete analysis"
          title="Delete"
          onClick={(e) => {
            e.preventDefault();
            onDelete();
          }}
          className="absolute right-2 top-2 rounded-lg p-1.5 text-fg-3 opacity-0 transition hover:bg-neg/10 hover:text-neg group-hover:opacity-100"
        >
          <Trash2 className="size-4" />
        </button>
      )}
    </a>
  );
}
