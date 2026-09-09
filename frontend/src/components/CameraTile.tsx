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
  type Camera,
} from "../lib/api";
import {
  ExpandIcon,
  CompressIcon,
  CloseIcon,
  CrosshairIcon,
  UserIcon,
  FaceIcon,
  MoonIcon,
} from "./Icons";

export interface TargetInspectData {
  trackId?: string;
  label: string;
  confidence?: number;
  thumbnail?: string | null;
}

function createFallbackThumb(box: Box, size = 160): string {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) return "";

    const isFace = box.label.toLowerCase() === "face";
    // Editorial obsidian and crimson palette
    const grad = ctx.createLinearGradient(0, 0, size, size);
    if (box.isAlert) {
      grad.addColorStop(0, "#7f1d1d");
      grad.addColorStop(1, "#450a0a");
    } else {
      grad.addColorStop(0, "#1c212c");
      grad.addColorStop(1, "#0f131a");
    }
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);

    // Subtle dark circular vignette
    ctx.beginPath();
    ctx.arc(size / 2, size * 0.42, size * 0.28, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255, 255, 255, 0.15)";
    ctx.fill();

    // Geometric silhouette vector (no emojis)
    if (isFace) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(size / 2, size * 0.42, size * 0.16, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
      ctx.beginPath();
      ctx.arc(size * 0.44, size * 0.39, 2.5, 0, Math.PI * 2);
      ctx.arc(size * 0.56, size * 0.39, 2.5, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
      ctx.beginPath();
      ctx.arc(size / 2, size * 0.34, size * 0.10, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(size / 2, size * 0.56, size * 0.16, Math.PI, 0);
      ctx.fill();
    }

    // Bottom banner with label & trackId
    ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
    ctx.fillRect(0, size * 0.7, size, size * 0.3);

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 13px system-ui, -apple-system, sans-serif";
    const text = box.trackId ? `#${box.trackId} ${box.label}` : box.label;
    ctx.fillText(text.toUpperCase().slice(0, 16), size / 2, size * 0.85);

    return canvas.toDataURL("image/jpeg", 0.9);
  } catch {
    return "";
  }
}

