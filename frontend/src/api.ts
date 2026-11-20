import type { JobState, SubmitPayload, Tier, Usage } from "./types";

// Where the backend lives. In the browser (same-origin) this is "".
// In the APK it's baked in at build time via VITE_API_BASE, e.g.
//   VITE_API_BASE=https://api.youfetch.app npm run build
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

function url(path: string): string {
  return API_BASE + path;
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.detail || `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export async function submitJob(payload: SubmitPayload): Promise<string> {
  const res = await fetch(url("/api/jobs"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = (await res.json()) as { id: string };
  return data.id;
}

export async function getJob(id: string): Promise<JobState> {
  const res = await fetch(url(`/api/jobs/${id}`));
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as JobState;
}

export async function fetchUsage(): Promise<Usage> {
  const res = await fetch(url("/api/usage"));
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Usage;
}

export async function setTier(tier: Tier): Promise<Usage> {
  const res = await fetch(url(`/api/tier?tier=${tier}`));
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Usage;
}

export async function igStatus(): Promise<{ connected: boolean }> {
  const res = await fetch(url("/api/instagram/status"));
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { connected: boolean };
}

export async function igConnect(cookies: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(url("/api/instagram/connect"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cookies }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data as { ok: boolean; message: string };
}
