import { Link, useLocation } from "react-router-dom";

const items = [
  { to: "/", label: "Overview" },
  { to: "/monitor", label: "Monitor" },
  { to: "/cameras", label: "Cameras" },
  { to: "/alerts", label: "Alerts" },
  { to: "/events", label: "Events" },
  { to: "/health", label: "Health" },
  { to: "/settings", label: "Settings" },
];

export function Navbar() {
  const loc = useLocation();
  return (
    <nav className="border-b border-slate-200 bg-white px-6 py-2 flex items-center gap-4 text-sm">
      {items.map((it) => (
        <Link
          key={it.to}
          to={it.to}
          className={`px-2 py-1 rounded ${loc.pathname === it.to ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
        >
          {it.label}
        </Link>
      ))}
    </nav>
  );
}
