import { Link, useLocation } from "react-router-dom";
import { useWatchlist, useModels } from "../lib/api";
import { ThemeToggle } from "./ThemeToggle";
import { ArrowLeftIcon, CameraIcon, CpuIcon, CrosshairIcon, SettingsIcon } from "./Icons";

const items = [
  { to: "/", label: "Overview" },
  { to: "/alerts", label: "Alerts" },
  { to: "/health", label: "Health" },
];

export function Topbar({
  onAddPhone,
  onOpenWatchlist,
  onOpenModels,
  onOpenSettings,
}: {
  onAddPhone: () => void;
  onOpenWatchlist?: () => void;
  onOpenModels?: () => void;
  onOpenSettings?: () => void;
}) {
  const loc = useLocation();
  const isCockpit = loc.pathname === "/" || loc.pathname.startsWith("/connect");
  const showBack = loc.pathname !== "/";
  const { data: suspects = [] } = useWatchlist();
  const { data: modelData } = useModels();
  const activeModel = modelData?.active_model || "yolo26n";
  return (
    <header className="topbar">
      <div className="flex items-center gap-3.5">
        <Link
          to="/"
          aria-label="IBVAP landing page"
          data-testid="brand-home"
          className="brand"
          style={{ textDecoration: "none", color: "inherit" }}
        >
          <span className="brand-lockup">
            <span className="brand-name">IBVAP</span>
            <span className="brand-subtitle">BOUNDARY / FIELD SYSTEM</span>
          </span>
        </Link>

        {showBack && (
          <Link
            to="/"
            data-testid="back-to-overview"
            aria-label="Back to overview"
            className="btn-instrument"
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
      </div>

      <div className="flex items-center gap-1.5">
        <button
          onClick={onOpenModels}
          data-testid="topbar-model-btn"
          className="btn-instrument"
          title="Model settings"
        >
          <CpuIcon className="w-3.5 h-3.5 text-indigo-400" />
          <span className="font-mono text-[11px] uppercase font-semibold">{activeModel}</span>
        </button>

        <button
          onClick={onOpenWatchlist}
          data-testid="topbar-watchlist-btn"
          className="btn-instrument"
          title="Watchlist"
        >
          <CrosshairIcon className="w-3.5 h-3.5 text-rose-400" />
          <span>Watchlist</span>
          {suspects.length > 0 && (
            <span className="rounded bg-rose-500/20 border border-rose-500/30 px-1.5 py-0.2 text-[10px] font-mono font-semibold text-rose-400">
              {suspects.length}
            </span>
          )}
        </button>

        <ThemeToggle idPrefix="topbar" className="btn-instrument !w-8 !px-0" />

        {onOpenSettings && (
          <button
            onClick={onOpenSettings}
            data-testid="topbar-settings-btn"
            className="btn-instrument !w-8 !px-0"
            title="System & C2 Dispatch Configuration"
            aria-label="System Settings"
          >
            <SettingsIcon className="w-3.5 h-3.5" />
          </button>
        )}

        <button
          onClick={onAddPhone}
          data-testid="cta-connect-phone-topbar"
          className="btn-primary-cobalt"
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
