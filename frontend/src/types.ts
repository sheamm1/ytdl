export type JobStatus = "pending" | "working" | "done" | "error";

export type Tier = "free" | "plus" | "power";

export interface Usage {
  tier: Tier;
  max_quality: string;
  bandwidth_cap_bytes: number | null;
  bandwidth_used_bytes: number;
  bandwidth_remaining_bytes: number | null;
  month: string;
  bandwidth_cap_gb: number | null;
  bandwidth_used_gb: number;
  bandwidth_remaining_gb: number | null;
}

export interface JobState {
  id: string;
  status: JobStatus;
  progress: string;
  pct?: number;
  title: string;
  error: string;
  download?: string;
}

export interface SubmitPayload {
  url: string;
  quality: string;
  audio_only: boolean;
  audio_format: string;
}

export const QUALITY_OPTIONS: { value: string; label: string }[] = [
  { value: "best", label: "Best (source)" },
  { value: "2160", label: "4K (2160p)" },
  { value: "1440", label: "2K (1440p)" },
  { value: "1080", label: "Full HD (1080p)" },
  { value: "720", label: "HD (720p)" },
  { value: "480", label: "SD (480p)" },
];

// Lowest -> highest. A quality is allowed if its rank is <= the user's max.
const QUALITY_RANK: Record<string, number> = {
  "480": 0,
  "720": 1,
  "1080": 2,
  "1440": 3,
  "2160": 4,
  best: 5,
};

export function qualityAllowed(quality: string, maxQuality: string): boolean {
  const q = QUALITY_RANK[quality] ?? -1;
  const m = QUALITY_RANK[maxQuality] ?? 5;
  return q <= m;
}

export const TIER_LABEL: Record<Tier, string> = {
  free: "Free",
  plus: "Plus",
  power: "Power",
};

export const TIER_PRICE: Record<Tier, string> = {
  free: "$0",
  plus: "$4/mo",
  power: "$9/mo",
};

export const AUDIO_FORMATS: { value: string; label: string }[] = [
  { value: "mp3", label: "MP3" },
  { value: "opus", label: "Opus" },
  { value: "m4a", label: "M4A" },
  { value: "wav", label: "WAV" },
  { value: "flac", label: "FLAC" },
];
