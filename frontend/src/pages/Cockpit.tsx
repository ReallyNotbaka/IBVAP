import { useState } from "react";
import { useCameras } from "../lib/api";
import { CameraTile } from "../components/CameraTile";
import { AlertRail } from "../components/AlertRail";
import { HealthBar } from "../components/HealthBar";

export function Cockpit({ modalOpen }: { modalOpen?: boolean }) {
  const { data: cameras = [] } = useCameras();
  const [mode, setMode] = useState<"minimal" | "operational" | "diagnostic">("operational");
  const [solo, setSolo] = useState<string | null>(null);

  const n = cameras.length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h1 className="text-sm font-semibold">Operations cockpit — {n} source{n !== 1 ? "s" : ""}</h1>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 hidden sm:inline">Overlay</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as never)} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium">
            <option value="minimal">Minimal</option>
            <option value="operational">Operational</option>
            <option value="diagnostic">Diagnostic</option>
          </select>
        </div>
      </div>

      <div className="cockpit-grid" data-n={String(n)} data-testid="cockpit-grid">
        {cameras.map((c) => (
          <CameraTile key={c.id} camera={c} mode={mode} isSolo={solo === c.id} onSolo={() => setSolo((prev) => (prev === c.id ? null : c.id))} />
        ))}
      </div>

      {n === 0 && <div className="text-sm text-slate-500">No cameras — add one to start</div>}

      <div className="grid gap-4">
        <AlertRail limit={5} />
        <HealthBar />
      </div>

      {modalOpen ? <span className="hidden" data-testid="modal-open" /> : null}
    </div>
  );
}
