import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { OverlayCanvas, type Box, type OverlayPreset } from "./OverlayCanvas";
import { TileHealth } from "./TileHealth";
import {
  base,
  controlPlayback,
  disableCamera,
  fetchCameraObservations,
  fetchPlayback,
  reconnectCamera,
  seekPlayback,
  type Camera,
} from "../lib/api";
import {
  ExpandIcon,
  CompressIcon,
  MoonIcon,
} from "./Icons";
import { createFallbackThumb, getInspectorStyle } from "./useCanvasCoords";
import { useFenceDrawing } from "./useFenceDrawing";
import { PlaybackScrubber } from "./PlaybackScrubber";
import { TargetInspector } from "./TargetInspector";
import {
  TacticalVisionMode,
  TacticalVisionSelector,
  TacticalVisionSVGDefs,
  getTacticalFilterStyle,
} from "./TacticalVisionFilters";

export interface TargetInspectData {
  trackId?: string;
  label: string;
  confidence?: number;
  thumbnail?: string | null;
  targetType?: "face" | "plate";
  plateNumber?: string;
  vehicleClass?: string;
}

// One video tile. <img> shows MJPEG from GET /cameras/{id}/stream,
// polling fetchCameraObservations (80ms) gives boxes drawn on OverlayCanvas.
// EMA smoothing keeps boxes from jittering. Fence drawing + click-to-inspect
// + watchlist enroll all live here.
export const CameraTile = memo(function CameraTile({
  camera,
  preset = "all",
  showPeople = true,
  showFaces = true,
  showLabels = true,
  showConfidence = true,
  mode = "operational",
  isSolo = false,
  onSolo,
  onInspectTarget,
  onStopped,
  fencePoints = [],
  showFence = false,
  fenceDrawing = false,
  onFencePoint,
  onRemoveFencePoint,
  onSelectCamera,
}: {
  camera: Camera;
  preset?: OverlayPreset;
  showPeople?: boolean;
  showFaces?: boolean;
  showLabels?: boolean;
  showConfidence?: boolean;
  mode?: "minimal" | "operational" | "analytics";
  isSolo?: boolean;
  onSolo?: () => void;
  onInspectTarget?: (target: TargetInspectData) => void;
  onStopped?: () => void;
  fencePoints?: [number, number][];
  showFence?: boolean;
  fenceDrawing?: boolean;
  onFencePoint?: (point: [number, number]) => void;
  onRemoveFencePoint?: (index: number) => void;
  onSelectCamera?: () => void;
}) {
  const qc = useQueryClient();
  const [selectedBox, setSelectedBox] = useState<Box | null>(null);
  const [targetThumb, setTargetThumb] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);
  const [videoAspect, setVideoAspect] = useState<number | null>(null);
  const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  const [transportBusy, setTransportBusy] = useState(false);
  const [visionMode, setVisionMode] = useState<TacticalVisionMode>("normal");

  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const smoothedCoordsRef = useRef<Map<string, [number, number, number, number]>>(new Map());
  const selectedBoxRef = useRef<Box | null>(null);
  selectedBoxRef.current = selectedBox;

  const isFootage = camera.source_type === "video_footage" || camera.protocol === "file";

  const { data: playback } = useQuery({
    queryKey: ["camera-playback", camera.id],
    queryFn: () => fetchPlayback(camera.id),
    enabled: isFootage,
    refetchInterval: isFootage ? 500 : false,
  });

  const runTransport = useCallback(
    async (action: "pause" | "resume" | "restart" | "stop") => {
      setTransportBusy(true);
      try {
        await controlPlayback(camera.id, action);
        await qc.invalidateQueries({ queryKey: ["camera-playback", camera.id] });
        if (action === "stop") {
          onStopped?.();
        }
      } finally {
        setTransportBusy(false);
      }
    },
    [camera.id, onStopped, qc],
  );

  const handleReconnect = useCallback(async () => {
    try {
      await reconnectCamera(camera.id);
      await qc.invalidateQueries({ queryKey: ["cameras"] });
    } catch {
      // Ignored
    }
  }, [camera.id, qc]);

  const handleDisable = useCallback(async () => {
    try {
      await disableCamera(camera.id);
      await qc.invalidateQueries({ queryKey: ["cameras"] });
    } catch {
      // Ignored
    }
  }, [camera.id, qc]);

  // Hook for fence drawing interactions
  const {
    hoverCoords,
    handleFenceMouseMove,
    handleFenceMouseLeave,
    handleFenceClick,
    handleUndoPoint,
    fencePointsStr,
  } = useFenceDrawing({
    fencePoints,
    fenceDrawing,
    onFencePoint,
    onRemoveFencePoint,
  });

  // Track keydown for undo when drawing fence
  useEffect(() => {
    if (!fenceDrawing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "Backspace" || e.key === "Delete") {
        handleUndoPoint();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fenceDrawing, handleUndoPoint]);

  // Stream observations polling (80ms)
  const { data: observations } = useQuery({
    queryKey: ["camera-observations", camera.id],
    queryFn: () => fetchCameraObservations(camera.id),
    refetchInterval: 80,
  });

  // Reset img error if camera changes
  useEffect(() => {
    setImgError(false);
  }, [camera.id, camera.endpoint, camera.stream_epoch]);

  // Measure container size with ResizeObserver
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const effectiveAspect = videoAspect || observations?.aspect_ratio || 16 / 9;

  const renderedDimensions = useMemo(() => {
    const cw = containerSize.width;
    const ch = containerSize.height;
    if (!cw || !ch) return { width: "100%", height: "100%" };
    const aspect = effectiveAspect;
    if (cw / ch > aspect) {
      const w = ch * aspect;
      return { width: `${Math.round(w)}px`, height: `${Math.round(ch)}px` };
    }
    const w = cw;
    const h = w / aspect;
    return { width: `${Math.round(w)}px`, height: `${Math.round(h)}px` };
  }, [containerSize, effectiveAspect]);

  const fencePointsLen = fencePoints.length;
  const cameraFence = camera.fence;
  const tracks = observations?.tracks;
  const detections = observations?.detections;
  const faces = observations?.faces;

  const boxes: Box[] = useMemo(() => {
    if (smoothedCoordsRef.current.size > 50) {
      smoothedCoordsRef.current.clear();
    }
    return (tracks ?? detections ?? [])
      .filter((item) => {
        const isIdentified = "identity" in item && Boolean((item as any).identity?.name);
        return isIdentified || item.confidence >= 0.50;
      })
      .map((item) => {
        const rawBbox = item.bbox_norm;
        const trackKey = "track_id" in item && item.track_id !== undefined ? `track-${item.track_id}` : `det-${item.class_name}`;
        const prev = smoothedCoordsRef.current.get(trackKey);
        let smoothed = rawBbox;
        if (prev) {
          const alpha = 0.12;
          smoothed = [
            (1 - alpha) * prev[0] + alpha * rawBbox[0],
            (1 - alpha) * prev[1] + alpha * rawBbox[1],
            (1 - alpha) * prev[2] + alpha * rawBbox[2],
            (1 - alpha) * prev[3] + alpha * rawBbox[3],
          ];
        }
        smoothedCoordsRef.current.set(trackKey, smoothed);

        const [x1, y1, x2, y2] = smoothed;
        const width = x2 - x1;
        const tightened = item.class_name === "person" ? width * 0.88 : width;
        const trackItem =
          "track_id" in item
            ? (item as {
                identity?: {
                  name: string;
                  score: number;
                  tier: string;
                  threat_level?: string;
                  locked: boolean;
                } | null;
              })
            : null;
        const identity = trackItem?.identity;
        const isWatchlistMatch = Boolean(identity && identity.name);
        let isFenceIntrusion = "intrusion" in item && Boolean((item as { intrusion?: boolean }).intrusion);

        const activeFence = cameraFence?.polygon && cameraFence.enabled !== false
          ? cameraFence.polygon
          : (showFence && fencePoints.length >= 2 ? fencePoints : null);
        const isPersonClass = ["person", "human", "car", "truck", "bus", "motorcycle", "bicycle"].includes(item.class_name?.toLowerCase() ?? "");
        if (!isFenceIntrusion && activeFence && activeFence.length >= 2 && isPersonClass) {
          const footX = (x1 + x2) / 2;
          const footY = y2;
          if (activeFence.length === 2) {
            const [p1, p2] = activeFence;
            const dx = p2[0] - p1[0];
            const dy = p2[1] - p1[1];
            const l2 = dx * dx + dy * dy;
            const t = l2 > 1e-9 ? Math.max(0, Math.min(1, ((footX - p1[0]) * dx + (footY - p1[1]) * dy) / l2)) : 0;
            const projX = p1[0] + t * dx;
            const projY = p1[1] + t * dy;
            const dist = Math.hypot(footX - projX, footY - projY);
            if (dist <= 0.045) {
              isFenceIntrusion = true;
            }
          } else if (activeFence.length >= 3) {
            let inside = false;
            const n = activeFence.length;
            for (let i = 0; i < n; i++) {
              const [ix1, iy1] = activeFence[i];
              const [ix2, iy2] = activeFence[(i + 1) % n];
              if (((iy1 > footY) !== (iy2 > footY)) && (footX < ((ix2 - ix1) * (footY - iy1)) / (iy2 - iy1 + 1e-9) + ix1)) {
                inside = !inside;
              }
            }
            if (inside) {
              isFenceIntrusion = true;
            }
          }
        }

        const threatLevel = identity?.threat_level?.toUpperCase();
        const isCritical = threatLevel === "CRITICAL" || identity?.tier === "RED";
        const targetName = identity?.name;

        const rawClass = item.class_name?.toLowerCase() ?? "";
        const isVehicle = ["car", "truck", "bus", "motorcycle"].includes(rawClass);
        const trackIdStr = "track_id" in item && item.track_id !== undefined ? String(item.track_id) : undefined;

        let plateText = (trackItem as { plate?: string | null })?.plate || null;
        if (!plateText && trackIdStr && observations?.plates) {
          const matched = observations.plates.find(
            (p) => p.track_id !== undefined && String(p.track_id) === trackIdStr && p.text
          );
          if (matched?.text) plateText = matched.text;
        }
        if (!plateText && trackIdStr && observations?.plate_detections) {
          const matched = observations.plate_detections.find(
            (p) => p.track_id !== undefined && String(p.track_id) === trackIdStr && p.text
          );
          if (matched?.text) plateText = matched.text;
        }
        if (!plateText && isVehicle && observations?.plate_detections) {
          const matched = observations.plate_detections.find((p) => {
            if (!p.text || !p.bbox_norm) return false;
            const [px1, py1, px2, py2] = p.bbox_norm;
            const pcx = (px1 + px2) / 2;
            const pcy = (py1 + py2) / 2;
            return pcx >= x1 && pcx <= x2 && pcy >= y1 && pcy <= y2;
          });
          if (matched?.text) plateText = matched.text;
        }

        const hasPlate = Boolean(plateText);

        const displayLabel = isFenceIntrusion
          ? (isWatchlistMatch
              ? `ROI INTRUDER: [${targetName}]`
              : hasPlate
              ? `ROI INTRUDER: [${plateText!.toUpperCase()}]`
              : "ROI INTRUDER")
          : isWatchlistMatch
          ? (isCritical ? `CRITICAL: [${targetName}]` : `TARGET: [${targetName}]`)
          : hasPlate
          ? plateText!.toUpperCase()
          : item.class_name;

        return {
          x: x1 + (width - tightened) / 2,
          y: y1,
          w: tightened,
          h: y2 - y1,
          label: displayLabel,
          confidence: isWatchlistMatch ? identity?.score : item.confidence,
          trackId: trackIdStr,
          isAlert: isWatchlistMatch || isFenceIntrusion,
          isFenceIntrusion,
          targetName: targetName,
          threatLevel: threatLevel,
          isCritical: isCritical,
          isPlate: hasPlate,
          plateText: plateText || undefined,
          vehicleClass: isVehicle ? item.class_name : undefined,
          rawClass,
        };
      })
      .filter(
        (item) =>
          item.label &&
          (item.isPlate ||
            item.isAlert ||
            ["person", "car", "truck", "bus", "motorcycle", "bicycle"].includes(
              (item.rawClass || item.label).toLowerCase()
            ))
      )
      .sort((a, b) => {
        if (Boolean(a.isCritical) !== Boolean(b.isCritical)) {
          return a.isCritical ? -1 : 1;
        }
        if (Boolean(a.isAlert) !== Boolean(b.isAlert)) {
          return a.isAlert ? -1 : 1;
        }
        return (b.confidence ?? 0) - (a.confidence ?? 0);
      });
  }, [tracks, detections, cameraFence, showFence, fencePoints, fencePointsLen, observations?.plates, observations?.plate_detections]);

  const minFaceConf = 0.50;
  const isMinimal = preset === "clean" || mode === "minimal";
  const faceBoxes: Box[] = useMemo(() => {
    if (isMinimal) return [];
    return (faces ?? [])
      .filter((face) => (face.confidence ?? 0) >= minFaceConf)
      .map((face, fIdx) => {
        const rawBbox = face.bbox_norm;
        let faceKey =
          face.track_id !== undefined && face.track_id !== null
            ? `face-track-${face.track_id}`
            : "";
        if (!faceKey) {
          const cx = Math.round(((rawBbox[0] + rawBbox[2]) / 2) * 20) / 20;
          const cy = Math.round(((rawBbox[1] + rawBbox[3]) / 2) * 20) / 20;
          faceKey = `face-pos-${cx}-${cy}`;
        }
        const prev = smoothedCoordsRef.current.get(faceKey);
        let smoothed = rawBbox;
        if (prev) {
          const alpha = 0.12;
          smoothed = [
            (1 - alpha) * prev[0] + alpha * rawBbox[0],
            (1 - alpha) * prev[1] + alpha * rawBbox[1],
            (1 - alpha) * prev[2] + alpha * rawBbox[2],
            (1 - alpha) * prev[3] + alpha * rawBbox[3],
          ];
        }
        smoothedCoordsRef.current.set(faceKey, smoothed);

        const [x1, y1, x2, y2] = smoothed;
        const conf = face.confidence ?? 0;
        return {
          x: x1,
          y: y1,
          w: x2 - x1,
          h: y2 - y1,
          label: "Face",
          confidence: conf,
          trackId: face.track_id !== undefined && face.track_id !== null ? String(face.track_id) : undefined,
          isAlert: false,
          isFace: true,
          faceIndex: fIdx,
        };
      });
  }, [faces, isMinimal]);

  const plateBoxes: Box[] = useMemo(() => {
    // Suppress bumper boxes if the parent vehicle already displays the plate,
    // or if the vehicle is already tracked and rendered in boxes
    const activeVehiclePlates = new Set<string>();
    const activeVehicleTracks = new Set<string>();
    for (const b of boxes) {
      if (b.trackId) activeVehicleTracks.add(b.trackId);
      if (b.plateText) activeVehiclePlates.add(b.plateText.toUpperCase());
      if (b.label) activeVehiclePlates.add(b.label.toUpperCase());
    }

    const detectionsPlates = observations?.plate_detections ?? [];
    const result: Box[] = [];

    for (const d of detectionsPlates) {
      if (!d.bbox_norm) continue;
      const tid = d.track_id !== undefined ? String(d.track_id) : undefined;
      const pText = d.text ? d.text.trim().toUpperCase() : undefined;
      const conf = d.confidence || 0;

      // Filter out invalid/empty/zero-confidence detections:
      // NEVER show 0% confidence boxes or empty "NUMBER PLATE" placeholders!
      if (!pText || conf <= 0 || conf < 0.40) continue;

      // If this plate belongs to a vehicle already tracked and drawn on screen,
      // suppress the duplicate sub-box (the vehicle box itself displays the plate).
      if (tid && activeVehicleTracks.has(tid)) continue;
      if (activeVehiclePlates.has(pText)) continue;

      const [x1, y1, x2, y2] = d.bbox_norm;
      result.push({
        x: x1,
        y: y1,
        w: x2 - x1,
        h: y2 - y1,
        label: pText,
        confidence: conf,
        trackId: tid,
        isAlert: false,
        isPlate: true,
        plateText: d.text,
      });
    }

    return result;
  }, [observations?.plate_detections, boxes]);

  const allBoxes = useMemo(() => {
    return [...boxes, ...faceBoxes, ...plateBoxes];
  }, [boxes, faceBoxes, plateBoxes]);

  const activeSelectedBox = useMemo(() => {
    if (!selectedBox) return null;
    if (selectedBox.trackId) {
      const match = allBoxes.find((b) => b.trackId === selectedBox.trackId);
      if (match) return match;
    }
    return selectedBox;
  }, [selectedBox, allBoxes]);

  const handleSelectBox = useCallback(
    (box: Box) => {
      setSelectedBox(box);
      if (imgRef.current) {
        try {
          const img = imgRef.current;
          const canvas = document.createElement("canvas");
          const iw = img.naturalWidth || img.width || 640;
          const ih = img.naturalHeight || img.height || 480;
          const bx = Math.max(0, Math.min(1, box.x));
          const by = Math.max(0, Math.min(1, box.y));
          const bw = Math.max(0.01, Math.min(1 - bx, box.w));
          const bh = Math.max(0.01, Math.min(1 - by, box.h));

          const sx = Math.floor(bx * iw);
          const sy = Math.floor(by * ih);
          const sw = Math.max(1, Math.floor(bw * iw));
          const sh = Math.max(1, Math.floor(bh * ih));

          canvas.width = 160;
          canvas.height = 160;
          const ctx = canvas.getContext("2d");
          if (ctx) {
            ctx.drawImage(img, sx, sy, sw, sh, 0, 0, 160, 160);
            setTargetThumb(canvas.toDataURL("image/jpeg", 0.9));
          } else {
            setTargetThumb(createFallbackThumb(box));
          }
        } catch {
          setTargetThumb(createFallbackThumb(box));
        }
      } else {
        setTargetThumb(createFallbackThumb(box));
      }
    },
    [],
  );

  const handlePutOnWatchlist = useCallback(() => {
    if (!activeSelectedBox) return;
    const isPlate = Boolean(activeSelectedBox.isPlate || activeSelectedBox.label.startsWith("NUMBER PLATE"));
    let plateText = activeSelectedBox.plateText || null;
    if (!plateText) {
      if (isPlate) {
        const m = activeSelectedBox.label.match(/NUMBER PLATE:\s*([^\s]+)/i);
        if (m) plateText = m[1];
        else if (activeSelectedBox.label && activeSelectedBox.label.toUpperCase() !== "NUMBER PLATE") {
          plateText = activeSelectedBox.label;
        }
      } else {
        const m = activeSelectedBox.label.match(/\[([A-Z0-9]+)\]/i);
        if (m) plateText = m[1];
      }
    }

    onInspectTarget?.({
      trackId: activeSelectedBox.trackId,
      label: activeSelectedBox.label,
      confidence: activeSelectedBox.confidence,
      thumbnail: targetThumb,
      targetType: isPlate || plateText ? "plate" : "face",
      plateNumber: plateText || undefined,
      vehicleClass: activeSelectedBox.vehicleClass || undefined,
    });
    setSelectedBox(null);
  }, [activeSelectedBox, onInspectTarget, targetThumb]);

  const handleTileClick = useCallback(() => {
    onSelectCamera?.();
  }, [onSelectCamera]);

  const handleTileKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onSelectCamera?.();
      }
    },
    [onSelectCamera],
  );

  const handleImageLoad = useCallback(() => {
    setImgError(false);
    const img = imgRef.current;
    if (img && img.naturalWidth && img.naturalHeight) {
      setVideoAspect(img.naturalWidth / img.naturalHeight);
    }
  }, []);

  const handleImageError = useCallback(() => setImgError(true), []);
  const handleCloseInspector = useCallback(() => setSelectedBox(null), []);

  const tileStyle = useMemo(() => ({ aspectRatio: effectiveAspect }), [effectiveAspect]);
  const runtimeLabel = observations?.runtime?.toUpperCase() || "DIRECTML";
  const nightInfo = observations?.night;
  const nightTitle = useMemo(() => {
    if (!nightInfo?.is_night) return undefined;
    const score = nightInfo.illumination_score ?? 0;
    const pct = score > 1 ? Math.round((score / 255) * 100) : Math.round(score * 100);
    return `Night / IR Mode Active (illumination: ${pct}%, limitation: ${nightInfo.limitation || "none"})`;
  }, [nightInfo]);

  const handleSoloClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onSolo?.();
    },
    [onSolo],
  );

  const inspectorStyle = useMemo(() => getInspectorStyle(activeSelectedBox), [activeSelectedBox]);

  const sourceUnavailable = camera.observed_state === "OFFLINE" || camera.observed_state === "DISABLED";
  const sourceReconnecting = camera.observed_state === "RECONNECTING" || camera.observed_state === "CONNECTING";
  const streamUrl = base(`/api/v1/cameras/${camera.id}/stream?_t=${camera.stream_epoch}`);
  const targetCount = allBoxes.filter((b) => !b.isPlate).length;

  return (
    <div
      data-testid={`live-player-${camera.id}`}
      style={tileStyle}
      className={`tile group relative select-none transition-all duration-300 ${
        isSolo ? "ring-2 ring-slate-400 dark:ring-slate-300 shadow-2xl scale-[1.002]" : ""
      }`}
      tabIndex={0}
      onClick={handleTileClick}
      onKeyDown={handleTileKeyDown}
    >
      {/* Tactical SVG filter definitions */}
      <TacticalVisionSVGDefs />

      {/* Refined Video Top Header */}
      <div className="absolute top-2.5 left-2.5 right-2.5 flex items-center justify-between text-xs text-white z-20 pointer-events-none">
        <div className="flex items-center gap-2 bg-black/70 border border-white/10 rounded-full px-3 py-1 backdrop-blur-md shadow-sm">
          <span className={`h-2 w-2 rounded-full shadow-[0_0_8px_rgba(52,211,153,0.8)] ${sourceUnavailable ? "bg-rose-400" : sourceReconnecting ? "bg-amber-400 animate-pulse" : "bg-emerald-400 animate-pulse"}`} />
          <span className="font-semibold text-white text-[11px] tracking-tight">{camera.name}</span>
          <span className="text-[10px] text-slate-300 font-mono font-medium">
            [{runtimeLabel}]
          </span>
        </div>

        <div className="flex items-center gap-2 pointer-events-auto">
          {/* Tactical Vision Enhancement Selector */}
          <TacticalVisionSelector mode={visionMode} onChange={setVisionMode} />

          {nightInfo?.is_night && (
            <div
              className="flex items-center gap-1.5 bg-indigo-950/80 border border-indigo-500/40 rounded-full px-2.5 py-1 backdrop-blur-md text-[10px] font-mono text-indigo-200 shadow-sm"
              title={nightTitle}
            >
              <MoonIcon className="w-3 h-3 text-indigo-300 animate-pulse" />
              <span>IR NIGHT</span>
            </div>
          )}

          {observations?.night?.limitation && observations.night.limitation.includes("low visibility") && (
            <div
              className="flex items-center gap-1.5 bg-amber-950/80 border border-amber-500/40 rounded-full px-2.5 py-1 backdrop-blur-md text-[10px] font-mono text-amber-200 shadow-sm"
              title={observations.night.limitation}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-ping" />
              <span>LOW LIGHT</span>
            </div>
          )}

          {targetCount > 0 && (
            <div className="flex items-center gap-1.5 bg-black/70 border border-white/10 rounded-full px-2.5 py-1 backdrop-blur-md text-[11px] font-mono text-slate-200 shadow-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-ping" />
              <span>
                {targetCount} {targetCount === 1 ? "Target" : "Targets"}
              </span>
            </div>
          )}

          {onSolo && (
            <button
              onClick={handleSoloClick}
              className="flex items-center justify-center h-6 w-6 rounded-full bg-black/60 hover:bg-black/90 border border-white/15 text-white/80 hover:text-white transition-all text-[11px] cursor-pointer"
              title={isSolo ? "Exit Theater Solo Mode" : "Expand to Theater Solo Mode"}
              aria-label={isSolo ? "Exit Theater Solo Mode" : "Expand to Theater Solo Mode"}
            >
              {isSolo ? <CompressIcon className="w-3.5 h-3.5" /> : <ExpandIcon className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
      </div>

      {/* Video Surface & Overlays */}
      <div
        ref={containerRef}
        className="w-full h-full flex items-center justify-center bg-black relative overflow-hidden"
      >
        <div
          className={`relative flex items-center justify-center select-none ${fenceDrawing ? "cursor-crosshair" : ""}`}
          onMouseMove={handleFenceMouseMove}
          onMouseLeave={handleFenceMouseLeave}
          onClick={handleFenceClick}
          style={renderedDimensions}
        >
          {!imgError ? (
            <img
              ref={imgRef}
              src={streamUrl}
              alt={camera.name}
              className="w-full h-full object-contain block select-none transition-[filter] duration-200"
              style={getTacticalFilterStyle(visionMode)}
              decoding="async"
              draggable={false}
              onLoad={handleImageLoad}
              onError={handleImageError}
            />
          ) : (
            <div className="text-white text-xs p-6 text-center max-w-sm">
              <div className="font-semibold text-slate-200">{sourceReconnecting ? "Reconnecting to camera" : "Video signal unavailable"}</div>
              <div className="mt-1 text-slate-400 text-[11px]">
                Waiting for stream at {camera.endpoint || "configured endpoint"}
              </div>
              <div className="mt-3 text-[11px] text-amber-300/90 bg-amber-950/40 border border-amber-800/50 rounded-lg p-2.5">
                Ensure device is on the same network and stream is active.
              </div>
            </div>
          )}

          {/* Fence Drawing Status Banner */}
          {fenceDrawing && (
            <div className="absolute top-2 left-1/2 -translate-x-1/2 z-30 pointer-events-none px-3 py-1 rounded-full bg-black/85 border border-amber-400/50 text-amber-200 text-[10px] font-mono shadow-lg backdrop-blur-md whitespace-nowrap">
              {fencePoints.length === 0
                ? "Click video to place Point 1"
                : fencePoints.length === 1
                ? "Point 1 set • Click Point 2 for Line Tripwire"
                : fencePoints.length === 2
                ? "Line Tripwire ready • Click more points for Polygon • Click a point to delete"
                : `Polygon Zone (${fencePoints.length} points) • Click points to add / delete • Save fence`}
            </div>
          )}

          {/* Fence & Tripwire SVG Surface */}
          {(showFence || fenceDrawing) && fencePoints.length >= 1 && (
            <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
              <defs>
                <filter id="fence-line-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="0" stdDeviation="0.8" floodColor={fenceDrawing ? "#facc15" : "#a855f7"} floodOpacity="0.85" />
                </filter>
              </defs>

              {fenceDrawing && hoverCoords && fencePoints.length >= 1 && (
                <>
                  <line
                    x1={fencePoints[fencePoints.length - 1][0] * 100}
                    y1={fencePoints[fencePoints.length - 1][1] * 100}
                    x2={hoverCoords[0] * 100}
                    y2={hoverCoords[1] * 100}
                    stroke="#facc15"
                    strokeWidth="1.5"
                    strokeDasharray="2,2"
                    opacity="0.75"
                  />
                  {fencePoints.length >= 2 && (
                    <line
                      x1={hoverCoords[0] * 100}
                      y1={hoverCoords[1] * 100}
                      x2={fencePoints[0][0] * 100}
                      y2={fencePoints[0][1] * 100}
                      stroke="#facc15"
                      strokeWidth="1"
                      strokeDasharray="3,3"
                      opacity="0.4"
                    />
                  )}
                </>
              )}

              {fencePoints.length >= 3 && (
                <polygon
                  points={fencePointsStr}
                  fill={fenceDrawing ? "rgba(250, 204, 21, 0.12)" : "rgba(168, 85, 247, 0.15)"}
                  stroke={fenceDrawing ? "#facc15" : "#a855f7"}
                  strokeWidth={fenceDrawing ? "2" : "2"}
                  filter="url(#fence-line-glow)"
                />
              )}

              {fencePoints.length === 2 && (
                <line
                  x1={fencePoints[0][0] * 100}
                  y1={fencePoints[0][1] * 100}
                  x2={fencePoints[1][0] * 100}
                  y2={fencePoints[1][1] * 100}
                  stroke={fenceDrawing ? "#facc15" : "#a855f7"}
                  strokeWidth="2.5"
                  filter="url(#fence-line-glow)"
                />
              )}

              {fencePoints.map(([x, y], idx) => (
                <g key={idx}>
                  <circle
                    cx={x * 100}
                    cy={y * 100}
                    r={fenceDrawing ? 3.5 : 2.5}
                    fill={idx === 0 && fenceDrawing ? "#22c55e" : fenceDrawing ? "#eab308" : "#c084fc"}
                    stroke="#000"
                    strokeWidth="1"
                    className={fenceDrawing ? "pointer-events-auto cursor-pointer" : ""}
                    onClick={
                      fenceDrawing && onRemoveFencePoint
                        ? (e) => {
                            e.stopPropagation();
                            onRemoveFencePoint(idx);
                          }
                        : undefined
                    }
                  />
                </g>
              ))}
            </svg>
          )}

          {/* HUD SVG Overlays */}
          <OverlayCanvas
            boxes={allBoxes}
            mode={mode}
            preset={preset}
            showPeople={showPeople}
            showFaces={showFaces}
            showLabels={showLabels}
            showConfidence={showConfidence}
            selectedTrackId={activeSelectedBox?.trackId}
            onSelectBox={handleSelectBox}
          />

          {/* Modular Target Inspector Card */}
          {activeSelectedBox && (
            <TargetInspector
              box={activeSelectedBox}
              thumbnail={targetThumb}
              style={inspectorStyle}
              onClose={handleCloseInspector}
              onPutOnWatchlist={handlePutOnWatchlist}
            />
          )}
        </div>
      </div>

      {/* Refined Bottom Bar */}
      <div className="absolute bottom-2.5 left-2.5 right-2.5 flex items-center justify-between gap-2 pointer-events-none z-20">
        <TileHealth id={camera.id} />
        <div className="flex items-center gap-2">
          {isFootage && playback && (
            <span className="text-[10px] text-slate-200 font-mono bg-black/70 border border-white/10 rounded-full px-2.5 py-0.5 backdrop-blur-md">
              {playback.state.toUpperCase()}
            </span>
          )}
          <span className="text-[10px] text-slate-300 font-mono bg-black/70 border border-white/10 rounded-full px-2.5 py-0.5 hidden sm:inline backdrop-blur-md">
            {sourceUnavailable ? "OFFLINE" : sourceReconnecting ? "RECONNECTING" : "CONNECTED"}
          </span>
        </div>
      </div>

      {/* Modular Playback Scrubber / Transport Controls */}
      <PlaybackScrubber
        isFootage={isFootage}
        playback={playback}
        transportBusy={transportBusy}
        onTransport={runTransport}
        onSeek={async (pos) => {
          await seekPlayback(camera.id, pos);
          await qc.invalidateQueries({ queryKey: ["camera-playback", camera.id] });
        }}
        onReconnect={handleReconnect}
        onDisable={handleDisable}
      />
    </div>
  );
});
