import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { testCamera, createCamera } from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";
import {
  CloseIcon,
  CheckCircleIcon,
  AlertTriangleIcon,
  CameraIcon,
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

export type PresetType = "droidcam" | "ipwebcam" | "rtsp" | "custom";

function extractHostAndPort(rawAddr: string, fallbackPort: string): { host: string; port: string } {
  let host = rawAddr.trim();
  let port = fallbackPort.trim();
  if (host.startsWith("[")) {
    const end = host.indexOf("]");
    if (end !== -1) {
      const rest = host.slice(end + 1);
      if (rest.startsWith(":")) {
        port = rest.slice(1).replace(/\D/g, "");
      }
      host = host.slice(0, end + 1);
    }
  } else if (host.includes(":")) {
    const parts = host.split(":");
    if (parts.length === 2 && /^\d+$/.test(parts[1])) {
      host = parts[0];
      port = parts[1];
    }
  }
  return { host, port };
}

export const ConnectModal = memo(function ConnectModal() {
  const nav = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const open = loc.pathname === "/connect/phone";

  const [preset, setPreset] = useState<PresetType>("droidcam");
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

  // Apply template defaults without locking or resetting user-entered custom parameters
  const applyPreset = useCallback((targetPreset: PresetType) => {
    setPreset(targetPreset);
    setResult(null);
    setSaveError("");

    if (targetPreset === "droidcam") {
      setProtocol("http");
      setPort("4747");
      setStreamPath("video");
    } else if (targetPreset === "ipwebcam") {
      setProtocol("http");
      setPort("8080");
      setStreamPath("video");
    } else if (targetPreset === "rtsp") {
      setProtocol("rtsp");
      setPort("554");
      setStreamPath("stream1");
    } else if (targetPreset === "custom") {
      if (!protocol) setProtocol("http");
      if (!port) setPort("8000");
    }
  }, [protocol, port]);

  // Intelligent URL / IP parser that extracts custom ports and protocols freely
  const handleAddressChange = useCallback((raw: string) => {
    const trimmed = raw.trim().replace(/^["']|["']$/g, "").trim();
    if (isFootagePath(trimmed, protocol)) {
      setAddress(trimmed);
      setProtocol("file");
      setPort("");
      setStreamPath("");
      return;
    }

    // Try parsing as full URL or host:port
    let candidate = trimmed;
    const hasScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(candidate);
    if (!hasScheme && (candidate.includes(":") || candidate.includes("/"))) {
      candidate = (protocol === "rtsp" ? "rtsp://" : "http://") + candidate;
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
          setPreset("custom");
        }
        if (hasScheme && parsed.protocol) {
          const proto = parsed.protocol.replace(":", "").toLowerCase();
          if (["http", "https", "rtsp", "rtsps"].includes(proto)) {
            setProtocol(proto);
          }
        }
        const p = parsed.pathname.replace(/^\/+/, "");
        if (p) {
          setStreamPath(p);
        }
        return;
      }
    } catch {
      // Fallback: standard plain input
    }
    setAddress(trimmed);
  }, [protocol]);

  // Free custom port input handler
  const handlePortChange = useCallback((val: string) => {
    const clean = val.replace(/\D/g, "");
    setPort(clean);
    setPreset("custom");
  }, []);

  // Quick port shortcut chip
  const handleSelectQuickPort = useCallback((p: string) => {
    setPort(p);
    setPreset("custom");
  }, []);

  // Real-time live endpoint preview
  const liveEndpoint = useMemo(() => {
    const cleanAddr = address.trim().replace(/^["']|["']$/g, "").trim();
    if (!cleanAddr) return "";
    if (isFootagePath(cleanAddr, protocol)) return cleanAddr;
    const { host, port: extractedPort } = extractHostAndPort(cleanAddr, port);
    const cleanProto = protocol.trim() || "http";
    const cleanPath = streamPath.trim().replace(/^\/+/, "");
    const portSection = extractedPort ? `:${extractedPort}` : "";
    const pathSection = cleanPath ? `/${cleanPath}` : "";
    return `${cleanProto}://${host}${portSection}${pathSection}`;
  }, [address, protocol, port, streamPath]);

  const doTest = useCallback(async () => {
    const cleanAddress = address.trim().replace(/^["']|["']$/g, "").trim();
    const isFile = isFootagePath(cleanAddress, protocol);

    let endpoint = "";
    if (isFile) {
      endpoint = cleanAddress;
    } else {
      if (!cleanAddress) {
        setResult({ result: "error", safe_message: "Enter the camera host IP address before testing.", stages: [] });
        setStep(1);
        return;
      }

      const cleanPort = port.trim() || (protocol === "rtsp" ? "554" : "8080");
      const { host, port: finalPort } = extractHostAndPort(cleanAddress, cleanPort);
      const cleanProtocol = protocol.trim() || "http";
      const cleanPath = streamPath.trim().replace(/^\/+/, "");

      endpoint = `${cleanProtocol}://${host}:${finalPort}${cleanPath ? `/${cleanPath}` : ""}`;
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
      if (!cleanAddress) {
        setSaveError("Enter the camera IP address before saving.");
        return;
      }

      const cleanPort = port.trim() || (protocol === "rtsp" ? "554" : "8080");
      const { host, port: finalPort } = extractHostAndPort(cleanAddress, cleanPort);
      cleanProtocol = cleanProtocol || (finalPort === "554" ? "rtsp" : "http");
      const cleanPath = streamPath.trim().replace(/^\/+/, "");

      endpoint = `${cleanProtocol}://${host}:${finalPort}${cleanPath ? `/${cleanPath}` : ""}`;
      const isPhone = cleanProtocol.startsWith("http") && (finalPort === "4747" || finalPort === "8080" || cleanPath.toLowerCase().includes("video"));
      cameraName = isPhone ? `Camera (${host})` : `${cleanProtocol.toUpperCase()} (${host}:${finalPort})`;
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

  return (
    <div
      className="fixed inset-0 bg-black/75 backdrop-blur-xs grid place-items-center p-4 z-50 modal-backdrop-animate overflow-y-auto"
      onClick={handleClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-camera-title"
        className="modal-content-animate panel w-full max-w-lg p-5 sm:p-6 text-[#e9e8d9] my-auto border border-[#3b473b] bg-[#1d241e] shadow-2xl rounded-[12px]"
        onClick={handleStopPropagation}
      >
        {/* Clean Tactical Header */}
        <div className="flex items-start justify-between gap-4 pb-4 border-b border-[#3b473b]">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-[#242d25] border border-[#3b473b] flex items-center justify-center text-[#d6e476] shrink-0">
              <CameraIcon className="w-5 h-5" />
            </div>
            <div>
              <h2 id="connect-camera-title" className="text-sm font-semibold tracking-tight text-[#f7f4e9]">
                Connect Camera Source
              </h2>
              <p className="text-xs text-[#a0a796] mt-0.5">
                Stream phone IP webcam, RTSP CCTV, or custom network feed
              </p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            onClick={handleClose}
            aria-label="Close"
            title="Close"
            className="h-8 w-8 rounded-md flex items-center justify-center text-[#a0a796] hover:bg-[#303a31] hover:text-[#f7f4e9] transition-colors cursor-pointer"
          >
            <CloseIcon className="w-4 h-4" />
          </button>
        </div>

        {step === 1 && (
          <div className="mt-4 space-y-4">
            {/* Quick Profile Template Bar */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-[#a0a796]">
                  Profile Preset
                </span>
                <span className="text-[10px] text-[#bdce70] font-mono">
                  {preset === "droidcam" && "Port 4747 • /video"}
                  {preset === "ipwebcam" && "Port 8080 • /video"}
                  {preset === "rtsp" && "Port 554 • /stream1"}
                  {preset === "custom" && "Custom Port Enabled"}
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 p-1 rounded-lg bg-[#151a16] border border-[#3b473b]">
                <button
                  type="button"
                  onClick={() => applyPreset("droidcam")}
                  className={`py-1.5 px-2 rounded-md text-xs font-medium transition-all cursor-pointer text-center ${
                    preset === "droidcam"
                      ? "bg-[#242d25] text-[#d6e476] font-semibold border border-[#d6e476]/40 shadow-xs"
                      : "text-[#c0c5b5] hover:text-[#f7f4e9] hover:bg-[#1d241e]"
                  }`}
                >
                  DroidCam
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset("ipwebcam")}
                  className={`py-1.5 px-2 rounded-md text-xs font-medium transition-all cursor-pointer text-center ${
                    preset === "ipwebcam"
                      ? "bg-[#242d25] text-[#d6e476] font-semibold border border-[#d6e476]/40 shadow-xs"
                      : "text-[#c0c5b5] hover:text-[#f7f4e9] hover:bg-[#1d241e]"
                  }`}
                >
                  IP Webcam
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset("rtsp")}
                  className={`py-1.5 px-2 rounded-md text-xs font-medium transition-all cursor-pointer text-center ${
                    preset === "rtsp"
                      ? "bg-[#242d25] text-[#d6e476] font-semibold border border-[#d6e476]/40 shadow-xs"
                      : "text-[#c0c5b5] hover:text-[#f7f4e9] hover:bg-[#1d241e]"
                  }`}
                >
                  RTSP CCTV
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset("custom")}
                  className={`py-1.5 px-2 rounded-md text-xs font-medium transition-all cursor-pointer text-center ${
                    preset === "custom"
                      ? "bg-[#242d25] text-[#d6e476] font-semibold border border-[#d6e476]/40 shadow-xs"
                      : "text-[#c0c5b5] hover:text-[#f7f4e9] hover:bg-[#1d241e]"
                  }`}
                >
                  Custom Port
                </button>
              </div>
            </div>

            {/* IP / Host Input */}
            <div>
              <label className="block text-xs font-medium text-[#c0c5b5] mb-1.5">
                Host or IP Address
              </label>
              <div className="relative">
                <input
                  value={address}
                  onChange={(e) => handleAddressChange(e.target.value)}
                  placeholder="e.g. 192.168.1.50 or 10.106.31.201:8000"
                  data-testid="stream-url"
                  autoFocus
                  className="w-full bg-[#151a16] border border-[#3b473b] focus:border-[#d6e476] rounded-md px-3.5 py-2 text-xs font-mono text-[#f7f4e9] placeholder-[#596055] focus:outline-none transition-colors"
                />
              </div>
              <p className="mt-1 text-[11px] text-[#747a6f]">
                Tip: You can paste full URLs or enter <span className="font-mono text-[#a0a796]">IP:PORT</span> directly.
              </p>
            </div>

            {/* Protocol, Port & Path Form Fields */}
            <div className="space-y-2">
              <div className="grid grid-cols-12 gap-2.5">
                {/* Protocol Selector */}
                <div className="col-span-4">
                  <label className="block text-xs font-medium text-[#c0c5b5] mb-1.5">
                    Protocol
                  </label>
                  <select
                    value={protocol}
                    onChange={(e) => {
                      setProtocol(e.target.value);
                      setPreset("custom");
                    }}
                    data-testid="camera-protocol"
                    className="w-full bg-[#151a16] border border-[#3b473b] focus:border-[#d6e476] rounded-md px-2.5 py-2 text-xs text-[#f7f4e9] focus:outline-none cursor-pointer"
                  >
                    <option value="http">HTTP</option>
                    <option value="https">HTTPS</option>
                    <option value="rtsp">RTSP</option>
                    <option value="rtsps">RTSPS</option>
                  </select>
                </div>

                {/* Custom Port Input */}
                <div className="col-span-4">
                  <label className="block text-xs font-medium text-[#c0c5b5] mb-1.5">
                    Port
                  </label>
                  <input
                    value={port}
                    onChange={(e) => handlePortChange(e.target.value)}
                    placeholder="4747"
                    inputMode="numeric"
                    maxLength={5}
                    data-testid="camera-port"
                    className="w-full bg-[#151a16] border border-[#3b473b] focus:border-[#d6e476] rounded-md px-2.5 py-2 text-xs font-mono text-[#f7f4e9] placeholder-[#596055] focus:outline-none transition-colors"
                  />
                </div>

                {/* Path Input */}
                <div className="col-span-4">
                  <label className="block text-xs font-medium text-[#c0c5b5] mb-1.5">
                    Path / Route
                  </label>
                  <input
                    value={streamPath}
                    onChange={(e) => {
                      setStreamPath(e.target.value);
                      setPreset("custom");
                    }}
                    placeholder="video"
                    data-testid="camera-path"
                    className="w-full bg-[#151a16] border border-[#3b473b] focus:border-[#d6e476] rounded-md px-2.5 py-2 text-xs font-mono text-[#f7f4e9] placeholder-[#596055] focus:outline-none transition-colors"
                  />
                </div>
              </div>

              {/* Quick Port Shortcuts */}
              <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
                <span className="text-[10px] text-[#747a6f] uppercase font-mono">Quick Ports:</span>
                {(["4747", "8080", "554", "8000", "8554", "9000"] as const).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => handleSelectQuickPort(p)}
                    className={`px-2 py-0.5 rounded text-[10px] font-mono transition-colors cursor-pointer ${
                      port === p
                        ? "bg-[#242d25] text-[#d6e476] border border-[#d6e476]/50 font-semibold"
                        : "bg-[#151a16] text-[#a0a796] border border-[#3b473b] hover:text-[#f7f4e9] hover:border-[#586454]"
                    }`}
                  >
                    :{p}
                  </button>
                ))}
              </div>
            </div>

            {/* Target Live Stream Preview Box */}
            <div className="rounded-md bg-[#151a16] border border-[#3b473b] p-2.5">
              <div className="flex items-center justify-between text-[10px] text-[#a0a796] font-mono mb-1">
                <span>TARGET ENDPOINT PREVIEW</span>
                <span className={address.trim() ? "text-[#bdce70]" : "text-[#747a6f]"}>
                  {address.trim() ? "VALID SYNTAX" : "AWAITING HOST"}
                </span>
              </div>
              <div className="font-mono text-xs text-[#d6e476] break-all select-all">
                {liveEndpoint || (
                  <span className="text-[#596055] italic">
                    {protocol || "http"}://&lt;host&gt;:{port || "4747"}/{streamPath || "video"}
                  </span>
                )}
              </div>
            </div>

            {/* Inline Options Row: Auth Toggle + Save Checkbox */}
            <div className="pt-1 flex items-center justify-between text-xs">
              <button
                type="button"
                onClick={handleToggleAuth}
                data-testid="toggle-auth"
                aria-expanded={showAuth}
                className="font-medium text-[#c0c5b5] hover:text-[#f7f4e9] transition-colors cursor-pointer inline-flex items-center gap-1"
              >
                <span>{showAuth ? "− Hide credentials" : "+ Add credentials (auth)"}</span>
              </button>

              <label className="inline-flex items-center gap-2 text-[#c0c5b5] cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={!temporary}
                  onChange={(e) => setTemporary(!e.target.checked)}
                  className="rounded accent-[#d6e476]"
                />
                <span className="text-xs">Save camera</span>
              </label>
            </div>

            {showAuth && (
              <div className="grid grid-cols-2 gap-2.5 p-3 rounded-md bg-[#151a16] border border-[#3b473b]">
                <div>
                  <label className="block text-[11px] text-[#a0a796] mb-1">Username</label>
                  <input
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="admin"
                    data-testid="username"
                    className="w-full bg-[#1d241e] border border-[#3b473b] focus:border-[#d6e476] rounded px-3 py-1.5 text-xs text-[#f7f4e9] placeholder-[#596055] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-[#a0a796] mb-1">Password</label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    data-testid="password"
                    className="w-full bg-[#1d241e] border border-[#3b473b] focus:border-[#d6e476] rounded px-3 py-1.5 text-xs text-[#f7f4e9] placeholder-[#596055] focus:outline-none"
                  />
                </div>
              </div>
            )}

            {/* Modal Actions */}
            <div className="pt-3 flex items-center justify-end gap-2 border-t border-[#3b473b]">
              <button
                type="button"
                onClick={handleClose}
                className="btn-instrument px-4 py-1.5"
              >
                Cancel
              </button>
              <button
                onClick={doTest}
                disabled={!address.trim() || loading}
                data-testid="test-connection"
                className="btn-instrument-active px-5 py-1.5 font-bold disabled:opacity-40"
              >
                {loading ? "Testing..." : "Test connection"}
              </button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="mt-4 space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[#a0a796]">
              Validating Connection
            </h3>
            <div className="space-y-1.5">
              {(result?.stages ?? [{ name: "Validating address", status: "running" }]).map((s) => (
                <div key={s.name} className="flex items-center justify-between text-xs py-1.5 border-b border-[#3b473b] last:border-0">
                  <span className="text-[#c0c5b5]">{s.name}</span>
                  <span className={s.status === "ok" ? "text-[#bdce70] font-medium inline-flex items-center gap-1" : s.status === "failed" ? "text-[#e27c5c] font-medium inline-flex items-center gap-1" : "text-[#a0a796] font-mono"}>
                    {s.status === "ok" ? (
                      <>
                        <CheckCircleIcon className="w-3.5 h-3.5 text-[#bdce70]" />
                        <span>Ready</span>
                      </>
                    ) : s.status === "failed" ? (
                      <>
                        <AlertTriangleIcon className="w-3.5 h-3.5 text-[#e27c5c]" />
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
              <div data-testid="test-result" className={`rounded-lg p-3 text-xs flex items-start gap-2.5 ${result.result === "ok" ? "bg-[#151a16] text-[#bdce70] border border-[#bdce70]/40" : "bg-[#151a16] text-[#e0a26c] border border-[#e0a26c]/40"}`}>
                {result.result === "ok" ? (
                  <CheckCircleIcon className="w-4 h-4 shrink-0 mt-0.5 text-[#bdce70]" />
                ) : (
                  <AlertTriangleIcon className="w-4 h-4 shrink-0 mt-0.5 text-[#e0a26c]" />
                )}
                <div>
                  <span className="font-medium">{result.safe_message}</span>
                  {result.reason_code && <span className="ml-1.5 opacity-75 font-mono">({result.reason_code})</span>}
                </div>
              </div>
            )}
            {result && result.result !== "ok" && (
              <div className="pt-2 flex justify-end gap-2 border-t border-[#3b473b]">
                <button onClick={handleBackToForm} className="btn-instrument px-4 py-1.5">
                  Edit connection
                </button>
              </div>
            )}
          </div>
        )}

        {step === 4 && result?.probe && (
          <div className="mt-4 space-y-3">
            <div data-testid="test-result" className="rounded-lg bg-[#151a16] text-[#bdce70] border border-[#bdce70]/40 p-2.5 text-xs flex items-center gap-2">
              <CheckCircleIcon className="w-4 h-4 shrink-0 text-[#bdce70]" />
              <span className="font-semibold">{result.safe_message}</span>
            </div>
            <div className="rounded-lg bg-black p-2 border border-[#3b473b]">
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
              <div className="grid grid-cols-3 gap-2 text-[11px] text-[#c0c5b5] mt-2 pt-2 border-t border-[#3b473b] font-mono">
                <span>Codec: {result.probe.codec}</span>
                <span>Res: {result.probe.width}×{result.probe.height}</span>
                <span>FPS: {result.probe.fps ?? "Live"}</span>
              </div>
            </div>
            <div className="pt-2 flex justify-end gap-2 border-t border-[#3b473b]">
              <button onClick={handleBackToForm} className="btn-instrument px-4 py-1.5">
                Edit
              </button>
              <button onClick={doSave} disabled={saving} data-testid="continue" className="btn-instrument-active px-5 py-1.5 font-bold disabled:opacity-50">
                {saving ? "Adding..." : "Add camera"}
              </button>
            </div>
            {saveError && (
              <p role="alert" className="rounded-lg border border-[#e27c5c]/40 bg-[#151a16] p-2.5 text-xs text-[#e27c5c]">
                {saveError}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
