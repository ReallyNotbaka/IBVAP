export function Health() {
  return (
    <div className="p-6 max-w-4xl mx-auto w-full">
      <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">System & Pipeline Diagnostics</h1>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        Inference latencies, neural pipelines, directML/hardware accelerators, and camera stream health
      </p>
      <div className="mt-4 rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl p-5 text-xs font-mono text-slate-700 dark:text-slate-300 shadow-sm">
        Metrics: last_frame_age, source/analysis FPS, decode_errors, queue_drops, reconnect_count, stream_epoch
      </div>
    </div>
  );
}
