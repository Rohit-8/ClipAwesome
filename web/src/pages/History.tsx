import { History as HistoryIcon, WandSparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AnalysisTile } from "../components/AnalysisTile";
import { useToast } from "../components/Toast";
import { Button, Card, EmptyState, Segmented } from "../components/ui";
import { api } from "../lib/api";
import { navigate } from "../lib/router";
import type { AnalysisSummary } from "../lib/types";

type Filter = "all" | "youtube" | "discover" | "local";

export function HistoryPage() {
  const [items, setItems] = useState<AnalysisSummary[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const toast = useToast();

  useEffect(() => {
    api
      .analyses()
      .then(setItems)
      .catch((e: Error) => {
        setItems([]);
        toast(e.message, "error");
      });
  }, [toast]);

  const shown = useMemo(() => (items ?? []).filter((i) => filter === "all" || i.kind === filter), [items, filter]);

  const remove = async (item: AnalysisSummary) => {
    if (!window.confirm(`Delete “${item.title}”? This cannot be undone.`)) return;
    try {
      await api.deleteAnalysis(item.id);
      setItems((prev) => (prev ?? []).filter((i) => i.id !== item.id));
      toast("Analysis deleted", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <div className="mx-auto max-w-[1200px] px-5 pb-16 pt-10 md:px-8">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight text-fg">History</h1>
          <p className="mt-1 text-[14px] text-fg-2">Every analysis is saved locally on this machine.</p>
        </div>
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All" },
            { value: "youtube", label: "YouTube" },
            { value: "discover", label: "Topics" },
            { value: "local", label: "Local" },
          ]}
        />
      </div>

      {items === null ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-[104px] animate-pulse rounded-2xl bg-white/[0.03]" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <Card>
          <EmptyState
            icon={<HistoryIcon className="size-5" />}
            title={items.length ? "Nothing in this filter" : "No analyses yet"}
            body={items.length ? "Try another filter." : "Run your first analysis from the Studio — results will show up here."}
            action={
              <Button variant="primary" icon={<WandSparkles className="size-4" />} onClick={() => navigate("")}>
                Open Studio
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((item) => (
            <AnalysisTile key={item.id} item={item} onDelete={() => remove(item)} />
          ))}
        </div>
      )}
    </div>
  );
}
