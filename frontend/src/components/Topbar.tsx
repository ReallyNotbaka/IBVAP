import { Link, useLocation } from "react-router-dom";

const items = [
  { to: "/", label: "Cockpit" },
  { to: "/alerts", label: "Alerts" },
  { to: "/health", label: "Health" },
];

export function Topbar({ onAddPhone }: { onAddPhone: () => void }) {
  const loc = useLocation();
  const isCockpit = loc.pathname === "/" || loc.pathname.startsWith("/connect");
  return (
    <header className="topbar">
      <div className="topbar-title flex items-center gap-3">
        <div className="brand" style={{ padding: 0 }}>
          <div className="brand-mark">IB</div>
          <div>
            <div className="brand-name">IBVAP</div>
            <div className="brand-subtitle">Operations</div>
          </div>
        </div>
        <div className="status-pill online hidden sm:inline-flex">
          <span className="dot" /> Live
        </div>
      </div>

      <div className="flex items-center gap-3">
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
        <button
          onClick={onAddPhone}
          data-testid="cta-connect-phone-topbar"
          className="primary-button h-9 px-5 text-sm hidden md:inline-flex"
        >
          Add phone camera
        </button>
        <button
          onClick={onAddPhone}
          data-testid="cta-connect-phone-topbar-mobile"
          className="primary-button h-9 w-9 p-0 text-sm md:hidden"
          aria-label="Add phone camera"
        >
          +
        </button>
      </div>
    </header>
  );
}
