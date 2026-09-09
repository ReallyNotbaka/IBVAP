import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { deleteCameraFence, setCameraFence, useCameras, useModels, useWatchlist, useEvents } from "../lib/api";
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

const EMPTY_FENCE: [number, number][] = [];

const CockpitTile = memo(function CockpitTile({
  camera,
  preset,
  showPeople,
  showFaces,
  showLabels,
  showConfidence,
  isSolo,
  fencePoints,
  showFence,
  fenceDrawing,
  onInspectTarget,
  onSoloToggle,
  onSelectCamera,
  onFencePoint,
  onRemoveFencePoint,
  onStopped,
}: {
  camera: Parameters<typeof CameraTile>[0]["camera"];
  preset: OverlayPreset;
  showPeople: boolean;
  showFaces: boolean;
  showLabels: boolean;
  showConfidence: boolean;
  isSolo: boolean;
  fencePoints: [number, number][];
  showFence: boolean;
  fenceDrawing: boolean;
  onInspectTarget?: (target: TargetInspectData) => void;
  onSoloToggle: (id: string) => void;
  onSelectCamera: (id: string) => void;
  onFencePoint: (cameraId: string, point: [number, number]) => void;
  onRemoveFencePoint: (cameraId: string, index: number) => void;
  onStopped: () => void;
}) {
  const cameraId = camera.id;
  const handleSolo = useCallback(() => onSoloToggle(cameraId), [onSoloToggle, cameraId]);
  const handleSelect = useCallback(() => onSelectCamera(cameraId), [onSelectCamera, cameraId]);
  const handlePoint = useCallback(
    (point: [number, number]) => onFencePoint(cameraId, point),
    [onFencePoint, cameraId],
  );
  const handleRemovePoint = useCallback(
    (index: number) => onRemoveFencePoint(cameraId, index),
    [onRemoveFencePoint, cameraId],
  );
  return (
    <CameraTile
      camera={camera}
      preset={preset}
      showPeople={showPeople}
      showFaces={showFaces}
      showLabels={showLabels}
      showConfidence={showConfidence}
      isSolo={isSolo}
      onSolo={handleSolo}
      onInspectTarget={onInspectTarget}
      onStopped={onStopped}
      fencePoints={fencePoints}
      showFence={showFence}
      fenceDrawing={fenceDrawing}
      onSelectCamera={handleSelect}
      onFencePoint={handlePoint}
      onRemoveFencePoint={handleRemovePoint}
    />
  );
});

