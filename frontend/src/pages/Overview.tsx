export function Overview() {
  return (
    <main className="p-6">
      <h1 className="text-lg font-semibold">Overview</h1>
      <p className="mt-2 text-sm text-slate-600">Operations overview — Phase 7 placeholder (camera grid, focus mode, alert rail).</p>
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="rounded-xl border bg-white p-4 text-sm">Camera grid: 1 large focused + 2×2 for 3-4 cams (virtualized beyond 4)</div>
        <div className="rounded-xl border bg-white p-4 text-sm">Alert rail: 5 newest high-priority • View all alerts</div>
      </div>
    </main>
  );
}
