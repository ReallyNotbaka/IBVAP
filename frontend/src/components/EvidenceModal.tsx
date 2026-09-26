import { memo, useState } from "react";
import { type EventItem, base } from "../lib/api";
import { CloseIcon, DownloadIcon, CrosshairIcon, VideoIcon, UserIcon } from "./Icons";
import type { TargetInspectData } from "./CameraTile";

export interface EvidenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  event: EventItem | null;
  cameraName?: string;
  onInspectTarget?: (data: TargetInspectData) => void;
}

export const EvidenceModal = memo(function EvidenceModal({
  isOpen,
  onClose,
  event,
  cameraName,
  onInspectTarget,
}: EvidenceModalProps) {
  const [activeView, setActiveView] = useState<"crop" | "snapshot">("crop");
  const [imgError, setImgError] = useState(false);

  if (!isOpen || !event) return null;

  const isCritical =
    event.event_type.includes("watchlist") ||
    event.explanation?.threat_level === "CRITICAL" ||
    event.explanation?.tier === "RED";
  const isIntrusion = event.event_type.includes("intrusion") || event.event_type.includes("crossing");

  const snapshotSrc = event.snapshot_url ? base(event.snapshot_url) : null;
  const cropSrc = event.crop_url ? base(event.crop_url) : null;
  const currentImage = activeView === "crop" && cropSrc ? cropSrc : snapshotSrc;

  const dtgTime = event.created_at
    ? new Date(event.created_at * 1000).toLocaleString()
    : "Recent Incident";

  const handleEnrollTarget = () => {
    if (!onInspectTarget) return;
    const plate = event.explanation?.plate;
    const suspectName = event.explanation?.suspect_name;
    if (plate) {
      onInspectTarget({
        label: `Vehicle [${plate}]`,
        confidence: event.confidence,
        thumbnail: cropSrc || snapshotSrc,
        targetType: "plate",
        plateNumber: plate,
        vehicleClass: "car",
      });
    } else {
      onInspectTarget({
        label: suspectName || `Suspect Track #${event.track_id || ""}`,
        confidence: event.confidence,
        thumbnail: cropSrc || snapshotSrc,
        targetType: "face",
      });
    }
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md modal-backdrop-animate"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-4xl max-h-[92vh] rounded-3xl border border-white/10 bg-slate-950 p-6 shadow-2xl text-slate-100 flex flex-col gap-4 overflow-hidden modal-content-animate font-sans"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-base font-bold uppercase tracking-wider text-slate-100 font-mono flex items-center gap-2">
                <CrosshairIcon className="w-5 h-5 text-rose-500" />
                Incident Evidence Dossier
              </span>
              <span
                className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold uppercase ${
                  isCritical
                    ? "bg-rose-950/80 border border-rose-500/40 text-rose-300"
                    : isIntrusion
                    ? "bg-red-950/80 border border-red-500/40 text-red-300"
                    : "bg-indigo-950/80 border border-indigo-500/40 text-indigo-300"
                }`}
              >
                {event.event_type.replace(/_/g, " ")}
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">
              Event ID: <span className="text-slate-200">{event.id}</span> • {dtgTime}
            </p>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            title="Close Dossier"
          >
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>

        {/* View Switcher Tabs */}
        {(cropSrc || snapshotSrc) && (
          <div className="flex items-center justify-between border-b border-white/5 pb-2">
            <div className="flex items-center gap-2">
              {cropSrc && (
                <button
                  onClick={() => setActiveView("crop")}
                  className={`px-3 py-1 rounded-lg text-xs font-mono font-semibold transition-all cursor-pointer ${
                    activeView === "crop"
                      ? "bg-slate-800 text-white border border-white/20 shadow-xs"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Target Focal Crop
                </button>
              )}
              {snapshotSrc && (
                <button
                  onClick={() => setActiveView("snapshot")}
                  className={`px-3 py-1 rounded-lg text-xs font-mono font-semibold transition-all cursor-pointer ${
                    activeView === "snapshot"
                      ? "bg-slate-800 text-white border border-white/20 shadow-xs"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Full Frame Snapshot
                </button>
              )}
            </div>

            {currentImage && (
              <a
                href={currentImage}
                download={`evidence_${event.id}_${activeView}.jpg`}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 hover:text-white text-xs font-mono transition-colors"
                title="Download high-resolution forensic image"
              >
                <DownloadIcon className="w-3.5 h-3.5" />
                <span>Save JPEG</span>
              </a>
            )}
          </div>
        )}

        {/* Visual Evidence Viewport */}
        <div className="relative flex-1 min-h-[280px] max-h-[460px] bg-black/60 rounded-2xl border border-white/5 overflow-hidden flex items-center justify-center">
          {currentImage && !imgError ? (
            <div className="relative w-full h-full flex items-center justify-center p-2">
              <img
                src={currentImage}
                alt="Tactical incident evidence"
                onError={() => setImgError(true)}
                className="max-h-[440px] max-w-full rounded-xl object-contain shadow-lg"
              />
              <div className="absolute bottom-4 left-4 bg-black/80 backdrop-blur-md px-3 py-1 rounded-md text-[11px] font-mono text-slate-300 border border-white/10 pointer-events-none">
                {cameraName || `Camera ${event.camera_id.slice(0, 8)}`} • {activeView.toUpperCase()}
              </div>
            </div>
          ) : (
            <div className="text-center p-8 space-y-2">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 border border-white/10 text-slate-500">
                <CrosshairIcon className="w-6 h-6 animate-pulse" />
              </div>
              <p className="text-sm font-mono text-slate-300">
                {imgError ? "Evidence image expired or unreachable" : "Generating real-time forensic snapshot..."}
              </p>
              <p className="text-xs text-slate-500 font-mono">
                Event logged at epoch {Math.round(event.created_at || Date.now() / 1000)}
              </p>
            </div>
          )}
        </div>

        {/* Forensic Metadata Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white/[0.02] border border-white/5 p-3 rounded-2xl">
          <div className="space-y-0.5">
            <span className="text-[10px] font-mono text-slate-400">CAMERA SOURCE</span>
            <div className="text-xs font-mono font-bold text-slate-200 truncate flex items-center gap-1.5">
              <VideoIcon className="w-3.5 h-3.5 text-slate-400" />
              {cameraName || event.camera_id.slice(0, 12)}
            </div>
          </div>

          <div className="space-y-0.5">
            <span className="text-[10px] font-mono text-slate-400">TRACK / TARGET</span>
            <div className="text-xs font-mono font-bold text-slate-200">
              {event.track_id !== undefined ? `Track #${event.track_id}` : "Perimeter Sector"}
            </div>
          </div>

          <div className="space-y-0.5">
            <span className="text-[10px] font-mono text-slate-400">MODEL CONFIDENCE</span>
            <div className="text-xs font-mono font-bold text-emerald-400">
              {event.confidence ? `${Math.round(event.confidence * 100)}%` : "Confirmed Rule"}
            </div>
          </div>

          <div className="space-y-0.5">
            <span className="text-[10px] font-mono text-slate-400">DETECTION ENGINE</span>
            <div className="text-xs font-mono font-bold text-indigo-300 truncate">
              {event.model_id || "YOLO26 + YuNet"}
            </div>
          </div>
        </div>

        {/* Description / Explanation Banner */}
        {event.explanation && (
          <div className="rounded-xl border border-white/5 bg-white/[0.03] p-3 text-xs font-mono text-slate-300">
            {event.explanation.suspect_name ? (
              <span className="text-rose-400 font-bold block mb-1">
                TARGET IDENTIFIED: [{event.explanation.suspect_name}] (Threat Tier:{" "}
                {event.explanation.threat_level || event.explanation.tier || "CRITICAL"})
              </span>
            ) : null}
            <span>{event.explanation.observed || event.explanation.rule || "Perimeter event observed"}</span>
            {event.zone_id && <span className="text-slate-500"> • Zone: {event.zone_id}</span>}
          </div>
        )}

        {/* Footer Actions */}
        <div className="flex items-center justify-between border-t border-white/10 pt-4">
          {onInspectTarget ? (
            <button
              onClick={handleEnrollTarget}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-xs font-semibold text-indigo-200 transition-colors cursor-pointer"
            >
              <UserIcon className="w-3.5 h-3.5" />
              <span>Enroll Target in Watchlist</span>
            </button>
          ) : (
            <div />
          )}

          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-xs font-semibold text-white transition-colors cursor-pointer"
          >
            Close Dossier
          </button>
        </div>
      </div>
    </div>
  );
});
