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

  const age = data.last_frame_age_ms ?? data.last_frame_age ?? 0;
  const fps = data.analysis_fps ?? data.fps ?? 12;
  const inference = data.inference_ms ?? 18;
  const drops = data.queue_drops ?? 0;
  const stale = age > 2000;

  return (
    <span className={`text-[11px] ${stale ? "text-amber-300" : "text-white/70"}`} title={drops ? `queue drops: ${drops}` : undefined}>
      Last {age}ms • {fps} FPS • {inference}ms{drops ? ` • drops ${drops}` : ""}
    </span>
  );
}
