import { CpuIcon } from "../components/Icons";

export function Health() {
  return (
    <div className="p-6 max-w-4xl mx-auto w-full">
      <div className="flex items-center gap-3 mb-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 shadow-sm">
          <CpuIcon className="w-5 h-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            System & Pipeline Diagnostics
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Inference latencies, neural pipelines, directML/hardware accelerators, and camera stream health
          </p>
        </div>
      </div>
      <div className="mt-4 rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl p-5 text-xs text-slate-700 dark:text-slate-300 shadow-sm">
        Real-time telemetry: frame latency, source and analysis FPS, hardware queue status, and active stream health.
      </div>
    </div>
  );
}
