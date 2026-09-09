import { memo, useId, useMemo } from "react";

export type OverlayPreset = "clean" | "all" | "alerts";

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  confidence?: number;
  trackId?: string;
  isAlert?: boolean;
  isFenceIntrusion?: boolean;
  targetName?: string;
  threatLevel?: string;
  isCritical?: boolean;
  isPlate?: boolean;
}

interface ColorTheme {
  primary: string;
  halo: string;
  bg: string;
  accent: string;
  border: string;
}

function getColorTheme(label: string, isAlert?: boolean, isCritical?: boolean, isPlate?: boolean, isFenceIntrusion?: boolean): ColorTheme {
  if (isFenceIntrusion) {
    return {
      primary: "#a855f7",
      halo: "rgba(88, 28, 135, 0.95)",
      bg: "rgba(88, 28, 135, 0.96)",
      accent: "#f3e8ff",
      border: "rgba(168, 85, 247, 0.95)",
    };
  }
  if (isAlert || isCritical) {
    return {
      primary: "#ef4444", // Vivid Crimson for true security alerts & critical targets
      halo: "rgba(0, 0, 0, 0.95)",
      bg: "rgba(185, 28, 28, 0.96)", // Deep tactical crimson badge background
      accent: "#ffffff",
      border: "rgba(239, 68, 68, 0.9)",
    };
  }

  if (isPlate) {
    return {
      primary: "#22d3ee",
      halo: "rgba(0, 15, 25, 0.95)",
      bg: "rgba(8, 47, 73, 0.96)",
      accent: "#cffafe",
      border: "rgba(34, 211, 238, 0.9)",
    };
  }

  const l = label.toLowerCase();
  if (l === "face") {
    // Quiet, elegant champagne / warm linen marker
    return {
      primary: "#e8dfd2",
      halo: "rgba(0, 0, 0, 0.85)",
      bg: "rgba(18, 21, 28, 0.90)",
      accent: "#f3ede3",
      border: "rgba(232, 223, 210, 0.35)",
    };
  }

  // High-contrast lime stays legible over daylight, road, and night footage.
  return {
    primary: "#a3e635",
    halo: "rgba(0, 15, 0, 0.95)",
    bg: "rgba(20, 55, 10, 0.94)",
    accent: "#ecfccb",
    border: "rgba(163, 230, 53, 0.85)",
  };
}

