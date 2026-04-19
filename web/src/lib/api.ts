import type { Profile, ServerConfig } from "./types";

export async function fetchConfig(): Promise<ServerConfig> {
  const r = await fetch("/api/config");
  if (!r.ok) throw new Error("config fetch failed");
  return r.json();
}

export async function saveProfile(p: Profile): Promise<void> {
  const r = await fetch("/api/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(p),
  });
  if (!r.ok) throw new Error(`save failed (${r.status})`);
}

export async function launchRuntime(): Promise<{ pid: number | null; status: string }> {
  const r = await fetch("/api/launch", { method: "POST" });
  if (!r.ok) throw new Error(`launch failed (${r.status})`);
  return r.json();
}

export async function stopRuntime(): Promise<void> {
  await fetch("/api/stop", { method: "POST" });
}
