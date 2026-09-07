import { useState, useMemo } from "react";
import { useEvents, clearEvents, useCameras, type EventItem } from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";
import {
  BellIcon,
  CrosshairIcon,
  AlertTriangleIcon,
  ShieldCheckIcon,
  VideoIcon,
  CloseIcon,
  SparkIcon,
} from "../components/Icons";

type AlertTab = "all" | "watchlist" | "intrusions" | "exits" | "system";

export function Alerts() {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<AlertTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCamera, setSelectedCamera] = useState<string>("all");
  const [threatFilter, setThreatFilter] = useState<string>("all");
  const [dedupEnabled, setDedupEnabled] = useState(true);
  const [isClearing, setIsClearing] = useState(false);
  const [acknowledgedIds, setAcknowledgedIds] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState("");

  const { data: rawEvents = [], isLoading, isError, refetch } = useEvents({ limit: 100 });
  const { data: cameras = [] } = useCameras();

  const cameraMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of cameras) {
      map.set(c.id, c.name || `Camera ${c.id.slice(0, 8)}`);
    }
    return map;
  }, [cameras]);

  // Tab categorization helper
  const getEventCategory = (ev: EventItem): AlertTab => {
    const type = (ev.event_type || "").toLowerCase();
    if (type.includes("watchlist") || type.includes("suspect")) return "watchlist";
    if (type.includes("intrusion")) return "intrusions";
    if (type.includes("exit")) return "exits";
    if (type.includes("system") || type.includes("low_vis") || type.includes("offline") || type.includes("reconnect")) return "system";
    return "all";
  };

  // Grouping & deduplication of rapid boundary crossing / exit events
  const processedEvents = useMemo(() => {
    // Exclude acknowledged events
    const active = rawEvents.filter((ev) => !acknowledgedIds.has(ev.id));

    if (!dedupEnabled) {
      return active.map((ev) => ({ event: ev, count: 1, latestTime: ev.created_at || Date.now() / 1000 }));
    }

    const grouped: Array<{ event: EventItem; count: number; latestTime: number }> = [];
    for (const ev of active) {
      const evTime = ev.created_at || Date.now() / 1000;
      // Match with last group if same camera, zone, event_type, and track within 20 seconds
      const existing = grouped.find((g) => {
        const prev = g.event;
        const timeDiff = Math.abs(g.latestTime - evTime);
        return (
          prev.camera_id === ev.camera_id &&
          prev.event_type === ev.event_type &&
          prev.zone_id === ev.zone_id &&
          prev.track_id === ev.track_id &&
          timeDiff <= 20
        );
      });

      if (existing) {
        existing.count += 1;
        if (evTime > existing.latestTime) {
          existing.latestTime = evTime;
          existing.event = ev;
        }
      } else {
        grouped.push({ event: ev, count: 1, latestTime: evTime });
      }
    }
    return grouped;
  }, [rawEvents, acknowledgedIds, dedupEnabled]);

  // Counts per tab
  const tabCounts = useMemo(() => {
    const counts = { all: 0, watchlist: 0, intrusions: 0, exits: 0, system: 0 };
    for (const item of processedEvents) {
      counts.all += 1;
      const cat = getEventCategory(item.event);
      if (cat in counts) {
        counts[cat] += 1;
      }
    }
    return counts;
  }, [processedEvents]);

  // Filter by tab, search, camera, threat level
  const filteredEvents = useMemo(() => {
    return processedEvents.filter(({ event: ev }) => {
      // Tab filter
      if (activeTab !== "all") {
        const cat = getEventCategory(ev);
        if (cat !== activeTab) return false;
      }

      // Camera filter
      if (selectedCamera !== "all" && ev.camera_id !== selectedCamera) {
        return false;
      }

      // Threat filter
      if (threatFilter !== "all") {
        const tl = (ev.explanation?.threat_level || ev.explanation?.tier || "INFO").toUpperCase();
        if (tl !== threatFilter) return false;
      }

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const camName = (cameraMap.get(ev.camera_id) || "").toLowerCase();
        const suspect = (ev.explanation?.suspect_name || "").toLowerCase();
        const zone = (ev.zone_id || "").toLowerCase();
        const rule = (ev.explanation?.rule || "").toLowerCase();
        const type = (ev.event_type || "").toLowerCase();
        const trackStr = ev.track_id !== undefined ? String(ev.track_id) : "";

        return (
          camName.includes(q) ||
          suspect.includes(q) ||
          zone.includes(q) ||
          rule.includes(q) ||
          type.includes(q) ||
          trackStr.includes(q)
        );
      }

      return true;
    });
  }, [processedEvents, activeTab, selectedCamera, threatFilter, searchQuery, cameraMap]);

  const handleClearAll = async () => {
    if (confirm("Clear all operational alerts from log?")) {
      setIsClearing(true);
      try {
        await clearEvents();
        setAcknowledgedIds(new Set());
        await qc.invalidateQueries({ queryKey: ["events"] });
      } catch (err) {
        setActionError("Alerts could not be cleared. Try again.");
      } finally {
        setIsClearing(false);
      }
    }
  };

  const handleAcknowledge = (id: string) => {
    setAcknowledgedIds((prev) => new Set(prev).add(id));
  };

  const formatTime = (epochSeconds?: number) => {
    if (!epochSeconds) return "Recent";
    const diff = Math.floor(Date.now() / 1000 - epochSeconds);
    if (diff < 5) return "Just now";
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto w-full space-y-5">
      {/* Header with Stats & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200/80 dark:border-white/10 pb-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900/50 text-rose-600 dark:text-rose-400 shadow-sm">
            <BellIcon className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-2">
              Operational Alerts Console
              {tabCounts.all > 0 && (
                <span className="rounded-full bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300 text-xs px-2.5 py-0.5 font-mono font-bold border border-rose-200 dark:border-rose-900/60">
                  {tabCounts.all} Active
                </span>
              )}
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Watchlist matches, boundary crossing telemetry, and system incident stream
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-400 cursor-pointer select-none bg-slate-100/70 dark:bg-slate-800/80 px-3 py-1.5 rounded-lg border border-slate-200/80 dark:border-white/5">
            <input
              type="checkbox"
              checked={dedupEnabled}
              onChange={(e) => setDedupEnabled(e.target.checked)}
              className="rounded accent-slate-900 dark:accent-white"
            />
            <span>Debounce Rapid Events</span>
          </label>

          <button
            onClick={() => refetch()}
            className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 shadow-xs transition-colors cursor-pointer"
          >
            Refresh
          </button>

          <button
            onClick={handleClearAll}
            disabled={isClearing || processedEvents.length === 0}
            className="rounded-lg bg-rose-50 dark:bg-rose-950/80 border border-rose-200 dark:border-rose-900/60 text-rose-700 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/60 disabled:opacity-40 px-3 py-1.5 text-xs font-semibold shadow-xs transition-colors cursor-pointer"
          >
            {isClearing ? "Clearing..." : "Clear Alerts"}
          </button>
        </div>
      </div>

      {actionError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
          <span>{actionError}</span>
          <button type="button" onClick={() => setActionError("")} className="font-semibold underline underline-offset-2 cursor-pointer">Dismiss</button>
        </div>
      )}

      {/* Categorized Tabs Bar */}
      <div className="flex items-center gap-2 border-b border-slate-200/80 dark:border-white/10 overflow-x-auto pb-1">
        {[
          { id: "all", label: "All Alerts", count: tabCounts.all, icon: BellIcon, color: "slate" },
          { id: "watchlist", label: "Watchlist Matches", count: tabCounts.watchlist, icon: CrosshairIcon, color: "rose" },
          { id: "intrusions", label: "Intrusions", count: tabCounts.intrusions, icon: AlertTriangleIcon, color: "red" },
          { id: "exits", label: "Exits", count: tabCounts.exits, icon: ShieldCheckIcon, color: "amber" },
          { id: "system", label: "System", count: tabCounts.system, icon: SparkIcon, color: "blue" },
        ].map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as AlertTab)}
              className={`flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
                isActive
                  ? "bg-slate-900 dark:bg-white text-white dark:text-slate-950 shadow-sm"
                  : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-200"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
              <span
                className={`rounded-full px-1.5 py-0.2 text-[10px] font-mono font-bold ${
                  isActive
                    ? "bg-white/20 dark:bg-black/20 text-white dark:text-slate-950"
                    : tab.count > 0
                    ? "bg-slate-200 dark:bg-slate-800 text-slate-800 dark:text-slate-200"
                    : "bg-slate-100 dark:bg-slate-800/40 text-slate-400 dark:text-slate-500"
                }`}
              >
                {tab.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-wrap items-center gap-3 bg-white/70 dark:bg-slate-900/70 backdrop-blur-xl border border-slate-200/80 dark:border-white/10 p-3 rounded-2xl shadow-xs">
        <div className="flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Search alerts by suspect, track ID, camera, or rule..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-50 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 dark:focus:border-slate-600"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={selectedCamera}
            onChange={(e) => setSelectedCamera(e.target.value)}
            aria-label="Filter by camera feed"
            className="bg-slate-50 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-800 dark:text-slate-200 focus:outline-none cursor-pointer"
          >
            <option value="all">All Cameras ({cameras.length})</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name || `Camera ${c.id.slice(0, 8)}`}
              </option>
            ))}
          </select>

          <select
            value={threatFilter}
            onChange={(e) => setThreatFilter(e.target.value)}
            aria-label="Filter by threat priority"
            className="bg-slate-50 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-800 dark:text-slate-200 focus:outline-none cursor-pointer"
          >
            <option value="all">All Priorities</option>
            <option value="CRITICAL">Critical Only</option>
            <option value="HIGH">High</option>
            <option value="AMBER">Amber / Medium</option>
            <option value="LOW">Low</option>
          </select>
        </div>
      </div>

      {/* Events List */}
      <div className="space-y-2.5">
        {isLoading ? (
          <div className="py-16 text-center text-xs text-slate-400 dark:text-slate-500 font-medium">
            Loading operational activity feed...
          </div>
        ) : isError ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-12 text-center dark:border-amber-900/60 dark:bg-amber-950/20">
            <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200">Alerts are unavailable</h3>
            <p className="mx-auto mt-2 max-w-sm text-xs text-amber-700 dark:text-amber-300">The activity feed could not be loaded. Your filters are still here.</p>
            <button type="button" onClick={() => void refetch()} className="mt-4 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white dark:bg-white dark:text-slate-950 cursor-pointer">Try again</button>
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white/60 dark:bg-slate-900/60 backdrop-blur-xl p-12 text-center space-y-2 shadow-xs">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 mb-1 border border-emerald-200 dark:border-emerald-900/50">
              <ShieldCheckIcon className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              Operational Zones Clear
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">
              {activeTab === "all"
                ? "No active security incidents or alerts detected. The live perimeter is secure."
                : `No events currently match the selected "${activeTab}" filter.`}
            </p>
          </div>
        ) : (
          filteredEvents.map(({ event: ev, count, latestTime }) => {
            const rawType = (ev.event_type || "").toLowerCase();
            const isWatchlist = rawType.includes("watchlist") || rawType.includes("suspect");
            const isIntrusion = rawType.includes("intrusion");
            const isExit = rawType.includes("exit");
            const isCritical =
              ev.explanation?.threat_level === "CRITICAL" ||
              ev.explanation?.tier === "RED" ||
              (isWatchlist && ev.confidence && ev.confidence >= 0.70);

            const camName = cameraMap.get(ev.camera_id) || `Camera ${ev.camera_id.slice(0, 8)}`;

            let borderStyle = "border-slate-200 dark:border-slate-800";
            let badgeBg = "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300";
            if (isCritical) {
              borderStyle = "border-rose-300 dark:border-rose-900/60 bg-rose-50/30 dark:bg-rose-950/20";
              badgeBg = "bg-rose-600 text-white shadow-[0_0_10px_rgba(225,29,72,0.5)]";
            } else if (isIntrusion) {
              borderStyle = "border-red-200 dark:border-red-900/40 bg-red-50/20 dark:bg-red-950/10";
              badgeBg = "bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900/50";
            } else if (isExit) {
              borderStyle = "border-amber-200/80 dark:border-amber-900/30 bg-amber-50/10 dark:bg-amber-950/10";
              badgeBg = "bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-900/50";
            }

            return (
              <div
                key={ev.id}
                className={`flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border p-4 backdrop-blur-xl transition-all shadow-xs ${borderStyle}`}
              >
                <div className="flex items-start gap-3.5">
                  <div className="mt-0.5 flex-shrink-0">
                    {isCritical ? (
                      <span className="relative flex h-3 w-3">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-600" />
                      </span>
                    ) : isIntrusion ? (
                      <span className="h-2.5 w-2.5 rounded-full bg-red-500 inline-block" />
                    ) : isExit ? (
                      <span className="h-2.5 w-2.5 rounded-full bg-amber-500 inline-block" />
                    ) : (
                      <span className="h-2.5 w-2.5 rounded-full bg-slate-400 inline-block" />
                    )}
                  </div>

                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${badgeBg}`}>
                        {(ev.event_type || "incident").replace(/_/g, " ")}
                      </span>

                      {count > 1 && (
                        <span className="rounded-full bg-slate-200 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-2 py-0.5 text-[10px] font-mono font-bold">
                          ×{count} occurrences
                        </span>
                      )}

                      <span className="text-xs font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                        <VideoIcon className="w-3.5 h-3.5 text-slate-400" />
                        {camName}
                      </span>

                      {ev.zone_id && (
                        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                          • Zone: {ev.zone_id}
                        </span>
                      )}

                      {ev.track_id !== undefined && (
                        <span className="rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.2 text-[10px] font-mono text-slate-600 dark:text-slate-400">
                          Track #{ev.track_id}
                        </span>
                      )}
                    </div>

                    {/* Explanatory description / suspect callout */}
                    <div className="text-xs text-slate-600 dark:text-slate-300">
                      {isWatchlist && ev.explanation?.suspect_name ? (
                        <span className="font-bold text-rose-700 dark:text-rose-400 text-sm">
                          TARGET IDENTIFIED: [{ev.explanation.suspect_name}]
                        </span>
                      ) : (
                        <span>{ev.explanation?.observed || ev.explanation?.rule || "Perimeter event observed"}</span>
                      )}
                    </div>

                    {ev.explanation && (
                      <div className="flex items-center gap-3 text-[11px] text-slate-400 dark:text-slate-500 font-mono">
                        {ev.confidence !== undefined && (
                          <span>Confidence: {Math.round(ev.confidence * 100)}%</span>
                        )}
                        {ev.model_id && <span>Model: {ev.model_id}</span>}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-between sm:justify-end gap-3 pt-2 sm:pt-0 border-t sm:border-t-0 border-slate-100 dark:border-slate-800">
                  <span className="text-xs font-mono text-slate-400 dark:text-slate-500 whitespace-nowrap">
                    {formatTime(latestTime)}
                  </span>

                  <button
                    onClick={() => handleAcknowledge(ev.id)}
                    className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 px-2.5 py-1 text-xs font-semibold text-slate-700 dark:text-slate-200 shadow-xs transition-colors cursor-pointer"
                    title="Dismiss alert"
                  >
                    Acknowledge
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
