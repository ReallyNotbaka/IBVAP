import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { testCamera, createCamera } from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";

export function ConnectModal() {
  const nav = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const open = loc.pathname === "/connect/phone";
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showAuth, setShowAuth] = useState(false);
  const [result, setResult] = useState<null | { result: string; reason_code?: string; safe_message: string; stages: { name: string; status: string }[]; probe?: { width: number; height: number; fps: number | null; codec: string } }>(null);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);

  if (!open) return null;

  async function doTest() {
    setLoading(true);
    setStep(3);
    try {
      const data = await testCamera({
        endpoint: url,
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
  }

  async function doSave() {
    await createCamera({
      endpoint: url,
      username: username || undefined,
      password: password || undefined,
      site_cidr_allowlist: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
      name: `Phone ${Date.now() % 1000}`,
    });
    qc.invalidateQueries({ queryKey: ["cameras"] });
    setStep(1);
    setResult(null);
    setUrl("");
    nav("/");
  }

  return (
    <div className="fixed inset-0 bg-slate-900/40 backdrop-blur grid place-items-center p-6 z-50" onClick={() => nav("/")}>
      <div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        {step === 1 && (
          <>
            <h2 className="text-base font-semibold">Prepare phone</h2>
            <ol className="mt-3 list-decimal pl-5 text-sm leading-6 text-slate-600 space-y-1">
              <li>Start DroidCam / IP-webcam on phone.</li>
              <li>Same WiFi as server, keep on power.</li>
              <li>Copy URL shown by app (e.g. http://192.168.1.10:4747/video).</li>
            </ol>
            <button onClick={() => setStep(2)} data-testid="prepare-done" className="primary-button mt-6 w-full">
              My phone camera is running
            </button>
          </>
        )}
        {step === 2 && (
          <>
            <h2 className="text-base font-semibold">Enter connection</h2>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://192.168.1.10:4747/video"
              data-testid="stream-url"
              className="mt-3 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
            />
            <button onClick={() => setShowAuth((v) => !v)} data-testid="toggle-auth" className="text-xs underline mt-2 text-slate-500">
              {showAuth ? "Hide authentication" : "Authentication (optional)"}
            </button>
            {showAuth && (
              <div className="grid grid-cols-2 gap-3 mt-2">
                <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username" data-testid="username" className="rounded-xl border px-3 py-2 text-sm" />
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" data-testid="password" className="rounded-xl border px-3 py-2 text-sm" />
              </div>
            )}
            <button onClick={doTest} disabled={!url || loading} data-testid="test-connection" className="primary-button mt-4 w-full disabled:opacity-50">
              {loading ? "Testing..." : "Test connection"}
            </button>
          </>
        )}
        {step === 3 && (
          <>
            <h2 className="text-base font-semibold">Testing connection</h2>
            <div className="mt-4 space-y-2">
              {(result?.stages ?? [{ name: "Validating address", status: "running" }]).map((s) => (
                <div key={s.name} className="flex items-center justify-between text-sm">
                  <span>{s.name}</span>
                  <span className={s.status === "ok" ? "text-emerald-600" : s.status === "failed" ? "text-red-600" : "text-slate-400"}>{s.status}</span>
                </div>
              ))}
            </div>
            {result && (
              <div data-testid="test-result" className={`mt-4 rounded-xl p-3 text-sm ${result.result === "ok" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}>
                {result.safe_message}
                {result.reason_code && <span className="ml-2 text-xs">({result.reason_code})</span>}
              </div>
            )}
            {result && result.result !== "ok" && (
              <button onClick={() => setStep(2)} className="text-sm underline mt-3">
                Edit connection
              </button>
            )}
          </>
        )}
        {step === 4 && result?.probe && (
          <>
            <h2 className="text-base font-semibold">Confirm live preview</h2>
            <div data-testid="test-result" className="rounded-xl bg-emerald-50 text-emerald-800 p-3 text-sm mb-3">
              {result.safe_message}
            </div>
            <div className="mt-3 rounded-xl bg-slate-900 p-3">
              {url.startsWith("http") && <img src={url} alt="Preview" className="max-h-72 w-full object-contain rounded-lg bg-black" />}
              <div className="grid grid-cols-3 gap-2 text-xs text-white mt-2 pt-2 border-t border-slate-800">
                <span>Codec: {result.probe.codec}</span>
                <span>Res: {result.probe.width}×{result.probe.height}</span>
                <span>FPS: {result.probe.fps ?? "Live"}</span>
              </div>
            </div>
            <div className="mt-4 flex gap-3">
              <button onClick={doSave} data-testid="continue" className="primary-button flex-1">
                Add camera → Go to cockpit
              </button>
              <button onClick={() => setStep(2)} className="ghost-button">
                Edit
              </button>
            </div>
          </>
        )}
        <button onClick={() => nav("/")} className="mt-4 text-xs text-slate-500 underline">
          Close
        </button>
      </div>
    </div>
  );
}
