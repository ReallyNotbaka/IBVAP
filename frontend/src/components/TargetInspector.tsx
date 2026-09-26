import { memo, useState } from "react";
import type { CSSProperties } from "react";
import type { Box } from "./OverlayCanvas";
import {
  CheckIcon,
  CloseIcon,
  CopyIcon,
  CrosshairIcon,
  FaceIcon,
  LicensePlateIcon,
  UserIcon,
} from "./Icons";

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
  const [copied, setCopied] = useState(false);
  const isFace = box.label.toLowerCase() === "face";
  const isPlate = Boolean(box.isPlate || box.label.startsWith("NUMBER PLATE"));

  // Extract number plate text if available:
  // e.g. box.plateText = "KA01AB1234"
  // or "NUMBER PLATE: KA01AB1234" -> "KA01AB1234"
  // or "CAR [KA01AB1234]" -> "KA01AB1234"
  // or direct label "KA01AB1234" when isPlate is true
  let plateText: string | null = box.plateText || null;
  if (!plateText) {
    if (isPlate) {
      const m = box.label.match(/NUMBER PLATE:\s*([^\s]+)/i);
      if (m) {
        plateText = m[1];
      } else if (box.label && box.label.toUpperCase() !== "NUMBER PLATE") {
        plateText = box.label;
      }
    } else {
      const m = box.label.match(/\[([A-Z0-9]+)\]/i);
      if (m) plateText = m[1];
    }
  }

  const displayLabel = box.vehicleClass
    ? `${box.vehicleClass.toUpperCase()} (ANPR)`
    : isPlate
    ? "NUMBER PLATE"
    : box.targetName ||
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
          ) : isPlate ? (
            <LicensePlateIcon className="w-7 h-7 text-amber-500 dark:text-amber-400" />
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
          {isPlate ? (
            <div className="mt-1">
              {plateText ? (
                <div className="text-xs font-mono font-bold tracking-widest text-amber-700 dark:text-amber-300 bg-amber-100/80 dark:bg-amber-950/60 border border-amber-300 dark:border-amber-700/60 rounded px-2 py-0.5 inline-block">
                  {plateText}
                </div>
              ) : (
                <div className="text-[11px] font-mono text-slate-500 italic">
                  Detecting...
                </div>
              )}
            </div>
          ) : plateText ? (
            <div className="mt-1">
              <span className="text-[10px] font-mono font-semibold text-amber-700 dark:text-amber-300 bg-amber-100/80 dark:bg-amber-950/60 border border-amber-300 dark:border-amber-700/60 rounded px-1.5 py-0.5">
                NUMBER PLATE: {plateText}
              </span>
            </div>
          ) : null}
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

      {isPlate || (box.vehicleClass && plateText) ? (
        <div className="space-y-1.5">
          <button
            onClick={() => {
              if (!plateText) return;
              navigator.clipboard.writeText(plateText);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
            disabled={!plateText}
            className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 active:scale-[0.98] text-xs font-semibold py-1.5 px-3 shadow-xs transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            title={plateText ? `Copy ${plateText}` : "Detecting plate..."}
          >
            {copied ? (
              <>
                <CheckIcon className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                <span>Plate Copied!</span>
              </>
            ) : (
              <>
                <CopyIcon className="w-3.5 h-3.5" />
                <span>Copy License Plate</span>
              </>
            )}
          </button>
          <button
            onClick={onPutOnWatchlist}
            className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-amber-600 hover:bg-amber-700 text-white active:scale-[0.98] text-xs font-semibold py-1.5 px-3 shadow-sm transition-all cursor-pointer"
          >
            <CrosshairIcon className="w-3.5 h-3.5" />
            <span>Add Plate to Watchlist</span>
          </button>
        </div>
      ) : (
        <button
          onClick={onPutOnWatchlist}
          className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-slate-900 dark:bg-white text-white dark:text-slate-950 hover:bg-black dark:hover:bg-slate-100 active:scale-[0.98] text-xs font-semibold py-2 px-3 shadow-sm transition-all cursor-pointer"
        >
          <CrosshairIcon className="w-3.5 h-3.5" />
          <span>Put on Watchlist</span>
        </button>
      )}
    </div>
  );
});

