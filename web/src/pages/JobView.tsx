import { ArrowLeft, CircleCheck, FileVideo, LoaderCircle, Settings, Telescope, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Card, Notice, ProgressBar, YouTubeMark } from "../components/ui";
import { api } from "../lib/api";
import { cx } from "../lib/format";
import { navigate } from "../lib/router";
import type { Job } from "../lib/types";

function elapsed(fromIso: string, toIso: string) {
  const s = Math.max(0, (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 1000);
  return s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export function JobView({ id }: { id: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const tick = async () => {
      try {
        const j = await api.job(id);
        if (stop) return;
        setJob(j);
        if (j.status === "done" && j.result_id) {
          timer = window.setTimeout(() => navigate(`analysis/${j.result_id}`, true), 450);
          return;
        }
        if (j.status === "error") return;
      } catch (e) {
        if (!stop) setError((e as Error).message);
        return;
      }
      timer = window.setTimeout(tick, 700);
    };
    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  const icon =
    job?.kind === "youtube" ? (
      <YouTubeMark className="h-6 w-8" />
    ) : job?.kind === "discover" ? (
      <Telescope className="size-6 text-fg" />
    ) : (
      <FileVideo className="size-6 text-fg" />
    );
  const failed = job?.status === "error" || !!error;
  const networkIssue = (job?.error ?? "").toLowerCase().includes("proxy");
  const stages = (job?.stages ?? []).filter((s) => s.name !== "Queued" && s.name !== "Starting");

  return (
    <div className="mx-auto flex min-h-[80vh] max-w-xl flex-col justify-center px-5 py-12">
      <Card className="animate-fade-up p-7">
        <div className="flex items-center gap-4">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-white/[0.05] ring-1 ring-white/[0.08]">{icon}</div>
          <div className="min-w-0">
            <div className="text-[12px] uppercase tracking-wider text-fg-3">
              {failed ? "Analysis failed" : job?.status === "done" ? "Complete" : "Analysing"}
            </div>
            <div className="truncate text-[17px] font-semibold text-fg">{job?.title || "Preparing…"}</div>
          </div>
        </div>

        {!failed && (
          <div className="mt-7 space-y-3">
            <div className="flex items-center justify-between text-[13px]">
              <span className="flex items-center gap-2 text-fg">
                {job?.status !== "done" && <LoaderCircle className="size-4 animate-spin text-accent-soft" />}
                {job?.stage ?? "Queued"}
              </span>
              <span className="tabular text-fg-2">{Math.round((job?.progress ?? 0) * 100)}%</span>
            </div>
            <ProgressBar value={job?.progress ?? 0} active={job?.status !== "done"} />
          </div>
        )}

        {stages.length > 0 && (
          <ol className="mt-7 space-y-2.5">
            {stages.slice(-8).map((s, i, arr) => {
              const current = i === arr.length - 1 && job?.status === "running";
              return (
                <li key={`${s.name}-${s.at}`} className={cx("flex items-center gap-3 text-[13px]", current ? "text-fg" : "text-fg-3")}>
                  {current ? (
                    <span className="flex size-4 items-center justify-center">
                      <span className="size-2 animate-pulse rounded-full bg-violet" />
                    </span>
                  ) : s.name === "Failed" ? (
                    <TriangleAlert className="size-4 text-neg" />
                  ) : (
                    <CircleCheck className="size-4 text-pos/80" />
                  )}
                  <span className="flex-1 truncate">{s.name}</span>
                  {job && <span className="tabular text-[11.5px] text-fg-3">{elapsed(job.created_at, s.at)}</span>}
                </li>
              );
            })}
          </ol>
        )}

        {failed && (
          <div className="mt-6 space-y-4">
            <Notice tone="neg" icon={<TriangleAlert className="size-4" />}>
              {job?.error || error}
            </Notice>
            <div className="flex gap-2">
              <Button icon={<ArrowLeft className="size-4" />} onClick={() => navigate("")}>
                Back to Studio
              </Button>
              {networkIssue && (
                <Button variant="ghost" icon={<Settings className="size-4" />} onClick={() => navigate("settings")}>
                  Network settings
                </Button>
              )}
            </div>
          </div>
        )}
      </Card>
      {!failed && <p className="mt-4 text-center text-[12px] text-fg-3">You can leave this page — the analysis keeps running and will appear in History.</p>}
    </div>
  );
}