export const OverlayCanvas = memo(function OverlayCanvas({
  boxes,
  mode = "operational",
  preset,
  showPeople = true,
  showFaces = true,
  showLabels = true,
  showConfidence = true,
  selectedTrackId,
  onSelectBox,
}: {
  boxes: Box[];
  mode?: string;
  preset?: OverlayPreset;
  showPeople?: boolean;
  showFaces?: boolean;
  showLabels?: boolean;
  showConfidence?: boolean;
  selectedTrackId?: string | null;
  onSelectBox?: (box: Box) => void;
}) {
  const activePreset: OverlayPreset =
    preset || (mode === "minimal" ? "clean" : "all");
  const uid = useId().replace(/:/g, "");
  const fBracket = `geometric-bracket-shadow-${uid}`;
  const fSelected = `selected-target-glow-${uid}`;
  const fCritical = `critical-target-glow-${uid}`;
  const fRoi = `roi-intruder-glow-${uid}`;

  const filteredBoxes = useMemo(
    () =>
      boxes.filter((b) => {
        const isFace = b.label.toLowerCase() === "face";
        const isPerson =
          b.label.toLowerCase() === "person" || b.label.toLowerCase() === "human";

        if (activePreset === "alerts" && !b.isAlert) {
          return false;
        }
        if (isFace && !showFaces) return false;
        if (isPerson && !showPeople && !b.isAlert) return false;

        return true;
      }),
    [boxes, activePreset, showFaces, showPeople],
  );

  if (!filteredBoxes.length) return null;

  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none select-none"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-hidden
    >
      <defs>
        {/* Fine, crisp geometric drop shadow for bracket contrast */}
        <filter id={fBracket} x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="0" stdDeviation="0.8" floodColor="#000000" floodOpacity="0.85" />
        </filter>
        <filter id={fSelected} x="-25%" y="-25%" width="150%" height="150%">
          <feDropShadow dx="0" dy="0" stdDeviation="1.2" floodColor="#ffffff" floodOpacity="0.9" />
        </filter>
        {/* Unmistakable tactical crimson beacon glow for critical targets & alerts */}
        <filter id={fCritical} x="-25%" y="-25%" width="150%" height="150%">
          <feDropShadow dx="0" dy="0" stdDeviation="1.6" floodColor="#ef4444" floodOpacity="0.85" />
        </filter>
        {/* Unmistakable tactical purple beacon glow for ROI intruders */}
        <filter id={fRoi} x="-25%" y="-25%" width="150%" height="150%">
          <feDropShadow dx="0" dy="0" stdDeviation="1.6" floodColor="#a855f7" floodOpacity="0.85" />
        </filter>
      </defs>

      {filteredBoxes.map((b, idx) => {
        const theme = getColorTheme(b.label, b.isAlert, b.isCritical, b.isPlate, b.isFenceIntrusion);
        const bx = b.x * 100;
        const by = b.y * 100;
        const bw = b.w * 100;
        const bh = b.h * 100;

        const isFace = b.label.toLowerCase() === "face";
        const hasTrack = Boolean(b.trackId);
        const isSelected = Boolean(selectedTrackId && b.trackId === selectedTrackId);
        const elementKey = b.trackId
          ? `track-${b.label}-${b.trackId}`
          : `det-${b.label}-${idx}`;

        // Micro-badge sizing and text formatting: clearly display target's name
        const formattedLabel = b.isFenceIntrusion
          ? (b.targetName ? `ROI INTRUDER: [${b.targetName}]` : "ROI INTRUDER")
          : b.targetName
          ? (b.isCritical ? `CRITICAL: [${b.targetName}]` : `[${b.targetName}]`)
          : b.isPlate
          ? b.label.toUpperCase()
          : b.isAlert
          ? b.label
          : b.label.charAt(0).toUpperCase() + b.label.slice(1).toLowerCase();

        const charCount =
          formattedLabel.length +
          (hasTrack ? 3 : 0) +
          (showConfidence && b.confidence !== undefined ? 4 : 0);
        const badgeW = isFace
          ? Math.max(5.5, charCount * 0.95 + 1.2)
          : Math.max(9.5, charCount * 1.35 + 2.2);
        const badgeH = isFace ? 2.3 : b.isAlert ? 3.4 : 3.0;

        const badgeY = by < badgeH + 1.2 ? by + 0.4 : by - (badgeH + 0.3);
        const badgeX = Math.max(0.5, Math.min(bx, 100 - badgeW - 0.5));

        // Geometric corner brackets
        const cornerSize = Math.min(Math.max(0.3, Math.min(bw, bh) * 0.22), 3.5);
        const bracketPath = `
          M ${bx} ${by + cornerSize} L ${bx} ${by} L ${bx + cornerSize} ${by}
          M ${bx + bw - cornerSize} ${by} L ${bx + bw} ${by} L ${bx + bw} ${by + cornerSize}
          M ${bx} ${by + bh - cornerSize} L ${bx} ${by + bh} L ${bx + cornerSize} ${by + bh}
          M ${bx + bw - cornerSize} ${by + bh} L ${bx + bw} ${by + bh} L ${bx + bw} ${by + bh - cornerSize}
        `;

        // Always render labels for critical target / alerts in all presets (clean, all, alerts)
        const renderLabels =
          b.isAlert || (showLabels && activePreset !== "clean");

        const filterUrl = isSelected
          ? `url(#${fSelected})`
          : b.isFenceIntrusion
          ? `url(#${fRoi})`
          : b.isAlert
          ? `url(#${fCritical})`
          : `url(#${fBracket})`;

        return (
          <g
            key={elementKey}
            filter={filterUrl}
          >
            {/* Interactive hit area for 1-click Quick Inspector trigger */}
            <rect
              x={bx}
              y={by}
              width={bw}
              height={bh}
              fill="rgba(255,255,255,0.001)"
              className="cursor-pointer pointer-events-auto"
              onClick={(e) => {
                e.stopPropagation();
                onSelectBox?.(b);
              }}
            />

            {/* Unmistakable, high-visibility box for critical targets & alerts (purple outline for ROI intruders) */}
            {b.isAlert && (
              <>
                <rect
                  x={bx}
                  y={by}
                  width={bw}
                  height={bh}
                  fill={b.isFenceIntrusion ? "rgba(168, 85, 247, 0.18)" : "rgba(239, 68, 68, 0.14)"}
                  rx={1}
                />
                <rect
                  x={bx}
                  y={by}
                  width={bw}
                  height={bh}
                  fill="none"
                  stroke={b.isFenceIntrusion ? "#a855f7" : "#ef4444"}
                  strokeWidth={2.0}
                  rx={1}
                  vectorEffect="non-scaling-stroke"
                  data-testid={b.isFenceIntrusion ? "roi-intruder-box" : "critical-target-box"}
                  data-roi-intruder={b.isFenceIntrusion ? "true" : undefined}
                  aria-label={b.isFenceIntrusion ? "ROI intruders with a purple outline" : undefined}
                />
              </>
            )}

            {/* Fine guideline in 'all' mode */}
            {activePreset === "all" && !b.isAlert && (
              <rect
                x={bx}
                y={by}
                width={bw}
                height={bh}
                fill="none"
                stroke={theme.primary}
                strokeWidth={0.5}
                strokeDasharray="1.5 2"
                opacity={0.35}
                vectorEffect="non-scaling-stroke"
              />
            )}

            {/* Geometric Corner Brackets: Thin, clean, precise framing; reinforced for alerts */}
            <path
              d={bracketPath}
              fill="none"
              stroke={isSelected ? "#ffffff" : theme.primary}
              strokeWidth={b.isAlert ? 2.5 : isFace ? 1.4 : 1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              style={{
                transition: "stroke 200ms ease",
              }}
            />

            {/* Selected highlight frame */}
            {isSelected && (
              <rect
                x={bx - 0.5}
                y={by - 0.5}
                width={bw + 1}
                height={bh + 1}
                rx={1.2}
                fill="none"
                stroke="#ffffff"
                strokeWidth={1.2}
                strokeDasharray="2 1.5"
                vectorEffect="non-scaling-stroke"
              />
            )}

            {/* Label Micro-Badge */}
            {renderLabels && (
              <g
                className="cursor-pointer pointer-events-auto"
                data-testid={b.isFenceIntrusion ? "roi-intruder-badge" : b.isAlert ? "critical-target-badge" : undefined}
                data-roi-intruder={b.isFenceIntrusion ? "true" : undefined}
                aria-label={b.isFenceIntrusion ? "ROI intruders with a purple outline" : undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectBox?.(b);
                }}
              >
                <rect
                  x={badgeX}
                  y={badgeY}
                  width={badgeW}
                  height={badgeH}
                  fill={theme.bg}
                  stroke={isSelected ? "#ffffff" : theme.border}
                  strokeWidth={b.isAlert ? 0.8 : 0.5}
                  rx={0.6}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={badgeX + (isFace ? 0.7 : 0.9)}
                  y={badgeY + (isFace ? 1.55 : b.isAlert ? 2.3 : 2.05)}
                  fill="#f8fafc"
                  fontSize={isFace ? 1.3 : b.isAlert ? 1.9 : 1.8}
                  fontWeight={b.isAlert ? 700 : 600}
                  letterSpacing="0.02em"
                  fontFamily="-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, system-ui, sans-serif"
                >
                  <tspan
                    fill={b.isAlert ? "#ffffff" : theme.accent}
                    data-testid={b.isFenceIntrusion ? "roi-intruder-text" : b.isAlert ? "target-name-text" : undefined}
                  >
                    {formattedLabel}
                  </tspan>
                  {hasTrack && <tspan fill={b.isAlert ? "#fecaca" : "#94a3b8"} fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"> #{b.trackId}</tspan>}
                  {showConfidence && b.confidence !== undefined && (
                    <tspan fill={b.isAlert ? "#fed7aa" : "#cbd5e1"} fontSize={isFace ? 1.1 : 1.5} fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace">
                      {" "}
                      {Math.round(b.confidence * 100)}%
                    </tspan>
                  )}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
});
