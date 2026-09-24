import { memo, useState } from "react";
import { useTargetDossiers, type SubjectDossier } from "../lib/api";
import { CloseIcon, UserIcon } from "./Icons";

export interface TargetDossierModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const TargetDossierModal = memo(function TargetDossierModal({
  isOpen,
  onClose,
}: TargetDossierModalProps) {
  const { data: dossiers = [], isLoading } = useTargetDossiers(isOpen);
  const [selectedDossier, setSelectedDossier] = useState<SubjectDossier | null>(null);

  if (!isOpen) return null;

  const activeDossier = selectedDossier ?? dossiers[0] ?? null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md modal-backdrop-animate"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-5xl max-h-[90vh] rounded-3xl border border-white/10 bg-slate-950 p-6 shadow-2xl text-slate-100 flex flex-col gap-4 overflow-hidden modal-content-animate font-sans"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold uppercase tracking-wider text-slate-100 font-mono">
                Cross-Camera Target Handover & Dossiers
              </h2>
              <span className="text-[10px] font-mono bg-indigo-950/80 border border-indigo-500/40 px-2 py-0.5 rounded text-indigo-300">
                SPATIO-TEMPORAL RE-ID TRACKING
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              Correlated subject journeys and handover trajectories across multi-camera perimeters
            </p>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            title="Close Dossiers"
          >
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>

        {/* Content: Left Dossier List + Right Chronological Journey Timeline */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-5 flex-1 min-h-[350px] overflow-hidden">
          {/* Left Column: Dossier Index */}
          <div className="md:col-span-4 border-r border-white/10 pr-3 flex flex-col gap-2 overflow-y-auto">
            <span className="text-xs font-mono text-slate-400">
              TRACKED DOSSIERS ({dossiers.length})
            </span>

            {isLoading ? (
              <div className="text-xs text-slate-500 font-mono p-4">Scanning cameras...</div>
            ) : dossiers.length === 0 ? (
              <div className="text-xs text-slate-500 font-mono p-4 text-center border border-white/5 rounded-xl">
                No active cross-camera subject handovers detected.
              </div>
            ) : (
              dossiers.map((d) => {
                const isSelected = activeDossier?.dossier_id === d.dossier_id;
                const isCrit = d.threat_level === "CRITICAL";
                const isHigh = d.threat_level === "HIGH";

                return (
                  <div
                    key={d.dossier_id}
                    onClick={() => setSelectedDossier(d)}
                    className={`p-3 rounded-2xl border transition-all cursor-pointer font-mono text-xs ${
                      isSelected
                        ? "bg-indigo-950/60 border-indigo-500 text-white shadow-lg"
                        : "bg-slate-900/60 border-white/10 text-slate-300 hover:bg-slate-800/60"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-100">{d.label}</span>
                      <span
                        className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
                          isCrit
                            ? "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                            : isHigh
                            ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                            : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {d.threat_level}
                      </span>
                    </div>

                    <div className="text-[11px] text-slate-400 mt-1 flex items-center justify-between">
                      <span>ID: {d.dossier_id}</span>
                      <span>{d.cameras_visited.length} {d.cameras_visited.length === 1 ? "Camera" : "Cameras"}</span>
                    </div>

                    {d.plate && (
                      <div className="mt-1 text-[10px] text-indigo-300 bg-indigo-950/40 border border-indigo-500/30 rounded px-1.5 py-0.5">
                        PLATE: {d.plate}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Right Column: Selected Subject Dossier & Cross-Camera Timeline */}
          <div className="md:col-span-8 flex flex-col gap-4 overflow-y-auto pl-2">
            {activeDossier ? (
              <>
                {/* Subject Overview Card */}
                <div className="bg-slate-900 border border-white/10 rounded-2xl p-4 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-slate-800 border border-white/10 flex items-center justify-center text-slate-400">
                      <UserIcon className="w-6 h-6" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-sm text-slate-100">
                          {activeDossier.label}
                        </span>
                        <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                          {activeDossier.dossier_id}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 font-mono mt-0.5">
                        Class: {activeDossier.subject_type.toUpperCase()} • Cameras Visited:{" "}
                        {activeDossier.cameras_visited.join(" → ")}
                      </div>
                    </div>
                  </div>

                  <span
                    className={`px-2.5 py-1 rounded-full font-mono text-xs font-bold border uppercase ${
                      activeDossier.threat_level === "CRITICAL"
                        ? "bg-rose-950/60 border-rose-500 text-rose-300"
                        : "bg-slate-800 border-white/20 text-slate-300"
                    }`}
                  >
                    THREAT: {activeDossier.threat_level}
                  </span>
                </div>

                {/* Chronological Sighting & Handover Timeline */}
                <div>
                  <h3 className="text-xs font-mono font-bold text-slate-300 uppercase tracking-wider mb-3">
                    CHRONOLOGICAL SIGHTING & HANDOVER TIMELINE
                  </h3>

                  <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-indigo-500/30">
                    {activeDossier.sightings.map((s, idx) => {
                      const dt = new Date(s.timestamp * 1000);
                      const timeStr = dt.toLocaleTimeString();

                      return (
                        <div key={idx} className="relative font-mono text-xs">
                          {/* Timeline node marker */}
                          <div
                            className={`absolute -left-[21px] top-1 w-3 h-3 rounded-full border-2 border-slate-950 ${
                              s.is_intrusion ? "bg-rose-500 animate-ping" : "bg-indigo-500"
                            }`}
                          />
                          <div
                            className={`absolute -left-[21px] top-1 w-3 h-3 rounded-full border-2 border-slate-950 ${
                              s.is_intrusion ? "bg-rose-500" : "bg-indigo-500"
                            }`}
                          />

                          <div className="bg-slate-900/80 border border-white/10 rounded-xl p-3">
                            <div className="flex items-center justify-between">
                              <span className="font-bold text-slate-100">
                                Sighted at [{s.camera_name}]
                              </span>
                              <span className="text-[10px] text-slate-400">{timeStr}</span>
                            </div>

                            <div className="text-[11px] text-slate-400 mt-1 flex items-center gap-3">
                              <span>Track #{s.track_id ?? "--"}</span>
                              <span>Confidence: {Math.round(s.confidence * 100)}%</span>
                              {s.plate && <span className="text-indigo-300">Plate: {s.plate}</span>}
                            </div>

                            {s.is_intrusion && (
                              <div className="mt-2 text-[10px] font-bold text-rose-400 bg-rose-950/60 border border-rose-500/30 rounded px-2 py-0.5">
                                PERIMETER BREACH RECORDED AT THIS SENSOR
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500 font-mono text-xs">
                Select a dossier from the left to view cross-camera trajectory.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});