// One video tile. <img> shows MJPEG from GET /cameras/{id}/stream,
// polling fetchCameraObservations (80ms) gives boxes drawn on OverlayCanvas.
// EMA smoothing keeps boxes from jittering. Fence drawing + click-to-inspect
// + watchlist enroll all live here.
export const CameraTile = memo(function CameraTile({
  camera,
  mode,
  preset,
  showPeople = true,
  showFaces = true,
  showLabels = true,
  showConfidence = true,
  onSolo,
  isSolo,
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
  mode?: "minimal" | "operational" | "diagnostic";
  preset?: OverlayPreset;
  showPeople?: boolean;
  showFaces?: boolean;
  showLabels?: boolean;
  showConfidence?: boolean;
  onSolo?: () => void;
  isSolo?: boolean;
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
  const [imgError, setImgError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [selectedBox, setSelectedBox] = useState<Box | null>(null);
  const [targetThumb, setTargetThumb] = useState<string | null>(null);
  const [videoAspect, setVideoAspect] = useState<number | null>(null);
  const [hoverCoords, setHoverCoords] = useState<[number, number] | null>(null);
  const lastClickRef = useRef<{ time: number; x: number; y: number } | null>(null);
  const lastPointPlacedTimeRef = useRef<number>(0);
  const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
  const imgRef = useRef<HTMLImageElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const smoothedCoordsRef = useRef<Map<string, [number, number, number, number]>>(new Map());
  const isFootage = camera.source_type === "video_footage" || camera.protocol === "file";
  const { data: playback } = useQuery({
    queryKey: ["camera-playback", camera.id],
    queryFn: () => fetchPlayback(camera.id),
    enabled: isFootage,
    refetchInterval: 1000,
    staleTime: 800,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: false,
    retry: 1,
  });
  const [transportBusy, setTransportBusy] = useState(false);

  const runTransport = useCallback(
    async (action: "pause" | "resume" | "stop" | "restart") => {
      if (!isFootage || transportBusy) return;
      setTransportBusy(true);
      try {
        await controlPlayback(camera.id, action);
        await qc.invalidateQueries({ queryKey: ["camera-playback", camera.id] });
        await qc.invalidateQueries({ queryKey: ["cameras"] });
        if (action === "stop") onStopped?.();
      } finally {
        setTransportBusy(false);
      }
    },
    [isFootage, transportBusy, camera.id, qc, onStopped],
  );

  const handleReconnect = useCallback(async () => {
    try {
      await reconnectCamera(camera.id);
      await qc.invalidateQueries({ queryKey: ["cameras"] });
    } catch {
      // keep tile visible; health polling will surface the failure
    }
  }, [camera.id, qc]);

  const handleDisable = useCallback(async () => {
    try {
      await disableCamera(camera.id);
      await qc.invalidateQueries({ queryKey: ["cameras"] });
    } catch {
      // keep tile visible; health polling will surface the failure
    }
  }, [camera.id, qc]);


  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setContainerSize((prev) =>
            Math.abs(prev.width - width) < 1 && Math.abs(prev.height - height) < 1
              ? prev
              : { width, height },
          );
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const playbackState = playback?.state;
  useEffect(() => {
    if (!isFootage || !isSolo) return;
    const handleSpace = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      event.preventDefault();
      void runTransport(playbackState === "playing" ? "pause" : "resume");
    };
    window.addEventListener("keydown", handleSpace);
    return () => window.removeEventListener("keydown", handleSpace);
  }, [isFootage, isSolo, playbackState, runTransport]);

  useEffect(() => {
    const checkNaturalDims = () => {
      const img = imgRef.current;
      if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
        const aspect = img.naturalWidth / img.naturalHeight;
        setVideoAspect((prev) => (prev && Math.abs(prev - aspect) < 0.01 ? prev : aspect));
      }
    };
    const interval = setInterval(checkNaturalDims, 250);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!imgError) return;
    const timer = setInterval(() => {
      setImgError(false);
      setRetryKey((k) => k + 1);
    }, 2500);
    return () => clearInterval(timer);
  }, [imgError]);

  const prevPointsLenRef = useRef(fencePoints.length);
  useEffect(() => {
    if (fencePoints.length === 0 && prevPointsLenRef.current > 0) {
      lastClickRef.current = null;
      lastPointPlacedTimeRef.current = 0;
    }
    prevPointsLenRef.current = fencePoints.length;
  }, [fencePoints.length]);

  useEffect(() => {
    lastClickRef.current = null;
    lastPointPlacedTimeRef.current = 0;
  }, [fenceDrawing]);

  const streamUrl = useMemo(
    () => base(`/api/v1/cameras/${camera.id}/stream?epoch=${camera.stream_epoch}&k=${retryKey}`),
    [camera.id, camera.stream_epoch, retryKey],
  );
  const { data: observations } = useQuery({
    queryKey: ["camera-observations", camera.id],
    queryFn: () => fetchCameraObservations(camera.id),
    refetchInterval: 120,
    staleTime: 100,
    gcTime: 60000,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: false,
    retry: 1,
  });

  const effectiveAspect = useMemo(
    () =>
      (observations?.aspect_ratio && observations.aspect_ratio > 0 ? observations.aspect_ratio : null) ??
      (observations?.frame_width && observations?.frame_height && observations.frame_height > 0
        ? observations.frame_width / observations.frame_height
        : null) ??
      videoAspect ??
      16 / 9,
    [observations?.aspect_ratio, observations?.frame_width, observations?.frame_height, videoAspect],
  );

  const renderedDimensions = useMemo(() => {
    const { width: cw, height: ch } = containerSize;
    if (!cw || !ch) return { width: "100%", height: "100%" };
    const aspect = effectiveAspect;
    const containerAspect = cw / ch;
    if (containerAspect > aspect) {
      // Height constrained (pillarbox)
      const h = ch;
      const w = h * aspect;
      return { width: `${Math.round(w)}px`, height: `${Math.round(h)}px` };
    }
    // Width constrained (letterbox)
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
        // Track-keyed EMA keeps the vehicle frame stable while detections fluctuate.
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

      // Also evaluate client-side against active fence points (line or polygon)
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
          } else {
            const minBx = Math.min(x1, x2);
            const maxBx = Math.max(x1, x2);
            const minBy = Math.min(y1, y2);
            const maxBy = Math.max(y1, y2);
            const inBbox = (px: number, py: number) => px >= minBx && px <= maxBx && py >= minBy && py <= maxBy;
            if (inBbox(p1[0], p1[1]) || inBbox(p2[0], p2[1])) {
              isFenceIntrusion = true;
            } else {
              const segIntersects = (ax: number, ay: number, bx: number, by: number, cx: number, cy: number, dx: number, dy: number) => {
                const EPS = 1e-9;
                const orient = (px: number, py: number, qx: number, qy: number, rx: number, ry: number) =>
                  (qx - px) * (ry - py) - (qy - py) * (rx - px);
                const onSeg = (ax0: number, ay0: number, bx0: number, by0: number, cx0: number, cy0: number) =>
                  Math.min(ax0, cx0) - EPS <= bx0 && bx0 <= Math.max(ax0, cx0) + EPS &&
                  Math.min(ay0, cy0) - EPS <= by0 && by0 <= Math.max(ay0, cy0) + EPS;
                const o1 = orient(ax, ay, bx, by, cx, cy);
                const o2 = orient(ax, ay, bx, by, dx, dy);
                const o3 = orient(cx, cy, dx, dy, ax, ay);
                const o4 = orient(cx, cy, dx, dy, bx, by);
                if (((o1 > EPS && o2 < -EPS) || (o1 < -EPS && o2 > EPS)) && ((o3 > EPS && o4 < -EPS) || (o3 < -EPS && o4 > EPS))) {
                  return true;
                }
                if (Math.abs(o1) < EPS && onSeg(ax, ay, cx, cy, bx, by)) return true;
                if (Math.abs(o2) < EPS && onSeg(ax, ay, dx, dy, bx, by)) return true;
                if (Math.abs(o3) < EPS && onSeg(cx, cy, ax, ay, dx, dy)) return true;
                if (Math.abs(o4) < EPS && onSeg(cx, cy, bx, by, dx, dy)) return true;
                return false;
              };
              if (
                segIntersects(p1[0], p1[1], p2[0], p2[1], minBx, minBy, maxBx, minBy) ||
                segIntersects(p1[0], p1[1], p2[0], p2[1], maxBx, minBy, maxBx, maxBy) ||
                segIntersects(p1[0], p1[1], p2[0], p2[1], maxBx, maxBy, minBx, maxBy) ||
                segIntersects(p1[0], p1[1], p2[0], p2[1], minBx, maxBy, minBx, minBy)
              ) {
                isFenceIntrusion = true;
              }
            }
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

      // Clearly display target's name with alert/priority styling (ROI INTRUDER for fence intrusion)
      const displayLabel = isFenceIntrusion
        ? (isWatchlistMatch ? `ROI INTRUDER: [${targetName}]` : "ROI INTRUDER")
        : isWatchlistMatch
        ? (isCritical ? `CRITICAL: [${targetName}]` : `TARGET: [${targetName}]`)
        : item.class_name;

      return {
        x: x1 + (width - tightened) / 2,
        y: y1,
        w: tightened,
        h: y2 - y1,
        label: displayLabel,
        confidence: isWatchlistMatch ? identity?.score : item.confidence,
        trackId:
          "track_id" in item
            ? String(item.track_id)
            : undefined,
        isAlert: isWatchlistMatch || isFenceIntrusion,
        isFenceIntrusion,
        targetName: targetName,
        threatLevel: threatLevel,
        isCritical: isCritical,
        isPlate: false,
      };
    })
    .filter(
      (item) =>
        item.label &&
        (item.isPlate ||
          item.isAlert ||
          ["person", "car", "truck", "bus", "motorcycle", "bicycle"].includes(
            item.label.toLowerCase()
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
  }, [tracks, detections, cameraFence, showFence, fencePoints, fencePointsLen]);

  // Show faces in operational/all modes with quiet, elegant champagne markers
  const minFaceConf = 0.50;
  const isMinimal = preset === "clean" || mode === "minimal";
  const faceBoxes: Box[] = useMemo(() => {
    if (isMinimal) return [];
    return (faces ?? [])
        .filter(
          (face) =>
            (face.confidence ?? 0) >= minFaceConf
        )
        .map((face, fIdx) => {
          const rawBbox = face.bbox_norm;
          let faceKey =
            face.track_id !== undefined && face.track_id !== null
              ? `face-track-${face.track_id}`
              : "";
          if (!faceKey) {
            let bestDist = 0.08;
            let bestKey = "";
            const fcx = (rawBbox[0] + rawBbox[2]) / 2;
            const fcy = (rawBbox[1] + rawBbox[3]) / 2;
            for (const [k, p] of smoothedCoordsRef.current.entries()) {
              if (k.startsWith("face-untracked-")) {
                const pcx = (p[0] + p[2]) / 2;
                const pcy = (p[1] + p[3]) / 2;
                const d = Math.hypot(fcx - pcx, fcy - pcy);
                if (d < bestDist) {
                  bestDist = d;
                  bestKey = k;
                }
              }
            }
            faceKey = bestKey || `face-untracked-${fIdx}`;
          }

          const prev = smoothedCoordsRef.current.get(faceKey);
          let smoothed = rawBbox;
          if (prev) {
            const cx = (rawBbox[0] + rawBbox[2]) / 2;
            const cy = (rawBbox[1] + rawBbox[3]) / 2;
            const pcx = (prev[0] + prev[2]) / 2;
            const pcy = (prev[1] + prev[3]) / 2;
            const dist = Math.hypot(cx - pcx, cy - pcy);

            // Sub-pixel jitter deadband and velocity-adaptive filter
            const alpha = dist < 0.006 ? 0.15 : dist < 0.03 ? 0.35 : dist < 0.12 ? 0.70 : 0.95;
            smoothed = [
              (1 - alpha) * prev[0] + alpha * rawBbox[0],
              (1 - alpha) * prev[1] + alpha * rawBbox[1],
              (1 - alpha) * prev[2] + alpha * rawBbox[2],
              (1 - alpha) * prev[3] + alpha * rawBbox[3],
            ];
          }
          smoothedCoordsRef.current.set(faceKey, smoothed);
          const [x1, y1, x2, y2] = smoothed;
          return {
            x: x1,
            y: y1,
            w: x2 - x1,
            h: y2 - y1,
            label: "face",
            confidence: face.confidence,
            trackId: face.track_id !== undefined && face.track_id !== null ? String(face.track_id) : undefined,
            isAlert: false,
          };
        })
        .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
  }, [faces, isMinimal]);

  const plateDetections = observations?.plate_detections;
  const plateBoxes: Box[] = useMemo(
    () =>
      (plateDetections ?? []).map((plate) => {
        const [x1, y1, x2, y2] = plate.bbox_norm;
        return {
          x: x1,
          y: y1,
          w: x2 - x1,
          h: y2 - y1,
          label: plate.text?.toUpperCase() || "plate",
          confidence: plate.confidence || undefined,
          trackId: plate.track_id !== undefined ? `track-${plate.track_id}` : undefined,
          isPlate: true,
        };
      }),
    [plateDetections],
  );

  const allBoxes = useMemo(() => {
    const matchedPlateBoxes = new Set<Box>();
    const vehicleBoxesWithPlates = boxes.map((vehicle) => {
      const plate = plateBoxes.find((candidate) => {
        if (!candidate.label || candidate.label === "plate") return false;
        if (vehicle.trackId && candidate.trackId) return vehicle.trackId === candidate.trackId;
        const centerX = candidate.x + candidate.w / 2;
        const centerY = candidate.y + candidate.h / 2;
        return (
          centerX >= vehicle.x &&
          centerX <= vehicle.x + vehicle.w &&
          centerY >= vehicle.y &&
          centerY <= vehicle.y + vehicle.h
        );
      });
      if (!plate) return vehicle;
      matchedPlateBoxes.add(plate);
      return {
        ...vehicle,
        label: plate.label,
        confidence: plate.confidence ?? vehicle.confidence,
        isPlate: true,
      };
    });
    const unmatchedPlateBoxes = plateBoxes.filter((plate) => !matchedPlateBoxes.has(plate));

    // Priority-aware deduplication: alerts and critical targets always win over non-alerts
    const deduped: Box[] = [];
    for (const box of [...vehicleBoxesWithPlates, ...faceBoxes, ...unmatchedPlateBoxes]) {
    const overlapIndex = deduped.findIndex((existing) => {
      // Don't suppress a face with a vehicle/person body or vice versa
      if (existing.label === "face" && box.label !== "face") return false;
      if (existing.label !== "face" && box.label === "face") return false;
      if (existing.isPlate || box.isPlate) return false;

      // Exact track ID match
      if (existing.trackId && box.trackId && existing.trackId === box.trackId) return true;

      const xOverlap = Math.max(
        0,
        Math.min(existing.x + existing.w, box.x + box.w) -
          Math.max(existing.x, box.x)
      );
      const yOverlap = Math.max(
        0,
        Math.min(existing.y + existing.h, box.y + box.h) -
          Math.max(existing.y, box.y)
      );
      const overlapArea = xOverlap * yOverlap;
      const minArea = Math.min(existing.w * existing.h, box.w * box.h);
      const unionArea = existing.w * existing.h + box.w * box.h - overlapArea;
      const iou = unionArea > 0 ? overlapArea / unionArea : 0;
      const containment = minArea > 0 ? overlapArea / minArea : 0;

      // Deduplicate if IoU > 0.35 or one box is >50% contained within another
      return iou > 0.35 || containment > 0.50;
    });

    if (overlapIndex === -1) {
      deduped.push(box);
    } else {
      const existing = deduped[overlapIndex];
      // Critical targets and security alerts must never be suppressed by non-alerts
      if ((box.isAlert || box.isCritical) && (!existing.isAlert && !existing.isCritical)) {
        deduped[overlapIndex] = box;
      } else if ((box.confidence ?? 0) > (existing.confidence ?? 0) && !existing.isAlert && !existing.isCritical) {
        deduped[overlapIndex] = box;
      }
    }
    }

    return deduped.slice(0, 32);
  }, [boxes, faceBoxes, plateBoxes]);

  const targetCount = useMemo(() => allBoxes.filter((box) => !box.isPlate).length, [allBoxes]);
  const observedState = camera.observed_state;
  const sourceUnavailable = useMemo(
    () => imgError || ["OFFLINE", "ERROR", "DISABLED"].includes(observedState?.toUpperCase() ?? ""),
    [imgError, observedState],
  );
  const sourceReconnecting = observedState?.toUpperCase() === "RECONNECTING";

  // Active selected box dynamically follows moving target if trackId matches
  const activeSelectedBox = useMemo(
    () =>
      selectedBox?.trackId
        ? allBoxes.find((b) => b.trackId === selectedBox.trackId) || selectedBox
        : selectedBox,
    [selectedBox, allBoxes],
  );

  const cropTarget = useCallback((box: Box): string => {
    const img = imgRef.current;
    const size = 160;
    try {
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) return createFallbackThumb(box, size);

      if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
        const pad = 0.08;
        const px = Math.max(0, (box.x - pad * box.w) * img.naturalWidth);
        const py = Math.max(0, (box.y - pad * box.h) * img.naturalHeight);
        const pw = Math.min(
          img.naturalWidth - px,
          Math.max(1, box.w * (1 + pad * 2) * img.naturalWidth)
        );
        const ph = Math.min(
          img.naturalHeight - py,
          Math.max(1, box.h * (1 + pad * 2) * img.naturalHeight)
        );

        if (pw > 0 && ph > 0) {
          ctx.drawImage(img, px, py, pw, ph, 0, 0, size, size);
          return canvas.toDataURL("image/jpeg", 0.9);
        }
      }
    } catch {
      // tainted or error - fallback to synthetic avatar badge
    }
    return createFallbackThumb(box, size);
  }, []);

  const handleSelectBox = useCallback(
    (box: Box) => {
      setSelectedBox(box);
      const thumb = cropTarget(box);
      setTargetThumb(thumb);
    },
    [cropTarget],
  );

  const handlePutOnWatchlist = useCallback(() => {
    if (!activeSelectedBox) return;
    const thumb = targetThumb || createFallbackThumb(activeSelectedBox);
    onInspectTarget?.({
      trackId: activeSelectedBox.trackId,
      label: activeSelectedBox.label,
      confidence: activeSelectedBox.confidence,
      thumbnail: thumb,
    });
    setSelectedBox(null);
  }, [activeSelectedBox, targetThumb, onInspectTarget]);

  const handleTileClick = useCallback(() => {
    onSelectCamera?.();
    setSelectedBox((prev) => (prev ? null : prev));
  }, [onSelectCamera]);

  const handleTileKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") onSolo?.();
      if (e.key === "Escape") setSelectedBox(null);
      if (fenceDrawing && (e.key === "Backspace" || e.key === "Delete")) {
        e.stopPropagation();
        if (fencePointsLen > 0) {
          onRemoveFencePoint?.(fencePointsLen - 1);
        }
      }
    },
    [onSolo, fenceDrawing, fencePointsLen, onRemoveFencePoint],
  );

  const handleImageLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    if (img.naturalWidth && img.naturalHeight) {
      setVideoAspect(img.naturalWidth / img.naturalHeight);
    }
  }, []);

  const handleImageError = useCallback(() => setImgError(true), []);
  const handleCloseInspector = useCallback(() => setSelectedBox(null), []);
  const handleStopInspectorPropagation = useCallback((e: React.MouseEvent) => e.stopPropagation(), []);

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

  const fenceMouseMove = useMemo(
    () =>
      fenceDrawing
        ? (event: React.MouseEvent<HTMLDivElement>) => {
            const rect = event.currentTarget.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            const nx = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
            const ny = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
            setHoverCoords((prev) => (prev && Math.abs(prev[0] - nx) < 0.002 && Math.abs(prev[1] - ny) < 0.002 ? prev : [nx, ny]));
          }
        : undefined,
    [fenceDrawing],
  );
  const handleFenceMouseLeave = useCallback(() => setHoverCoords(null), []);
  const handleFenceClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!fenceDrawing || !onFencePoint) return;
      event.preventDefault();
      event.stopPropagation();
      const rect = event.currentTarget.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const nx = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const ny = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));

      const now = Date.now();
      if (lastClickRef.current) {
        const elapsed = now - lastClickRef.current.time;
        const dist = Math.hypot(nx - lastClickRef.current.x, ny - lastClickRef.current.y);
        if (elapsed < 250 || dist < 0.015) {
          return;
        }
      }
      lastClickRef.current = { time: now, x: nx, y: ny };
      lastPointPlacedTimeRef.current = now;
      onFencePoint([nx, ny]);
    },
    [fenceDrawing, onFencePoint],
  );
  const fencePointsStr = useMemo(
    () => fencePoints.map(([x, y]) => `${x * 100},${y * 100}`).join(" "),
    [fencePoints],
  );
  const inspectorStyle = useMemo(() => {
    if (!activeSelectedBox) return undefined;
    const top = `${Math.min(Math.max(activeSelectedBox.y * 100, 12), 55)}%`;
    if (activeSelectedBox.x * 100 > 55) {
      return {
        top,
        right: `${Math.min(Math.max(100 - activeSelectedBox.x * 100 + 2, 4), 60)}%`,
        maxWidth: "min(280px, calc(100% - 24px))",
      } as const;
    }
    return {
      top,
      left: `${Math.min(Math.max((activeSelectedBox.x + activeSelectedBox.w) * 100 + 2, 4), 60)}%`,
      maxWidth: "min(280px, calc(100% - 24px))",
    } as const;
  }, [activeSelectedBox]);

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
      {/* Refined Video Top Header */}
      <div className="absolute top-2.5 left-2.5 right-2.5 flex items-center justify-between text-xs text-white z-20 pointer-events-none">
        <div className="flex items-center gap-2 bg-black/70 border border-white/10 rounded-full px-3 py-1 backdrop-blur-md shadow-sm">
          <span className={`h-2 w-2 rounded-full shadow-[0_0_8px_rgba(52,211,153,0.8)] ${sourceUnavailable ? "bg-rose-400" : sourceReconnecting ? "bg-amber-400 animate-pulse" : "bg-emerald-400 animate-pulse"}`} />
          <span className="font-semibold text-white text-[11px] tracking-tight">{camera.name}</span>
          <span className="text-[10px] text-slate-300 font-mono font-medium">
            [{runtimeLabel}]
          </span>
        </div>

        <div className="flex items-center gap-2">
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
              className="pointer-events-auto flex items-center justify-center h-6 w-6 rounded-full bg-black/60 hover:bg-black/90 border border-white/15 text-white/80 hover:text-white transition-all text-[11px] cursor-pointer"
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
          onMouseMove={fenceMouseMove}
          onMouseLeave={handleFenceMouseLeave}
          onClick={handleFenceClick}
          style={renderedDimensions}
        >
          {!imgError ? (
            <img
              ref={imgRef}
              src={streamUrl}
              alt={camera.name}
              className="w-full h-full object-contain block select-none"
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

              {/* Dynamic preview line to cursor while drawing */}
              {fenceDrawing && hoverCoords && fencePoints.length >= 1 && (
                <>
                  <line
                    x1={fencePoints[fencePoints.length - 1][0] * 100}
                    y1={fencePoints[fencePoints.length - 1][1] * 100}
                    x2={hoverCoords[0] * 100}
                    y2={hoverCoords[1] * 100}
                    stroke="#facc15"
                    strokeWidth="0.8"
                    strokeDasharray="2 1.5"
                    vectorEffect="non-scaling-stroke"
                    opacity="0.85"
                  />
                  {fencePoints.length >= 2 && (
                    <line
                      x1={hoverCoords[0] * 100}
                      y1={hoverCoords[1] * 100}
                      x2={fencePoints[0][0] * 100}
                      y2={fencePoints[0][1] * 100}
                      stroke="#facc15"
                      strokeWidth="0.5"
                      strokeDasharray="1.5 2"
                      vectorEffect="non-scaling-stroke"
                      opacity="0.5"
                    />
                  )}
                </>
              )}

              {/* 1 Point: Beacon */}
              {fencePoints.length === 1 && (
                <g>
                  <circle
                    cx={fencePoints[0][0] * 100}
                    cy={fencePoints[0][1] * 100}
                    r="1.5"
                    fill="#facc15"
                    stroke="#ffffff"
                    strokeWidth="0.4"
                  />
                  <circle
                    cx={fencePoints[0][0] * 100}
                    cy={fencePoints[0][1] * 100}
                    r="3.2"
                    fill="none"
                    stroke="#facc15"
                    strokeWidth="0.4"
                    opacity="0.75"
                    className="animate-ping"
                  />
                </g>
              )}

              {/* 2 Points: Line Tripwire */}
              {fencePoints.length === 2 && (
                <g filter="url(#fence-line-glow)">
                  <line
                    x1={fencePoints[0][0] * 100}
                    y1={fencePoints[0][1] * 100}
                    x2={fencePoints[1][0] * 100}
                    y2={fencePoints[1][1] * 100}
                    stroke={fenceDrawing ? "#facc15" : "#a855f7"}
                    strokeWidth="1.2"
                    strokeDasharray={fenceDrawing ? "2 1" : undefined}
                    vectorEffect="non-scaling-stroke"
                  />
                  {/* Midpoint badge for tripwire line */}
                  <g>
                    <rect
                      x={(fencePoints[0][0] + fencePoints[1][0]) * 50 - 6}
                      y={(fencePoints[0][1] + fencePoints[1][1]) * 50 - 2}
                      width="12"
                      height="4"
                      fill="rgba(88, 28, 135, 0.92)"
                      stroke={fenceDrawing ? "#facc15" : "#a855f7"}
                      strokeWidth="0.4"
                      rx="0.8"
                    />
                    <text
                      x={(fencePoints[0][0] + fencePoints[1][0]) * 50}
                      y={(fencePoints[0][1] + fencePoints[1][1]) * 50 + 0.8}
                      fill="#f3e8ff"
                      fontSize="1.6"
                      fontWeight="bold"
                      textAnchor="middle"
                      fontFamily="ui-monospace, monospace"
                    >
                      TRIPWIRE LINE
                    </text>
                  </g>
                </g>
              )}

              {/* 3+ Points: Polygon Zone */}
              {fencePoints.length >= 3 && (
                <polygon
                  points={fencePointsStr}
                  fill={fenceDrawing ? "rgba(250, 204, 21, 0.12)" : "rgba(168, 85, 247, 0.12)"}
                  stroke={fenceDrawing ? "#facc15" : "#a855f7"}
                  strokeWidth="1.0"
                  strokeDasharray={fenceDrawing ? "2 1" : undefined}
                  vectorEffect="non-scaling-stroke"
                />
              )}

              {/* Interactive Numbered Vertex Handles in Drawing Mode */}
              {fenceDrawing && fencePoints.map(([x, y], index) => (
                <g
                  key={`vertex-${x}-${y}-${index}`}
                  className="cursor-pointer pointer-events-auto"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (Date.now() - lastPointPlacedTimeRef.current < 350) {
                      return;
                    }
                    onRemoveFencePoint?.(index);
                  }}
                >
                  <title>{`Click to remove Point ${index + 1}`}</title>
                  <circle
                    cx={x * 100}
                    cy={y * 100}
                    r="2.8"
                    fill="rgba(250, 204, 21, 0.25)"
                    stroke="#facc15"
                    strokeWidth="0.3"
                    className="hover:fill-rose-500/40 hover:stroke-rose-400 transition-colors"
                  />
                  <circle
                    cx={x * 100}
                    cy={y * 100}
                    r="1.4"
                    fill="#facc15"
                    stroke="#ffffff"
                    strokeWidth="0.4"
                  />
                  <circle
                    cx={x * 100}
                    cy={y * 100}
                    r="0.5"
                    fill="#000000"
                  />
                  <text
                    x={x * 100}
                    y={y * 100 - 2.8}
                    fill="#facc15"
                    fontSize="1.9"
                    fontWeight="bold"
                    textAnchor="middle"
                    fontFamily="ui-monospace, monospace"
                  >
                    {index + 1}
                  </text>
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

          {/* Quick Inspector Card */}
          {activeSelectedBox && (
            <div
              className="inspector-card absolute z-50 w-64 rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl shadow-2xl p-3.5 text-slate-900 dark:text-slate-100 modal-content-animate"
              style={inspectorStyle}
              onClick={handleStopInspectorPropagation}
            >
              <button
                onClick={handleCloseInspector}
                aria-label="Close"
                className="absolute top-2.5 right-2.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 h-6 w-6 rounded-full flex items-center justify-center hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs cursor-pointer"
                title="Close Inspector"
              >
                <CloseIcon className="w-3.5 h-3.5" />
              </button>

              <div className="flex items-center gap-3 mb-3">
                <div className="h-14 w-14 rounded-xl overflow-hidden bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 flex-shrink-0 flex items-center justify-center shadow-inner">
                  {targetThumb ? (
                    <img
                      src={targetThumb}
                      alt="Target crop"
                      className="h-full w-full object-cover"
                    />
                  ) : activeSelectedBox.label.toLowerCase() === "face" ? (
                    <FaceIcon className="w-6 h-6 text-slate-400 dark:text-slate-500" />
                  ) : (
                    <UserIcon className="w-6 h-6 text-slate-400 dark:text-slate-500" />
                  )}
                </div>
                <div className="min-w-0 flex-1 pr-4">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-xs font-bold uppercase tracking-tight text-slate-900 dark:text-slate-100">
                      {activeSelectedBox.targetName || activeSelectedBox.label.replace(/^(MATCH|SUSPECT|WATCHLIST|TARGET|CRITICAL):\s*/i, "").replace(/^\[|\]$/g, "")}
                    </span>
                    {activeSelectedBox.trackId && (
                      <span className="text-[10px] font-mono font-semibold bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-slate-600 dark:text-slate-300">
                        #{activeSelectedBox.trackId}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 font-medium">
                    Confidence:{" "}
                    <span className="font-semibold text-slate-700 dark:text-slate-200">
                      {activeSelectedBox.confidence
                        ? `${Math.round(activeSelectedBox.confidence * 100)}%`
                        : "--"}
                    </span>
                  </div>
                  {activeSelectedBox.isAlert && (
                    <span
                      data-testid={activeSelectedBox.isFenceIntrusion ? "roi-intruder-inspector-badge" : undefined}
                      className={`inline-block mt-1 text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider ${
                        activeSelectedBox.isFenceIntrusion
                          ? "text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-950/60 border-purple-200 dark:border-purple-900/50"
                          : "text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/60 border-rose-200 dark:border-rose-900/50"
                      }`}
                    >
                      {activeSelectedBox.isFenceIntrusion
                        ? "ROI Intruder"
                        : activeSelectedBox.isCritical
                        ? "Critical Target Match"
                        : "Watchlist Match"}
                    </span>
                  )}
                </div>
              </div>

              <button
                onClick={handlePutOnWatchlist}
                className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-slate-900 dark:bg-white text-white dark:text-slate-950 hover:bg-black dark:hover:bg-slate-100 active:scale-[0.98] text-xs font-semibold py-2 px-3 shadow-sm transition-all cursor-pointer"
              >
                <CrosshairIcon className="w-3.5 h-3.5" />
                <span>Put on Watchlist</span>
              </button>
            </div>
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

      <div className="absolute bottom-10 left-3 right-3 z-30 flex items-center gap-2 rounded-xl border border-white/10 bg-black/75 px-2.5 py-2 text-white backdrop-blur-md opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        {isFootage ? (
          <>
            <button type="button" onClick={() => void runTransport(playbackState === "playing" ? "pause" : "resume")} disabled={transportBusy} className="transport-button" aria-label={playbackState === "playing" ? "Pause footage" : "Play footage"}>
              {playbackState === "playing" ? "Pause" : "Play"}
            </button>
            <button type="button" onClick={() => void runTransport("restart")} disabled={transportBusy} className="transport-button" aria-label="Restart footage">Restart</button>
            <button type="button" onClick={() => void runTransport("stop")} disabled={transportBusy} className="transport-button transport-button-danger" aria-label="Stop footage">Stop</button>
          </>
        ) : (
          <>
            <button type="button" onClick={() => void handleReconnect()} className="transport-button" aria-label="Reconnect camera">Reconnect</button>
            <button type="button" onClick={() => void handleDisable()} className="transport-button transport-button-danger" aria-label="Stop camera">Stop</button>
          </>
        )}
      </div>
    </div>
  );
});
