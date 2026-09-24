import { useCallback, useMemo, useRef, useState } from "react";
import { clientToNorm } from "./useCanvasCoords";

export function pointToSegmentDistance(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(px - ax, py - ay);
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lenSq));
  const projX = ax + t * dx;
  const projY = ay + t * dy;
  return Math.hypot(px - projX, py - projY);
}

export function isPointInPolygon(
  px: number,
  py: number,
  poly: [number, number][],
): boolean {
  let inside = false;
  const n = poly.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    const intersect =
      yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function useFenceDrawing({
  fencePoints = [],
  fenceDrawing = false,
  onFencePoint,
  onRemoveFencePoint,
}: {
  fencePoints?: [number, number][];
  fenceDrawing?: boolean;
  onFencePoint?: (point: [number, number]) => void;
  onRemoveFencePoint?: (index: number) => void;
}) {
  const [hoverCoords, setHoverCoords] = useState<[number, number] | null>(null);
  const lastClickRef = useRef<{ time: number; x: number; y: number } | null>(null);

  const handleFenceMouseMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!fenceDrawing) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const [nx, ny] = clientToNorm(event.clientX, event.clientY, rect);
      setHoverCoords((prev) =>
        prev && Math.abs(prev[0] - nx) < 0.002 && Math.abs(prev[1] - ny) < 0.002
          ? prev
          : [nx, ny],
      );
    },
    [fenceDrawing],
  );

  const handleFenceMouseLeave = useCallback(() => {
    setHoverCoords(null);
  }, []);

  const handleFenceClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!fenceDrawing || !onFencePoint) return;
      event.preventDefault();
      event.stopPropagation();
      const rect = event.currentTarget.getBoundingClientRect();
      const [nx, ny] = clientToNorm(event.clientX, event.clientY, rect);

      const now = Date.now();
      if (lastClickRef.current) {
        const elapsed = now - lastClickRef.current.time;
        const dist = Math.hypot(nx - lastClickRef.current.x, ny - lastClickRef.current.y);
        if (elapsed < 250 || dist < 0.015) {
          return;
        }
      }
      lastClickRef.current = { time: now, x: nx, y: ny };
      onFencePoint([nx, ny]);
    },
    [fenceDrawing, onFencePoint],
  );

  const handleUndoPoint = useCallback(() => {
    if (fencePoints.length > 0) {
      onRemoveFencePoint?.(fencePoints.length - 1);
    }
  }, [fencePoints.length, onRemoveFencePoint]);

  const fencePointsStr = useMemo(
    () => fencePoints.map(([x, y]) => `${x * 100},${y * 100}`).join(" "),
    [fencePoints],
  );

  return {
    hoverCoords,
    handleFenceMouseMove,
    handleFenceMouseLeave,
    handleFenceClick,
    handleUndoPoint,
    fencePointsStr,
  };
}
