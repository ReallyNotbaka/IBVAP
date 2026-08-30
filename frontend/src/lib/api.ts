import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const base = (p: string) => (API_BASE ? `${API_BASE}${p}` : p);

export type Camera = {
  id: string;
  name: string;
  endpoint: string;
  observed_state: string;
  stream_epoch: number;
};

export type TestStage = { name: string; status: string };
export type TestResult = {
  result: string;
  reason_code?: string;
  safe_message: string;
  stages: TestStage[];
  probe?: { width: number; height: number; fps: number | null; codec: string };
};

export async function fetchHealth(): Promise<{ status: string; version: string }> {
  const r = await fetch(base("/api/v1/health"));
  if (!r.ok) throw new Error(`health ${r.status}`);
  return (await r.json()) as { status: string; version: string };
}

export async function fetchCapabilities(): Promise<unknown> {
  const r = await fetch(base("/api/v1/capabilities"));
  if (!r.ok) throw new Error(`capabilities ${r.status}`);
  return await r.json();
}

export async function fetchCameras(): Promise<Camera[]> {
  const r = await fetch(base("/api/v1/cameras"));
  if (!r.ok) throw new Error(`cameras ${r.status}`);
  const j = await r.json();
  if (Array.isArray(j)) return j as Camera[];
  if (j && Array.isArray((j as { items?: unknown }).items)) return (j as { items: Camera[] }).items;
  return [];
}

export async function testCamera(payload: {
  endpoint: string;
  username?: string;
  password?: string;
  site_cidr_allowlist: string[];
}): Promise<TestResult> {
  const r = await fetch(base("/api/v1/cameras/test"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const j = (await r.json()) as TestResult;
  if (!r.ok) throw new Error(j.safe_message || `test ${r.status}`);
  return j;
}

export async function createCamera(payload: {
  endpoint: string;
  username?: string;
  password?: string;
  site_cidr_allowlist: string[];
  name?: string;
}): Promise<Camera> {
  const r = await fetch(base("/api/v1/cameras"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`create ${r.status}: ${await r.text()}`);
  return (await r.json()) as Camera;
}

export async function fetchEvents(limit = 5): Promise<Array<{ id: string; camera_id: string; event_type: string; zone_id?: string; confidence?: number }>> {
  const r = await fetch(base(`/api/v1/events?limit=${limit}`));
  if (!r.ok) throw new Error(`events ${r.status}`);
  const j = await r.json();
  if (Array.isArray(j)) return j;
  if (j && Array.isArray((j as { items?: unknown }).items)) return (j as { items: never[] }).items;
  return [];
}

export async function fetchCameraHealth(id: string): Promise<{ last_frame_age_ms?: number; analysis_fps?: number; inference_ms?: number; queue_drops?: number; last_frame_age?: number; fps?: number }> {
  const r = await fetch(base(`/api/v1/cameras/${id}/health`));
  if (!r.ok) throw new Error(`camera health ${r.status}`);
  return (await r.json()) as never;
}

export function useCameras() {
  return useQuery({ queryKey: ["cameras"], queryFn: fetchCameras, refetchInterval: 5000, retry: 3 });
}

export function useEvents(limit = 5) {
  return useQuery({ queryKey: ["events", limit], queryFn: () => fetchEvents(limit), refetchInterval: 5000 });
}

export function useCreateCamera() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCamera,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cameras"] }),
  });
}
