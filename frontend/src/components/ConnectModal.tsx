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
      site_id: "00000000-0000-0000-0000-000000000001",
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
    <div
      className="fixed inset-0 bg-black/60 dark:bg-black/80 backdrop-blur-md grid place-items-center p-6 z-50 modal-backdrop-animate"
      onClick={() => nav("/")}
    >
      <div
        className="modal-content-animate w-full max-w-xl rounded-2xl bg-white dark:bg-[#131720] border border-neutral-200/80 dark:border-white/10 p-6 shadow-2xl text-slate-900 dark:text-slate-100 transition-colors"
        onClick={(e) => e.stopPropagation()}
      >
        {step === 1 && (
          <>
            <h2 className="text-base font-bold tracking-tight">Prepare phone</h2>
            <ol className="mt-3 list-decimal pl-5 text-sm leading-6 text-slate-600 dark:text-slate-300 space-y-1">
              <li>Start DroidCam / IP-webcam on phone.</li>
              <li>Same WiFi as server, keep on power.</li>
              <li>Copy URL shown by app (e.g. http://192.168.1.10:4747/video).</li>
            </ol>
            <button onClick={() => setStep(2)} data-testid="prepare-done" className="primary-button mt-6 w-full cursor-pointer">
              My phone camera is running
            </button>
          </>
        )}
        {step === 2 && (
          <>
            <h2 className="text-base font-bold tracking-tight">Enter connection</h2>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://192.168.1.10:4747/video"
              data-testid="stream-url"
              className="mt-3 w-full rounded-xl border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-[#0b0d11] px-3 py-2 text-sm text-slate-900 dark:text-slate-100 placeholder-neutral-400 dark:placeholder-neutral-500 focus:outline-none focus:border-neutral-900 dark:focus:border-neutral-300"
            />
            <button
              onClick={() => setShowAuth((v) => !v)}
              data-testid="toggle-auth"
              className="text-xs underline mt-2 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer"
            >
              {showAuth ? "Hide authentication" : "Authentication (optional)"}
            </button>
            {showAuth && (
              <div className="grid grid-cols-2 gap-3 mt-2">
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
            <button onClick={doTest} disabled={!url || loading} data-testid="test-connection" className="primary-button mt-4 w-full disabled:opacity-50 cursor-pointer">
              {loading ? "Testing..." : "Test connection"}
            </button>
          </>
        )}
        {step === 3 && (
          <>
            <h2 className="text-base font-bold tracking-tight">Testing connection</h2>
            <div className="mt-4 space-y-2">
              {(result?.stages ?? [{ name: "Validating address", status: "running" }]).map((s) => (
                <div key={s.name} className="flex items-center justify-between text-sm">
                  <span>{s.name}</span>
                  <span className={s.status === "ok" ? "text-emerald-600 dark:text-emerald-400 font-semibold" : s.status === "failed" ? "text-red-600 dark:text-red-400 font-semibold" : "text-slate-400"}>{s.status}</span>
                </div>
              ))}
            </div>
            {result && (
              <div data-testid="test-result" className={`mt-4 rounded-xl p-3 text-sm ${result.result === "ok" ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60" : "bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-900/60"}`}>
                {result.safe_message}
                {result.reason_code && <span className="ml-2 text-xs">({result.reason_code})</span>}
              </div>
            )}
            {result && result.result !== "ok" && (
              <button onClick={() => setStep(2)} className="text-sm underline mt-3 text-neutral-900 dark:text-neutral-200 font-medium cursor-pointer">
                Edit connection
              </button>
            )}
          </>
        )}
        {step === 4 && result?.probe && (
          <>
            <h2 className="text-base font-bold tracking-tight">Confirm live preview</h2>
            <div data-testid="test-result" className="rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60 p-3 text-sm mb-3">
              {result.safe_message}
            </div>
            <div className="mt-3 rounded-xl bg-slate-900 p-3 border border-slate-800">
              {url.startsWith("http") && <img src={url} alt="Preview" className="max-h-72 w-full object-contain rounded-lg bg-black" />}
              <div className="grid grid-cols-3 gap-2 text-xs text-white mt-2 pt-2 border-t border-slate-800 font-mono">
                <span>Codec: {result.probe.codec}</span>
                <span>Res: {result.probe.width}×{result.probe.height}</span>
                <span>FPS: {result.probe.fps ?? "Live"}</span>
              </div>
            </div>
            <div className="mt-4 flex gap-3">
              <button onClick={doSave} data-testid="continue" className="primary-button flex-1 cursor-pointer">
                Add camera → Go to cockpit
              </button>
              <button onClick={() => setStep(2)} className="ghost-button cursor-pointer">
                Edit
              </button>
            </div>
          </>
        )}
        <button onClick={() => nav("/")} className="mt-4 text-xs text-slate-500 dark:text-slate-400 underline hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer">
          Close
        </button>
      </div>
    </div>
  );
}
