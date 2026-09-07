import { BellIcon } from "../components/Icons";

export function Alerts() {
  return (
    <div className="p-6 max-w-4xl mx-auto w-full">
      <div className="flex items-center gap-3 mb-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900/50 text-rose-600 dark:text-rose-400 shadow-sm">
          <BellIcon className="w-5 h-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Operational Alerts Console
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Watchlist detections, zone crossings, and operational incident activity log
          </p>
        </div>
      </div>
      <div className="mt-4 rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl p-5 text-xs text-slate-700 dark:text-slate-300 shadow-sm">
        Incident management and real-time activity stream. Filter events by camera, detection class, or threat level.
      </div>
    </div>
  );
}
