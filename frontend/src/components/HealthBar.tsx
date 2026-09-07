import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../lib/api";

export function HealthBar() {
  const { data } = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 5000, retry: 1 });

  if (!data) {
    return (
      <div className="rounded-2xl border border-neutral-200/80 dark:border-white/10 bg-white dark:bg-[#131720] backdrop-blur-xl p-3.5 text-xs text-slate-400 dark:text-slate-500 shadow-sm">
        System health — loading…
      </div>
    );
  }

  const storage = (data as { storage_pressure?: string }).storage_pressure ?? "Normal";
  const drops = (data as { queue_drops?: number }).queue_drops ?? 0;
  const isEmergency = storage === "Emergency";

  return (
    <div
      className={`rounded-2xl border p-3.5 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2 backdrop-blur-xl shadow-sm transition-colors ${
        isEmergency
          ? "bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-900/60 text-red-800 dark:text-red-200"
          : "bg-white dark:bg-[#131720] border-neutral-200/80 dark:border-white/10 text-slate-600 dark:text-slate-300"
      }`}
    >
      <span className="font-medium">
        System health • queue_drops {drops} • status {(data as { status?: string }).status ?? "ok"}
      </span>
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
          isEmergency
            ? "bg-red-100 dark:bg-red-900/50 text-red-800 dark:text-red-200"
            : "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
        }`}
      >
        <span
          className={`h-2 w-2 rounded-full ${
            isEmergency ? "bg-red-500 animate-ping" : "bg-emerald-500"
          }`}
        />{" "}
        Storage: {storage}
      </span>
    </div>
  );
}
