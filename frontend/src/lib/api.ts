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

export type ThreatLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type WatchlistEntry = {
  id: string;
  name: string;
  threat_level: ThreatLevel;
  notes: string;
  created_at: number;
  photo_count: number;
  thumbnail_b64: string;
  sight_count: number;
  last_sighted: number | null;
};

export type ModelItem = {
  name: string;
  filename: string;
  description: string;
  size_mb: number;
  is_installed: boolean;
  is_active: boolean;
  est_latency_ms: number;
  mAP_val: number;
};

export type ModelListResponse = {
  models: ModelItem[];
  active_model: string;
};

export type DownloadProgress = {
  model_name: string;
  status: "idle" | "downloading" | "verifying" | "ready" | "failed";
  downloaded_bytes: number;
  total_bytes: number;
  progress_percent: number;
  speed_mbps: number;
  eta_seconds: number;
  error_message: string;
};

export type CameraObservations = {
  runtime?: string;
  active_model?: string;
  detections: Array<{ bbox_norm: [number, number, number, number]; class_name: string; confidence: number }>;
  tracks: Array<{
    bbox_norm: [number, number, number, number];
    class_name: string;
    confidence: number;
    track_id: number;
    identity?: {
      entry_id: string;
      name: string;
      score: number;
      tier: "RED" | "AMBER";
      locked: boolean;
    } | null;
    identity_locked?: boolean;
  }>;
  frame_at: number | null;
  faces?: Array<{ bbox_norm: [number, number, number, number]; confidence: number; quality_passed: boolean }>;
  plates?: Array<{ text: string; confidence: number }>;
  night?: { is_night: boolean; illumination_score: number; motion_area: number; confidence: number; limitation: string };
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
  site_id: string;
  username?: string;
  password?: string;
  site_cidr_allowlist: string[];
  name?: string;
  source_type?: string;
  protocol?: string;
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

export async function uploadFootage(file: File): Promise<{ upload_id: string; filename: string; size: number; sha256: string; status: string }> {
  const form = new FormData();
  form.append("file", file, file.name);
  const r = await fetch(base("/api/v1/uploads"), {
    method: "POST",
    body: form,
  });
  if (!r.ok) throw new Error(`upload ${r.status}: ${await r.text()}`);
  return (await r.json()) as { upload_id: string; filename: string; size: number; sha256: string; status: string };
}

export async function finalizeUpload(uploadId: string): Promise<{ upload_id: string; filename: string; status: string; path: string }> {
  const r = await fetch(base(`/api/v1/uploads/${uploadId}/finalize`), { method: "POST" });
  if (!r.ok) throw new Error(`finalize ${r.status}: ${await r.text()}`);
  return (await r.json()) as { upload_id: string; filename: string; status: string; path: string };
}

export async function analyzeUpload(
  uploadId: string,
  opts: { max_frames?: number; sample_stride?: number; face_stride?: number; enable_face?: boolean } = {},
): Promise<{
  upload_id: string;
  analyzed_frames: number;
  sample_stride: number;
  face_stride: number;
  events_created: number;
  queue_drops: number;
  faces_analyzed: number;
  frames_skipped: number;
  last_faces: Array<{ bbox_norm: [number, number, number, number]; confidence: number; quality_passed: boolean }>;
  last_detections: Array<{ bbox_norm: [number, number, number, number]; class_name: string; confidence: number }>;
}> {
  const params = new URLSearchParams({
    max_frames: String(opts.max_frames ?? 30),
    sample_stride: String(opts.sample_stride ?? 3),
    face_stride: String(opts.face_stride ?? 2),
    enable_face: String(opts.enable_face ?? true),
  });
  const r = await fetch(base(`/api/v1/uploads/${uploadId}/analyze?${params.toString()}`), { method: "POST" });
  if (!r.ok) throw new Error(`analyze ${r.status}: ${await r.text()}`);
  return (await r.json()) as never;
}

export async function fetchCameraHealth(id: string): Promise<{ last_frame_age_ms?: number; analysis_fps?: number; inference_ms?: number; queue_drops?: number; last_frame_age?: number; fps?: number; samples?: Array<{ last_frame_age_ms?: number; analysis_fps?: number; inference_ms?: number; queue_drops?: number }> }> {
  const r = await fetch(base(`/api/v1/cameras/${id}/health`));
  if (!r.ok) throw new Error(`camera health ${r.status}`);
  return (await r.json()) as never;
}

export async function fetchCameraObservations(id: string): Promise<CameraObservations> {
  const r = await fetch(base(`/api/v1/cameras/${id}/observations`));
  if (!r.ok) throw new Error(`camera observations ${r.status}`);
  return (await r.json()) as CameraObservations;
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

export async function fetchWatchlist(): Promise<WatchlistEntry[]> {
  const r = await fetch(base("/api/v1/watchlist"));
  if (!r.ok) throw new Error(`watchlist ${r.status}`);
  const data = await r.json();
  if (Array.isArray(data)) return data;
  return Array.isArray(data?.entries) ? data.entries : [];
}

export async function enrollSuspect(formData: FormData): Promise<{ status: string; entry: unknown }> {
  const r = await fetch(base("/api/v1/watchlist/enroll"), {
    method: "POST",
    body: formData,
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || `Enrollment failed (${r.status})`);
  return data;
}

export async function deleteSuspect(id: string): Promise<void> {
  const r = await fetch(base(`/api/v1/watchlist/${id}`), {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`Delete failed (${r.status})`);
}

export function useWatchlist() {
  return useQuery({
    queryKey: ["watchlist"],
    queryFn: fetchWatchlist,
    refetchInterval: 5000,
  });
}

export async function fetchModels(): Promise<ModelListResponse> {
  const r = await fetch(base("/api/v1/models"));
  if (!r.ok) throw new Error(`models ${r.status}`);
  return await r.json();
}

export async function activateModel(modelName: string): Promise<{ status: string; active_model: string }> {
  const r = await fetch(base("/api/v1/models/activate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_name: modelName }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || `Activation failed (${r.status})`);
  return data;
}

export async function startModelDownload(modelName: string): Promise<void> {
  const r = await fetch(base("/api/v1/models/download"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_name: modelName }),
  });
  if (!r.ok) throw new Error(`Download start failed (${r.status})`);
}

export async function fetchDownloadProgress(modelName: string): Promise<DownloadProgress> {
  const r = await fetch(base(`/api/v1/models/download/${modelName}/progress`));
  if (!r.ok) throw new Error(`Progress failed (${r.status})`);
  return await r.json();
}

export async function uploadModel(modelName: string, file: File): Promise<void> {
  const form = new FormData();
  form.append("model_name", modelName);
  form.append("file", file, file.name);
  const r = await fetch(base("/api/v1/models/upload"), {
    method: "POST",
    body: form,
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || `Model upload failed (${r.status})`);
  }
}

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: fetchModels,
    refetchInterval: 3000,
  });
}
