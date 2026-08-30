import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../lib/api";

export function HealthBar() {
  const { data } = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 5000, retry: 1 });

  if (!data) {
    return <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-400">System health — loading…</div>;
  }

  const storage = (data as { storage_pressure?: string }).storage_pressure ?? "Normal";
  const drops = (data as { queue_drops?: number }).queue_drops ?? 0;
  const isEmergency = storage === "Emergency";

  return (
    <div className={`rounded-xl border p-3 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2 ${isEmergency ? "bg-red-50 border-red-200 text-red-800" : "bg-white border-slate-200 text-slate-500"}`}>
      <span>System health • queue_drops {drops} • status {(data as { status?: string }).status ?? "ok"}</span>
      <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium ${isEmergency ? "bg-red-100 text-red-800" : "bg-slate-100 text-slate-600"}`}>
        <span className={`h-2 w-2 rounded-full ${isEmergency ? "bg-red-500" : "bg-emerald-500"}`} /> Storage: {storage}
      </span>
    </div>
  );
}
