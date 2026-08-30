import { useState } from "react";

export function EmptyState() {
  const [otherOpen, setOtherOpen] = useState(false);

  return (
    <main className="min-h-screen bg-slate-50 flex flex-col">
      <header className="border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto max-w-5xl px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-teal-700 text-white grid place-items-center font-semibold">
              IB
            </div>
            <div>
              <div className="text-sm font-semibold tracking-tight">IBVAP</div>
              <div className="text-xs text-slate-500 -mt-0.5">Intelligent Border Video Analytics Platform</div>
            </div>
          </div>
          <div className="text-xs text-slate-500">No sources connected</div>
        </div>
      </header>

      <div className="flex-1 grid place-items-center p-6">
        <div className="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-900">Connect your first source</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Start with a smartphone acting as an IP camera, or analyze uploaded footage. You can add
            additional IP cameras later — no proprietary hardware required.
          </p>

          {/* Exactly two prominent actions — per spec */}
          <div className="mt-8 grid gap-3">
            <a
              href="/connect/phone"
              data-testid="cta-connect-phone"
              className="inline-flex h-12 items-center justify-center rounded-xl bg-teal-700 px-6 text-sm font-medium text-white hover:bg-teal-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-700 focus-visible:ring-offset-2"
            >
              Connect phone camera
            </a>
            <a
              href="/use/footage"
              data-testid="cta-use-footage"
              className="inline-flex h-12 items-center justify-center rounded-xl border border-slate-200 bg-white px-6 text-sm font-medium text-slate-900 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-700 focus-visible:ring-offset-2"
            >
              Use video footage
            </a>
          </div>

          {/* Subdued link — not equal prominence */}
          <div className="mt-6 flex justify-center">
            <button
              type="button"
              onClick={() => setOtherOpen((v) => !v)}
              data-testid="cta-other-ip"
              className="text-xs text-slate-500 underline decoration-slate-300 underline-offset-4 hover:text-slate-700"
            >
              Other IP camera options
            </button>
          </div>

          {otherOpen && (
            <div
              data-testid="other-ip-panel"
              className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700"
            >
              RTSP / RTSPS and standard IP cameras use the same source abstraction. Add them after you
              connect your first phone feed — no model or pipeline changes required.
            </div>
          )}

          <div className="mt-8 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-500">
            Tip: Keep the phone on power, on the same reachable network as this server, and copy the
            stream URL shown by your IP-webcam app (e.g. IP Webcam, DroidCam). Authentication is
            recommended.
          </div>
        </div>

        <p className="mt-6 text-xs text-slate-400">
          IBVAP will show a real preview only after decoding a real frame — no placeholder images.
        </p>
      </div>

      <footer className="border-t border-slate-200 bg-white px-6 py-3">
        <div className="mx-auto max-w-5xl flex items-center justify-between text-xs text-slate-500">
          <span>IBVAP 0.1.0 · Phase 1 foundation</span>
          <span className="hidden sm:inline">YOLO26 gate: BLOCKED pending Enterprise — no weights bundled</span>
        </div>
      </footer>
    </main>
  );
}
