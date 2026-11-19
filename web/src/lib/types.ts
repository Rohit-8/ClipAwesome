export type Mode = "deterministic" | "ai";
export type Preset = "shorts" | "standard" | "long" | "custom";
export type Provider = "custom" | "gemini" | "groq" | "nvidia";

export interface AnalyzeOptions {
  mode?: Mode;
  preset?: Preset;
  min_len?: number;
  max_len?: number;
  query?: string | null;
  max_clips?: number;
  include_comments?: boolean;
}

export interface DiscoverRequest extends AnalyzeOptions {
  topic: string;
  search_limit: number;
  analyze_top: number;
  min_duration: number;
  max_duration: number;
  creative_commons: boolean;
}

export interface Reason {
  text: string;
  signal: string;
  polarity: "pos" | "neg" | "info";
}

export interface Contribution {
  signal: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
}

export interface Clip {
  id: string;
  rank: number;
  source_id: string;
  start: number;
  end: number;
  duration: number;
  score: number;
  engine_score: number;
  ai_score: number | null;
  title: string;
  hook: string | null;
  transcript: string;
  chapter: string | null;
  tags: string[];
  reasons: Reason[];
  breakdown: Contribution[];
}

export interface Chapter {
  start: number;
  end: number;
  title: string;
}

export interface SourceVideo {
  id: string;
  platform: "youtube" | "local";
  video_id: string | null;
  url: string | null;
  title: string;
  channel: string | null;
  duration: number;
  thumbnail: string | null;
  view_count: number | null;
  upload_date: string | null;
  media_id: string | null;
  media_kind: "video" | "audio" | null;
  transcript_source: string | null;
  language: string | null;
  signals: string[];
  chapters: Chapter[];
  relevance: number | null;
}

export interface Timeline {
  bin_sec: number;
  series: Record<string, number[]>;
  markers: {
    excluded?: { start: number; end: number; label: string }[];
    highlights?: { t: number; label: string }[];
    reactions?: { t: number; label: string }[];
    scene_cuts?: { t: number }[];
    comments?: { t: number; label: string }[];
  };
}

export interface TranscriptLine {
  start: number;
  end: number;
  text: string;
}

export interface SearchResult {
  video_id: string;
  url: string;
  title: string;
  channel: string | null;
  duration: number | null;
  view_count: number | null;
  thumbnail: string | null;
  description: string | null;
  relevance: number;
  analyzed: boolean;
}

export interface Analysis {
  id: string;
  kind: "youtube" | "local" | "discover";
  mode: Mode;
  preset: string;
  min_len: number;
  max_len: number;
  query: string | null;
  created_at: string;
  elapsed_sec: number;
  title: string;
  sources: SourceVideo[];
  clips: Clip[];
  timelines: Record<string, Timeline>;
  transcripts: Record<string, TranscriptLine[]>;
  other_results: SearchResult[];
  warnings: string[];
}

export interface AnalysisSummary {
  id: string;
  kind: Analysis["kind"];
  mode: Mode;
  title: string;
  created_at: string;
  thumbnail: string | null;
  clip_count: number;
  top_score: number | null;
  source_count: number;
  query: string | null;
}

export interface Job {
  id: string;
  kind: string;
  title: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  stage: string;
  stages: { name: string; at: string }[];
  error: string | null;
  result_id: string | null;
  created_at: string;
}

export interface AISettings {
  provider: Provider;
  base_url: string;
  model: string;
  api_key: string;
  ai_weight: number;
  temperature: number;
  max_tokens: number;
  timeout_sec: number;
  has_api_key?: boolean;
  configured?: boolean;
  effective_base_url?: string;
  effective_model?: string;
}

export interface Weights {
  heatmap: number;
  audio: number;
  reactions: number;
  relevance: number;
  comments: number;
  highlight: number;
  pace: number;
  visual: number;
  hook: number;
  completeness: number;
}

export interface Settings {
  default_mode: Mode;
  default_preset: Exclude<Preset, "custom">;
  default_max_clips: number;
  include_comments: boolean;
  max_comments: number;
  visual_analysis: "off" | "fast" | "full";
  whisper_model: string;
  whisper_device: "cpu" | "cuda" | "auto";
  whisper_compute_type: string;
  youtube_audio: "never" | "when_needed" | "always";
  caption_languages: string[];
  youtube_api_key: string;
  proxy: string;
  has_youtube_api_key?: boolean;
  ai: AISettings;
  weights: Weights;
}

export interface Health {
  status: string;
  version: string;
  capabilities: {
    pyav: boolean;
    whisper: boolean;
    js_runtime: string | null;
    ai_configured: boolean;
    ai_provider: Provider;
    ai_model: string | null;
    youtube_api_key: boolean;
  };
}

export interface CheckResult {
  ok: boolean;
  message: string;
  model?: string;
}
