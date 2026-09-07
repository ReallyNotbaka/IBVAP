import { useState } from "react";
import { CpuIcon, CrosshairIcon, CameraIcon, VideoIcon } from "../components/Icons";

export function EmptyState({
  onConnect,
}: {
  onConnect?: () => void;
}) {
  const [otherOpen, setOtherOpen] = useState(false);

  return (
    <div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-8rem)] py-8 px-4 w-full">
      <div className="w-full max-w-xl rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white dark:bg-slate-900/95 backdrop-blur-xl p-8 shadow-xl transition-all">
        <h1 className="text-[22px] font-bold tracking-tight text-slate-900 dark:text-slate-100">
          Connect your first source
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Connect an RTSP or IP camera, or analyze video footage directly.
        </p>

        {/* Feature Highlights with sleek icons */}
        <div className="mt-6 grid grid-cols-2 gap-3">
          <div className="flex items-center gap-2.5 rounded-xl border border-slate-200/70 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/60 p-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-200/80 dark:bg-slate-800 text-slate-700 dark:text-slate-300 flex-shrink-0">
              <CpuIcon className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">Detection</div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">YOLO26</div>
            </div>
          </div>

          <div className="flex items-center gap-2.5 rounded-xl border border-slate-200/70 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/60 p-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 flex-shrink-0">
              <CrosshairIcon className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">Watchlist</div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">Target matching</div>
            </div>
          </div>
        </div>

        {/* Prominent actions */}
        <div className="mt-6 grid gap-3">
          {onConnect ? (
            <button
              type="button"
              onClick={onConnect}
              data-testid="cta-connect-phone"
              className="inline-flex h-12 items-center justify-center gap-2.5 rounded-xl bg-slate-900 hover:bg-black text-white dark:bg-white dark:hover:bg-slate-100 dark:text-slate-950 px-6 text-sm font-semibold shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 cursor-pointer"
            >
              <CameraIcon className="w-4 h-4" />
              <span>Connect CCTV / IP camera</span>
            </button>
          ) : (
            <a
              href="/connect/phone"
              data-testid="cta-connect-phone"
              className="inline-flex h-12 items-center justify-center gap-2.5 rounded-xl bg-slate-900 hover:bg-black text-white dark:bg-white dark:hover:bg-slate-100 dark:text-slate-950 px-6 text-sm font-semibold shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 text-center"
            >
              <CameraIcon className="w-4 h-4" />
              <span>Connect CCTV / IP camera</span>
            </a>
          )}
          <a
            href="/use/footage"
            data-testid="cta-use-footage"
            className="inline-flex h-12 items-center justify-center gap-2.5 rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-800 px-6 text-sm font-semibold text-slate-900 dark:text-slate-100 hover:bg-slate-50 dark:hover:bg-slate-700 shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 text-center"
          >
            <VideoIcon className="w-4 h-4 text-slate-600 dark:text-slate-400" />
            <span>Use video footage</span>
          </a>
        </div>

        {/* Subdued link */}
        <div className="mt-6 flex justify-center">
          <button
            type="button"
            onClick={() => setOtherOpen((v) => !v)}
            data-testid="cta-other-ip"
            className="text-xs text-slate-500 dark:text-slate-400 underline decoration-slate-300 dark:decoration-slate-600 underline-offset-4 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer"
          >
            Other IP camera options
          </button>
        </div>

        {otherOpen && (
          <div
            data-testid="other-ip-panel"
            className="mt-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 p-4 text-sm text-slate-700 dark:text-slate-300"
          >
            Supports standard RTSP, RTSPS, and IP video sources. Configure and manage your camera sources from the overview.
          </div>
        )}

        <div className="mt-6 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200/60 dark:border-slate-800 p-4 text-xs leading-5 text-slate-500 dark:text-slate-400">
          Tip: Ensure the device is connected to the same local network and powered. Provide the streaming URL from your IP camera application.
        </div>
      </div>

      <footer className="mt-8 text-center text-xs text-slate-400 dark:text-slate-500 flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
        <span className="inline-flex items-center gap-1.5">
          <CpuIcon className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
          <span>Video monitoring</span>
        </span>
        <span className="hidden sm:inline">·</span>
        <span className="inline-flex items-center gap-1.5">
          <CrosshairIcon className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
          <span>Target matching</span>
        </span>
        <span className="hidden sm:inline">·</span>
        <span>IBVAP Platform</span>
      </footer>
    </div>
  );
}
