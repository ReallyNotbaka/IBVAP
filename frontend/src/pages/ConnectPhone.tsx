import { useState } from "react";

type TestStage = { name: string; status: string };
type TestResult = {
  result: string;
  reason_code?: string;
  safe_message: string;
  stages: TestStage[];
  probe?: { width: number; height: number; fps: number | null; codec: string };
};

export function ConnectPhone() {
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showAuth, setShowAuth] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);

  async function testConnection() {
    setLoading(true);
    setStep(3);
    try {
      const res = await fetch("/api/v1/cameras/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: url,
          username: username || undefined,
          password: password || undefined,
          site_cidr_allowlist: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        }),
      });

      const data = (await res.json()) as TestResult;
      setResult(data);
      if (data.result === "ok") setStep(4);
    } catch (e) {
      setResult({ result: "error", safe_message: String(e), stages: [] });
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-6 py-4 flex items-center justify-between">
          <h1 className="text-sm font-semibold">Connect phone camera</h1>
          <a href="/" className="text-xs text-slate-500 hover:text-slate-700">
            Back
          </a>
        </div>
      </header>

      <div className="mx-auto max-w-3xl px-6 py-8 space-y-6">
        {step === 1 && (
          <section className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="text-base font-semibold">Prepare phone</h2>
            <ol className="mt-3 list-decimal pl-5 text-sm leading-6 text-slate-600 space-y-1">
              <li>Start the IP-webcam server on the phone.</li>
              <li>Connect phone and IBVAP server to same reachable network.</li>
              <li>Keep phone on power; disable battery optimization for camera app.</li>
              <li>Copy the stream URL shown by the app.</li>
              <li>Configure authentication in the app where supported.</li>
              <li>Avoid exposing the phone stream to the public internet.</li>
            </ol>
            <button
              onClick={() => setStep(2)}
              data-testid="prepare-done"
              className="mt-6 inline-flex h-10 items-center justify-center rounded-xl bg-teal-700 px-6 text-sm font-medium text-white hover:bg-teal-800"
            >
              My phone camera is running
            </button>
          </section>
        )}

        {step === 2 && (
          <section className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="text-base font-semibold">Enter connection</h2>
            <div className="mt-4 space-y-4">
              <label className="block text-sm">
                <span className="text-slate-700">Stream URL</span>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="http://192.168.1.10:8080/video"
                  data-testid="stream-url"
                  className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                />
              </label>

              <button
                type="button"
                onClick={() => setShowAuth((v) => !v)}
                className="text-xs text-slate-500 underline"
                data-testid="toggle-auth"
              >
                {showAuth ? "Hide authentication" : "Authentication (optional)"}
              </button>

              {showAuth && (
                <div className="grid grid-cols-2 gap-3">
                  <label className="block text-sm">
                    <span className="text-slate-600">Username</span>
                    <input
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      data-testid="username"
                      className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="text-slate-600">Password or token</span>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      data-testid="password"
                      className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                    />
                  </label>
                </div>
              )}

              <button
                onClick={testConnection}
                disabled={!url || loading}
                data-testid="test-connection"
                className="inline-flex h-10 items-center justify-center rounded-xl bg-teal-700 px-6 text-sm font-medium text-white disabled:opacity-50 hover:bg-teal-800"
              >
                {loading ? "Testing..." : "Test connection"}
              </button>
            </div>
          </section>
        )}

        {step === 3 && (
          <section className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="text-base font-semibold">Testing connection</h2>
            <div className="mt-4 space-y-2">
              {(result?.stages ?? [{ name: "Validating address", status: "running" }]).map((s) => (
                <div key={s.name} className="flex items-center justify-between text-sm">
                  <span>{s.name}</span>
                  <span
                    className={
                      s.status === "ok"
                        ? "text-emerald-600"
                        : s.status === "failed"
                          ? "text-red-600"
                          : "text-slate-400"
                    }
                  >
                    {s.status}
                  </span>
                </div>
              ))}
            </div>
            {result && (
              <div
                className={`mt-4 rounded-xl p-3 text-sm ${result.result === "ok" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}
                data-testid="test-result"
              >
                {result.safe_message}
                {result.reason_code && <span className="ml-2 text-xs">({result.reason_code})</span>}
              </div>
            )}
            {result && result.result !== "ok" && (
              <button onClick={() => setStep(2)} className="mt-4 text-sm underline">
                Edit connection
              </button>
            )}
          </section>
        )}

        {step === 4 && result?.probe && (
          <section className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="text-base font-semibold">Confirm live preview</h2>
            <div className="mt-3 rounded-xl bg-slate-900 text-white p-4 text-sm space-y-3">
              {url.startsWith("http") && (
                <div className="overflow-hidden rounded-lg bg-black flex items-center justify-center border border-slate-800">
                  <img
                    src={url}
                    alt="Live Phone Camera Preview"
                    className="max-h-72 w-full object-contain"
                  />
                </div>
              )}
              <div className="grid grid-cols-3 gap-2 text-xs pt-1 border-t border-slate-800">
                <div><span className="text-slate-400">Codec:</span> {result.probe.codec}</div>
                <div><span className="text-slate-400">Resolution:</span> {result.probe.width}×{result.probe.height}</div>
                <div><span className="text-slate-400">FPS:</span> {result.probe.fps ?? "Live"}</div>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-3">
              <a
                href="/monitor"
                className="inline-flex h-10 items-center justify-center rounded-xl bg-teal-700 px-6 text-sm font-medium text-white hover:bg-teal-800"
                data-testid="continue"
              >
                Go to Monitoring
              </a>
              <button onClick={() => setStep(2)} className="text-sm text-slate-600 underline">
                Edit connection
              </button>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

