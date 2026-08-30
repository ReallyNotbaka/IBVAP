export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchHealth(): Promise<{ status: string; version: string }> {
  const r = await fetch(`${API_BASE}/api/v1/health`);
  if (!r.ok) throw new Error(`health ${r.status}`);
  return (await r.json()) as { status: string; version: string };
}

export async function fetchCapabilities(): Promise<unknown> {
  const r = await fetch(`${API_BASE}/api/v1/capabilities`);
  if (!r.ok) throw new Error(`capabilities ${r.status}`);
  return await r.json();
}
