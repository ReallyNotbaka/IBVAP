import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../lib/api";

export function HealthBar() {
  const { data } = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 5000, refetchIntervalInBackground: false, refetchOnWindowFocus: false, retry: 1 });

  if (!data) {
    return (
      <div className="border-t border-slate-200/80 dark:border-white/10 px-3.5 py-2.5 text-[11px] text-slate-400 dark:text-slate-500">
        System health — loading…
      </div>
    );
  }

  const storage = (data as { storage_pressure?: string }).storage_pressure ?? "Normal";
  // Missing/null backend counters render as unknown — never fabricate.
  const drops = (data as { queue_drops?: number | null }).queue_drops ?? null;
  const ocrTimeouts = (data as { ocr_timeouts?: number | null }).ocr_timeouts ?? null;
  const isEmergency = storage === "Emergency";

  return (
    <div
      className={`border-t px-3.5 py-2.5 text-[11px] flex items-center justify-between gap-2 shrink-0 transition-colors ${
        isEmergency
          ? "bg-rose-500/10 border-rose-500/30 text-rose-400"
          : "border-slate-200/80 dark:border-white/10 text-slate-500 dark:text-slate-400"
      }`}
    >
      <span className="font-medium truncate">
        Health • drops {drops ?? "--"}{ocrTimeouts !== null ? ` • ocr ${ocrTimeouts}` : ""} • {(data as { status?: string }).status ?? "ok"}
      </span>
      <span
        className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[10px] font-mono font-semibold shrink-0 ${
          isEmergency
            ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
            : "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200/70 dark:border-white/10"
        }`}
      >
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            isEmergency ? "bg-rose-500 animate-ping" : "bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.8)]"
          }`}
        />
        {storage}
      </span>
    </div>
  );
}
