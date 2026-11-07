import { useState } from "react";
import { useEvents } from "../lib/api";
import { ChevronDownIcon, ChevronUpIcon } from "./Icons";

const NOISY_FOV_TYPES = new Set(["target_entered", "target_exited", "target_lost"]);

export function AlertRail({ limit = 10 }: { limit?: number }) {
  const { data: rawEvents = [] } = useEvents(limit <= 10 ? 25 : 50);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [expandedCount, setExpandedCount] = useState(false);

  // Filter out routine FOV entry/exit noise and consecutive duplicate events
  const events = rawEvents
    .filter((ev) => !NOISY_FOV_TYPES.has((ev.event_type || "").toLowerCase()))
    .filter((ev, idx, arr) => {
      if (idx === 0) return true;
      const prev = arr[idx - 1];
      return !(prev.event_type === ev.event_type && prev.camera_id === ev.camera_id && prev.zone_id === ev.zone_id);
    });

  const show = expandedCount ? events : events.slice(0, limit);
  const latestEvent = events[0];

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3.5 py-2.5 border-b border-slate-200/80 dark:border-white/[0.08]">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              events.length > 0
                ? "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.7)]"
                : "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]"
            }`}
          />
          <h3 className="text-xs font-semibold tracking-tight text-slate-900 dark:text-slate-100 truncate">
            Security Alerts
          </h3>
          <span className="rounded-md bg-slate-100 dark:bg-slate-800 border border-slate-200/70 dark:border-white/10 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-slate-700 dark:text-slate-300 shrink-0">
            {events.length}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {!isCollapsed && events.length > limit && (
            <button
              onClick={() => setExpandedCount((v) => !v)}
              className="text-[11px] text-blue-500 dark:text-blue-400 hover:underline font-medium whitespace-nowrap cursor-pointer"
            >
              {expandedCount ? `Top ${limit}` : "View all"}
            </button>
          )}

          <button
            onClick={() => setIsCollapsed((v) => !v)}
            data-testid="toggle-alert-rail"
            className="btn-instrument !h-7 !px-2.5 !text-[11px]"
            title={isCollapsed ? "Show activity" : "Hide activity"}
          >
            <span>{isCollapsed ? "Show activity" : "Hide activity"}</span>
            {isCollapsed ? (
              <ChevronDownIcon className="w-3 h-3 text-slate-400" />
            ) : (
              <ChevronUpIcon className="w-3 h-3 text-slate-400" />
            )}
          </button>
        </div>
      </div>

      {isCollapsed && latestEvent && (
        <div className="px-3.5 py-2 text-[11px] text-slate-500 dark:text-slate-400 flex items-center justify-between border-b border-slate-200/60 dark:border-white/[0.05]">
          <span>
            Latest:{" "}
            <strong className="font-semibold text-slate-800 dark:text-slate-200">
              {latestEvent.event_type.replace(/_/g, " ").toUpperCase()}
            </strong>
          </span>
          {latestEvent.confidence !== undefined && (
            <span className="font-mono">{Math.round(latestEvent.confidence * 100)}%</span>
          )}
        </div>
      )}

      {!isCollapsed && (
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <div className="space-y-1.5">
            {events.length === 0 ? (
              <div className="text-xs text-slate-400 dark:text-slate-500 py-8 text-center">
                No security incidents — perimeter clear
              </div>
            ) : (
              show.map((ev) => {
                const type = ev.event_type.toLowerCase();
                const isWatchlist = type.includes("watchlist") || type.includes("suspect");
                const isIntrusion = type.includes("intrusion");

                let badgeStyle =
                  "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-white/10";
                if (isWatchlist || isIntrusion) {
                  badgeStyle =
                    "bg-rose-500/15 text-rose-600 dark:text-rose-300 border-rose-500/30";
                }

                return (
                  <div
                    key={ev.id}
                    className={`flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs transition-colors ${
                      isWatchlist || isIntrusion
                        ? "border-rose-500/25 bg-rose-500/[0.06]"
                        : "border-slate-200/70 dark:border-white/[0.07] bg-white/70 dark:bg-slate-900/50"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold uppercase border shrink-0 ${badgeStyle}`}
                      >
                        {ev.event_type.replace(/_/g, " ")}
                      </span>
                      <span className="font-medium text-slate-700 dark:text-slate-200 truncate">
                        {ev.explanation?.suspect_name
                          ? ev.explanation.suspect_name
                          : ev.zone_id
                          ? `Zone: ${ev.zone_id}`
                          : "Perimeter"}
                      </span>
                    </div>

                    {ev.confidence !== undefined && (
                      <span className="text-[11px] font-mono text-slate-500 dark:text-slate-400 shrink-0">
                        {Math.round(ev.confidence * 100)}%
                      </span>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
