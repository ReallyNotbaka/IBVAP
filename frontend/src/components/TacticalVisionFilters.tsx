import { memo } from "react";

export type TacticalVisionMode = "normal" | "white-hot" | "black-hot" | "ironbow" | "defog";

export function getTacticalFilterStyle(mode: TacticalVisionMode): React.CSSProperties {
  switch (mode) {
    case "white-hot":
      // Grayscale + boosted contrast + slight brightness
      return { filter: "grayscale(100%) contrast(220%) brightness(115%)" };
    case "black-hot":
      // Inverted grayscale + boosted contrast
      return { filter: "grayscale(100%) invert(100%) contrast(220%) brightness(110%)" };
    case "ironbow":
      // Ironbow FLIR palette via SVG filter
      return { filter: "url(#tactical-ironbow-filter) contrast(150%) brightness(105%)" };
    case "defog":
      // Tactical CLAHE / Defog: high contrast + saturation + edge clarity
      return { filter: "contrast(180%) saturate(140%) brightness(105%)" };
    case "normal":
    default:
      return {};
  }
}

export const TacticalVisionSVGDefs = memo(function TacticalVisionSVGDefs() {
  return (
    <svg className="absolute w-0 h-0 pointer-events-none" aria-hidden="true">
      <defs>
        {/* Ironbow false-color thermal simulation */}
        <filter id="tactical-ironbow-filter" colorInterpolationFilters="sRGB">
          <feColorMatrix
            type="matrix"
            values="
              0.299 0.587 0.114 0 0
              0.299 0.587 0.114 0 0
              0.299 0.587 0.114 0 0
              0     0     0     1 0
            "
          />
          <feComponentTransfer>
            {/* R: 0 at cold, rises through purple/red/yellow, saturated at heat */}
            <feFuncR
              type="table"
              tableValues="0.0 0.05 0.3 0.7 0.95 1.0 1.0 1.0"
            />
            {/* G: rises in middle heat (yellow/orange), saturated at white-hot */}
            <feFuncG
              type="table"
              tableValues="0.0 0.0 0.0 0.1 0.45 0.85 1.0 1.0"
            />
            {/* B: high at extreme cold (deep blue), drops in mid, returns at white-hot */}
            <feFuncB
              type="table"
              tableValues="0.4 0.6 0.45 0.05 0.0 0.0 0.5 1.0"
            />
          </feComponentTransfer>
        </filter>
      </defs>
    </svg>
  );
});

export interface TacticalVisionSelectorProps {
  mode: TacticalVisionMode;
  onChange: (mode: TacticalVisionMode) => void;
}

export const TacticalVisionSelector = memo(function TacticalVisionSelector({
  mode,
  onChange,
}: TacticalVisionSelectorProps) {
  const modes: { id: TacticalVisionMode; label: string; tag: string }[] = [
    { id: "normal", label: "Normal (RGB)", tag: "RGB" },
    { id: "white-hot", label: "White-Hot FLIR", tag: "W-HOT" },
    { id: "black-hot", label: "Black-Hot FLIR", tag: "B-HOT" },
    { id: "ironbow", label: "Ironbow Thermal", tag: "IRON" },
    { id: "defog", label: "Tactical Defog", tag: "DEFOG" },
  ];

  return (
    <div
      className="flex items-center bg-black/70 backdrop-blur-md rounded-lg border border-white/10 p-0.5"
      onClick={(e) => e.stopPropagation()}
      title="Tactical Vision Enhancement Mode"
    >
      {modes.map((m) => {
        const active = mode === m.id;
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => onChange(m.id)}
            className={`px-1.5 py-0.5 text-[9px] font-mono font-bold rounded transition-all cursor-pointer ${
              active
                ? "bg-emerald-500/90 text-slate-950 shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-white/10"
            }`}
            aria-label={`Select ${m.label}`}
          >
            {m.tag}
          </button>
        );
      })}
    </div>
  );
});
