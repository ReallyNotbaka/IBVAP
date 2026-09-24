import { memo, useCallback } from "react";
import type { PlaybackState } from "../lib/api";

export interface PlaybackScrubberProps {
  isFootage: boolean;
  playback?: PlaybackState;
  transportBusy: boolean;
  onTransport: (action: "pause" | "resume" | "restart" | "stop") => Promise<void>;
  onSeek?: (positionSeconds: number) => Promise<void>;
  onReconnect?: () => Promise<void>;
  onDisable?: () => Promise<void>;
}

export const PlaybackScrubber = memo(function PlaybackScrubber({
  isFootage,
  playback,
  transportBusy,
  onTransport,
  onSeek,
  onReconnect,
  onDisable,
}: PlaybackScrubberProps) {
  const playbackState = playback?.state;
  const position = playback?.position_seconds ?? 0;
  const duration = playback?.duration_seconds ?? 0;

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseFloat(e.target.value);
      if (!isNaN(val) && onSeek) {
        void onSeek(val);
      }
    },
    [onSeek],
  );

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
            value={position}
            onChange={handleSliderChange}
            className="flex-1 h-1.5 bg-white/20 rounded-lg appearance-none cursor-pointer accent-emerald-500 hover:accent-emerald-400"
            aria-label="Seek footage"
          />
          <span>{formatTime(duration)}</span>
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
