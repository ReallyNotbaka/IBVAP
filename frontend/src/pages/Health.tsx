export function Health() {
  return (
    <main className="p-6">
      <h1 className="text-lg font-semibold">Health</h1>
      <p className="mt-2 text-sm text-slate-600">Camera health + processing jobs + system + storage pressure</p>
      <div className="mt-4 rounded-xl border bg-white p-4 text-xs">
        Metrics: last_frame_age, source/analysis FPS, decode_errors, queue_drops, reconnect_count, stream_epoch
      </div>
    </main>
  );
}