export const Cockpit = memo(function Cockpit({
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
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);

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
  const [fenceSaveState, setFenceSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const n = cameras.length;
  const soloCamera = useMemo(
    () => (solo ? cameras.find((c) => c.id === solo) ?? null : null),
    [solo, cameras],
  );
  const displayedCameras = useMemo(() => (soloCamera ? [soloCamera] : cameras), [soloCamera, cameras]);
  const displayN = soloCamera ? 1 : n;

  const suspectList = useMemo(() => (Array.isArray(suspects) ? suspects : []), [suspects]);
  const eventList = useMemo(() => (Array.isArray(events) ? events : []), [events]);
  const alertCount = eventList.length;
  const suspectSightings = useMemo(
    () => suspectList.filter((s) => (s && s.sight_count ? s.sight_count > 0 : false)),
    [suspectList],
  );

  const handleSoloToggle = useCallback((id: string) => {
    setSolo((prev) => (prev === id ? null : id));
  }, []);
  const handleSelectCamera = useCallback((id: string) => {
    setSelectedCameraId(id);
  }, []);
  const handleFencePoint = useCallback((cameraId: string, point: [number, number]) => {
    setFencePoints((previous) => {
      const current = previous[cameraId] ?? [];
      if (current.length >= 32) return previous;
      if (current.length > 0) {
        const last = current[current.length - 1];
        if (Math.hypot(point[0] - last[0], point[1] - last[1]) < 0.015) {
          return previous;
        }
      }
      return { ...previous, [cameraId]: [...current, point] };
    });
  }, []);
  const handleRemoveFencePoint = useCallback((cameraId: string, index: number) => {
    setFencePoints((previous) => {
      const current = previous[cameraId] ?? [];
      return { ...previous, [cameraId]: current.filter((_, idx) => idx !== index) };
    });
  }, []);
  const handleStopped = useCallback(() => navigate("/"), [navigate]);
  const handleToggleDrawer = useCallback(() => setDrawerOpen((v) => !v), []);
  const handleCloseDrawer = useCallback(() => setDrawerOpen(false), []);
  const handleToggleShowFence = useCallback(() => setShowFence((visible) => !visible), []);
  const handleExitSolo = useCallback(() => setSolo(null), []);
  const tileFencePoints = useMemo(() => {
    const m: Record<string, [number, number][]> = {};
    for (const c of displayedCameras) {
      m[c.id] = fencePoints[c.id] ?? c.fence?.polygon ?? EMPTY_FENCE;
    }
    return m;
  }, [displayedCameras, fencePoints]);
  const tileShowFence = useMemo(() => {
    const m: Record<string, boolean> = {};
    for (const c of displayedCameras) {
      m[c.id] = showFence && Boolean(c.fence?.polygon?.length);
    }
    return m;
  }, [displayedCameras, showFence]);
  const tileDrawing = useMemo(() => {
    const m: Record<string, boolean> = {};
    for (const c of displayedCameras) {
      m[c.id] = drawingFenceFor === c.id;
    }
    return m;
  }, [displayedCameras, drawingFenceFor]);

  useEffect(() => {
    if (!drawingFenceFor) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "Backspace" || e.key === "Delete") {
        e.preventDefault();
        setFencePoints((prev) => {
          const pts = prev[drawingFenceFor] ?? [];
          if (pts.length === 0) return prev;
          return { ...prev, [drawingFenceFor]: pts.slice(0, -1) };
        });
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [drawingFenceFor]);

  const activeFenceCamera = useMemo(
    () =>
      soloCamera ??
      (drawingFenceFor
        ? cameras.find((c) => c.id === drawingFenceFor) ?? cameras[0]
        : selectedCameraId
          ? cameras.find((c) => c.id === selectedCameraId) ?? cameras[0]
          : cameras[0]),
    [soloCamera, drawingFenceFor, cameras, selectedCameraId],
  );

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
              onClick={handleExitSolo}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200 bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-2.5 py-1 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors cursor-pointer"
              title="Back to overview"
            >
              ← Back to Grid
            </button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
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
            <CockpitTile
              key={c.id}
              camera={c}
              preset={preset}
              showPeople={showPeople}
              showFaces={showFaces}
              showLabels={showLabels}
              showConfidence={showConfidence}
              isSolo={Boolean(soloCamera)}
              onInspectTarget={onInspectTarget}
              onSoloToggle={handleSoloToggle}
              onSelectCamera={handleSelectCamera}
              onFencePoint={handleFencePoint}
              onRemoveFencePoint={handleRemoveFencePoint}
              onStopped={handleStopped}
              fencePoints={tileFencePoints[c.id] ?? EMPTY_FENCE}
              showFence={tileShowFence[c.id] ?? false}
              fenceDrawing={tileDrawing[c.id] ?? false}
            />
          ))}
        </div>

        {/* Video Control Pill Bar */}
        {n > 0 && (
          <div className="control-pill-bar mt-3 w-full max-w-[1200px] flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-2xl bg-white/85 dark:bg-slate-900/90 backdrop-blur-xl border border-slate-200/80 dark:border-white/10 shadow-md transition-colors">
            {/* Left: Fence Controls */}
            <div className="flex items-center gap-2 flex-wrap">
              {activeFenceCamera && (
                <>
                  {/* Show/Hide fence toggle */}
                  {(activeFenceCamera.fence?.polygon?.length ?? 0) > 0 && !drawingFenceFor && (
                    <button
                      type="button"
                      onClick={handleToggleShowFence}
                      className="secondary-button border border-cyan-300/60 bg-cyan-50 text-cyan-900 dark:border-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-100 cursor-pointer text-xs"
                      title={showFence ? "Hide fence overlay" : "Show fence overlay"}
                    >
                      {showFence ? "Hide fence" : "Show fence"}
                    </button>
                  )}

                  {/* Draw / Cancel button */}
                  <button
                    type="button"
                    onClick={() => {
                      setFenceSaveState("idle");
                      if (drawingFenceFor === activeFenceCamera.id) {
                        setDrawingFenceFor(null);
                        setFencePoints((previous) => {
                          const next = { ...previous };
                          delete next[activeFenceCamera.id];
                          return next;
                        });
                      } else {
                        setDrawingFenceFor(activeFenceCamera.id);
                        setFencePoints((previous) => ({
                          ...previous,
                          [activeFenceCamera.id]: [],
                        }));
                      }
                    }}
                    className="secondary-button border border-amber-300/60 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100 cursor-pointer text-xs"
                  >
                    {drawingFenceFor === activeFenceCamera.id
                      ? "Cancel drawing"
                      : (activeFenceCamera.fence?.polygon?.length ?? 0) > 0
                      ? "Redraw fence"
                      : "Draw fence"}
                  </button>

                  {/* Drawing Active controls */}
                  {drawingFenceFor === activeFenceCamera.id && (
                    <>
                      <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded-lg bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200 border border-amber-300/50 dark:border-amber-700/50">
                        {fencePoints[activeFenceCamera.id]?.length ?? 0} pts
                        {(fencePoints[activeFenceCamera.id]?.length ?? 0) === 2
                          ? " (Line Tripwire)"
                          : (fencePoints[activeFenceCamera.id]?.length ?? 0) >= 3
                          ? " (Polygon Zone)"
                          : ""}
                      </span>

                      {/* Undo point */}
                      <button
                        type="button"
                        onClick={() => {
                          setFencePoints((prev) => {
                            const pts = prev[activeFenceCamera.id] ?? [];
                            return { ...prev, [activeFenceCamera.id]: pts.slice(0, -1) };
                          });
                        }}
                        disabled={(fencePoints[activeFenceCamera.id]?.length ?? 0) === 0}
                        className="secondary-button border border-slate-300 dark:border-slate-700 text-xs px-2.5 py-1 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                        title="Remove last placed point (or press Backspace)"
                      >
                        Undo point
                      </button>

                      {/* Clear all points */}
                      <button
                        type="button"
                        onClick={() => {
                          setFencePoints((prev) => ({ ...prev, [activeFenceCamera.id]: [] }));
                        }}
                        disabled={(fencePoints[activeFenceCamera.id]?.length ?? 0) === 0}
                        className="secondary-button border border-rose-300/60 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200 text-xs px-2.5 py-1 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                        title="Clear all points being drawn"
                      >
                        Clear points
                      </button>

                      {/* Save button: enabled for >= 2 points */}
                      {(fencePoints[activeFenceCamera.id]?.length ?? 0) >= 2 && (
                        <button
                          type="button"
                          onClick={async () => {
                            const pts = fencePoints[activeFenceCamera.id] ?? [];
                            const fenceType = pts.length === 2 ? "line" : "polygon";
                            setFenceSaveState("saving");
                            try {
                              await setCameraFence(activeFenceCamera.id, pts, true, fenceType);
                              await qc.invalidateQueries({ queryKey: ["cameras"] });
                              setDrawingFenceFor(null);
                              setShowFence(true);
                              setFencePoints((prev) => {
                                const next = { ...prev };
                                delete next[activeFenceCamera.id];
                                return next;
                              });
                              setFenceSaveState("saved");
                            } catch {
                              setFenceSaveState("error");
                            }
                          }}
                          disabled={fenceSaveState === "saving"}
                          className="primary-button bg-amber-400 text-amber-950 hover:bg-amber-300 text-xs px-3 py-1 cursor-pointer disabled:cursor-wait disabled:opacity-60 font-semibold"
                        >
                          {fenceSaveState === "saving"
                            ? "Saving..."
                            : fenceSaveState === "error"
                            ? "Retry save"
                            : fenceSaveState === "saved"
                            ? "Saved!"
                            : (fencePoints[activeFenceCamera.id]?.length ?? 0) === 2
                            ? "Save line fence"
                            : "Save polygon fence"}
                        </button>
                      )}
                    </>
                  )}

                  {/* Delete saved fence */}
                  {(activeFenceCamera.fence?.polygon?.length ?? 0) > 0 && !drawingFenceFor && (
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await deleteCameraFence(activeFenceCamera.id);
                          setFencePoints((prev) => {
                            const next = { ...prev };
                            delete next[activeFenceCamera.id];
                            return next;
                          });
                          await qc.invalidateQueries({ queryKey: ["cameras"] });
                        } catch {
                          // ignore or retry
                        }
                      }}
                      className="secondary-button border border-rose-300/50 bg-rose-50/50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300 text-xs px-2.5 py-1 cursor-pointer hover:bg-rose-100 dark:hover:bg-rose-900/50"
                      title="Delete saved perimeter fence"
                    >
                      Delete fence
                    </button>
                  )}
                </>
              )}
              {soloCamera ? (
                <button
                  onClick={handleExitSolo}
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
                onClick={handleToggleDrawer}
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
          onClick={handleCloseDrawer}
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
});
