import { memo, useMemo, useState } from "react";
import { useTacticalRadar, type RadarBlip } from "../lib/api";
import { CloseIcon, CrosshairIcon } from "./Icons";
import { RadarCalibrationModal } from "./RadarCalibrationModal";

export interface TacticalRadarModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialCameraId?: string;
}

export const TacticalRadarModal = memo(function TacticalRadarModal({
  isOpen,
  onClose,
  initialCameraId,
}: TacticalRadarModalProps) {
  const { data: radarData } = useTacticalRadar(isOpen);
  const [selectedBlip, setSelectedBlip] = useState<RadarBlip | null>(null);
  const [calibrationOpen, setCalibrationOpen] = useState(false);

  const blips = radarData?.blips ?? [];
  const cameras = radarData?.cameras ?? [];
  const rangeRings = radarData?.range_rings_m ?? [10, 25, 50, 100];
  const maxRange = radarData?.max_range_m ?? 100;

  // Radar Center & Radius in SVG units
  const cx = 250;
  const cy = 250;
  const radarRadius = 220;

  // Map meters to SVG distance from center
  const metersToRadius = (m: number) => (m / maxRange) * radarRadius;

  // Convert (x_m, y_m) to SVG (cx + dx, cy - dy) (North is up: +Y is North, +X is East)
  const toSvgCoords = (x_m: number, y_m: number) => {
    const scale = radarRadius / maxRange;
    return {
      x: cx + x_m * scale,
      y: cy - y_m * scale,
    };
  };

  const threatCounts = useMemo(() => {
    let critical = 0;
    let high = 0;
    let normal = 0;
    for (const b of blips) {
      if (b.is_intrusion || b.threat_level === "CRITICAL") critical++;
      else if (b.threat_level === "HIGH" || b.threat_level === "MEDIUM") high++;
      else normal++;
    }
    return { critical, high, normal, total: blips.length };
  }, [blips]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md modal-backdrop-animate"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-5xl rounded-3xl border border-emerald-500/30 bg-slate-950/95 p-5 shadow-2xl text-slate-100 flex flex-col gap-4 overflow-hidden modal-content-animate font-sans"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Radar Ambient Glow Header */}
        <div className="flex items-center justify-between border-b border-emerald-500/20 pb-3">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500 shadow-[0_0_12px_#10b981]" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-black uppercase tracking-wider text-emerald-400 font-mono">
                  Tactical 2D Bird's-Eye-View (BEV) Radar
                </h2>
                <span className="text-[10px] font-mono bg-emerald-950/80 border border-emerald-500/30 px-2 py-0.5 rounded text-emerald-300">
                  HOMOGRAPHY COORD MAPPING
                </span>
              </div>
              <p className="text-[11px] text-slate-400 font-mono">
                Real-time Planar Ground Coordinate Projection (Range: {maxRange}m)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-2 text-xs font-mono">
              <span className="text-rose-400 font-bold">[{threatCounts.critical} BREACH]</span>
              <span className="text-amber-400 font-bold">[{threatCounts.high} SUSPECT]</span>
              <span className="text-emerald-400 font-bold">[{threatCounts.total} ACTIVE BLIPS]</span>
            </div>
            <button
              type="button"
              onClick={() => setCalibrationOpen(true)}
              className="px-2.5 py-1 text-xs font-mono font-bold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 border border-emerald-500/40 rounded-lg transition-colors cursor-pointer flex items-center gap-1.5"
              title="Calibrate 4-point homography for radar"
            >
              <CrosshairIcon className="w-3.5 h-3.5" />
              <span>Calibrate Camera</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
              title="Close Radar"
            >
              <CloseIcon className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content: Radar Screen (Left/Center) + Blip Dossier List (Right) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-center">
          {/* Circular Radar Screen */}
          <div className="lg:col-span-7 flex justify-center items-center relative py-2">
            <div className="relative w-[340px] h-[340px] sm:w-[480px] sm:h-[480px] rounded-full border-2 border-emerald-500/40 bg-slate-950 shadow-[0_0_40px_rgba(16,185,129,0.15)] flex items-center justify-center overflow-hidden">
              {/* Radar Rotating Sweep Line */}
              <div className="absolute inset-0 rounded-full pointer-events-none animate-spin [animation-duration:4s] [animation-timing-function:linear]">
                <div className="w-1/2 h-1/2 ml-auto origin-bottom-left bg-gradient-to-br from-emerald-500/30 via-emerald-500/5 to-transparent clip-radar-wedge" />
                <div className="w-1/2 h-[2px] ml-auto origin-bottom-left bg-emerald-400/80 shadow-[0_0_8px_#34d399]" />
              </div>

              {/* Radar SVG Grid, Rings, Sectors, and Blips */}
              <svg className="absolute inset-0 w-full h-full" viewBox="0 0 500 500">
                {/* Crosshairs */}
                <line x1={cx} y1={20} x2={cx} y2={480} stroke="#065f46" strokeWidth="1" strokeDasharray="3,3" />
                <line x1={20} y1={cy} x2={480} y2={cy} stroke="#065f46" strokeWidth="1" strokeDasharray="3,3" />

                {/* Range Rings */}
                {rangeRings.map((r) => {
                  const rad = metersToRadius(r);
                  return (
                    <g key={r}>
                      <circle cx={cx} cy={cy} r={rad} fill="none" stroke="#047857" strokeWidth="1" opacity="0.4" />
                      <text x={cx + 4} y={cy - rad + 12} fill="#34d399" fontSize="9" fontFamily="monospace" opacity="0.75">
                        {r}m
                      </text>
                    </g>
                  );
                })}

                {/* Cardinal Markers */}
                <text x={cx} y={16} fill="#10b981" fontSize="11" fontWeight="bold" fontFamily="monospace" textAnchor="middle">
                  N (000°)
                </text>
                <text x={485} y={cy + 4} fill="#10b981" fontSize="11" fontWeight="bold" fontFamily="monospace">
                  E (090°)
                </text>
                <text x={cx} y={495} fill="#10b981" fontSize="11" fontWeight="bold" fontFamily="monospace" textAnchor="middle">
                  S (180°)
                </text>
                <text x={4} y={cy + 4} fill="#10b981" fontSize="11" fontWeight="bold" fontFamily="monospace">
                  W (270°)
                </text>

                {/* Camera FOV Sector Cones */}
                {cameras.map((cam) => {
                  const azRad = (cam.azimuth_deg - 90) * (Math.PI / 180);
                  const halfFovRad = (cam.fov_deg / 2) * (Math.PI / 180);
                  const startAngle = azRad - halfFovRad;
                  const endAngle = azRad + halfFovRad;
                  const coneR = metersToRadius(cam.range_m || 80);

                  const x1 = cx + coneR * Math.cos(startAngle);
                  const y1 = cy + coneR * Math.sin(startAngle);
                  const x2 = cx + coneR * Math.cos(endAngle);
                  const y2 = cy + coneR * Math.sin(endAngle);

                  return (
                    <g key={cam.camera_id} opacity="0.3">
                      <path
                        d={`M ${cx} ${cy} L ${x1} ${y1} A ${coneR} ${coneR} 0 0 1 ${x2} ${y2} Z`}
                        fill="rgba(16, 185, 129, 0.08)"
                        stroke="#10b981"
                        strokeWidth="1"
                        strokeDasharray="2,2"
                      />
                      <text x={(x1 + x2) / 2} y={(y1 + y2) / 2} fill="#6ee7b7" fontSize="9" fontFamily="monospace" textAnchor="middle">
                        {cam.name}
                      </text>
                    </g>
                  );
                })}

                {/* Tactical Target Blips */}
                {blips.map((blip) => {
                  const { x, y } = toSvgCoords(blip.x_m, blip.y_m);
                  const isSelected = selectedBlip?.track_id === blip.track_id;
                  const isCrit = blip.is_intrusion || blip.threat_level === "CRITICAL";
                  const isHigh = blip.threat_level === "HIGH" || blip.threat_level === "MEDIUM";

                  const blipColor = isCrit ? "#ef4444" : isHigh ? "#f59e0b" : "#10b981";

                  return (
                    <g
                      key={`${blip.camera_id}-${blip.track_id}`}
                      className="cursor-pointer transition-transform hover:scale-125"
                      onClick={() => setSelectedBlip(blip)}
                    >
                      {/* Pulsing Outer Halo */}
                      <circle
                        cx={x}
                        cy={y}
                        r={isSelected ? 10 : 7}
                        fill={blipColor}
                        opacity={isCrit ? "0.4" : "0.25"}
                        className="animate-ping"
                      />
                      {/* Solid Core Dot */}
                      <circle
                        cx={x}
                        cy={y}
                        r={isSelected ? 5 : 4}
                        fill={blipColor}
                        stroke="#ffffff"
                        strokeWidth={isSelected ? 2 : 1}
                      />
                      {/* Target Label Callout */}
                      <text
                        x={x + 7}
                        y={y - 4}
                        fill={blipColor}
                        fontSize="9"
                        fontWeight="bold"
                        fontFamily="monospace"
                        className="drop-shadow-md"
                      >
                        #{blip.track_id} {blip.identity || blip.class_name.toUpperCase()}
                      </text>
                    </g>
                  );
                })}
              </svg>

              {/* Center Tower Sensor Dot */}
              <div className="absolute w-3 h-3 rounded-full bg-emerald-400 shadow-[0_0_10px_#10b981] border-2 border-slate-950 z-10" />
            </div>
          </div>

          {/* Right Panel: Active Blip Target Telemetry List */}
          <div className="lg:col-span-5 flex flex-col gap-3 h-full max-h-[460px] overflow-hidden">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400 border-b border-white/10 pb-2">
              <span>TARGET DIRECTORY ({blips.length})</span>
              <span>RANGE / AZIMUTH</span>
            </div>

            <div className="flex-1 overflow-y-auto pr-1 space-y-2">
              {blips.length === 0 ? (
                <div className="p-8 text-center text-slate-500 font-mono text-xs border border-white/5 rounded-2xl">
                  No active contacts inside calibrated radar perimeter sector.
                </div>
              ) : (
                blips.map((blip) => {
                  const isCrit = blip.is_intrusion || blip.threat_level === "CRITICAL";
                  const isSelected = selectedBlip?.track_id === blip.track_id;

                  return (
                    <div
                      key={`${blip.camera_id}-${blip.track_id}`}
                      onClick={() => setSelectedBlip(blip)}
                      className={`p-3 rounded-xl border transition-all cursor-pointer font-mono text-xs ${
                        isSelected
                          ? "bg-emerald-950/60 border-emerald-500 text-emerald-200 shadow-md"
                          : isCrit
                          ? "bg-rose-950/30 border-rose-500/40 text-rose-200 hover:bg-rose-900/30"
                          : "bg-slate-900/60 border-white/10 text-slate-300 hover:bg-slate-800/60"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`w-2 h-2 rounded-full ${
                              isCrit ? "bg-rose-500 animate-ping" : "bg-emerald-400"
                            }`}
                          />
                          <span className="font-bold">
                            #{blip.track_id} {blip.identity || blip.class_name.toUpperCase()}
                          </span>
                        </div>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase ${
                            isCrit
                              ? "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                              : "bg-slate-800 text-slate-400"
                          }`}
                        >
                          {blip.threat_level}
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 mt-2 text-[11px] text-slate-400">
                        <div>
                          Range: <span className="text-slate-100 font-semibold">{blip.distance_m}m</span>
                        </div>
                        <div>
                          Bearing: <span className="text-slate-100 font-semibold">{blip.bearing_deg}°</span>
                        </div>
                        <div>
                          Cartesian: <span className="text-slate-100">X:{blip.x_m}m Y:{blip.y_m}m</span>
                        </div>
                        <div>
                          Sensor: <span className="text-slate-100">{blip.camera_name}</span>
                        </div>
                      </div>

                      {blip.is_intrusion && (
                        <div className="mt-2 text-[10px] text-rose-300 bg-rose-900/40 border border-rose-500/30 rounded px-2 py-0.5">
                          GEOFENCE / TRIPWIRE BREACH DETECTED
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* Selected Blip Interdiction Quick Action */}
            {selectedBlip && (
              <div className="p-3 bg-slate-900 border border-emerald-500/40 rounded-2xl flex items-center justify-between text-xs">
                <div>
                  <div className="font-mono text-emerald-400 font-bold">
                    LOCKED: #{selectedBlip.track_id} ({selectedBlip.class_name.toUpperCase()})
                  </div>
                  <div className="text-[11px] text-slate-400">
                    Bearing {selectedBlip.bearing_deg}° @ {selectedBlip.distance_m}m
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedBlip(null)}
                  className="px-2.5 py-1 text-[11px] font-mono bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors cursor-pointer"
                >
                  Clear Lock
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Visual Homography Calibration Modal */}
      <RadarCalibrationModal
        isOpen={calibrationOpen}
        onClose={() => setCalibrationOpen(false)}
        initialCameraId={initialCameraId}
      />
    </div>
  );
});
