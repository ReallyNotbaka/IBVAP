import { memo } from "react";
import type { CSSProperties } from "react";
import type { Box } from "./OverlayCanvas";
import { CloseIcon, CrosshairIcon, FaceIcon, UserIcon } from "./Icons";

export interface TargetInspectorProps {
  box: Box;
  thumbnail?: string | null;
  style?: CSSProperties;
  onClose: () => void;
  onPutOnWatchlist: () => void;
}

export const TargetInspector = memo(function TargetInspector({
  box,
  thumbnail,
  style,
  onClose,
  onPutOnWatchlist,
}: TargetInspectorProps) {
  const isFace = box.label.toLowerCase() === "face";
  const displayLabel =
    box.targetName ||
    box.label
      .replace(/^(MATCH|SUSPECT|WATCHLIST|TARGET|CRITICAL):\s*/i, "")
      .replace(/^\[|\]$/g, "");

  return (
    <div
      className="inspector-card absolute z-50 w-64 rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl shadow-2xl p-3.5 text-slate-900 dark:text-slate-100 modal-content-animate"
      style={style}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        onClick={onClose}
        aria-label="Close"
        className="absolute top-2.5 right-2.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 h-6 w-6 rounded-full flex items-center justify-center hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs cursor-pointer"
        title="Close Inspector"
      >
        <CloseIcon className="w-3.5 h-3.5" />
      </button>

      <div className="flex items-center gap-3 mb-3">
        <div className="h-14 w-14 rounded-xl overflow-hidden bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 flex-shrink-0 flex items-center justify-center shadow-inner">
          {thumbnail ? (
            <img src={thumbnail} alt="Target crop" className="h-full w-full object-cover" />
          ) : isFace ? (
            <FaceIcon className="w-6 h-6 text-slate-400 dark:text-slate-500" />
          ) : (
            <UserIcon className="w-6 h-6 text-slate-400 dark:text-slate-500" />
          )}
        </div>
        <div className="min-w-0 flex-1 pr-4">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-bold uppercase tracking-tight text-slate-900 dark:text-slate-100">
              {displayLabel}
            </span>
            {box.trackId && (
              <span className="text-[10px] font-mono font-semibold bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-slate-600 dark:text-slate-300">
                #{box.trackId}
              </span>
            )}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 font-medium">
            Confidence:{" "}
            <span className="font-semibold text-slate-700 dark:text-slate-200">
              {box.confidence ? `${Math.round(box.confidence * 100)}%` : "--"}
            </span>
          </div>
          {box.isAlert && (
            <span
              data-testid={box.isFenceIntrusion ? "roi-intruder-inspector-badge" : undefined}
              className={`inline-block mt-1 text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider ${
                box.isFenceIntrusion
                  ? "text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-950/60 border-purple-200 dark:border-purple-900/50"
                  : box.isCritical
                  ? "text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/60 border-rose-200 dark:border-rose-900/50"
                  : "text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/60 border-rose-200 dark:border-rose-900/50"
              }`}
            >
              {box.isFenceIntrusion
                ? "ROI Intruder"
                : box.isCritical
                ? "Critical Target Match"
                : "Watchlist Match"}
            </span>
          )}
        </div>
      </div>

      <button
        onClick={onPutOnWatchlist}
        className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-slate-900 dark:bg-white text-white dark:text-slate-950 hover:bg-black dark:hover:bg-slate-100 active:scale-[0.98] text-xs font-semibold py-2 px-3 shadow-sm transition-all cursor-pointer"
      >
        <CrosshairIcon className="w-3.5 h-3.5" />
        <span>Put on Watchlist</span>
      </button>
    </div>
  );
});
