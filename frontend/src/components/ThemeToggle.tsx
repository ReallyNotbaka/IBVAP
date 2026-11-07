import { useState, useEffect } from "react";
import { flushSync } from "react-dom";

interface ThemeToggleProps {
  idPrefix?: string;
  className?: string;
}

export function ThemeToggle({ idPrefix = "header", className = "" }: ThemeToggleProps) {
  const [isDark, setIsDark] = useState(() => {
    if (typeof window === "undefined") return false;
    const saved = localStorage.getItem("ibvap-theme");
    if (saved) return saved === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [isDark]);

  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === "ibvap-theme") {
        setIsDark(e.newValue === "dark");
      }
    };
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  const toggleTheme = () => {
    const next = !isDark;
    const root = document.documentElement;
    const button = document.querySelector<HTMLButtonElement>(`[data-testid="theme-toggle"]`);
    const bounds = button?.getBoundingClientRect();

    if (bounds) {
      const x = bounds.left + bounds.width / 2;
      const y = bounds.top + bounds.height / 2;
      const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
      root.style.setProperty("--theme-transition-x", `${x}px`);
      root.style.setProperty("--theme-transition-y", `${y}px`);
      root.style.setProperty("--theme-transition-radius", `${radius}px`);
    }

    const updateTheme = () => {
      flushSync(() => setIsDark(next));
      if (next) {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
      try {
        localStorage.setItem("ibvap-theme", next ? "dark" : "light");
      } catch {
        // LocalStorage disabled or quota exceeded
      }
    };

    if ("startViewTransition" in document && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.startViewTransition(updateTheme);
    } else {
      updateTheme();
    }
  };

  const maskId = `theme-moon-mask-${idPrefix}`;

  return (
    <button
      type="button"
      onClick={toggleTheme}
      data-testid="theme-toggle"
      className={`relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10 bg-transparent hover:bg-slate-100 dark:hover:bg-white/[0.06] text-slate-600 dark:text-slate-300 transition-colors cursor-pointer overflow-hidden ${className}`}
      title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
      aria-label={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
    >
      <svg
        viewBox="0 0 24 24"
        width="15"
        height="15"
        className="w-3.5 h-3.5 transition-transform duration-300 ease-out"
        style={{
          transform: isDark ? "rotate(40deg)" : "rotate(0deg)",
          transition: "transform 420ms cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      >
        <mask id={maskId}>
          <rect x="0" y="0" width="100%" height="100%" fill="white" />
          <circle
            cx={isDark ? "17" : "26"}
            cy={isDark ? "8" : "-6"}
            r="6"
            fill="black"
          />
        </mask>

        <circle
          cx="12"
          cy="12"
          r={isDark ? "6" : "4.5"}
          fill="currentColor"
          mask={`url(#${maskId})`}
        />

        <g
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          style={{
            opacity: isDark ? 0 : 1,
            transform: isDark ? "scale(0.2) rotate(90deg)" : "scale(1) rotate(0deg)",
            transformOrigin: "center",
            transition: "transform 420ms cubic-bezier(0.22, 1, 0.36, 1), opacity 220ms ease-out",
          }}
        >
          <line x1="12" y1="1.5" x2="12" y2="3.5" />
          <line x1="12" y1="20.5" x2="12" y2="22.5" />
          <line x1="4.5" y1="4.5" x2="6" y2="6" />
          <line x1="18" y1="18" x2="19.5" y2="19.5" />
          <line x1="1.5" y1="12" x2="3.5" y2="12" />
          <line x1="20.5" y1="12" x2="22.5" y2="12" />
          <line x1="4.5" y1="19.5" x2="6" y2="18" />
          <line x1="18" y1="6" x2="19.5" y2="4.5" />
        </g>
      </svg>
    </button>
  );
}
