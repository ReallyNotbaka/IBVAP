import { memo, useCallback, useState } from "react";
import { useMilitarySitrep } from "../lib/api";
import { CloseIcon } from "./Icons";

export interface MilitarySitrepModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const MilitarySitrepModal = memo(function MilitarySitrepModal({
  isOpen,
  onClose,
}: MilitarySitrepModalProps) {
  const { data: sitrep, isLoading, refetch, isFetching } = useMilitarySitrep(isOpen);
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    if (!sitrep?.formatted_text) return;
    navigator.clipboard.writeText(sitrep.formatted_text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [sitrep?.formatted_text]);

  const handleDownload = useCallback(() => {
    if (!sitrep?.formatted_text) return;
    const blob = new Blob([sitrep.formatted_text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `SITREP_${sitrep.dtg.replace(/\s+/g, "_")}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [sitrep]);

  if (!isOpen) return null;

  const threatColor =
    sitrep?.threat_posture === "RED"
      ? "text-rose-400 border-rose-500/50 bg-rose-950/50"
      : sitrep?.threat_posture === "AMBER"
      ? "text-amber-400 border-amber-500/50 bg-amber-950/50"
      : "text-emerald-400 border-emerald-500/50 bg-emerald-950/50";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md modal-backdrop-animate"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-4xl max-h-[90vh] rounded-3xl border border-slate-700 bg-slate-950 p-6 shadow-2xl text-slate-100 flex flex-col gap-4 overflow-hidden modal-content-animate font-sans"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold uppercase tracking-wider text-slate-100 font-mono">
                MILITARY SITUATION REPORT (SITREP)
              </h2>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded border font-bold ${threatColor}`}>
                POSTURE: {sitrep?.threat_posture || "ASSESSING"}
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              STANAG Automated Incident Intelligence • DTG: {sitrep?.dtg || "--"}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => void refetch()}
              disabled={isFetching}
              className="px-3 py-1.5 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs font-mono transition-all cursor-pointer"
            >
              {isFetching ? "Generating..." : "Regenerate"}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
              title="Close SITREP"
            >
              <CloseIcon className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Telemetry Summary Cards */}
        {sitrep && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono">
            <div className="bg-slate-900/80 border border-white/10 rounded-2xl p-3">
              <span className="text-[10px] text-slate-400 uppercase">Active Targets</span>
              <div className="text-lg font-bold text-slate-100 mt-0.5">{sitrep.total_active_tracks}</div>
            </div>
            <div className="bg-slate-900/80 border border-white/10 rounded-2xl p-3">
              <span className="text-[10px] text-rose-400 uppercase">Breaches / Incursions</span>
              <div className="text-lg font-bold text-rose-400 mt-0.5">{sitrep.critical_breaches}</div>
            </div>
            <div className="bg-slate-900/80 border border-white/10 rounded-2xl p-3">
              <span className="text-[10px] text-amber-400 uppercase">Watchlist Matches</span>
              <div className="text-lg font-bold text-amber-400 mt-0.5">{sitrep.watchlist_hits}</div>
            </div>
            <div className="bg-slate-900/80 border border-white/10 rounded-2xl p-3">
              <span className="text-[10px] text-indigo-400 uppercase">Vehicles Tracked</span>
              <div className="text-lg font-bold text-indigo-400 mt-0.5">{sitrep.vehicles_tracked}</div>
            </div>
          </div>
        )}

        {/* Formatted Report Body (Monospace Military Paper View) */}
        <div className="flex-1 min-h-[250px] overflow-y-auto rounded-2xl bg-slate-900/90 border border-white/10 p-4 font-mono text-xs text-emerald-300/90 leading-relaxed select-text shadow-inner">
          {isLoading ? (
            <div className="flex items-center justify-center h-full text-slate-400">
              Aggregating sector sensor feeds and synthesizing military SITREP...
            </div>
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-[11px] sm:text-xs">
              {sitrep?.formatted_text}
            </pre>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between pt-2 border-t border-white/10">
          <span className="text-[11px] font-mono text-slate-400">
            STATION: {sitrep?.unit_station}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-100 text-xs font-semibold font-mono transition-all cursor-pointer flex items-center gap-1.5"
            >
              {copied ? "✓ Copied to Clipboard" : "Copy SITREP (STANAG)"}
            </button>
            <button
              onClick={handleDownload}
              className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold text-xs font-mono transition-all cursor-pointer shadow-lg"
            >
              Download Report (.txt)
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});
