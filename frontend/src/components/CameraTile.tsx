import { useState } from "react";
import { OverlayCanvas } from "./OverlayCanvas";
import { TileHealth } from "./TileHealth";
import type { Camera } from "../lib/api";

type OverlayMode = "minimal" | "operational" | "diagnostic";

export function CameraTile({ camera, mode, onSolo, isSolo }: { camera: Camera; mode: OverlayMode; onSolo?: () => void; isSolo?: boolean }) {
  const [imgError, setImgError] = useState(false);
  const isHttp = camera.endpoint?.startsWith("http");

  // PS demo boxes — in real pipeline these come from WS/events; here show empty or sample when diagnostic
  const demoBoxes =
    mode === "diagnostic"
      ? [
          { x: 0.12, y: 0.22, w: 0.18, h: 0.36, label: "person", confidence: 0.92, trackId: "3" },
          { x: 0.58, y: 0.35, w: 0.22, h: 0.2, label: "car", confidence: 0.88, trackId: "7" },
        ]
      : [];

  return (
    <div
      data-testid={`live-player-${camera.id}`}
      className={`tile group relative cursor-pointer ${isSolo ? "ring-2 ring-teal-600" : ""}`}
      onClick={onSolo}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSolo?.();
      }}
    >
      <div className="absolute top-2 left-2 right-2 flex items-center justify-between text-xs text-white z-10 pointer-events-none">
        <span className="bg-slate-900/70 rounded-full px-2 py-1 backdrop-blur">
          {camera.name} • {camera.observed_state} • epoch {camera.stream_epoch}
        </span>
        <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_4px_rgba(34,197,94,0.22)]" />
      </div>

      <div className="w-full h-full grid place-items-center bg-slate-900 relative overflow-hidden">
        {isHttp && !imgError ? (
          <img src={camera.endpoint} alt={camera.name} className="w-full h-full object-contain" onError={() => setImgError(true)} />
        ) : (
          <div className="text-white text-xs p-4 text-center">
            <div className="font-medium">Live player — WHEP/HLS when MediaMTX available</div>
            <div className="mt-1 text-slate-400">Overlay: {mode} • Zone: Restricted • Track IDs • Direction</div>
            {!isHttp && <div className="mt-2 text-[11px] text-amber-300">{camera.endpoint || "no endpoint"}</div>}
            {imgError && <div className="mt-2 text-[11px] text-amber-300">No frame yet — check DroidCam URL / same WiFi • retry</div>}
          </div>
        )}
        <OverlayCanvas boxes={demoBoxes} mode={mode} />
      </div>

      <div className="absolute bottom-1 left-2 right-2 flex items-center justify-between gap-2 pointer-events-none">
        <TileHealth id={camera.id} />
        <span className="text-[10px] text-white/70 bg-slate-900/60 rounded-full px-2 py-0.5 hidden sm:inline">Zone: Restricted</span>
      </div>
    </div>
  );
}
