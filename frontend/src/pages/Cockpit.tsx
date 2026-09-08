import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { setCameraFence, useCameras, useModels, useWatchlist, useEvents } from "../lib/api";
import { CameraTile, type TargetInspectData } from "../components/CameraTile";
import { AlertRail } from "../components/AlertRail";
import { HealthBar } from "../components/HealthBar";
import type { OverlayPreset } from "../components/OverlayCanvas";
import {
  CompressIcon,
  UserIcon,
  FaceIcon,
  TagIcon,
  BellIcon,
  CloseIcon,
  PercentIcon,
} from "../components/Icons";

export function Cockpit({
  modalOpen,
  onOpenWatchlist,
  onInspectTarget,
}: {
  modalOpen?: boolean;
  onOpenWatchlist?: () => void;
  onInspectTarget?: (target: TargetInspectData) => void;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: cameras = [] } = useCameras();
  const { data: modelData } = useModels();
  const { data: suspects = [] } = useWatchlist();
  const { data: events = [] } = useEvents(25);

  const activeModel = modelData?.active_model || "yolo26n";
  const [solo, setSolo] = useState<string | null>(null);

  // Overlay state & presets: "clean" | "all" | "alerts"
  const [preset, setPreset] = useState<OverlayPreset>("all");
  const [showPeople, setShowPeople] = useState(true);
  const [showFaces, setShowFaces] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showConfidence, setShowConfidence] = useState(true);

  // Collapsible Alerts & Suspects Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [fencePoints, setFencePoints] = useState<Record<string, [number, number][]>>({});
  const [drawingFenceFor, setDrawingFenceFor] = useState<string | null>(null);
  const [showFence, setShowFence] = useState(false);

  const n = cameras.length;
  const soloCamera = solo ? cameras.find((c) => c.id === solo) : null;
  const displayedCameras = soloCamera ? [soloCamera] : cameras;
  const displayN = soloCamera ? 1 : n;

  const suspectList = Array.isArray(suspects) ? suspects : [];
  const eventList = Array.isArray(events) ? events : [];
  const alertCount = eventList.length;
  const suspectSightings = suspectList.filter((s) => (s && s.sight_count) ? s.sight_count > 0 : false);

  return (
    <div className="flex flex-col gap-5 max-w-[1400px] mx-auto w-full">
      {/* Top Header / Status bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-white/80 dark:bg-slate-900/80 border border-slate-200/80 dark:border-white/10 rounded-2xl px-5 py-3.5 backdrop-blur-xl shadow-sm transition-colors">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2.5">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.8)] animate-pulse" />
            <h1 className="text-sm font-bold tracking-tight text-slate-900 dark:text-slate-100 uppercase">
              Camera overview
            </h1>
          </div>
          <span className="text-xs font-mono font-medium text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 rounded-full px-3 py-0.5">
            {n} {n === 1 ? "Active Source" : "Active Sources"}
          </span>
          {soloCamera && (
            <button
              onClick={() => setSolo(null)}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200 bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-2.5 py-1 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors cursor-pointer"
              title="Back to overview"
            >
              <CompressIcon className="w-3.5 h-3.5" />
              <span>Back to overview</span>
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-slate-400 font-medium hidden md:inline">
            Model:
          </span>
          <span className="font-mono text-xs font-bold uppercase px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-700">
            {activeModel}
          </span>
        </div>
      </div>

      {/* Centered Video Grid */}
      <div className="w-full flex flex-col items-center">
        {/* Primary Video Grid */}
        <div
          className="cockpit-grid w-full"
          data-n={String(displayN)}
          data-testid="cockpit-grid"
        >
          {displayedCameras.map((c) => (
            <CameraTile
              key={c.id}
              camera={c}
              preset={preset}
              showPeople={showPeople}
              showFaces={showFaces}
              showLabels={showLabels}
              showConfidence={showConfidence}
              isSolo={Boolean(soloCamera)}
              onSolo={() => setSolo((prev) => (prev === c.id ? null : c.id))}
              onInspectTarget={onInspectTarget}
              onStopped={() => navigate("/")}
              fencePoints={fencePoints[c.id] ?? c.fence?.polygon ?? []}
              showFence={showFence && Boolean(c.fence?.polygon?.length)}
              fenceDrawing={drawingFenceFor === c.id}
              onFencePoint={(point) => setFencePoints((previous) => ({ ...previous, [c.id]: [...(previous[c.id] ?? []), point] }))}
            />
          ))}
        </div>

        {/* Video Control Pill Bar */}
        {n > 0 && (
          <div className="control-pill-bar mt-3 w-full max-w-[1200px] flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-2xl bg-white/85 dark:bg-slate-900/90 backdrop-blur-xl border border-slate-200/80 dark:border-white/10 shadow-md transition-colors">
            {/* Left: Exit Solo mode when active, or overlay label */}
            <div className="flex items-center gap-2">
              {n === 1 && (cameras[0]?.fence?.polygon?.length ?? 0) > 0 && (
                <button
                  type="button"
                  onClick={() => setShowFence((visible) => !visible)}
                  className="secondary-button border border-cyan-300/60 bg-cyan-50 text-cyan-900 dark:border-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-100 cursor-pointer"
                >
                  {showFence ? "Hide fence" : "Show fence"}
                </button>
              )}
              {n === 1 && (
                <button
                  type="button"
                  onClick={() => {
                    const camera = cameras[0];
                    setFencePoints((previous) => ({ ...previous, [camera.id]: camera.fence?.polygon ?? [] }));
                    setDrawingFenceFor((current) => (current === camera.id ? null : camera.id));
                  }}
                  className="secondary-button border border-amber-300/60 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100 cursor-pointer"
                >
                  {drawingFenceFor ? "Finish fence" : "Draw fence"}
                </button>
              )}
              {n === 1 && drawingFenceFor && (fencePoints[drawingFenceFor]?.length ?? 0) >= 3 && (
                <button
                  type="button"
                  onClick={async () => {
                    const camera = cameras[0];
                    await setCameraFence(camera.id, fencePoints[camera.id] ?? []);
                    await qc.invalidateQueries({ queryKey: ["cameras"] });
                    setDrawingFenceFor(null);
                    setShowFence(true);
                  }}
                  className="primary-button bg-amber-400 text-amber-950 hover:bg-amber-300 cursor-pointer"
                >
                  Save fence
                </button>
              )}
              {soloCamera ? (
                <button
                  onClick={() => setSolo(null)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all cursor-pointer shadow-sm active:scale-95"
                  title="Exit Theater Solo Mode"
                >
                  <CompressIcon className="w-3.5 h-3.5" />
                  <span>Exit Solo ({soloCamera.name})</span>
                </button>
              ) : (
                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  Overlay
                </span>
              )}
            </div>

            {/* Center: Overlay Presets Segmented Bar */}
            <div className="flex items-center gap-1 bg-slate-100/90 dark:bg-slate-800/90 p-1 rounded-full border border-slate-200/80 dark:border-white/5">
              <button
                onClick={() => setPreset("clean")}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition-all cursor-pointer ${
                  preset === "clean"
                    ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-xs"
                    : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                }`}
                title="Minimalist subtle corner brackets"
              >
                Clean
              </button>
              <button
                onClick={() => setPreset("all")}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition-all cursor-pointer ${
                  preset === "all"
                    ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-xs"
                    : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                }`}
                title="Full bounding boxes, track IDs, scores"
              >
                All Data
              </button>
              <button
                onClick={() => setPreset("alerts")}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition-all cursor-pointer ${
                  preset === "alerts"
                    ? "bg-rose-600 text-white shadow-xs"
                    : "text-slate-600 dark:text-slate-400 hover:text-rose-600 dark:hover:text-rose-300"
                }`}
                title="Only highlights watchlist matches and priority alerts"
              >
                Alerts Only
              </button>
            </div>

            {/* Right: Fine-Grained Toggles & Drawer Button */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {/* People Toggle */}
              <button
                onClick={() => setShowPeople((v) => !v)}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold border transition-all cursor-pointer ${
                  showPeople
                    ? "bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-slate-100 border-slate-300 dark:border-slate-600"
                    : "bg-slate-100/50 dark:bg-slate-800/40 text-slate-400 border-transparent opacity-60"
                }`}
                title="Toggle Person Bounding Boxes"
              >
                <UserIcon className="w-3.5 h-3.5" />
                <span>People</span>
              </button>

              {/* Faces Toggle */}
              <button
                onClick={() => setShowFaces((v) => !v)}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold border transition-all cursor-pointer ${
                  showFaces
                    ? "bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-slate-100 border-slate-300 dark:border-slate-600"
                    : "bg-slate-100/50 dark:bg-slate-800/40 text-slate-400 border-transparent opacity-60"
                }`}
                title="Toggle Face Detections"
              >
                <FaceIcon className="w-3.5 h-3.5" />
                <span>Faces</span>
              </button>

              {/* Labels Toggle */}
              <button
                onClick={() => setShowLabels((v) => !v)}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold border transition-all cursor-pointer ${
                  showLabels
                    ? "bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-slate-100 border-slate-300 dark:border-slate-600"
                    : "bg-slate-100/50 dark:bg-slate-800/40 text-slate-400 border-transparent opacity-60"
                }`}
                title="Toggle Detection Text & Track IDs"
              >
                <TagIcon className="w-3.5 h-3.5" />
                <span>Labels</span>
              </button>

              {/* Confidence % Toggle */}
              <button
                onClick={() => setShowConfidence((v) => !v)}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold border transition-all cursor-pointer ${
                  showConfidence
                    ? "bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-slate-100 border-slate-300 dark:border-slate-600"
                    : "bg-slate-100/50 dark:bg-slate-800/40 text-slate-400 border-transparent opacity-60"
                }`}
                title="Toggle Confidence Percentage"
              >
                <PercentIcon className="w-3 h-3" />
                <span>Conf</span>
              </button>

              {/* Drawer Toggle Button */}
              <button
                onClick={() => setDrawerOpen((v) => !v)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold border transition-all cursor-pointer shadow-sm active:scale-95 ${
                  drawerOpen
                    ? "bg-rose-600 text-white border-rose-600"
                    : "border-slate-200 dark:border-slate-700/80 bg-slate-100/80 dark:bg-slate-800/80 text-slate-700 dark:text-slate-200 hover:border-rose-500"
                }`}
                title="Toggle Alerts & Watchlist Drawer"
              >
                <BellIcon className="w-3.5 h-3.5" />
                <span>Alerts</span>
                {alertCount > 0 && (
                  <span
                    className={`flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px] font-bold ${
                      drawerOpen ? "bg-white text-rose-600" : "bg-rose-600 text-white"
                    }`}
                  >
                    {alertCount}
                  </span>
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {n === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 bg-white/50 dark:bg-slate-900/50 p-12 text-center text-slate-500 dark:text-slate-400 transition-colors">
          <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            No Video Feeds Connected
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Add a live phone camera, IP camera, or CCTV feed from the top bar to begin monitoring.
          </p>
        </div>
      )}

      {/* Incident & Alert Log / System Status */}
      <div className="grid gap-3.5">
        <AlertRail limit={5} />
        <HealthBar />
      </div>

      {/* Collapsible Right-Hand Slide-Over Drawer: Real-Time Watchlist Matches & Activity Events */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs transition-opacity flex justify-end modal-backdrop-animate"
          onClick={() => setDrawerOpen(false)}
        >
          <div
            className="drawer-slide-animate w-full max-w-md h-full bg-white/95 dark:bg-slate-900/95 backdrop-blur-2xl border-l border-slate-200/80 dark:border-white/10 shadow-2xl flex flex-col p-6 text-slate-900 dark:text-slate-100 overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer Header */}
            <div className="flex items-center justify-between pb-4 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-xl bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900/50 flex items-center justify-center text-rose-500 shadow-xs">
                  <BellIcon className="w-4 h-4" />
                </div>
                <div>
                  <h2 className="text-sm font-bold tracking-tight">Alerts & Watchlist</h2>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Alerts and recent activity
                  </p>
                </div>
              </div>
              <button
                onClick={() => setDrawerOpen(false)}
                aria-label="Close"
                className="h-7 w-7 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs cursor-pointer"
              >
                <CloseIcon className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Suspect Sightings Section */}
            <div className="mt-5 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Watchlist Matches ({suspectSightings.length})
                </span>
                {onOpenWatchlist && (
                  <button
                    onClick={() => {
                      setDrawerOpen(false);
                      onOpenWatchlist();
                    }}
                    className="text-[11px] text-slate-800 dark:text-slate-200 hover:underline font-medium cursor-pointer"
                  >
                    Manage Watchlist
                  </button>
                )}
              </div>

              {suspectSightings.length === 0 ? (
                <div className="rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 p-4 text-center text-xs text-slate-400">
                  No watchlist matches recorded yet
                </div>
              ) : (
                suspectSightings.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between rounded-xl border border-rose-200/60 dark:border-rose-900/40 bg-rose-50/40 dark:bg-rose-950/20 p-3"
                  >
                    <div className="flex items-center gap-3">
                      {s.thumbnail_b64 ? (
                        <img
                          src={`data:image/jpeg;base64,${s.thumbnail_b64}`}
                          alt={s.name}
                          className="h-10 w-10 rounded-lg object-cover border border-rose-300 dark:border-rose-800 shadow-xs"
                        />
                      ) : (
                        <div className="h-10 w-10 rounded-lg bg-rose-100 dark:bg-rose-950 border border-rose-200 dark:border-rose-900/50 flex items-center justify-center text-rose-500 dark:text-rose-400">
                          <UserIcon className="w-5 h-5" />
                        </div>
                      )}
                      <div>
                        <div className="text-xs font-bold text-slate-900 dark:text-slate-100">
                          {s.name}
                        </div>
                        <div className="text-[10px] text-rose-600 dark:text-rose-400 font-semibold uppercase">
                          {s.threat_level} Priority • {s.sight_count} Sightings
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Perimeter & Intrusion Events Section */}
            <div className="mt-6 space-y-3 flex-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Perimeter Events ({eventList.length})
                </span>
                <span className="text-[10px] text-slate-400 font-mono">Latest</span>
              </div>

              {eventList.length === 0 ? (
                <div className="rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 p-4 text-center text-xs text-slate-400">
                  No recent events
                </div>
              ) : (
                <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                  {eventList.map((ev) => {
                    const isIntrusion = ev.event_type.toLowerCase().includes("intrusion");
                    return (
                      <div
                        key={ev.id}
                        className={`flex items-center justify-between rounded-xl border p-2.5 text-xs transition-colors ${
                          isIntrusion
                            ? "border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-950/40 text-rose-900 dark:text-rose-100"
                            : "border-slate-100 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/40 text-slate-800 dark:text-slate-200"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${
                              isIntrusion
                                ? "bg-rose-600 text-white"
                                : "bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300"
                            }`}
                          >
                            {ev.event_type.replace(/_/g, " ")}
                          </span>
                          <span className="font-medium text-[11px]">
                            {ev.zone_id ? `Zone: ${ev.zone_id}` : "Camera FOV"}
                          </span>
                        </div>

                        {ev.confidence !== undefined && (
                          <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
                            {Math.round(ev.confidence * 100)}%
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Bottom Close Action */}
            <div className="pt-4 mt-auto border-t border-slate-100 dark:border-slate-800">
              <button
                onClick={() => setDrawerOpen(false)}
                className="w-full py-2 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-xs font-semibold transition-colors cursor-pointer"
              >
                Close Drawer
              </button>
            </div>
          </div>
        </div>
      )}

      {modalOpen ? <span className="hidden" data-testid="modal-open" /> : null}
    </div>
  );
}
