import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { OverlayCanvas, type Box, type OverlayPreset } from "./OverlayCanvas";
import { TileHealth } from "./TileHealth";
import { fetchCameraObservations, type Camera } from "../lib/api";

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

    // Silhouette icon
    ctx.font = "40px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(isFace ? "◎" : "👤", size / 2, size * 0.42);

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

export function CameraTile({
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
}) {
  const [imgError, setImgError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [selectedBox, setSelectedBox] = useState<Box | null>(null);
  const [targetThumb, setTargetThumb] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    if (!imgError) return;
    const timer = setInterval(() => {
      setImgError(false);
      setRetryKey((k) => k + 1);
    }, 2500);
    return () => clearInterval(timer);
  }, [imgError]);

  const streamUrl = `/api/v1/cameras/${camera.id}/stream?epoch=${camera.stream_epoch}&k=${retryKey}`;
  const { data: observations } = useQuery({
    queryKey: ["camera-observations", camera.id],
    queryFn: () => fetchCameraObservations(camera.id),
    refetchInterval: 80,
  });

  const boxes: Box[] = (observations?.tracks ?? observations?.detections ?? [])
    .filter((item) => {
      const isIdentified = "identity" in item && Boolean((item as any).identity?.name);
      return isIdentified || item.confidence >= 0.45;
    })
    .map((item) => {
      const [x1, y1, x2, y2] = item.bbox_norm;
      const width = x2 - x1;
      const tightened = item.class_name === "person" ? width * 0.88 : width;
      const trackItem =
        "track_id" in item
          ? (item as unknown as {
              identity?: {
                name: string;
                score: number;
                tier: string;
                threat_level?: string;
                locked?: boolean;
              };
              identity_locked?: boolean;
            })
          : null;
      const identity = trackItem?.identity;
      const isWatchlistMatch = Boolean(identity && identity.name);
      const threatLevel = identity?.threat_level?.toUpperCase();
      const isCritical = threatLevel === "CRITICAL" || identity?.tier === "RED";
      const targetName = identity?.name;

      // Clearly display target's name with alert/priority styling
      const displayLabel = isWatchlistMatch
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
            ? String((item as unknown as { track_id: number }).track_id)
            : undefined,
        isAlert: isWatchlistMatch,
        targetName: targetName,
        threatLevel: threatLevel,
        isCritical: isCritical,
      };
    })
    .filter(
      (item) =>
        item.label &&
        (item.isAlert ||
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

  // Show faces in operational/all modes with quiet, elegant champagne markers
  const minFaceConf = 0.35;
  const isMinimal = preset === "clean" || mode === "minimal";
  const faceBoxes: Box[] = !isMinimal
    ? (observations?.faces ?? [])
        .filter((face) => (face.confidence ?? 0) >= minFaceConf)
        .map((face) => {
          const [x1, y1, x2, y2] = face.bbox_norm;
          return {
            x: x1,
            y: y1,
            w: x2 - x1,
            h: y2 - y1,
            label: "face",
            confidence: face.confidence,
            isAlert: false,
          };
        })
        .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    : [];

  // Priority-aware deduplication: alerts and critical targets always win over non-alerts
  const deduped: Box[] = [];
  for (const box of [...boxes, ...faceBoxes]) {
    const overlapIndex = deduped.findIndex((existing) => {
      if (existing.label === "face" && box.label !== "face") return false;
      if (existing.label !== "face" && box.label === "face") return false;
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
      const area = Math.min(existing.w * existing.h, box.w * box.h);
      return area > 0 && overlapArea / area > 0.65;
    });

    if (overlapIndex === -1) {
      deduped.push(box);
    } else {
      const existing = deduped[overlapIndex];
      // Critical targets and security alerts must never be suppressed by non-alerts
      if ((box.isAlert || box.isCritical) && (!existing.isAlert && !existing.isCritical)) {
        deduped[overlapIndex] = box;
      }
    }
  }

  const allBoxes = deduped.slice(0, 32);
  const targetCount = allBoxes.length;

  // Active selected box dynamically follows moving target if trackId matches
  const activeSelectedBox = selectedBox?.trackId
    ? allBoxes.find((b) => b.trackId === selectedBox.trackId) || selectedBox
    : selectedBox;

  const cropTarget = (box: Box): string => {
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
  };

  const handleSelectBox = (box: Box) => {
    setSelectedBox(box);
    const thumb = cropTarget(box);
    setTargetThumb(thumb);
  };

  const handlePutOnWatchlist = () => {
    if (!activeSelectedBox) return;
    const thumb = targetThumb || createFallbackThumb(activeSelectedBox);
    onInspectTarget?.({
      trackId: activeSelectedBox.trackId,
      label: activeSelectedBox.label,
      confidence: activeSelectedBox.confidence,
      thumbnail: thumb,
    });
    setSelectedBox(null);
  };

  return (
    <div
      data-testid={`live-player-${camera.id}`}
      className={`tile group relative select-none transition-all duration-300 ${
        isSolo ? "ring-2 ring-slate-400 dark:ring-slate-300 shadow-2xl scale-[1.002]" : ""
      }`}
      tabIndex={0}
      onClick={() => {
        if (selectedBox) setSelectedBox(null);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSolo?.();
        if (e.key === "Escape") setSelectedBox(null);
      }}
    >
      {/* Refined Video Top Header */}
      <div className="absolute top-2.5 left-2.5 right-2.5 flex items-center justify-between text-xs text-white z-20 pointer-events-none">
        <div className="flex items-center gap-2 bg-black/70 border border-white/10 rounded-full px-3 py-1 backdrop-blur-md shadow-sm">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
          <span className="font-semibold text-white text-[11px] tracking-tight">{camera.name}</span>
          <span className="text-[10px] text-slate-300 font-mono font-medium">
            [{observations?.runtime?.toUpperCase() || "DIRECTML"}]
          </span>
        </div>

        <div className="flex items-center gap-2">
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
              onClick={(e) => {
                e.stopPropagation();
                onSolo();
              }}
              className="pointer-events-auto flex items-center justify-center h-6 w-6 rounded-full bg-black/60 hover:bg-black/90 border border-white/15 text-white/80 hover:text-white transition-all text-[11px] cursor-pointer"
              title={isSolo ? "Exit Theater Solo Mode" : "Expand to Theater Solo Mode"}
              aria-label={isSolo ? "Exit Theater Solo Mode" : "Expand to Theater Solo Mode"}
            >
              {isSolo ? "⤡" : "⤢"}
            </button>
          )}
        </div>
      </div>

      {/* Video Surface & Overlays */}
      <div className="w-full h-full grid place-items-center bg-black relative overflow-hidden">
        {!imgError ? (
          <img
            ref={imgRef}
            src={streamUrl}
            alt={camera.name}
            crossOrigin="anonymous"
            className="w-full h-full object-contain"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="text-white text-xs p-6 text-center max-w-sm">
            <div className="font-semibold text-slate-200">Video Signal Searching</div>
            <div className="mt-1 text-slate-400 text-[11px]">
              Waiting for stream at {camera.endpoint || "configured endpoint"}
            </div>
            <div className="mt-3 text-[11px] text-amber-300/90 bg-amber-950/40 border border-amber-800/50 rounded-lg p-2.5">
              Ensure device is on the same network and stream is active.
            </div>
          </div>
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
            className="inspector-card absolute z-50 w-64 rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white/95 dark:bg-[#131720]/95 backdrop-blur-xl shadow-2xl p-3.5 text-slate-900 dark:text-slate-100 modal-content-animate"
            style={{
              top: `${Math.min(Math.max(activeSelectedBox.y * 100, 12), 55)}%`,
              left:
                activeSelectedBox.x * 100 > 55
                  ? undefined
                  : `${Math.min(
                      Math.max((activeSelectedBox.x + activeSelectedBox.w) * 100 + 2, 4),
                      60
                    )}%`,
              right:
                activeSelectedBox.x * 100 > 55
                  ? `${Math.min(Math.max(100 - activeSelectedBox.x * 100 + 2, 4), 60)}%`
                  : undefined,
              maxWidth: "min(280px, calc(100% - 24px))",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setSelectedBox(null)}
              className="absolute top-2.5 right-2.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 h-6 w-6 rounded-full flex items-center justify-center hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs cursor-pointer"
              title="Close Inspector"
            >
              ✕
            </button>

            <div className="flex items-center gap-3 mb-3">
              <div className="h-14 w-14 rounded-xl overflow-hidden bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 flex-shrink-0 flex items-center justify-center shadow-inner">
                {targetThumb ? (
                  <img
                    src={targetThumb}
                    alt="Target crop"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <span className="text-2xl">
                    {activeSelectedBox.label.toLowerCase() === "face" ? "◎" : "👤"}
                  </span>
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
                  <span className="inline-block mt-1 text-[9px] font-bold text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/60 px-1.5 py-0.5 rounded border border-rose-200 dark:border-rose-900/50 uppercase tracking-wider">
                    {activeSelectedBox.isCritical ? "Critical Target Match" : "Watchlist Match"}
                  </span>
                )}
              </div>
            </div>

            <button
              onClick={handlePutOnWatchlist}
              className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-slate-900 dark:bg-white text-white dark:text-slate-950 hover:bg-black dark:hover:bg-slate-100 active:scale-[0.98] text-xs font-semibold py-2 px-3 shadow-sm transition-all cursor-pointer"
            >
              <span>🎯</span>
              <span>Put on Watchlist</span>
            </button>
          </div>
        )}
      </div>

      {/* Refined Bottom Bar */}
      <div className="absolute bottom-2.5 left-2.5 right-2.5 flex items-center justify-between gap-2 pointer-events-none z-20">
        <TileHealth id={camera.id} />
        <span className="text-[10px] text-slate-300 font-mono bg-black/70 border border-white/10 rounded-full px-2.5 py-0.5 hidden sm:inline backdrop-blur-md">
          MONITORING ACTIVE
        </span>
      </div>
    </div>
  );
}
