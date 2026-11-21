import type {
  AISettings,
  Analysis,
  AnalysisSummary,
  AnalyzeOptions,
  CheckResult,
  DiscoverRequest,
  DownloadInfo,
  DownloadTask,
  EditSource,
  ExportRequest,
  ExportTask,
  GpuStatus,
  Health,
  Job,
  MergeRequest,
  PreviewStatus,
  Settings,
  BatchOptions,
  DiagnosticCheck,
  EditSourceResult,
  ExportBatch,
  StorageUsage,
  SystemInfo,
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
    throw new ApiError(errorMessage(data, res.status), res.status);
  }
  return data as T;
}

function errorMessage(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join("; ");
  return `Request failed (${status})`;
}

function uploadWithProgress<T>(path: string, form: FormData, onProgress: (fraction: number) => void, signal?: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        data = xhr.responseText;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(new ApiError(errorMessage(data, xhr.status), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Upload failed. Is the ClipAwesome server running?", 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled", 0));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
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
  retryJob: (id: string) => request<{ job_id: string }>("POST", `/jobs/${encodeURIComponent(id)}/retry`),
  systemInfo: () => request<SystemInfo>("GET", "/system"),
  storage: () => request<StorageUsage>("GET", "/storage"),
  cleanupStorage: () => request<{ freed_bytes: number; usage: StorageUsage }>("POST", "/storage/cleanup"),
  diagnostics: () => request<{ ok: boolean; checks: DiagnosticCheck[] }>("GET", "/diagnostics"),
  reviewClip: (analysisId: string, clipId: string, review: "approved" | "rejected" | null) =>
    request<{ id: string; review: string | null }>("PATCH", `/analyses/${encodeURIComponent(analysisId)}/clips/${encodeURIComponent(clipId)}`, { review }),
  editSource: (analysisId: string, sourceId: string, quality: number) =>
    request<EditSourceResult>("POST", `/analyses/${encodeURIComponent(analysisId)}/sources/${encodeURIComponent(sourceId)}/edit-source`, { quality }),
  exportClips: (analysisId: string, opts: BatchOptions) => request<ExportBatch>("POST", `/analyses/${encodeURIComponent(analysisId)}/export`, opts),
  exportBatch: (id: string) => request<ExportBatch>("GET", `/export-batches/${encodeURIComponent(id)}`),
  download: (id: string) => request<DownloadTask>("GET", `/downloads/${encodeURIComponent(id)}`),
  analyses: () => request<AnalysisSummary[]>("GET", "/analyses"),
  analysis: (id: string) => request<Analysis>("GET", `/analyses/${encodeURIComponent(id)}`),
  deleteAnalysis: (id: string) => request<void>("DELETE", `/analyses/${encodeURIComponent(id)}`),
  mediaUrl: (mediaId: string) => `/api/media/${encodeURIComponent(mediaId)}`,
  youtubePreview: (videoId: string) => request<PreviewStatus>("GET", `/youtube/${encodeURIComponent(videoId)}/preview`),
  startYoutubePreview: (videoId: string) => request<PreviewStatus>("POST", `/youtube/${encodeURIComponent(videoId)}/preview`),
  youtubePreviewMediaUrl: (videoId: string) => `/api/youtube/${encodeURIComponent(videoId)}/preview/media`,
  youtubePreviewAudioUrl: (videoId: string) => `/api/youtube/${encodeURIComponent(videoId)}/preview/audio`,
  downloadFormats: (url: string) => request<DownloadInfo>("POST", "/download/formats", { url }),
  startDownload: (url: string, option_id: string) => request<DownloadTask>("POST", "/downloads", { url, option_id }),
  downloads: () => request<DownloadTask[]>("GET", "/downloads"),
  cancelDownload: (id: string) => request<DownloadTask>("POST", `/downloads/${encodeURIComponent(id)}/cancel`),
  deleteDownload: (id: string) => request<void>("DELETE", `/downloads/${encodeURIComponent(id)}`),
  downloadFileUrl: (id: string) => `/api/downloads/${encodeURIComponent(id)}/file`,
  editorUpload: (file: File, onProgress: (fraction: number) => void, signal?: AbortSignal) => {
    const form = new FormData();
    form.append("file", file);
    return uploadWithProgress<EditSource>("/editor/sources/upload", form, onProgress, signal);
  },
  editorFromDownload: (download_id: string) => request<EditSource>("POST", "/editor/sources/from-download", { download_id }),
  editorSources: () => request<EditSource[]>("GET", "/editor/sources"),
  editorSource: (id: string) => request<EditSource>("GET", `/editor/sources/${encodeURIComponent(id)}`),
  deleteEditorSource: (id: string) => request<void>("DELETE", `/editor/sources/${encodeURIComponent(id)}`),
  editorMediaUrl: (id: string) => `/api/editor/sources/${encodeURIComponent(id)}/media`,
  editorPreviewAudioUrl: (id: string) => `/api/editor/sources/${encodeURIComponent(id)}/preview-audio`,
  mediaPreviewAudioUrl: (mediaId: string) => `/api/media/${encodeURIComponent(mediaId)}/preview-audio`,
  startExport: (req: ExportRequest) => request<ExportTask>("POST", "/editor/exports", req),
  startMerge: (req: MergeRequest) => request<ExportTask>("POST", "/editor/merges", req),
  gpuStatus: () => request<GpuStatus>("GET", "/editor/gpu"),
  detectGpu: () => request<GpuStatus>("POST", "/editor/gpu/detect"),
  exports: () => request<ExportTask[]>("GET", "/editor/exports"),
  cancelExport: (id: string) => request<ExportTask>("POST", `/editor/exports/${encodeURIComponent(id)}/cancel`),
  deleteExport: (id: string) => request<void>("DELETE", `/editor/exports/${encodeURIComponent(id)}`),
  exportFileUrl: (id: string) => `/api/editor/exports/${encodeURIComponent(id)}/file`,
};
