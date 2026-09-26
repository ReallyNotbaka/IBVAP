import { memo, useState, useCallback, useRef } from "react";
import {
  useCameras,
  calibrateRadar,
  base,
  type Camera,
  type RadarCalibrationRequest,
} from "../lib/api";
import { CloseIcon, CrosshairIcon, CheckCircleIcon, AlertTriangleIcon } from "./Icons";
import { clientToNorm } from "./useCanvasCoords";

export interface RadarCalibrationModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialCameraId?: string;
}

// Preset Ground Configurations [Width (m), Depth (m), Near Distance (m)]
const PRESETS = [
  { id: "lane", name: "Road Lane (3.5m × 15m)", width: 3.5, depth: 15.0, near: 5.0 },
  { id: "gate", name: "Perimeter Gate (6.0m × 20m)", width: 6.0, depth: 20.0, near: 5.0 },
  { id: "sector", name: "Wide Sector (15.0m × 30m)", width: 15.0, depth: 30.0, near: 10.0 },
];

export const RadarCalibrationModal = memo(function RadarCalibrationModal({
  isOpen,
  onClose,
  initialCameraId,
}: RadarCalibrationModalProps) {
  const { data: cameras = [] } = useCameras(isOpen);
  const [selectedCameraId, setSelectedCameraId] = useState<string>(
    initialCameraId || (cameras[0]?.id ?? "")
  );

  // 4 image points [u, v] normalized between 0 and 1
  // Sequence: [Near Left, Near Right, Far Right, Far Left]
  const [points, setPoints] = useState<[number, number][]>([
    [0.25, 0.85], // Near Left
    [0.75, 0.85], // Near Right
    [0.65, 0.35], // Far Right
    [0.35, 0.35], // Far Left
  ]);

  const [activePointIdx, setActivePointIdx] = useState<number | null>(null);
  const [presetId, setPresetId] = useState<string>("lane");
  const [customWidth, setCustomWidth] = useState<number>(4.0);
  const [customDepth, setCustomDepth] = useState<number>(20.0);
  const [customNear, setCustomNear] = useState<number>(5.0);
  const [azimuthDeg, setAzimuthDeg] = useState<number>(0.0);

  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const videoContainerRef = useRef<HTMLDivElement>(null);

  const activeCamera = cameras.find((c: Camera) => c.id === selectedCameraId) || cameras[0];

  // Derive ground points in meters from selected preset or custom values
  const getGroundPoints = useCallback((): [number, number][] => {
    let w = customWidth;
    let d = customDepth;
    let near = customNear;

    const pr = PRESETS.find((p) => p.id === presetId);
    if (pr) {
      w = pr.width;
      d = pr.depth;
      near = pr.near;
    }

    const halfW = w / 2.0;
    const far = near + d;

    // 4 ground points in meters [X, Y]:
    // P1: Near Left, P2: Near Right, P3: Far Right, P4: Far Left
    return [
      [-halfW, near],
      [halfW, near],
      [halfW, far],
      [-halfW, far],
    ];
  }, [presetId, customWidth, customDepth, customNear]);

  const handleContainerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!videoContainerRef.current) return;
    const rect = videoContainerRef.current.getBoundingClientRect();
    const [u, v] = clientToNorm(e.clientX, e.clientY, rect);

    if (activePointIdx !== null) {
      // Reposition selected point
      const next = [...points] as [number, number][];
      next[activePointIdx] = [u, v];
      setPoints(next);
      setActivePointIdx(null);
    } else if (points.length < 4) {
      setPoints([...points, [u, v]]);
    }
  };

  const handleSaveCalibration = async () => {
    if (points.length < 4) {
      setStatusMessage({ type: "error", text: "Please set all 4 calibration points on the video stream." });
      return;
    }
    if (!activeCamera) return;

    setSaving(true);
    setStatusMessage(null);

    try {
      const ground = getGroundPoints();
      const payload: RadarCalibrationRequest = {
        camera_id: activeCamera.id,
        image_points: points,
        ground_points: ground,
        azimuth_deg: azimuthDeg,
      };

      await calibrateRadar(payload);
      setStatusMessage({
        type: "success",
        text: `Homography calibrated successfully for "${activeCamera.name}". Radar projection active!`,
      });
      setTimeout(() => {
        setStatusMessage(null);
      }, 3500);
    } catch (err: unknown) {
      setStatusMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to calibrate radar.",
      });
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  const pointLabels = [
    { label: "P1: Near Left", color: "#3b82f6" },
    { label: "P2: Near Right", color: "#10b981" },
    { label: "P3: Far Right", color: "#f59e0b" },
    { label: "P4: Far Left", color: "#ec4899" },
  ];

  const polygonPointsStr =
    points.length >= 3 ? points.map(([x, y]) => `${x * 100}%,${y * 100}%`).join(" ") : "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 modal-backdrop-animate font-sans"
      onClick={onClose}
    >
      <div
        className="modal-content-animate relative w-full max-w-4xl rounded-2xl border border-emerald-500/30 bg-slate-950 text-slate-100 shadow-2xl overflow-hidden flex flex-col max-h-[92vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-emerald-500/20 px-6 py-4 bg-slate-900/60">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-950/80 border border-emerald-500/40 text-emerald-400">
              <CrosshairIcon className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold tracking-tight text-emerald-400 font-mono">
                Visual 4-Point Homography Calibration
              </h2>
              <p className="text-xs text-slate-400">
                Calibrate Bird's-Eye View (BEV) 2D radar coordinates by mapping 4 ground boundary points
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors cursor-pointer"
          >
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>

        {/* Status notification */}
        {statusMessage && (
          <div
            className={`mx-6 mt-4 p-3 rounded-xl border flex items-center gap-2 text-xs font-mono ${
              statusMessage.type === "success"
                ? "bg-emerald-950/60 border-emerald-500/50 text-emerald-300"
                : "bg-rose-950/60 border-rose-500/50 text-rose-300"
            }`}
          >
            {statusMessage.type === "success" ? (
              <CheckCircleIcon className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            ) : (
              <AlertTriangleIcon className="w-4 h-4 text-rose-400 flex-shrink-0" />
            )}
            <span>{statusMessage.text}</span>
          </div>
        )}

        {/* Main Body */}
        <div className="flex-1 overflow-y-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Video Canvas Area (7 Cols) */}
          <div className="lg:col-span-8 flex flex-col gap-2">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-1">
              <span>Interactive Camera Viewport</span>
              <span className="text-emerald-400">
                {activePointIdx !== null
                  ? `Click to reposition ${pointLabels[activePointIdx].label}`
                  : "Click video or handles to adjust calibration polygon"}
              </span>
            </div>

            <div
              ref={videoContainerRef}
              onClick={handleContainerClick}
              className="relative w-full aspect-video rounded-xl overflow-hidden border border-slate-800 bg-black cursor-crosshair select-none shadow-inner"
            >
              {activeCamera ? (
                <img
                  src={base(`/api/v1/cameras/${activeCamera.id}/stream`)}
                  alt={activeCamera.name}
                  className="w-full h-full object-contain pointer-events-none"
                  onError={(e) => {
                    // Fallback placeholder pattern if camera is offline
                    e.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <div className="flex items-center justify-center h-full text-xs text-slate-500">
                  No Camera Selected
                </div>
              )}

              {/* Homography Calibration SVG Layer */}
              <svg className="absolute inset-0 w-full h-full pointer-events-none">
                {/* Ground Polygon Fill */}
                {polygonPointsStr && (
                  <polygon
                    points={polygonPointsStr}
                    fill="rgba(16, 185, 129, 0.15)"
                    stroke="rgba(52, 211, 153, 0.8)"
                    strokeWidth="2"
                    strokeDasharray="4 2"
                  />
                )}

                {/* Perspective Guide Lines */}
                {points.length === 4 && (
                  <>
                    {/* Near to Far left */}
                    <line
                      x1={`${points[0][0] * 100}%`}
                      y1={`${points[0][1] * 100}%`}
                      x2={`${points[3][0] * 100}%`}
                      y2={`${points[3][1] * 100}%`}
                      stroke="rgba(59, 130, 246, 0.6)"
                      strokeWidth="1.5"
                    />
                    {/* Near to Far right */}
                    <line
                      x1={`${points[1][0] * 100}%`}
                      y1={`${points[1][1] * 100}%`}
                      x2={`${points[2][0] * 100}%`}
                      y2={`${points[2][1] * 100}%`}
                      stroke="rgba(245, 158, 11, 0.6)"
                      strokeWidth="1.5"
                    />
                  </>
                )}
              </svg>

              {/* Draggable Point Markers */}
              {points.map(([u, v], idx) => {
                const isActive = activePointIdx === idx;
                const info = pointLabels[idx] || { label: `P${idx + 1}`, color: "#ffffff" };
                return (
                  <div
                    key={idx}
                    onClick={(e) => {
                      e.stopPropagation();
                      setActivePointIdx(isActive ? null : idx);
                    }}
                    style={{
                      left: `${u * 100}%`,
                      top: `${v * 100}%`,
                      transform: "translate(-50%, -50%)",
                      borderColor: info.color,
                    }}
                    className={`absolute w-7 h-7 rounded-full border-2 flex items-center justify-center font-mono font-bold text-[10px] text-white shadow-lg cursor-pointer transition-transform ${
                      isActive ? "scale-125 ring-4 ring-white/30" : "hover:scale-110"
                    }`}
                  >
                    <div
                      className="w-full h-full rounded-full flex items-center justify-center"
                      style={{ backgroundColor: `${info.color}cc` }}
                    >
                      {idx + 1}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Point Legend & Coordinate Details */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2">
              {pointLabels.map((p, i) => (
                <div
                  key={i}
                  onClick={() => setActivePointIdx(activePointIdx === i ? null : i)}
                  className={`p-2 rounded-lg border text-xs cursor-pointer transition-colors ${
                    activePointIdx === i
                      ? "bg-slate-800 border-white/40 text-white"
                      : "bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center gap-1.5 font-mono font-bold">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: p.color }} />
                    <span>{p.label}</span>
                  </div>
                  <div className="text-[10px] font-mono text-slate-400 mt-0.5">
                    {points[i]
                      ? `[${Math.round(points[i][0] * 100)}%, ${Math.round(points[i][1] * 100)}%]`
                      : "Not set"}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Calibration Settings & Geometry Presets (4 Cols) */}
          <div className="lg:col-span-4 flex flex-col justify-between space-y-4">
            <div className="space-y-4">
              {/* Camera Selection */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1 font-mono">
                  Select Camera Feed
                </label>
                <select
                  value={selectedCameraId}
                  onChange={(e) => setSelectedCameraId(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 focus:border-emerald-500 focus:outline-none font-mono cursor-pointer"
                >
                  {cameras.map((c: Camera) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.id.slice(0, 8)})
                    </option>
                  ))}
                </select>
              </div>

              {/* Ground Geometry Preset */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1 font-mono">
                  Ground Plane Geometry Preset
                </label>
                <div className="space-y-1.5">
                  {PRESETS.map((pr) => (
                    <button
                      key={pr.id}
                      type="button"
                      onClick={() => setPresetId(pr.id)}
                      className={`w-full text-left px-3 py-2 rounded-xl text-xs font-mono border transition-all cursor-pointer ${
                        presetId === pr.id
                          ? "bg-emerald-950/60 border-emerald-500 text-emerald-300 shadow-xs"
                          : "bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700"
                      }`}
                    >
                      <div className="font-bold">{pr.name}</div>
                      <div className="text-[10px] text-slate-500">
                        {pr.width}m width × {pr.depth}m range from {pr.near}m
                      </div>
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => setPresetId("custom")}
                    className={`w-full text-left px-3 py-2 rounded-xl text-xs font-mono border transition-all cursor-pointer ${
                      presetId === "custom"
                        ? "bg-emerald-950/60 border-emerald-500 text-emerald-300 shadow-xs"
                        : "bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700"
                    }`}
                  >
                    <div className="font-bold">Custom Dimensions</div>
                    <div className="text-[10px] text-slate-500">Specify custom metric width & depth</div>
                  </button>
                </div>
              </div>

              {/* Custom Dimensions Input if selected */}
              {presetId === "custom" && (
                <div className="grid grid-cols-3 gap-2 p-3 bg-slate-900/80 border border-slate-800 rounded-xl">
                  <div>
                    <label className="text-[10px] font-mono text-slate-400 block mb-1">Width (m)</label>
                    <input
                      type="number"
                      step="0.5"
                      min="1"
                      value={customWidth}
                      onChange={(e) => setCustomWidth(parseFloat(e.target.value) || 1)}
                      className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-slate-400 block mb-1">Depth (m)</label>
                    <input
                      type="number"
                      step="1"
                      min="1"
                      value={customDepth}
                      onChange={(e) => setCustomDepth(parseFloat(e.target.value) || 5)}
                      className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-slate-400 block mb-1">Near (m)</label>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={customNear}
                      onChange={(e) => setCustomNear(parseFloat(e.target.value) || 0)}
                      className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs font-mono"
                    />
                  </div>
                </div>
              )}

              {/* Camera Heading / Azimuth */}
              <div>
                <div className="flex items-center justify-between text-xs font-semibold text-slate-300 mb-1 font-mono">
                  <span>Camera Optical Heading (Azimuth)</span>
                  <span className="text-emerald-400">{azimuthDeg}°</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="359"
                  value={azimuthDeg}
                  onChange={(e) => setAzimuthDeg(parseInt(e.target.value))}
                  className="w-full accent-emerald-500 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] font-mono text-slate-500">
                  <span>0° (N)</span>
                  <span>90° (E)</span>
                  <span>180° (S)</span>
                  <span>270° (W)</span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-2 pt-4 border-t border-slate-800">
              <button
                type="button"
                onClick={handleSaveCalibration}
                disabled={saving || points.length < 4}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-emerald-500 hover:bg-emerald-600 active:scale-[0.98] text-slate-950 font-mono font-bold text-xs py-2.5 px-4 shadow-lg shadow-emerald-500/20 disabled:opacity-50 transition-all cursor-pointer"
              >
                <CrosshairIcon className="w-4 h-4" />
                <span>{saving ? "Computing Matrix..." : "Apply & Save Calibration"}</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setPoints([
                    [0.25, 0.85],
                    [0.75, 0.85],
                    [0.65, 0.35],
                    [0.35, 0.35],
                  ]);
                  setActivePointIdx(null);
                }}
                className="w-full rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white font-mono text-xs py-2 transition-colors cursor-pointer"
              >
                Reset Default Points
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});
