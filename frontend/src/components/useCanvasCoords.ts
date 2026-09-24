import type { CSSProperties } from "react";
import type { Box } from "./OverlayCanvas";

export function clampNorm(val: number): number {
  return Math.max(0, Math.min(1, val));
}

export function clientToNorm(
  clientX: number,
  clientY: number,
  rect: DOMRect,
): [number, number] {
  if (!rect.width || !rect.height) return [0, 0];
  return [
    clampNorm((clientX - rect.left) / rect.width),
    clampNorm((clientY - rect.top) / rect.height),
  ];
}

export function getInspectorStyle(
  box: { x: number; y: number; w: number; h: number } | null,
): CSSProperties | undefined {
  if (!box) return undefined;
  const top = `${Math.min(Math.max(box.y * 100, 12), 55)}%`;
  if (box.x * 100 > 55) {
    return {
      top,
      right: `${Math.min(Math.max(100 - box.x * 100 + 2, 4), 60)}%`,
      maxWidth: "min(280px, calc(100% - 24px))",
    };
  }
  return {
    top,
    left: `${Math.min(Math.max((box.x + box.w) * 100 + 2, 4), 60)}%`,
    maxWidth: "min(280px, calc(100% - 24px))",
  };
}

export function createFallbackThumb(_box: Box, _size = 160): string {
  return "";
}
