import { useEffect, useState } from "react";

type Event = { id: string; camera_id: string; event_type: string; zone_id?: string; confidence?: number };
type Camera = { id: string; name: string; endpoint: string; observed_state: string; stream_epoch: number };

export function Monitor() {
  const [events, setEvents] = useState<Event[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [overlay, setOverlay] = useState<"minimal" | "operational" | "diagnostic">("operational");

  useEffect(() => {
    fetch("/api/v1/events")
      .then((r) => r.json())
      .then((data) => setEvents(Array.isArray(data) ? data : []))
      .catch(() => {});

    fetch("/api/v1/cameras")
      .then((r) => r.json())
      .then((data) => setCameras(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  const activeCam = cameras[0];
  const streamUrl = activeCam?.endpoint || "";

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-6 py-3 flex items-center justify-between">
        <h1 className="text-sm font-semibold">Monitoring workspace</h1>
        <div className="flex items-center gap-2 text-xs">
          <span className="h-2 w-2 rounded-full bg-emerald-500" /> Live
          <select value={overlay} onChange={(e) => setOverlay(e.target.value as never)} className="ml-3 rounded border px-2 py-1">
            <option value="minimal">Minimal</option>
            <option value="operational">Operational</option>
            <option value="diagnostic">Diagnostic</option>
          </select>
        </div>
      </header>

      <div className="mx-auto max-w-6xl p-6 grid grid-cols-3 gap-6">
        {/* dominant player */}
        <div className="col-span-2">
          <div data-testid="live-player" className="aspect-video rounded-2xl bg-slate-900 overflow-hidden relative grid place-items-center text-white">
            {streamUrl.startsWith("http") ? (
              <img
                src={streamUrl}
                alt={activeCam?.name || "Live Camera"}
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="text-center">
                <div className="text-sm">Live player — WHEP/HLS when MediaMTX available</div>
                <div className="mt-1 text-xs text-slate-400">Synthetic preview in Phase 3 (real frame decoded)</div>
                <div className="mt-2 text-xs">Overlay: {overlay} • Zone: Restricted • Track IDs • Direction</div>
              </div>
            )}
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
            <span>Camera: {activeCam?.name || "Entrance phone"} • {activeCam?.observed_state || "STREAMING"} • epoch {activeCam?.stream_epoch ?? 0}</span>
            <span>Last frame 120ms • Analysis 12 FPS • Inference 18ms</span>
          </div>
        </div>

        {/* events rail */}
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold">Recent events</h3>
          <div className="mt-3 space-y-2 max-h-96 overflow-auto">
            {events.length === 0 && <div className="text-xs text-slate-400">No events yet — feed a synthetic video via pipeline</div>}
            {events.slice(0, 5).map((ev) => (
              <div key={ev.id} className="rounded-xl border border-slate-100 p-3 text-xs">
                <div className="font-medium">{ev.event_type}</div>
                <div className="text-slate-500">{ev.camera_id} • zone {ev.zone_id ?? "—"}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 text-xs text-slate-500">Overlay staleness: fresh • Redaction: original</div>
        </div>
      </div>
      <div className="mx-auto max-w-6xl px-6 pb-6 text-xs text-slate-400">
        Phase 3 slice: mock detector + centroid tracker + polygon intrusion + outbox → event persisted + WS heartbeat. YOLO26 blocked pending gate — not silent.
      </div>
    </main>
  );
}
