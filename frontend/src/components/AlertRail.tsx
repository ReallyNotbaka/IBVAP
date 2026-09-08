import { useState } from "react";
import { useEvents } from "../lib/api";
import { ChevronDownIcon, ChevronUpIcon } from "./Icons";

export function AlertRail({ limit = 5 }: { limit?: number }) {
  const { data: rawEvents = [] } = useEvents(limit === 5 ? 10 : 30);
  const [isCollapsed, setIsCollapsed] = useState(true);
  const [expandedCount, setExpandedCount] = useState(false);

  // Filter consecutive duplicate events for the same camera and event_type
  const events = rawEvents.filter((ev, idx, arr) => {
    if (idx === 0) return true;
    const prev = arr[idx - 1];
    return !(prev.event_type === ev.event_type && prev.camera_id === ev.camera_id && prev.zone_id === ev.zone_id);
  });

  const show = expandedCount ? events : events.slice(0, 5);
  const latestEvent = events[0];

  return (
    <div className="rounded-2xl border border-neutral-200/90 dark:border-white/10 bg-white dark:bg-slate-900 backdrop-blur-xl shadow-sm transition-all overflow-hidden">
      {/* Header with Expand / Contract Button */}
      <div className="flex items-center justify-between px-4 py-3 bg-neutral-50/70 dark:bg-slate-950/60 border-b border-neutral-100 dark:border-white/5">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className={`h-2.5 w-2.5 rounded-full ${events.length > 0 ? "bg-rose-500 animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.65)]" : "bg-slate-300 dark:bg-slate-600"}`} />
          <h3 className="text-sm font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Alerts & activity
          </h3>
          <span className="rounded-full bg-slate-200/70 dark:bg-slate-800 px-2 py-0.5 text-[11px] font-mono font-semibold text-slate-700 dark:text-slate-300">
            {events.length} {events.length === 1 ? "Event" : "Events"}
          </span>

          {/* Compact latest summary when collapsed */}
          {isCollapsed && (
            <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 ml-2">
              <span className="text-slate-400 dark:text-slate-500">{latestEvent ? "Latest:" : "All clear"}</span>
              {latestEvent && (
              <span className="font-semibold text-slate-700 dark:text-slate-200">
                {latestEvent.event_type.replace(/_/g, " ").toUpperCase()}
              </span>
              )}
              {latestEvent && latestEvent.confidence !== undefined && (
                <span className="text-slate-500 dark:text-slate-400">({Math.round(latestEvent.confidence * 100)}%)</span>
              )}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {!isCollapsed && events.length > 5 && (
            <button
              onClick={() => setExpandedCount((v) => !v)}
              className="text-xs text-neutral-800 dark:text-neutral-200 hover:underline font-semibold mr-2 cursor-pointer"
            >
              {expandedCount ? "Show 5" : "View All"}
            </button>
          )}

          {/* Explicit Expand / Contract Button */}
          <button
            onClick={() => setIsCollapsed((v) => !v)}
            data-testid="toggle-alert-rail"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700/80 bg-white dark:bg-slate-800 px-2.5 py-1 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 shadow-sm transition-colors cursor-pointer"
            title={isCollapsed ? "Show activity" : "Hide activity"}
          >
            <span>{isCollapsed ? "Show activity" : "Hide activity"}</span>
            {isCollapsed ? <ChevronDownIcon className="w-3 h-3 text-slate-500 dark:text-slate-400" /> : <ChevronUpIcon className="w-3 h-3 text-slate-500 dark:text-slate-400" />}
          </button>
        </div>
      </div>

      {/* Collapsible Body */}
      {!isCollapsed && (
        <div className="p-4">
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {events.length === 0 ? (
              <div className="text-xs text-slate-400 dark:text-slate-500 py-4 text-center font-medium">
                No recent events
              </div>
            ) : (
              show.map((ev) => {
                const type = ev.event_type.toLowerCase();
                const isIntrusion = type.includes("intrusion");
                const isEntry = type.includes("enter");
                const isExit = type.includes("exit");

                let badgeStyle = "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700";
                if (isIntrusion) {
                  badgeStyle = "bg-red-100 dark:bg-red-950/80 text-red-700 dark:text-red-300 border-red-200 dark:border-red-900/60";
                } else if (isEntry) {
                  badgeStyle = "bg-emerald-100 dark:bg-emerald-950/80 text-emerald-800 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900/60";
                } else if (isExit) {
                  badgeStyle = "bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-900/60";
                }

                return (
                  <div
                    key={ev.id}
                    className={`flex items-center justify-between rounded-xl border px-3.5 py-2.5 text-xs transition-colors ${
                      isIntrusion
                        ? "border-red-200/80 dark:border-red-900/40 bg-red-50/50 dark:bg-red-950/20"
                        : "border-slate-100 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-950/40 hover:bg-slate-100/80 dark:hover:bg-slate-900/60"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <span
                        className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border ${badgeStyle}`}
                      >
                        {ev.event_type.replace(/_/g, " ")}
                      </span>
                      <span className="font-medium text-slate-700 dark:text-slate-200">
                        {ev.zone_id ? `Zone: ${ev.zone_id}` : "Camera FOV"}
                      </span>
                    </div>

                    <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
                      {ev.confidence !== undefined && (
                        <span className="font-semibold text-slate-700 dark:text-slate-300">
                          {Math.round(ev.confidence * 100)}% conf
                        </span>
                      )}
                    </div>
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
