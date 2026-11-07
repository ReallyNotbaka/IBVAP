import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { deleteCameraFence, setCameraFence, useCameras, useWatchlist, useEvents } from "../lib/api";
import { playTacticalAlert } from "../lib/audio";
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
import { TacticalRadarModal } from "../components/TacticalRadarModal";
import { MilitarySitrepModal } from "../components/MilitarySitrepModal";
import { TargetDossierModal } from "../components/TargetDossierModal";

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
  const { data: suspects = [] } = useWatchlist();
  const { data: events = [] } = useEvents(25);

  const [solo, setSolo] = useState<string | null>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);

  const [preset, setPreset] = useState<OverlayPreset>("all");
  const [showPeople, setShowPeople] = useState(true);
  const [showFaces, setShowFaces] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showConfidence, setShowConfidence] = useState(true);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [fencePoints, setFencePoints] = useState<Record<string, [number, number][]>>({});
  const [drawingFenceFor, setDrawingFenceFor] = useState<string | null>(null);
  const [showFence, setShowFence] = useState(false);
  const [fenceSaveState, setFenceSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const [radarOpen, setRadarOpen] = useState(false);
  const [sitrepOpen, setSitrepOpen] = useState(false);
  const [dossierOpen, setDossierOpen] = useState(false);

  const n = cameras.length;
  const soloCamera = useMemo(
    () => (solo ? cameras.find((c) => c.id === solo) ?? null : null),
    [solo, cameras],
  );
  const displayedCameras = useMemo(() => (soloCamera ? [soloCamera] : cameras), [soloCamera, cameras]);
  const displayN = soloCamera ? 1 : n;

  const suspectList = useMemo(() => (Array.isArray(suspects) ? suspects : []), [suspects]);
  const eventList = useMemo(
    () =>
      (Array.isArray(events) ? events : []).filter(
        (ev) => !["target_entered", "target_exited", "target_lost"].includes((ev.event_type || "").toLowerCase()),
      ),
    [events],
  );
  const alertCount = eventList.length;
  const suspectSightings = useMemo(
    () => suspectList.filter((s) => (s && s.sight_count ? s.sight_count > 0 : false)),
    [suspectList],
  );

  const lastAlertIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (events.length > 0) {
      const latest = events[0];
      if (lastAlertIdRef.current && latest.id !== lastAlertIdRef.current) {
        const threat = (latest.explanation?.threat_level || latest.explanation?.tier || "LOW").toUpperCase();
        if (
          threat === "CRITICAL" ||
          threat === "HIGH" ||
          latest.event_type.includes("watchlist") ||
          latest.event_type.includes("intrusion")
        ) {
          playTacticalAlert(threat === "CRITICAL" ? "CRITICAL" : "HIGH");
        }
      }
      lastAlertIdRef.current = latest.id;
    }
  }, [events]);

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
    <div className="w-full flex-1 flex flex-col">
      {/* Camera stage with a dedicated perimeter activity rail */}
      <div className="gg-split-workspace">
        {/* Left Column: Primary Video Stage + Under-Video Control Row */}
        <div className="gg-main-stage">
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

          {/* Under-Video Action Bar (YouTube Action Row) */}
          {n > 0 && (
            <div className="control-pill-bar panel w-full flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5">
              {/* Left: Camera Info, Fence Controls & Tactical Modals */}
              <div className="flex items-center gap-1.5 flex-wrap">
                {soloCamera ? (
                  <button
                    onClick={handleExitSolo}
                    className="btn-instrument"
                    title="Exit Theater Solo Mode"
                  >
                    <CompressIcon className="w-3.5 h-3.5" />
                    <span>Exit Solo ({soloCamera.name})</span>
                  </button>
                ) : (
                  <span className="inline-flex items-center gap-2 px-2 py-1 text-xs font-semibold text-slate-800 dark:text-slate-200">
                    <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]" />
                    <span>{activeFenceCamera?.name || `${n} Active`}</span>
                  </span>
                )}

                <div className="h-4 w-px bg-slate-200 dark:bg-white/10 mx-1" />

                {activeFenceCamera && (
                  <>
                    {(activeFenceCamera.fence?.polygon?.length ?? 0) > 0 && !drawingFenceFor && (
                      <button
                        type="button"
                        onClick={handleToggleShowFence}
                        className={showFence ? "btn-instrument-active" : "btn-instrument"}
                      >
                        {showFence ? "Hide fence" : "Show fence"}
                      </button>
                    )}

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
                      className={drawingFenceFor === activeFenceCamera.id ? "btn-instrument-active" : "btn-instrument"}
                    >
                      {drawingFenceFor === activeFenceCamera.id
                        ? "Cancel drawing"
                        : (activeFenceCamera.fence?.polygon?.length ?? 0) > 0
                        ? "Redraw fence"
                        : "Draw fence"}
                    </button>

                    {drawingFenceFor === activeFenceCamera.id && (
                      <>
                        <span className="text-[11px] font-mono font-semibold px-2.5 py-1 rounded-md bg-indigo-500/15 text-indigo-400 border border-indigo-500/30">
                          {fencePoints[activeFenceCamera.id]?.length ?? 0} pts
                          {(fencePoints[activeFenceCamera.id]?.length ?? 0) === 2
                            ? " (Line Tripwire)"
                            : (fencePoints[activeFenceCamera.id]?.length ?? 0) >= 3
                            ? " (Polygon Zone)"
                            : ""}
                        </span>

                        <button
                          type="button"
                          onClick={() => {
                            setFencePoints((prev) => {
                              const pts = prev[activeFenceCamera.id] ?? [];
                              return { ...prev, [activeFenceCamera.id]: pts.slice(0, -1) };
                            });
                          }}
                          disabled={(fencePoints[activeFenceCamera.id]?.length ?? 0) === 0}
                          className="btn-instrument"
                        >
                          Undo point
                        </button>

                        <button
                          type="button"
                          onClick={() => {
                            setFencePoints((prev) => ({ ...prev, [activeFenceCamera.id]: [] }));
                          }}
                          disabled={(fencePoints[activeFenceCamera.id]?.length ?? 0) === 0}
                          className="btn-instrument"
                        >
                          Clear points
                        </button>

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
                            className="btn-primary-cobalt"
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
                            // ignore
                          }
                        }}
                        className="btn-instrument !text-rose-400 hover:!border-rose-500/40"
                      >
                        Delete fence
                      </button>
                    )}
                  </>
                )}

                <div className="h-4 w-px bg-slate-200 dark:bg-white/10 mx-1" />

                <button
                  type="button"
                  onClick={() => setRadarOpen(true)}
                  className="btn-instrument"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  <span>BEV Radar</span>
                </button>
                <button
                  type="button"
                  onClick={() => setSitrepOpen(true)}
                  className="btn-instrument"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
                  <span>Military SITREP</span>
                </button>
                <button
                  type="button"
                  onClick={() => setDossierOpen(true)}
                  className="btn-instrument"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                  <span>Target Dossier</span>
                </button>
              </div>

              {/* Right: Overlay Presets & Layer Toggles */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <div className="inline-flex items-center gap-1 bg-slate-100 dark:bg-slate-950/70 p-1 rounded-lg border border-slate-200/80 dark:border-white/[0.08]">
                  <button
                    onClick={() => setPreset("clean")}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-all cursor-pointer ${
                      preset === "clean"
                        ? "bg-indigo-600 text-white shadow-xs font-semibold"
                        : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                    }`}
                  >
                    Clean
                  </button>
                  <button
                    onClick={() => setPreset("all")}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-all cursor-pointer ${
                      preset === "all"
                        ? "bg-indigo-600 text-white shadow-xs font-semibold"
                        : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                    }`}
                  >
                    All Data
                  </button>
                  <button
                    onClick={() => setPreset("alerts")}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-all cursor-pointer ${
                      preset === "alerts"
                        ? "bg-rose-600 text-white shadow-xs font-semibold"
                        : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                    }`}
                  >
                    Alerts Only
                  </button>
                </div>

                <button
                  onClick={() => setShowPeople((v) => !v)}
                  className={showPeople ? "btn-instrument-active" : "btn-instrument opacity-65"}
                >
                  <UserIcon className="w-3.5 h-3.5" />
                  <span>People</span>
                </button>

                <button
                  onClick={() => setShowFaces((v) => !v)}
                  className={showFaces ? "btn-instrument-active" : "btn-instrument opacity-65"}
                >
                  <FaceIcon className="w-3.5 h-3.5" />
                  <span>Faces</span>
                </button>

                <button
                  onClick={() => setShowLabels((v) => !v)}
                  className={showLabels ? "btn-instrument-active" : "btn-instrument opacity-65"}
                >
                  <TagIcon className="w-3.5 h-3.5" />
                  <span>Labels</span>
                </button>

                <button
                  onClick={() => setShowConfidence((v) => !v)}
                  className={showConfidence ? "btn-instrument-active" : "btn-instrument opacity-65"}
                >
                  <PercentIcon className="w-3 h-3" />
                  <span>Conf</span>
                </button>

                <button
                  onClick={handleToggleDrawer}
                  className={drawerOpen ? "btn-instrument-active" : "btn-instrument"}
                >
                  <BellIcon className="w-3.5 h-3.5" />
                  <span>Alerts</span>
                  {alertCount > 0 && (
                    <span className="rounded px-1.5 py-0.2 text-[10px] font-mono font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">
                      {alertCount}
                    </span>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Full-Height Edge-to-Edge Sidebar */}
        {!soloCamera && (
          <aside className="gg-sidebar-pane">
            <AlertRail limit={10} />
            <HealthBar />
          </aside>
        )}
      </div>

      {/* Slide-Over Drawer (Preserved for E2E & Full Watchlist Sightings View) */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex justify-end modal-backdrop-animate"
          onClick={handleCloseDrawer}
        >
          <div
            className="drawer-slide-animate w-full max-w-md h-full bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-white/10 shadow-2xl flex flex-col p-5 text-slate-900 dark:text-slate-100 overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-3.5 border-b border-slate-100 dark:border-white/10">
              <div className="flex items-center gap-2">
                <BellIcon className="w-4 h-4 text-slate-500" />
                <div>
                  <h2 className="text-sm font-semibold">Alerts &amp; Watchlist</h2>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Recent perimeter activity
                  </p>
                </div>
              </div>
              <button
                onClick={() => setDrawerOpen(false)}
                aria-label="Close"
                className="h-7 w-7 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/10 transition-colors cursor-pointer"
              >
                <CloseIcon className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="mt-4 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                  Watchlist Matches ({suspectSightings.length})
                </span>
                {onOpenWatchlist && (
                  <button
                    onClick={() => {
                      setDrawerOpen(false);
                      onOpenWatchlist();
                    }}
                    className="text-xs text-slate-800 dark:text-slate-200 hover:underline font-medium cursor-pointer"
                  >
                    Manage Watchlist
                  </button>
                )}
              </div>

              {suspectSightings.length === 0 ? (
                <div className="rounded-xl border border-slate-100 dark:border-white/10 bg-slate-50 dark:bg-slate-950/40 p-4 text-center text-xs text-slate-400">
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
                          className="h-9 w-9 rounded-lg object-cover border border-rose-300 dark:border-rose-800"
                        />
                      ) : (
                        <div className="h-9 w-9 rounded-lg bg-rose-100 dark:bg-rose-950 flex items-center justify-center text-rose-500">
                          <UserIcon className="w-4 h-4" />
                        </div>
                      )}
                      <div>
                        <div className="text-xs font-semibold text-slate-900 dark:text-slate-100">
                          {s.name}
                        </div>
                        <div className="text-[10px] text-rose-600 dark:text-rose-400 font-mono uppercase">
                          {s.threat_level} | {s.sight_count} Sightings
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="mt-5 space-y-2.5 flex-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                  Perimeter Events ({eventList.length})
                </span>
              </div>

              {eventList.length === 0 ? (
                <div className="rounded-xl border border-slate-100 dark:border-white/10 bg-slate-50 dark:bg-slate-950/40 p-4 text-center text-xs text-slate-400">
                  No recent events
                </div>
              ) : (
                <div className="space-y-1.5 max-h-[380px] overflow-y-auto pr-1">
                  {eventList.map((ev) => {
                    const isIntrusion = ev.event_type.toLowerCase().includes("intrusion");
                    return (
                      <div
                        key={ev.id}
                        className="flex items-center justify-between rounded-lg border border-slate-200/70 dark:border-white/10 bg-slate-50/70 dark:bg-slate-950/40 p-2.5 text-xs"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold uppercase ${
                              isIntrusion
                                ? "bg-rose-500/15 text-rose-600 dark:text-rose-300"
                                : "bg-slate-200 dark:bg-white/10 text-slate-700 dark:text-slate-300"
                            }`}
                          >
                            {ev.event_type.replace(/_/g, " ")}
                          </span>
                          <span className="text-[11px] text-slate-600 dark:text-slate-300">
                            {ev.zone_id ? `Zone: ${ev.zone_id}` : "Camera FOV"}
                          </span>
                        </div>

                        {ev.confidence !== undefined && (
                          <span className="font-mono text-[10px] text-slate-400">
                            {Math.round(ev.confidence * 100)}%
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="pt-3 mt-auto border-t border-slate-100 dark:border-white/10">
              <button
                onClick={() => setDrawerOpen(false)}
                className="w-full py-2 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-semibold transition-colors cursor-pointer"
              >
                Close Drawer
              </button>
            </div>
          </div>
        </div>
      )}

      <TacticalRadarModal
        isOpen={radarOpen}
        onClose={() => setRadarOpen(false)}
        initialCameraId={selectedCameraId ?? solo ?? cameras[0]?.id}
      />
      <MilitarySitrepModal isOpen={sitrepOpen} onClose={() => setSitrepOpen(false)} />
      <TargetDossierModal isOpen={dossierOpen} onClose={() => setDossierOpen(false)} />

      {modalOpen ? <span className="hidden" data-testid="modal-open" /> : null}
    </div>
  );
});
