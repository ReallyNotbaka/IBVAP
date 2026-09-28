import { memo, useCallback, useEffect, useRef, useState } from "react";
import type { PlaybackState } from "../lib/api";

export interface PlaybackScrubberProps {
  isFootage: boolean;
  playback?: PlaybackState;
  transportBusy: boolean;
  seekError?: string | null;
  onTransport: (action: "pause" | "resume" | "restart" | "stop") => Promise<void>;
  onSeek?: (positionSeconds: number) => Promise<void>;
  onReconnect?: () => Promise<void>;
  onDisable?: () => Promise<void>;
}

// Trailing debounce for seek commits so rapid re-grabs collapse to one request.
const SEEK_COMMIT_DEBOUNCE_MS = 250;

export const PlaybackScrubber = memo(function PlaybackScrubber({
  isFootage,
  playback,
  transportBusy,
  seekError,
  onTransport,
  onSeek,
  onReconnect,
  onDisable,
}: PlaybackScrubberProps) {
  const playbackState = playback?.state;
  const position = playback?.position_seconds ?? 0;
  const duration = playback?.duration_seconds ?? 0;

  // Local drag draft: slider moves update the draft only; the seek request
  // fires once on release (debounced), never per-input-event (seek flood fix).
  const [draft, setDraft] = useState<number | null>(null);
  const draftRef = useRef<number | null>(null);
  // Last committed value: the draft is held until the backend-reported
  // position catches up to it (avoids snapping back to the stale position
  // while the seek request is in flight). Epsilon covers step/float noise.
  const committedRef = useRef(0);
  const commitTimer = useRef<number | null>(null);
  const onSeekRef = useRef(onSeek);
  onSeekRef.current = onSeek;

  const shown = draft ?? position;

  useEffect(() => {
    if (draft !== null && Math.abs(position - committedRef.current) <= 0.15) {
      draftRef.current = null;
      setDraft(null);
    }
  }, [position, draft]);

  // A failed seek never converges: drop the draft so the slider falls back
  // to the live position while the error message explains why.
  useEffect(() => {
    if (seekError) {
      draftRef.current = null;
      setDraft(null);
    }
  }, [seekError]);

  const commitSeek = useCallback((value: number) => {
    if (commitTimer.current !== null) {
      window.clearTimeout(commitTimer.current);
    }
    commitTimer.current = window.setTimeout(() => {
      commitTimer.current = null;
      void onSeekRef.current?.(value);
    }, SEEK_COMMIT_DEBOUNCE_MS);
  }, []);

  useEffect(() => {
    return () => {
      if (commitTimer.current !== null) {
        window.clearTimeout(commitTimer.current);
      }
    };
  }, []);

  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseFloat(e.target.value);
      if (isNaN(val)) return;
      draftRef.current = val;
      setDraft(val);
    },
    [],
  );

  const handleRelease = useCallback(() => {
    if (draftRef.current !== null) {
      const val = draftRef.current;
      // Keep the draft rendered until the backend position catches up
      // (see the committedRef effect above); only the ref moves on.
      draftRef.current = null;
      committedRef.current = val;
      commitSeek(val);
    }
  }, [commitSeek]);

  const handleKeyUp = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") handleRelease();
    },
    [handleRelease],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") handleRelease();
    },
    [handleRelease],
  );

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className="absolute bottom-10 left-3 right-3 z-30 flex flex-col gap-1.5 rounded-xl border border-white/10 bg-black/80 px-3 py-2 text-white backdrop-blur-md opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
      onClick={(e) => e.stopPropagation()}
    >
      {isFootage && duration > 0 && (
        <div className="flex items-center gap-2 w-full text-[10px] font-mono text-slate-300">
          <span>{formatTime(position)}</span>
          <input
            type="range"
            min={0}
            max={duration}
            step={0.1}
            value={shown}
            onChange={handleSliderChange}
            onMouseUp={handleRelease}
            onTouchEnd={handleRelease}
            onPointerUp={handleRelease}
            onLostPointerCapture={handleRelease}
            onBlur={handleRelease}
            onKeyUp={handleKeyUp}
            onKeyDown={handleKeyDown}
            className="flex-1 h-1.5 bg-white/20 rounded-lg appearance-none cursor-pointer accent-emerald-500 hover:accent-emerald-400"
            aria-label="Seek footage"
          />
          <span>{formatTime(duration)}</span>
        </div>
      )}
      {seekError && (
        <div className="text-[10px] font-mono text-red-300" role="alert">
          Seek failed: {seekError}
        </div>
      )}

      <div className="flex items-center gap-2">
        {isFootage ? (
          <>
            <button
              type="button"
              onClick={() => void onTransport(playbackState === "playing" ? "pause" : "resume")}
              disabled={transportBusy}
              className="transport-button"
              aria-label={playbackState === "playing" ? "Pause footage" : "Play footage"}
            >
              {playbackState === "playing" ? "Pause" : "Play"}
            </button>
            <button
              type="button"
              onClick={() => void onTransport("restart")}
              disabled={transportBusy}
              className="transport-button"
              aria-label="Restart footage"
            >
              Restart
            </button>
            <button
              type="button"
              onClick={() => void onTransport("stop")}
              disabled={transportBusy}
              className="transport-button transport-button-danger"
              aria-label="Stop footage"
            >
              Stop
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void onReconnect?.()}
              className="transport-button"
              aria-label="Reconnect camera"
            >
              Reconnect
            </button>
            <button
              type="button"
              onClick={() => void onDisable?.()}
              className="transport-button transport-button-danger"
              aria-label="Stop camera"
            >
              Stop
            </button>
          </>
        )}
      </div>
    </div>
  );
});
