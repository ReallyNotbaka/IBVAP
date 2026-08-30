import { useState } from "react";
import { useEvents } from "../lib/api";

export function AlertRail({ limit = 5 }: { limit?: number }) {
  const { data: events = [] } = useEvents(limit === 5 ? 5 : 20);
  const [expanded, setExpanded] = useState(false);
  const show = expanded ? events : events.slice(0, 5);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Recent events</h3>
        <button onClick={() => setExpanded((v) => !v)} className="text-xs text-slate-500 underline decoration-slate-300 underline-offset-4">
          {expanded ? "Show 5" : "View all alerts"}
        </button>
      </div>
      <div className="mt-3 space-y-2 max-h-96 overflow-auto">
        {events.length === 0 && <div className="text-xs text-slate-400">No events yet — feed a synthetic video via pipeline</div>}
        {show.map((ev) => (
          <div key={ev.id} className="rounded-xl border border-slate-100 p-3 text-xs hover:bg-slate-50">
            <div className="font-medium">{ev.event_type}</div>
            <div className="text-slate-500">
              {ev.camera_id} • zone {ev.zone_id ?? "—"}
              {ev.confidence !== undefined ? ` • ${(ev.confidence * 100).toFixed(0)}%` : ""}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-slate-500">Overlay staleness: fresh • Redaction: original</div>
    </div>
  );
}
