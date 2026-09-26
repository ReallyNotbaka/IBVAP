import { memo, useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchSystemSettings,
  updateSystemSettings,
  testC2Webhook,
  type SystemSettings,
} from "../lib/api";
import { CloseIcon, SettingsIcon, SlidersIcon, SparkIcon } from "./Icons";

export interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal = memo(function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const qc = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ["system-settings"],
    queryFn: fetchSystemSettings,
    enabled: isOpen,
  });

  const [activeTab, setActiveTab] = useState<"c2" | "engine">("c2");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookEnabled, setWebhookEnabled] = useState(false);
  const [minSeverity, setMinSeverity] = useState<"ALL" | "HIGH" | "CRITICAL">("HIGH");
  const [confThreshold, setConfThreshold] = useState(0.45);
  const [loiterCooldown, setLoiterCooldown] = useState(10.0);

  const [testResult, setTestResult] = useState<{
    loading: boolean;
    success?: boolean;
    message?: string;
  } | null>(null);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);

  useEffect(() => {
    if (settings) {
      setWebhookUrl(settings.c2_webhook_url || "");
      setWebhookEnabled(settings.c2_webhook_enabled);
      setMinSeverity(settings.c2_min_severity);
      setConfThreshold(settings.detection_confidence_threshold);
      setLoiterCooldown(settings.loiter_cooldown_seconds);
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: (data: Partial<SystemSettings>) => updateSystemSettings(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system-settings"] });
      setSaveStatus("Settings saved successfully.");
      setTimeout(() => setSaveStatus(null), 2500);
    },
    onError: (err: any) => {
      setSaveStatus(`Failed to save: ${err.message}`);
    },
  });

  const handleSave = () => {
    saveMutation.mutate({
      c2_webhook_url: webhookUrl.trim() || null,
      c2_webhook_enabled: webhookEnabled,
      c2_min_severity: minSeverity,
      detection_confidence_threshold: confThreshold,
      loiter_cooldown_seconds: loiterCooldown,
    });
  };

  const handleTestWebhook = async () => {
    if (!webhookUrl) {
      setTestResult({ loading: false, success: false, message: "Enter a webhook URL first." });
      return;
    }
    setTestResult({ loading: true });
    try {
      const res = await testC2Webhook(webhookUrl.trim());
      setTestResult({
        loading: false,
        success: res.success,
        message: res.message,
      });
    } catch (e: any) {
      setTestResult({
        loading: false,
        success: false,
        message: e.message || "Failed to reach webhook.",
      });
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md modal-backdrop-animate"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl rounded-3xl border border-white/10 bg-slate-950 p-6 shadow-2xl text-slate-100 flex flex-col gap-5 overflow-hidden modal-content-animate font-sans"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 border border-white/10 text-slate-300">
              <SettingsIcon className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold uppercase tracking-wider text-slate-100 font-mono">
                System & C2 Dispatch Configuration
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                Command & Control integrations, alert thresholds, and engine parameters
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            title="Close Settings"
          >
            <CloseIcon className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Selection */}
        <div className="flex items-center gap-2 border-b border-white/10 pb-2">
          <button
            onClick={() => setActiveTab("c2")}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-mono font-semibold transition-all cursor-pointer ${
              activeTab === "c2"
                ? "bg-slate-800 text-white border border-white/20 shadow-xs"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <SparkIcon className="w-3.5 h-3.5 text-rose-400" />
            <span>C2 Webhook Relay</span>
          </button>

          <button
            onClick={() => setActiveTab("engine")}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-mono font-semibold transition-all cursor-pointer ${
              activeTab === "engine"
                ? "bg-slate-800 text-white border border-white/20 shadow-xs"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <SlidersIcon className="w-3.5 h-3.5 text-indigo-400" />
            <span>Detection Parameters</span>
          </button>
        </div>

        {/* Tab Body */}
        {activeTab === "c2" ? (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-mono font-bold text-slate-300">
                  C2 WEBHOOK ENDPOINT
                </label>
                <label className="flex items-center gap-2 text-xs font-mono text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={webhookEnabled}
                    onChange={(e) => setWebhookEnabled(e.target.checked)}
                    className="rounded accent-emerald-500"
                  />
                  <span>Relay Active</span>
                </label>
              </div>
              <input
                type="text"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://discord.com/api/webhooks/... or https://c2.defense.gov/api/v1/alerts"
                className="w-full bg-slate-900 border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-white/30"
              />
              <p className="text-[11px] text-slate-500 font-mono">
                Dispatches JSON incident notifications with forensic snapshot links directly to command centers.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-mono font-bold text-slate-300">
                  MINIMUM DISPATCH SEVERITY
                </label>
                <select
                  value={minSeverity}
                  onChange={(e) => setMinSeverity(e.target.value as any)}
                  className="w-full bg-slate-900 border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none"
                >
                  <option value="CRITICAL">CRITICAL ONLY (Watchlist Matches)</option>
                  <option value="HIGH">HIGH & CRITICAL (Intrusions + Watchlist)</option>
                  <option value="ALL">ALL INCIDENTS (Including Loitering)</option>
                </select>
              </div>

              <div className="space-y-1.5 flex flex-col justify-end">
                <button
                  type="button"
                  onClick={handleTestWebhook}
                  disabled={testResult?.loading || !webhookUrl}
                  className="px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono font-semibold text-slate-300 hover:text-white transition-colors cursor-pointer disabled:opacity-40"
                >
                  {testResult?.loading ? "Sending Test Ping..." : "Send Test Dispatch Ping"}
                </button>
              </div>
            </div>

            {testResult && (
              <div
                className={`p-3 rounded-xl border text-xs font-mono ${
                  testResult.success
                    ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
                    : "bg-rose-950/40 border-rose-500/40 text-rose-300"
                }`}
              >
                {testResult.success ? "✓ " : "✗ "}
                {testResult.message}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-5">
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-mono">
                <span className="font-bold text-slate-300">OBJECT DETECTION CONFIDENCE</span>
                <span className="text-emerald-400 font-bold">{Math.round(confThreshold * 100)}%</span>
              </div>
              <input
                type="range"
                min="0.2"
                max="0.85"
                step="0.05"
                value={confThreshold}
                onChange={(e) => setConfThreshold(parseFloat(e.target.value))}
                className="w-full accent-indigo-500"
              />
              <p className="text-[11px] text-slate-500 font-mono">
                Lower values increase sensitivity on distant intruders; higher values reduce false alarms.
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-mono">
                <span className="font-bold text-slate-300">LOITERING COOLDOWN WINDOW</span>
                <span className="text-indigo-400 font-bold">{loiterCooldown}s</span>
              </div>
              <input
                type="range"
                min="5"
                max="60"
                step="5"
                value={loiterCooldown}
                onChange={(e) => setLoiterCooldown(parseFloat(e.target.value))}
                className="w-full accent-indigo-500"
              />
              <p className="text-[11px] text-slate-500 font-mono">
                Minimum stationary dwelling duration in seconds before triggering suspicious loitering alarms.
              </p>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-white/10 pt-4">
          <div className="text-xs font-mono text-emerald-400">{saveStatus}</div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-mono text-slate-300 transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saveMutation.isPending}
              className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs font-mono font-bold text-white transition-colors cursor-pointer disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save Settings"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});
