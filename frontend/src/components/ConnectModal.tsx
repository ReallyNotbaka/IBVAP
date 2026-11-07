import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { testCamera, createCamera } from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";
import {
  CloseIcon,
  CheckCircleIcon,
  AlertTriangleIcon,
} from "./Icons";

function isFootagePath(value: string, protocol?: string): boolean {
  const clean = value.trim().replace(/^["']|["']$/g, "").trim();
  if (/^(https?|rtsps?|mjpeg|hls|whip|synthetic):\/\//i.test(clean)) return false;
  return (
    protocol === "file" ||
    clean.startsWith("file://") ||
    /^[a-zA-Z]:[/\\]/.test(clean) ||
    (!clean.includes("://") && !/^(?:\d{1,3}\.){3}\d{1,3}/.test(clean) && /\.(mp4|mov|avi|mkv|webm)$/i.test(clean))
  );
}

export const ConnectModal = memo(function ConnectModal() {
  const nav = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const open = loc.pathname === "/connect/phone";
  const [address, setAddress] = useState("");
  const [port, setPort] = useState("4747");
  const [protocol, setProtocol] = useState("http");
  const [streamPath, setStreamPath] = useState("video");
  const [temporary, setTemporary] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showAuth, setShowAuth] = useState(false);
  const [result, setResult] = useState<null | {
    result: string;
    reason_code?: string;
    safe_message: string;
    stages: { name: string; status: string }[];
    probe?: { width: number; height: number; fps: number | null; codec: string; preview_b64?: string | null };
  }>(null);
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

  const applyProfile = useCallback((presetPort: string, presetProto: string, presetPath: string) => {
    setPort(presetPort);
    setProtocol(presetProto);
    setStreamPath(presetPath);
    setResult(null);
    setSaveError("");
  }, []);

  const handleAddressChange = useCallback((raw: string) => {
    const trimmed = raw.trim().replace(/^["']|["']$/g, "").trim();
    if (isFootagePath(trimmed, protocol)) {
      setAddress(trimmed);
      setProtocol("file");
      setPort("");
      setStreamPath("");
      return;
    }

    let candidate = trimmed;
    if (!candidate.includes("://") && (candidate.includes(":") || candidate.includes("/"))) {
      candidate = "http://" + candidate;
    }
    try {
      const parsed = new URL(candidate);
      if (parsed.username) {
        setUsername(decodeURIComponent(parsed.username));
        setShowAuth(true);
      }
      if (parsed.password) {
        setPassword(decodeURIComponent(parsed.password));
        setShowAuth(true);
      }
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
    setAddress(trimmed);
  }, [protocol]);

  const handlePortChange = useCallback((val: string) => {
    const clean = val.replace(/\D/g, "");
    setPort(clean);
    if (clean === "4747" || clean === "8080") {
      setProtocol("http");
      setStreamPath((prev) => prev || "video");
    } else if (clean === "554") {
      setProtocol("rtsp");
    }
  }, []);

  const doTest = useCallback(async () => {
    const cleanAddress = address.trim().replace(/^["']|["']$/g, "").trim();
    const isFile = isFootagePath(cleanAddress, protocol);

    let endpoint = "";
    if (isFile) {
      endpoint = cleanAddress;
    } else {
      const cleanPort = port.trim() || "8080";
      let cleanProtocol = protocol.trim() || "http";
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
        setResult({ result: "error", safe_message: "Enter the camera IP address and port before testing.", stages: [] });
        setStep(1);
        return;
      }

      endpoint = `${cleanProtocol}://${cleanAddress}:${cleanPort}${cleanPath ? `/${cleanPath}` : ""}`;
    }

    setLoading(true);
    setStep(3);
    try {
      const data = await testCamera({
        endpoint,
        protocol: isFile ? "file" : undefined,
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
    const cleanAddress = address.trim().replace(/^["']|["']$/g, "").trim();
    const isFile = isFootagePath(cleanAddress, protocol);

    let endpoint = "";
    let cameraName = "";
    let cleanProtocol = protocol.trim();
    let sourceType: "smartphone_ip_webcam" | "ip_camera" | "video_footage" = "ip_camera";

    if (isFile) {
      endpoint = cleanAddress;
      const fileName = cleanAddress.split(/[/\\]/).pop() || cleanAddress;
      cameraName = `Footage (${fileName})`;
      cleanProtocol = "file";
      sourceType = "video_footage";
    } else {
      const cleanPort = port.trim() || "8080";
      cleanProtocol = cleanProtocol || ((cleanPort === "4747" || cleanPort === "8080") ? "http" : cleanPort === "554" ? "rtsp" : "http");
      let cleanPath = streamPath.trim().replace(/^\/+/, "");
      if ((cleanPort === "4747" || cleanPort === "8080") && !cleanPath) {
        cleanPath = "video";
      }

      if (!cleanAddress || !cleanPort || !cleanProtocol) {
        setSaveError("Enter the camera IP address, port, and protocol before saving.");
        return;
      }

      endpoint = `${cleanProtocol}://${cleanAddress}:${cleanPort}${cleanPath ? `/${cleanPath}` : ""}`;
      const isPhone = cleanPort === "4747" || cleanPort === "8080" || cleanPath.toLowerCase().includes("video");
      cameraName = isPhone ? `Camera (${cleanAddress})` : `RTSP (${cleanAddress})`;
      sourceType = isPhone ? "smartphone_ip_webcam" : "ip_camera";
    }

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
        source_type: sourceType,
        protocol: cleanProtocol as any,
        temporary,
      });
      await qc.invalidateQueries({ queryKey: ["cameras"] });
      setStep(1);
      setResult(null);
      setAddress("");
      setPort("4747");
      setProtocol("http");
      setStreamPath("video");
      setTemporary(false);
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

  const activeProfile =
    port === "4747" && protocol === "http"
      ? "droidcam"
      : port === "8080" && protocol === "http"
      ? "ipwebcam"
      : port === "554" && protocol === "rtsp"
      ? "rtsp"
      : "custom";

  return (
    <div
      className="fixed inset-0 bg-black/65 backdrop-blur-xs grid place-items-center p-4 z-50 modal-backdrop-animate overflow-y-auto"
      onClick={handleClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-camera-title"
        className="modal-content-animate liquid-glass-window w-full max-w-md p-6 text-slate-900 dark:text-white my-auto"
        onClick={handleStopPropagation}
      >
        {/* Clean Single Header */}
        <div className="flex items-start justify-between gap-4 pb-4 border-b border-slate-100 dark:border-white/10">
          <div>
            <h2 id="connect-camera-title" className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Connect Camera Source
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Enter a local IP address or paste a stream URL
            </p>
          </div>
          <button
            ref={closeButtonRef}
            onClick={handleClose}
            aria-label="Close"
            title="Close"
            className="h-7 w-7 rounded-lg flex items-center justify-center text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white transition-colors cursor-pointer"
          >
            <CloseIcon className="w-4 h-4" />
          </button>
        </div>

        {step === 1 && (
          <div className="mt-4 space-y-4">
            {/* Clean 3-Segment App Profile Selector (Never hardcodes IPs) */}
            <div>
              <span className="block text-[11px] font-medium text-slate-500 dark:text-slate-400 mb-1.5">
                Stream profile
              </span>
              <div className="grid grid-cols-3 gap-1.5 p-1 rounded-full liquid-glass-input">
                <button
                  type="button"
                  onClick={() => applyProfile("4747", "http", "video")}
                  className={`py-1 px-2 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                    activeProfile === "droidcam"
                      ? "liquid-glass-pill !h-7 font-semibold"
                      : "text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
                  }`}
                >
                  DroidCam :4747
                </button>
                <button
                  type="button"
                  onClick={() => applyProfile("8080", "http", "video")}
                  className={`py-1 px-2 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                    activeProfile === "ipwebcam"
                      ? "liquid-glass-pill !h-7 font-semibold"
                      : "text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
                  }`}
                >
                  IP Webcam :8080
                </button>
                <button
                  type="button"
                  onClick={() => applyProfile("554", "rtsp", "stream1")}
                  className={`py-1 px-2 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                    activeProfile === "rtsp"
                      ? "liquid-glass-pill !h-7 font-semibold"
                      : "text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
                  }`}
                >
                  RTSP :554
                </button>
              </div>
            </div>

            {/* IP / Host Input */}
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
              Host or IP address
              <input
                value={address}
                onChange={(e) => handleAddressChange(e.target.value)}
                placeholder="e.g. 192.168.1.50 or http://..."
                data-testid="stream-url"
                autoFocus
                className="mt-1.5 w-full liquid-glass-input px-3.5 py-2 text-xs font-mono text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none"
              />
            </label>

            {/* Compact 3-Column Protocol / Port / Path Row */}
            <div className="grid grid-cols-3 gap-2.5">
              <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
                Protocol
                <select
                  value={protocol}
                  onChange={(e) => setProtocol(e.target.value)}
                  data-testid="camera-protocol"
                  className="mt-1.5 w-full liquid-glass-input px-2.5 py-2 text-xs text-slate-900 dark:text-white focus:outline-none"
                >
                  <option value="">Select</option>
                  <option value="http">HTTP</option>
                  <option value="https">HTTPS</option>
                  <option value="rtsp">RTSP</option>
                  <option value="rtsps">RTSPS</option>
                </select>
              </label>

              <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
                Port
                <input
                  value={port}
                  onChange={(e) => handlePortChange(e.target.value)}
                  placeholder="4747"
                  inputMode="numeric"
                  data-testid="camera-port"
                  className="mt-1.5 w-full liquid-glass-input px-2.5 py-2 text-xs font-mono text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none"
                />
              </label>

              <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
                Path
                <input
                  value={streamPath}
                  onChange={(e) => setStreamPath(e.target.value)}
                  placeholder="video"
                  data-testid="camera-path"
                  className="mt-1.5 w-full liquid-glass-input px-2.5 py-2 text-xs font-mono text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none"
                />
              </label>
            </div>

            {/* Inline Options Row: Auth Toggle + Save Checkbox */}
            <div className="pt-1 flex items-center justify-between text-xs">
              <button
                type="button"
                onClick={handleToggleAuth}
                data-testid="toggle-auth"
                aria-expanded={showAuth}
                className="font-medium text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors cursor-pointer"
              >
                {showAuth ? "− Hide authentication" : "+ Add authentication"}
              </button>

              <label className="inline-flex items-center gap-2 text-slate-600 dark:text-slate-300 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={!temporary}
                  onChange={(e) => setTemporary(!e.target.checked)}
                  className="rounded accent-slate-900 dark:accent-white"
                />
                <span>Save camera</span>
              </label>
            </div>

            {showAuth && (
              <div className="grid grid-cols-2 gap-2.5 pt-1">
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Username"
                  data-testid="username"
                  className="w-full liquid-glass-input px-3.5 py-2 text-xs text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none"
                />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  data-testid="password"
                  className="w-full liquid-glass-input px-3.5 py-2 text-xs text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none"
                />
              </div>
            )}

            <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-100 dark:border-white/10">
              <button
                type="button"
                onClick={handleClose}
                className="ghost-button"
              >
                Cancel
              </button>
              <button
                onClick={doTest}
                disabled={!address.trim() || !port.trim() || !protocol || loading}
                data-testid="test-connection"
                className="liquid-glass-cta disabled:opacity-40"
              >
                {loading ? "Testing..." : "Test connection"}
              </button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="mt-4 space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Validating Connection
            </h3>
            <div className="space-y-1.5">
              {(result?.stages ?? [{ name: "Validating address", status: "running" }]).map((s) => (
                <div key={s.name} className="flex items-center justify-between text-xs py-1.5 border-b border-slate-100 dark:border-white/5 last:border-0">
                  <span className="text-slate-600 dark:text-slate-300">{s.name}</span>
                  <span className={s.status === "ok" ? "text-emerald-600 dark:text-emerald-400 font-medium inline-flex items-center gap-1" : s.status === "failed" ? "text-rose-600 dark:text-rose-400 font-medium inline-flex items-center gap-1" : "text-slate-400 font-mono"}>
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
              <div data-testid="test-result" className={`rounded-lg p-3 text-xs flex items-start gap-2 ${result.result === "ok" ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60" : "bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-900/60"}`}>
                {result.result === "ok" ? (
                  <CheckCircleIcon className="w-4 h-4 flex-shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
                ) : (
                  <AlertTriangleIcon className="w-4 h-4 flex-shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
                )}
                <div>
                  <span>{result.safe_message}</span>
                  {result.reason_code && <span className="ml-1.5 opacity-75 font-mono">({result.reason_code})</span>}
                </div>
              </div>
            )}
            {result && result.result !== "ok" && (
              <div className="pt-2 flex justify-end">
                <button onClick={handleBackToForm} className="secondary-button">
                  Edit connection
                </button>
              </div>
            )}
          </div>
        )}

        {step === 4 && result?.probe && (
          <div className="mt-4 space-y-3">
            <div data-testid="test-result" className="rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60 p-2.5 text-xs flex items-center gap-2">
              <CheckCircleIcon className="w-4 h-4 flex-shrink-0 text-emerald-600 dark:text-emerald-400" />
              <span>{result.safe_message}</span>
            </div>
            <div className="rounded-lg bg-black p-2 border border-slate-800">
              {result.probe.preview_b64 ? (
                <img src={result.probe.preview_b64} alt="Preview" className="max-h-56 w-full object-contain rounded bg-black" />
              ) : (
                protocol.startsWith("http") && (
                  <img
                    src={`${protocol}://${address}:${port}${streamPath.trim() ? `/${streamPath.trim().replace(/^\/+/, "")}` : ""}`}
                    alt="Preview"
                    className="max-h-56 w-full object-contain rounded bg-black"
                  />
                )
              )}
              <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-300 mt-2 pt-2 border-t border-white/10 font-mono">
                <span>Codec: {result.probe.codec}</span>
                <span>Res: {result.probe.width}×{result.probe.height}</span>
                <span>FPS: {result.probe.fps ?? "Live"}</span>
              </div>
            </div>
            <div className="pt-2 flex justify-end gap-2">
              <button onClick={handleBackToForm} className="ghost-button">
                Edit
              </button>
              <button onClick={doSave} disabled={saving} data-testid="continue" className="primary-button disabled:opacity-50">
                {saving ? "Adding..." : "Add camera"}
              </button>
            </div>
            {saveError && (
              <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
                {saveError}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
