import { Link, useLocation } from "react-router-dom";
import { useWatchlist, useModels } from "../lib/api";
import { ThemeToggle } from "./ThemeToggle";
import { ArrowLeftIcon, CameraIcon, CpuIcon, CrosshairIcon } from "./Icons";

const items = [
  { to: "/", label: "Overview" },
  { to: "/alerts", label: "Alerts" },
  { to: "/health", label: "Health" },
];

export function Topbar({
  onAddPhone,
  onOpenWatchlist,
  onOpenModels,
}: {
  onAddPhone: () => void;
  onOpenWatchlist?: () => void;
  onOpenModels?: () => void;
}) {
  const loc = useLocation();
  const isCockpit = loc.pathname === "/" || loc.pathname.startsWith("/connect");
  const showBack = loc.pathname !== "/";
  const { data: suspects = [] } = useWatchlist();
  const { data: modelData } = useModels();
  const activeModel = modelData?.active_model || "yolo26n";

  return (
    <header className="topbar">
      <div className="topbar-title flex items-center gap-3">
        <Link
          to="/"
          aria-label="IBVAP landing page"
          data-testid="brand-home"
          className="brand"
          style={{ padding: 0, textDecoration: "none", color: "inherit" }}
        >
          <div className="brand-mark">IB</div>
          <div>
            <div className="brand-name">IBVAP</div>
            <div className="brand-subtitle">Operations</div>
          </div>
        </Link>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">
        {showBack && (
          <Link
            to="/"
            data-testid="back-to-overview"
            aria-label="Back to overview"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-800/70 px-2.5 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:border-slate-400 dark:hover:border-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            <ArrowLeftIcon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Back</span>
          </Link>
        )}
        <nav className="topbar-nav" aria-label="Section navigation">
          {items.map((it) => {
            const active = it.to === "/" ? isCockpit : loc.pathname === it.to;
            return (
              <Link key={it.to} to={it.to} className={active ? "topbar-link active" : "topbar-link"}>
                {it.label}
              </Link>
            );
          })}
        </nav>

        {/* Dynamic Model Switcher Button */}
        <button
          onClick={onOpenModels}
          data-testid="topbar-model-btn"
          className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 dark:border-slate-800 bg-slate-100/80 dark:bg-slate-800/80 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:border-slate-400 dark:hover:border-slate-600 hover:bg-slate-200/80 dark:hover:bg-slate-700/80 transition-all shadow-sm cursor-pointer"
          title="Model settings"
        >
          <CpuIcon className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
          <span className="hidden sm:inline text-slate-500 dark:text-slate-400 font-medium">Model:</span>
          <span className="font-mono uppercase font-bold text-slate-900 dark:text-slate-100">{activeModel}</span>
        </button>

        <button
          onClick={onOpenWatchlist}
          data-testid="topbar-watchlist-btn"
          className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 dark:border-slate-800 bg-slate-100/80 dark:bg-slate-800/80 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:border-rose-400 dark:hover:border-rose-600 hover:bg-rose-50/50 dark:hover:bg-rose-950/30 transition-all shadow-sm cursor-pointer"
          title="Watchlist"
        >
          <CrosshairIcon className="w-3.5 h-3.5 text-rose-500 dark:text-rose-400" />
          <span>Watchlist</span>
          {suspects.length > 0 && (
            <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-600 px-1 text-[10px] font-bold text-white">
              {suspects.length}
            </span>
          )}
        </button>

        {/* Animated Light / Dark Mode Toggle Button */}
        <ThemeToggle idPrefix="topbar" />

        <button
          onClick={onAddPhone}
          data-testid="cta-connect-phone-topbar"
          className="inline-flex h-8 sm:h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-900 px-2.5 sm:px-3.5 text-xs font-semibold text-white shadow-sm transition-all hover:-translate-y-0.5 hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100 cursor-pointer"
          title="Add camera"
          aria-label="Add CCTV or IP camera"
        >
          <CameraIcon className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Add camera</span>
        </button>
      </div>
    </header>
  );
}
