import type {
  AISettings,
  Analysis,
  AnalysisSummary,
  AnalyzeOptions,
  CheckResult,
  DiscoverRequest,
  Health,
  Job,
  Settings,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError("Cannot reach the ClipAwesome server. Is it running on port 8765?", 0);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg).join("; ")
          : `Request failed (${res.status})`;
    throw new ApiError(message, res.status);
  }
  return data as T;
}

export const api = {
  health: () => request<Health>("GET", "/health"),
  settings: () => request<Settings>("GET", "/settings"),
  defaults: () => request<Settings>("GET", "/settings/defaults"),
  saveSettings: (s: Partial<Settings>) => request<Settings>("PUT", "/settings", s),
  providers: () => request<Record<string, { base_url: string; model: string }>>("GET", "/ai/providers"),
  testAI: (ai: Partial<AISettings>) => request<CheckResult>("POST", "/ai/test", ai),
  listModels: (ai: Partial<AISettings>) =>
    request<{ ok: boolean; models: string[]; message?: string }>("POST", "/ai/models", ai),
  checkYouTube: (proxy?: string) =>
    request<CheckResult>("POST", "/network/youtube", proxy === undefined ? {} : { proxy }),
  analyzeYouTube: (url: string, opts: AnalyzeOptions) =>
    request<{ job_id: string }>("POST", "/analyze/youtube", { url, ...opts }),
  analyzeLocal: (file: File, subtitle: File | null, opts: AnalyzeOptions) => {
    const form = new FormData();
    form.append("file", file);
    if (subtitle) form.append("subtitle", subtitle);
    form.append("options", JSON.stringify(opts));
    return request<{ job_id: string }>("POST", "/analyze/local", form);
  },
  analyzeLocalPath: (path: string, subtitle_path: string | null, opts: AnalyzeOptions) =>
    request<{ job_id: string }>("POST", "/analyze/local-path", { path, subtitle_path, ...opts }),
  discover: (req: DiscoverRequest) => request<{ job_id: string }>("POST", "/discover", req),
  job: (id: string) => request<Job>("GET", `/jobs/${encodeURIComponent(id)}`),
  analyses: () => request<AnalysisSummary[]>("GET", "/analyses"),
  analysis: (id: string) => request<Analysis>("GET", `/analyses/${encodeURIComponent(id)}`),
  deleteAnalysis: (id: string) => request<void>("DELETE", `/analyses/${encodeURIComponent(id)}`),
  mediaUrl: (mediaId: string) => `/api/media/${encodeURIComponent(mediaId)}`,
};
