import { useState } from "react";

export function EmptyState({
  onConnect,
}: {
  onConnect?: () => void;
}) {
  const [otherOpen, setOtherOpen] = useState(false);

  return (
    <div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-8rem)] py-8 px-4 w-full">
      <div className="w-full max-w-xl rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white dark:bg-[#131720]/95 backdrop-blur-xl p-8 shadow-xl transition-all">
        <h1 className="text-[22px] font-bold tracking-tight text-slate-900 dark:text-slate-100">
          Connect your first source
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Start with a smartphone acting as an IP camera, or analyze uploaded footage. You can add
          additional IP cameras later — no proprietary hardware required.
        </p>

        {/* Prominent actions — per spec */}
        <div className="mt-8 grid gap-3">
          {onConnect ? (
            <button
              type="button"
              onClick={onConnect}
              data-testid="cta-connect-phone"
              className="inline-flex h-12 items-center justify-center rounded-xl bg-slate-900 hover:bg-black text-white dark:bg-white dark:hover:bg-slate-100 dark:text-slate-950 px-6 text-sm font-semibold shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 cursor-pointer"
            >
              Connect phone camera
            </button>
          ) : (
            <a
              href="/connect/phone"
              data-testid="cta-connect-phone"
              className="inline-flex h-12 items-center justify-center rounded-xl bg-slate-900 hover:bg-black text-white dark:bg-white dark:hover:bg-slate-100 dark:text-slate-950 px-6 text-sm font-semibold shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 text-center"
            >
              Connect phone camera
            </a>
          )}
          <a
            href="/use/footage"
            data-testid="cta-use-footage"
            className="inline-flex h-12 items-center justify-center rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-800 px-6 text-sm font-semibold text-slate-900 dark:text-slate-100 hover:bg-slate-50 dark:hover:bg-slate-700 shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 text-center"
          >
            Use video footage
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
            RTSP / RTSPS and standard IP cameras use the same source abstraction. Add them after you
            connect your first phone feed — no model or pipeline changes required.
          </div>
        )}

        <div className="mt-8 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200/60 dark:border-slate-800 p-4 text-xs leading-5 text-slate-500 dark:text-slate-400">
          Tip: Keep the phone on power, on the same reachable network as this server, and copy the
          stream URL shown by your IP-webcam app (e.g. IP Webcam, DroidCam). Authentication is
          recommended.
        </div>
      </div>

      <p className="mt-6 text-xs text-slate-400 dark:text-slate-500 text-center">
        IBVAP will show a real preview only after decoding a real frame — no placeholder images.
      </p>

      <footer className="mt-8 text-center text-xs text-slate-400 dark:text-slate-500 flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
        <span>IBVAP 0.1.0 · Phase 1 foundation</span>
        <span className="hidden sm:inline">·</span>
        <span className="hidden sm:inline">YOLO26 gate: BLOCKED pending Enterprise — no weights bundled</span>
      </footer>
    </div>
  );
}
