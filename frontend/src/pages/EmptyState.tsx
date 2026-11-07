import { useState } from "react";
import { CameraIcon, VideoIcon } from "../components/Icons";

export function EmptyState({
  onConnect,
}: {
  onConnect?: () => void;
}) {
  const [otherOpen, setOtherOpen] = useState(false);

  return (
    <div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-5.5rem)] p-4 w-full">
      <div className="liquid-glass-window w-full max-w-[420px] p-8 text-center">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">
          Connect a Video Source
        </h1>
        <p className="mt-2 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
          Stream live from a phone IP camera, connect an RTSP CCTV feed, or analyze a recorded video file.
        </p>

        <div className="mt-6 grid gap-3">
          {onConnect ? (
            <button
              type="button"
              onClick={onConnect}
              data-testid="cta-connect-phone"
              className="liquid-glass-cta !h-11 !text-xs"
            >
              <CameraIcon className="w-4 h-4" />
              <span>Connect phone / CCTV camera</span>
            </button>
          ) : (
            <a
              href="/connect/phone"
              data-testid="cta-connect-phone"
              className="liquid-glass-cta !h-11 !text-xs"
            >
              <CameraIcon className="w-4 h-4" />
              <span>Connect phone / CCTV camera</span>
            </a>
          )}

          <a
            href="/use/footage"
            data-testid="cta-use-footage"
            className="liquid-glass-pill !h-11 !text-xs"
          >
            <VideoIcon className="w-4 h-4 opacity-80" />
            <span>Use video footage</span>
          </a>
        </div>

        <div className="mt-5 flex justify-center">
          <button
            type="button"
            onClick={() => setOtherOpen((v) => !v)}
            data-testid="cta-other-ip"
            className="text-[11px] font-medium text-slate-500 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors cursor-pointer"
          >
            {otherOpen ? "Hide supported protocols" : "Other IP camera options"}
          </button>
        </div>

        {otherOpen && (
          <div
            data-testid="other-ip-panel"
            className="mt-3.5 liquid-glass-input p-3.5 text-xs text-slate-600 dark:text-slate-200 leading-relaxed text-left"
          >
            Supports RTSP/RTSPS (`:554`), IP Webcam (`:8080/video`), and DroidCam (`:4747/video`) over local Wi-Fi or hotspot.
          </div>
        )}
      </div>
    </div>
  );
}
