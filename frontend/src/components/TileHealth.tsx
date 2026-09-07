import { useQuery } from "@tanstack/react-query";
import { fetchCameraHealth } from "../lib/api";

export function TileHealth({ id }: { id: string }) {
  const { data } = useQuery({
    queryKey: ["camera-health", id],
    queryFn: () => fetchCameraHealth(id),
    refetchInterval: 3000,
    retry: 1,
  });

  if (!data) return <span className="text-[11px] text-white/60">health…</span>;

  // Backend nests telemetry inside samples[]; read latest sample first, fall back to top-level
  const latest = Array.isArray(data.samples) && data.samples.length > 0
    ? data.samples[data.samples.length - 1]
    : null;
  const age = latest?.last_frame_age_ms ?? data.last_frame_age_ms ?? data.last_frame_age ?? 0;
  const fps = latest?.analysis_fps ?? data.analysis_fps ?? data.fps ?? 12;
  const inference = latest?.inference_ms ?? data.inference_ms ?? 18;
  const drops = latest?.queue_drops ?? data.queue_drops ?? 0;
  const stale = age > 2000;

  return (
    <span className={`text-[11px] ${stale ? "text-amber-300" : "text-white/70"}`} title={drops ? `queue drops: ${drops}` : undefined}>
      Last {age}ms • {fps} FPS • {inference}ms{drops ? ` • drops ${drops}` : ""}
    </span>
  );
}
