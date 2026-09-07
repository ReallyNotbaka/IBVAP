import { useState, useEffect } from "react";

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
    setIsDark((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("ibvap-theme", next ? "dark" : "light");
      } catch {
        // LocalStorage disabled or quota exceeded
      }
      return next;
    });
  };

  const maskId = `theme-moon-mask-${idPrefix}`;

  return (
    <button
      type="button"
      onClick={toggleTheme}
      data-testid="theme-toggle"
      className={`relative flex h-8 w-8 sm:h-9 sm:w-9 items-center justify-center rounded-full border border-neutral-200/90 dark:border-white/10 bg-neutral-100/90 dark:bg-[#1a202c] text-amber-600 dark:text-neutral-200 shadow-sm hover:scale-105 active:scale-95 transition-all duration-300 cursor-pointer overflow-hidden ${className}`}
      title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
      aria-label={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
    >
      <svg
        viewBox="0 0 24 24"
        width="20"
        height="20"
        className="w-5 h-5 transition-transform duration-500 ease-out"
        style={{
          transform: isDark ? "rotate(40deg)" : "rotate(0deg)",
        }}
      >
        <mask id={maskId}>
          <rect x="0" y="0" width="100%" height="100%" fill="white" />
          <circle
            cx={isDark ? "17" : "26"}
            cy={isDark ? "8" : "-6"}
            r="6"
            fill="black"
            style={{
              transition: "cx 400ms cubic-bezier(0.4, 0, 0.2, 1), cy 400ms cubic-bezier(0.4, 0, 0.2, 1)",
            }}
          />
        </mask>

        <circle
          cx="12"
          cy="12"
          r={isDark ? "6" : "4.5"}
          fill="currentColor"
          mask={`url(#${maskId})`}
          style={{
            transition: "r 400ms cubic-bezier(0.4, 0, 0.2, 1)",
          }}
        />

        {/* Sun Rays - collapse into crescent moon */}
        <g
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          style={{
            opacity: isDark ? 0 : 1,
            transform: isDark ? "scale(0.2) rotate(90deg)" : "scale(1) rotate(0deg)",
            transformOrigin: "center",
            transition: "all 400ms cubic-bezier(0.4, 0, 0.2, 1)",
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
