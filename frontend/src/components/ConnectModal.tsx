import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { testCamera, createCamera } from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";
import {
  CameraIcon,
  CloseIcon,
  ArrowLeftIcon,
  CheckCircleIcon,
  AlertTriangleIcon,
} from "./Icons";

// Add-camera dialog. Handles phones (DroidCam :4747 / IP Webcam :8080) plus
// normal RTSP cams. Builds http://ip:port/path, hits POST /cameras/test,
// shows probe result, then POST /cameras on save. Port presets fill in
// protocol + /video automatically so users don't have to remember it.
export const ConnectModal = memo(function ConnectModal() {
  const nav = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const open = loc.pathname === "/connect/phone";
  const [address, setAddress] = useState("");
  const [port, setPort] = useState("");
  const [protocol, setProtocol] = useState("");
  const [streamPath, setStreamPath] = useState("video");
  const [temporary, setTemporary] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showAuth, setShowAuth] = useState(false);
  const [result, setResult] = useState<null | { result: string; reason_code?: string; safe_message: string; stages: { name: string; status: string }[]; probe?: { width: number; height: number; fps: number | null; codec: string } }>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") nav("/");
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [open, nav]);

  const applyPreset = useCallback((presetAddr: string, presetPort: string, presetProto: string, presetPath: string) => {
    setAddress(presetAddr);
    setPort(presetPort);
    setProtocol(presetProto);
    setStreamPath(presetPath);
    setResult(null);
    setSaveError("");
  }, []);

  const handleAddressChange = useCallback((raw: string) => {
    const trimmed = raw.trim();
    let candidate = trimmed;
    if (!candidate.includes("://") && (candidate.includes(":") || candidate.includes("/"))) {
      candidate = "http://" + candidate;
    }
    try {
      const parsed = new URL(candidate);
      if (parsed.hostname) {
        setAddress(parsed.hostname);
        if (parsed.port) {
          setPort(parsed.port);
          if (parsed.port === "4747" || parsed.port === "8080") {
            setProtocol("http");
            setStreamPath(parsed.pathname.replace(/^\/+/, "") || "video");
          } else if (parsed.port === "554") {
            setProtocol("rtsp");
          }
        }
        if (trimmed.includes("://") && parsed.protocol && ["http:", "https:", "rtsp:", "rtsps:"].includes(parsed.protocol)) {
          setProtocol(parsed.protocol.replace(":", ""));
        }
        const p = parsed.pathname.replace(/^\/+/, "");
        if (p) setStreamPath(p);
        return;
      }
    } catch {
      // fallback to plain input
    }
    setAddress(raw);
  }, []);

  const handlePortChange = useCallback((val: string) => {
    const clean = val.replace(/\D/g, "");
    setPort(clean);
    setProtocol((prev) => {
      if ((clean === "4747" || clean === "8080") && !prev) return "http";
      if (clean === "554" && !prev) return "rtsp";
      return prev;
    });
    setStreamPath((prev) => {
      if ((clean === "4747" || clean === "8080") && !prev) return "video";
      return prev;
    });
  }, []);

  const doTest = useCallback(async () => {
    const cleanAddress = address.trim();
    const cleanPort = port.trim();
    let cleanProtocol = protocol.trim();
    let cleanPath = streamPath.trim().replace(/^\/+/, "");

    if ((cleanPort === "4747" || cleanPort === "8080") && !cleanProtocol) {
      cleanProtocol = "http";
      setProtocol("http");
    } else if (cleanPort === "554" && !cleanProtocol) {
      cleanProtocol = "rtsp";
      setProtocol("rtsp");
    }
    if ((cleanPort === "4747" || cleanPort === "8080") && !cleanPath) {
      cleanPath = "video";
      setStreamPath("video");
    }

    if (!cleanAddress || !cleanPort || !cleanProtocol) {
      setResult({ result: "error", safe_message: "Enter the device IP, port, and protocol before testing.", stages: [] });
      setStep(1);
      return;
    }

    const endpoint = `${cleanProtocol}://${cleanAddress}:${cleanPort}${cleanPath ? `/${cleanPath}` : ""}`;

    setLoading(true);
    setStep(3);
    try {
      const data = await testCamera({
        endpoint,
        username: username || undefined,
        password: password || undefined,
        site_cidr_allowlist: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
      });
      setResult(data);
      if (data.result === "ok") setStep(4);
    } catch (e) {
      setResult({ result: "error", safe_message: String(e), stages: [] });
    } finally {
      setLoading(false);
    }
  }, [address, port, protocol, streamPath, username, password]);

  const doSave = useCallback(async () => {
    const cleanAddress = address.trim();
    const cleanPort = port.trim();
    let cleanProtocol = protocol.trim() || ((cleanPort === "4747" || cleanPort === "8080") ? "http" : cleanPort === "554" ? "rtsp" : "http");
    let cleanPath = streamPath.trim().replace(/^\/+/, "");
    if ((cleanPort === "4747" || cleanPort === "8080") && !cleanPath) {
      cleanPath = "video";
    }

    if (!cleanAddress || !cleanPort || !cleanProtocol) {
      setSaveError("Enter the device IP, port, and protocol before saving.");
      return;
    }

    const endpoint = `${cleanProtocol}://${cleanAddress}:${cleanPort}${cleanPath ? `/${cleanPath}` : ""}`;
    const isPhone = cleanPort === "4747" || cleanPort === "8080" || cleanPath.toLowerCase().includes("video");
    const cameraName = cleanPort === "4747"
      ? `Phone Camera (${cleanAddress})`
      : `Camera ${cleanAddress || (Date.now() % 1000)}`;

    setSaving(true);
    setSaveError("");
    try {
      await createCamera({
        endpoint,
        site_id: "00000000-0000-0000-0000-000000000001",
        username: username || undefined,
        password: password || undefined,
        site_cidr_allowlist: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        name: cameraName,
        source_type: isPhone ? "smartphone_ip_webcam" : "ip_camera",
        protocol: cleanProtocol as any,
        temporary,
      });
      await qc.invalidateQueries({ queryKey: ["cameras"] });
      setStep(1);
      setResult(null);
      setAddress("");
      setPort("");
      setProtocol("");
      setStreamPath("video");
      setTemporary(true);
      nav("/");
    } catch {
      setSaveError("The camera could not be added. Check the connection and try again.");
    } finally {
      setSaving(false);
    }
  }, [address, port, protocol, streamPath, username, password, temporary, qc, nav]);

  const handleClose = useCallback(() => nav("/"), [nav]);
  const handleStopPropagation = useCallback((e: React.MouseEvent) => e.stopPropagation(), []);
  const handleToggleAuth = useCallback(() => setShowAuth((v) => !v), []);
  const handleBackToForm = useCallback(() => setStep(1), []);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 dark:bg-black/80 backdrop-blur-md grid place-items-center p-4 sm:p-6 z-50 modal-backdrop-animate overflow-y-auto"
      onClick={handleClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-camera-title"
        className="modal-content-animate w-full max-w-xl max-h-[92vh] overflow-y-auto rounded-2xl bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-white/10 p-5 sm:p-6 shadow-2xl text-slate-900 dark:text-slate-100 transition-colors my-auto"
        onClick={handleStopPropagation}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3.5 mb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-lg shadow-sm">
              <CameraIcon className="w-5 h-5 text-slate-700 dark:text-slate-300" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                <span id="connect-camera-title">Connect Camera Source</span>
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Add a live phone camera over Wi-Fi, IP camera, or CCTV feed
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleClose}
              aria-label="Back to overview"
              title="Back to overview"
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 transition-colors cursor-pointer"
            >
              <ArrowLeftIcon className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Back</span>
            </button>
            <button
              ref={closeButtonRef}
              onClick={handleClose}
              aria-label="Close"
              title="Close"
              className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 transition-colors cursor-pointer"
            >
              <CloseIcon className="w-4 h-4" />
            </button>
          </div>
        </div>

        {step === 1 && (
          <>
            {/* Quick Source Presets */}
            <div className="mb-3.5 rounded-xl border border-slate-200 bg-slate-50/90 p-3.5 dark:border-slate-700 dark:bg-slate-950/60">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Quick Source Presets
                </span>
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Wi-Fi Stream Boosted
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => applyPreset("10.80.5.52", "4747", "http", "video")}
                  data-testid="preset-phone-live"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-800 dark:text-emerald-300 hover:bg-emerald-500/20 transition-colors cursor-pointer"
                >
                  <span>⚡ Live Phone (10.80.5.52:4747)</span>
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset(address || "10.80.5.52", "4747", "http", "video")}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer"
                >
                  DroidCam (:4747)
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset(address || "192.168.1.10", "8080", "http", "video")}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer"
                >
                  IP Webcam (:8080)
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset(address || "192.168.1.100", "554", "rtsp", "stream1")}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer"
                >
                  RTSP CCTV (:554)
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950/60">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Source details</h3>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Enter the network details for your camera or select a preset.</p>
                </div>
                <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500 shadow-sm dark:bg-slate-800 dark:text-slate-400">Required</span>
              </div>
              <label className="mt-4 block text-xs font-semibold text-slate-600 dark:text-slate-300">
                Device IP address
                <input
                  value={address}
                  onChange={(e) => handleAddressChange(e.target.value)}
                  placeholder="Device IP address"
                  data-testid="stream-url"
                  autoFocus
                  className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-900 placeholder-slate-400 focus:border-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900/10 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:placeholder-slate-500 dark:focus:border-slate-300 dark:focus:ring-white/10"
                />
              </label>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                  Port
                  <input value={port} onChange={(e) => handlePortChange(e.target.value)} placeholder="Port" inputMode="numeric" data-testid="camera-port" className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-900 placeholder-slate-400 focus:border-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900/10 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:placeholder-slate-500 dark:focus:border-slate-300 dark:focus:ring-white/10" />
                </label>
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                  Protocol
                  <select value={protocol} onChange={(e) => setProtocol(e.target.value)} data-testid="camera-protocol" className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-900 focus:border-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900/10 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-slate-300 dark:focus:ring-white/10">
                    <option value="">Select protocol</option>
                    <option value="http">HTTP / MJPEG</option>
                    <option value="https">HTTPS</option>
                    <option value="rtsp">RTSP</option>
                    <option value="rtsps">RTSPS</option>
                  </select>
                </label>
              </div>
              <label className="mt-3 block text-xs font-semibold text-slate-600 dark:text-slate-300">
                Stream path <span className="font-normal text-slate-400">optional</span>
                <input value={streamPath} onChange={(e) => setStreamPath(e.target.value)} placeholder="Stream path" data-testid="camera-path" className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-900 placeholder-slate-400 focus:border-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900/10 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:placeholder-slate-500 dark:focus:border-slate-300 dark:focus:ring-white/10" />
              </label>
            </div>

            <div className="mt-3 rounded-xl border border-slate-200 dark:border-slate-700">
              <button
                type="button"
                onClick={handleToggleAuth}
                data-testid="toggle-auth"
                aria-expanded={showAuth}
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-slate-700 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 cursor-pointer"
              >
                <span>Authentication <span className="font-normal text-slate-400">optional</span></span>
                <span className="text-lg leading-none text-slate-400">{showAuth ? "−" : "+"}</span>
              </button>
            {showAuth && (
              <div className="grid grid-cols-2 gap-3 border-t border-slate-200 px-4 pb-4 pt-3 dark:border-slate-700">
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Username"
                  data-testid="username"
                  className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100"
                />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  data-testid="password"
                  className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100"
                />
              </div>
            )}
            </div>

            <div className="mt-4">
              <p className="mb-2 text-xs font-semibold text-slate-600 dark:text-slate-300">Keep this source</p>
              <div className="grid grid-cols-2 gap-2">
                <button type="button" onClick={() => setTemporary(true)} className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors cursor-pointer ${temporary ? "border-slate-900 bg-slate-100 dark:border-white dark:bg-slate-800" : "border-slate-200 dark:border-slate-700"}`}>
                  <span className="block font-semibold">This session</span>
                  <span className="mt-0.5 block text-slate-500 dark:text-slate-400">Temporary</span>
                </button>
                <button type="button" onClick={() => setTemporary(false)} className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors cursor-pointer ${!temporary ? "border-slate-900 bg-slate-100 dark:border-white dark:bg-slate-800" : "border-slate-200 dark:border-slate-700"}`}>
                  <span className="block font-semibold">Save camera</span>
                  <span className="mt-0.5 block text-slate-500 dark:text-slate-400">Keep in camera list</span>
                </button>
              </div>
            </div>

            <button
              onClick={doTest}
              disabled={!address.trim() || !port.trim() || !protocol || loading}
              data-testid="test-connection"
              className="primary-button mt-5 w-full disabled:opacity-50 cursor-pointer"
            >
              {loading ? "Testing Connection..." : "Test connection"}
            </button>
          </>
        )}
        {step === 3 && (
          <>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Validating Connection
            </h3>
            <div className="mt-4 space-y-2">
              {(result?.stages ?? [{ name: "Validating address", status: "running" }]).map((s) => (
                <div key={s.name} className="flex items-center justify-between text-sm py-1 border-b border-slate-100 dark:border-slate-800/60 last:border-0">
                  <span className="text-slate-700 dark:text-slate-300">{s.name}</span>
                  <span className={s.status === "ok" ? "text-emerald-600 dark:text-emerald-400 font-semibold inline-flex items-center gap-1" : s.status === "failed" ? "text-red-600 dark:text-red-400 font-semibold inline-flex items-center gap-1" : "text-slate-400 font-mono text-xs"}>
                    {s.status === "ok" ? (
                      <>
                        <CheckCircleIcon className="w-3.5 h-3.5" />
                        <span>Ready</span>
                      </>
                    ) : s.status === "failed" ? (
                      <>
                        <AlertTriangleIcon className="w-3.5 h-3.5" />
                        <span>Failed</span>
                      </>
                    ) : (
                      s.status
                    )}
                  </span>
                </div>
              ))}
            </div>
            {result && (
              <div data-testid="test-result" className={`mt-4 rounded-xl p-3 text-sm flex items-start gap-2 ${result.result === "ok" ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60" : "bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-900/60"}`}>
                {result.result === "ok" ? (
                  <CheckCircleIcon className="w-4 h-4 flex-shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
                ) : (
                  <AlertTriangleIcon className="w-4 h-4 flex-shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
                )}
                <div>
                  <span>{result.safe_message}</span>
                  {result.reason_code && <span className="ml-2 text-xs opacity-75">({result.reason_code})</span>}
                </div>
              </div>
            )}
            {result && result.result !== "ok" && (
              <button onClick={handleBackToForm} className="text-sm underline mt-3 text-neutral-900 dark:text-neutral-200 font-medium cursor-pointer">
                Edit connection
              </button>
            )}
          </>
        )}
        {step === 4 && result?.probe && (
          <>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Confirm live preview
            </h3>
            <div data-testid="test-result" className="rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60 p-3 text-sm mb-3 flex items-center gap-2">
              <CheckCircleIcon className="w-4 h-4 flex-shrink-0 text-emerald-600 dark:text-emerald-400" />
              <span>{result.safe_message}</span>
            </div>
            <div className="mt-3 rounded-xl bg-slate-900 p-3 border border-slate-800">
              {protocol.startsWith("http") && <img src={`${protocol}://${address}:${port}${streamPath.trim() ? `/${streamPath.trim().replace(/^\/+/, "")}` : ""}`} alt="Preview" className="max-h-72 w-full object-contain rounded-lg bg-black" />}
              <div className="grid grid-cols-3 gap-2 text-xs text-white mt-2 pt-2 border-t border-slate-800 font-mono">
                <span>Codec: {result.probe.codec}</span>
                <span>Res: {result.probe.width}×{result.probe.height}</span>
                <span>FPS: {result.probe.fps ?? "Live"}</span>
              </div>
            </div>
            <div className="mt-4 flex gap-3">
              <button onClick={doSave} disabled={saving} data-testid="continue" className="primary-button flex-1 cursor-pointer disabled:cursor-not-allowed disabled:opacity-60">
                {saving ? "Adding camera..." : "Add camera & go to overview"}
              </button>
              <button onClick={handleBackToForm} className="ghost-button cursor-pointer">
                Edit
              </button>
            </div>
            {saveError && (
              <p role="alert" className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
                {saveError}
              </p>
            )}
          </>
        )}
        <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800/80 flex justify-end">
          <button onClick={() => nav("/")} className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer">
            Close
          </button>
        </div>
      </div>
    </div>
  );
});
