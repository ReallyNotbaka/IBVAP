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
}

interface ColorTheme {
  primary: string;
  halo: string;
  bg: string;
  accent: string;
  border: string;
}

function getColorTheme(label: string, isAlert?: boolean): ColorTheme {
  if (isAlert) {
    return {
      primary: "#ef4444", // Vivid Crimson for true security alerts
      halo: "rgba(0, 0, 0, 0.9)",
      bg: "rgba(185, 28, 28, 0.94)",
      accent: "#fecaca",
      border: "rgba(239, 68, 68, 0.8)",
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

  // Normal pedestrians, vehicles, and general objects: elegant quiet champagne/neutral
  return {
    primary: "#dfd5c6",
    halo: "rgba(0, 0, 0, 0.85)",
    bg: "rgba(18, 21, 28, 0.90)",
    accent: "#dfd5c6",
    border: "rgba(223, 213, 198, 0.35)",
  };
}

export function OverlayCanvas({
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

  const filteredBoxes = boxes.filter((b) => {
    const isFace = b.label.toLowerCase() === "face";
    const isPerson =
      b.label.toLowerCase() === "person" || b.label.toLowerCase() === "human";

    if (activePreset === "alerts" && !b.isAlert) {
      return false;
    }
    if (isFace && !showFaces) return false;
    if (isPerson && !showPeople && !b.isAlert) return false;

    return true;
  });

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
        <filter id="geometric-bracket-shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="0" stdDeviation="0.8" floodColor="#000000" floodOpacity="0.85" />
        </filter>
        <filter id="selected-target-glow" x="-25%" y="-25%" width="150%" height="150%">
          <feDropShadow dx="0" dy="0" stdDeviation="1.2" floodColor="#ffffff" floodOpacity="0.9" />
        </filter>
      </defs>

      {filteredBoxes.map((b, idx) => {
        const theme = getColorTheme(b.label, b.isAlert);
        const bx = b.x * 100;
        const by = b.y * 100;
        const bw = b.w * 100;
        const bh = b.h * 100;

        const isFace = b.label.toLowerCase() === "face";
        const hasTrack = Boolean(b.trackId);
        const isSelected = Boolean(selectedTrackId && b.trackId === selectedTrackId);
        const elementKey = b.trackId
          ? `track-${b.trackId}`
          : `det-${b.label}-${idx}`;

        // Micro-badge sizing
        const formattedLabel = b.isAlert
          ? b.label
          : b.label.charAt(0).toUpperCase() + b.label.slice(1).toLowerCase();
        const charCount =
          formattedLabel.length +
          (hasTrack ? 3 : 0) +
          (showConfidence && b.confidence !== undefined ? 4 : 0);
        const badgeW = isFace
          ? Math.max(5.5, charCount * 0.95 + 1.2)
          : Math.max(9.5, charCount * 1.3 + 1.8);
        const badgeH = isFace ? 2.3 : 3.0;

        const badgeY = by < badgeH + 1.2 ? by + 0.4 : by - (badgeH + 0.3);
        const badgeX = Math.max(0.5, Math.min(bx, 100 - badgeW - 0.5));

        // Thin, elegant geometric corner brackets (no loud colored fill rectangles)
        const cornerSize = Math.min(Math.max(0.3, Math.min(bw, bh) * 0.22), 3.5);
        const bracketPath = `
          M ${bx} ${by + cornerSize} L ${bx} ${by} L ${bx + cornerSize} ${by}
          M ${bx + bw - cornerSize} ${by} L ${bx + bw} ${by} L ${bx + bw} ${by + cornerSize}
          M ${bx} ${by + bh - cornerSize} L ${bx} ${by + bh} L ${bx + cornerSize} ${by + bh}
          M ${bx + bw - cornerSize} ${by + bh} L ${bx + bw} ${by + bh} L ${bx + bw} ${by + bh - cornerSize}
        `;

        const renderLabels =
          b.isAlert || (showLabels && activePreset !== "clean");

        return (
          <g
            key={elementKey}
            filter={isSelected ? "url(#selected-target-glow)" : "url(#geometric-bracket-shadow)"}
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

            {/* Subtle alert wash if and only if true security alert */}
            {b.isAlert && (
              <rect
                x={bx}
                y={by}
                width={bw}
                height={bh}
                fill="rgba(239, 68, 68, 0.08)"
                rx={1}
              />
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

            {/* Geometric Corner Brackets: Thin, clean, precise framing */}
            <path
              d={bracketPath}
              fill="none"
              stroke={isSelected ? "#ffffff" : theme.primary}
              strokeWidth={isFace ? 1.4 : 1.5}
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
                  strokeWidth={0.5}
                  rx={0.6}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={badgeX + (isFace ? 0.7 : 0.9)}
                  y={badgeY + (isFace ? 1.55 : 2.05)}
                  fill="#f8fafc"
                  fontSize={isFace ? 1.3 : 1.8}
                  fontWeight={600}
                  letterSpacing="0.02em"
                  fontFamily="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
                >
                  <tspan fill={theme.accent}>{formattedLabel}</tspan>
                  {hasTrack && <tspan fill="#94a3b8"> #{b.trackId}</tspan>}
                  {showConfidence && b.confidence !== undefined && (
                    <tspan fill="#cbd5e1" fontSize={isFace ? 1.1 : 1.5}>
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
}
