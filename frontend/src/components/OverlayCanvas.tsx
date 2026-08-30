type Box = { x: number; y: number; w: number; h: number; label: string; confidence?: number; trackId?: string };

export function OverlayCanvas({ boxes, mode = "operational" }: { boxes: Box[]; mode?: string }) {
  if (!boxes.length) return null;
  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
      {boxes.map((b, i) => (
        <g key={i}>
          <rect x={b.x * 100} y={b.y * 100} width={b.w * 100} height={b.h * 100} fill="none" stroke="#0f766e" strokeWidth={0.6} vectorEffect="non-scaling-stroke" />
          {mode !== "minimal" && (
            <g>
              <rect x={b.x * 100} y={Math.max(0, b.y * 100 - 5)} width={Math.max(14, b.label.length * 1.2)} height={4} fill="rgba(15,23,42,0.75)" rx={0.6} />
              <text x={b.x * 100 + 0.6} y={b.y * 100 - 1.6} fill="white" fontSize={2.2} fontWeight={600}>
                {b.label}
                {b.confidence !== undefined ? ` ${(b.confidence * 100).toFixed(0)}%` : ""}
                {b.trackId ? ` #${b.trackId}` : ""}
              </text>
            </g>
          )}
        </g>
      ))}
    </svg>
  );
}
