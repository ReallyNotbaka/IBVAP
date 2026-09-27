import { useQuery } from "@tanstack/react-query";
import { fetchCameraHealth } from "../lib/api";

const UNKNOWN = "--";

function fmtTelemetry(v: number | null | undefined): string {
  return v === null || v === undefined ? UNKNOWN : String(v);
}

export function TileHealth({ id }: { id: string }) {
  const { data } = useQuery({
    queryKey: ["camera-health", id],
    queryFn: () => fetchCameraHealth(id),
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  if (!data) return <span className="text-[11px] text-white/60">health…</span>;

  // Backend nests telemetry inside samples[]; read latest sample first, fall back to top-level.
  // Missing/null fields render as "--" (unknown) — never fabricate defaults.
  const latest = Array.isArray(data.samples) && data.samples.length > 0
    ? data.samples[data.samples.length - 1]
    : null;
  const age = latest?.last_frame_age_ms ?? data.last_frame_age_ms ?? data.last_frame_age ?? null;
  const fps = latest?.analysis_fps ?? data.analysis_fps ?? data.fps ?? null;
  const inference = latest?.inference_ms ?? data.inference_ms ?? null;
  const drops = latest?.queue_drops ?? data.queue_drops ?? null;
  const ocrTimeouts = latest?.ocr_timeouts ?? data.ocr_timeouts ?? null;
  const stale = age !== null && age > 2000;

  return (
    <span className={`text-[11px] ${stale ? "text-amber-300" : "text-white/70"}`} title={drops !== null ? `queue drops: ${drops}` : undefined}>
      Last {fmtTelemetry(age)}ms • {fps !== null ? `${fps} FPS` : UNKNOWN} • {inference !== null ? `${inference}ms` : UNKNOWN} • drops {fmtTelemetry(drops)}{ocrTimeouts !== null ? ` • ocr timeouts ${ocrTimeouts}` : ""}
    </span>
  );
}
