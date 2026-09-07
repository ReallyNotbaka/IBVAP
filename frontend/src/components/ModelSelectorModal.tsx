import React, { useState, useEffect } from "react";
import {
  useModels,
  activateModel,
  startModelDownload,
  fetchDownloadProgress,
  uploadModel,
  deleteModelWeights,
  type ModelItem,
  type DownloadProgress,
} from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { CpuIcon, SparkIcon, CrosshairIcon, AlertTriangleIcon, CloseIcon, DownloadIcon, UploadIcon, TrashIcon } from "./Icons";

interface ModelSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ModelSelectorModal({ isOpen, onClose }: ModelSelectorModalProps) {
  const qc = useQueryClient();
  const { data: modelData, isLoading } = useModels();
  const models = modelData?.models || [];
  const activeModel = modelData?.active_model || "yolo26n";

  const [activeTab, setActiveTab] = useState<"models" | "usb">("models");
  const [selectedForDownload, setSelectedForDownload] = useState<ModelItem | null>(null);
  const [downloadingModel, setDownloadingModel] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<DownloadProgress | null>(null);
  const [actionError, setActionError] = useState("");
  const [activating, setActivating] = useState(false);
  const [deletingModel, setDeletingModel] = useState<string | null>(null);

  // USB Upload state
  const [uploadTargetVariant, setUploadTargetVariant] = useState("yolo26s");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // Polling for download progress
  useEffect(() => {
    if (!downloadingModel) return;

    const interval = setInterval(async () => {
      try {
        const prog = await fetchDownloadProgress(downloadingModel);
        setDownloadProgress(prog);

        if (prog.status === "ready") {
          clearInterval(interval);
          setDownloadingModel(null);
          await qc.invalidateQueries({ queryKey: ["models"] });
        } else if (prog.status === "failed") {
          clearInterval(interval);
          setDownloadingModel(null);
          setActionError(`Download failed: ${prog.error_message || "Unknown error"}`);
        }
      } catch {
        // network blip, continue
      }
    }, 400);

    return () => clearInterval(interval);
  }, [downloadingModel, qc]);

  if (!isOpen) return null;

  const handleSelectModel = async (model: ModelItem) => {
    setActionError("");
    if (model.is_active) return;

    if (model.is_installed) {
      // Installed: Activate immediately
      setActivating(true);
      try {
        await activateModel(model.name);
        await qc.invalidateQueries({ queryKey: ["models"] });
      } catch (err: unknown) {
        setActionError(err instanceof Error ? err.message : "Failed to activate model");
      } finally {
        setActivating(false);
      }
    } else {
      // Not installed: Prompt confirmation workflow
      setSelectedForDownload(model);
    }
  };

  const confirmDownload = async () => {
    if (!selectedForDownload) return;
    const modelName = selectedForDownload.name;
    setSelectedForDownload(null);
    setDownloadingModel(modelName);
    setActionError("");

    try {
      await startModelDownload(modelName);
    } catch (err: unknown) {
      setDownloadingModel(null);
      setActionError(err instanceof Error ? err.message : "Failed to start download");
    }
  };

  const handleDeleteWeights = async (model: ModelItem) => {
    if (model.name === "yolo26n") {
      setActionError("Base default model 'yolo26n' cannot be deleted.");
      return;
    }
    if (model.is_active) {
      setActionError("Cannot delete active model weights. Switch to another model first.");
      return;
    }
    if (!confirm(`Are you sure you want to delete downloaded weights for ${model.name}?`)) {
      return;
    }

    setDeletingModel(model.name);
    setActionError("");
    try {
      await deleteModelWeights(model.name);
      await qc.invalidateQueries({ queryKey: ["models"] });
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Failed to delete model weights");
    } finally {
      setDeletingModel(null);
    }
  };

  const handleUsbUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      setActionError("Please choose an ONNX weight file to upload.");
      return;
    }

    setUploading(true);
    setActionError("");

    try {
      await uploadModel(uploadTargetVariant, uploadFile);
      await qc.invalidateQueries({ queryKey: ["models"] });
      setUploadFile(null);
      setActiveTab("models");
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Model file upload failed.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 dark:bg-black/80 backdrop-blur-md p-4 modal-backdrop-animate">
      <div className="modal-content-animate relative w-full max-w-2xl rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden flex flex-col max-h-[90vh] text-slate-900 dark:text-slate-100">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-lg shadow-sm">
              <CpuIcon className="w-5 h-5 text-slate-800 dark:text-slate-200" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Dynamic YOLO26 Neural Model Switcher
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Switch neural network architectures with zero pipeline downtime
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 transition-colors cursor-pointer"
          >
            <CloseIcon className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-100 dark:border-slate-800 bg-slate-50/30 dark:bg-slate-950/30 px-6">
          <button
            onClick={() => setActiveTab("models")}
            className={`py-3 px-4 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === "models"
                ? "border-slate-900 dark:border-white text-slate-900 dark:text-white"
                : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
            }`}
          >
            Available Models
          </button>
          <button
            onClick={() => setActiveTab("usb")}
            className={`py-3 px-4 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === "usb"
                ? "border-slate-900 dark:border-white text-slate-900 dark:text-white"
                : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
            }`}
          >
            Air-Gapped / USB Weight Import
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {actionError && (
            <div className="flex items-center gap-2 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 p-3 text-xs text-rose-700 dark:text-rose-300">
              <AlertTriangleIcon className="w-4 h-4 flex-shrink-0 text-rose-600 dark:text-rose-400" />
              <span>{actionError}</span>
            </div>
          )}

          {/* Active Download Progress Widget */}
          {downloadingModel && (
            <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/90 dark:bg-slate-800/90 p-4 space-y-2.5 shadow-sm">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-2">
                  <span className="inline-block h-2 w-2 rounded-full bg-slate-900 dark:bg-white animate-ping" />
                  Downloading {downloadingModel}...
                </span>
                <span className="font-mono font-bold text-slate-900 dark:text-slate-100">
                  {downloadProgress ? `${downloadProgress.progress_percent}%` : "0%"}
                </span>
              </div>

              {/* Progress Track */}
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                <div
                  className="h-full bg-slate-900 dark:bg-white transition-all duration-300"
                  style={{
                    width: `${downloadProgress ? downloadProgress.progress_percent : 0}%`,
                  }}
                />
              </div>

              <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                <span>
                  Speed:{" "}
                  {downloadProgress?.speed_mbps
                    ? `${downloadProgress.speed_mbps} MB/s`
                    : "--"}
                </span>
                <span>
                  ETA:{" "}
                  {downloadProgress?.eta_seconds
                    ? `${downloadProgress.eta_seconds}s`
                    : "--"}
                </span>
              </div>
            </div>
          )}

          {activeTab === "models" ? (
            <div className="space-y-3">
              {isLoading ? (
                <div className="py-12 text-center text-xs text-slate-400">
                  Loading model catalog...
                </div>
              ) : (
                models.map((m: ModelItem) => {
                  const isActive = m.name === activeModel;
                  return (
                    <div
                      key={m.name}
                      className={`flex items-center justify-between rounded-xl border p-4 transition-all ${
                        isActive
                          ? "border-slate-400 dark:border-slate-500 bg-slate-100/70 dark:bg-slate-800/60 shadow-xs"
                          : "border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 hover:border-slate-300 dark:hover:border-slate-700"
                      }`}
                    >
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold text-slate-900 dark:text-slate-100 uppercase tracking-wide">
                            {m.name}
                          </span>
                          {isActive && (
                            <span className="rounded-full bg-slate-200 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 px-2 py-0.5 text-[10px] font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider">
                              Active Engine
                            </span>
                          )}
                          {m.is_installed ? (
                            <span className="rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                              Ready ({m.size_mb} MB)
                            </span>
                          ) : (
                            <span className="rounded-full bg-slate-200 dark:bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-slate-600 dark:text-slate-400">
                              {m.size_mb} MB (On-Demand)
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {m.description}
                        </p>
                        <div className="flex items-center gap-4 text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                          <span className="flex items-center gap-1">
                            <SparkIcon className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
                            <span>Est. Latency: ~{m.est_latency_ms}ms</span>
                          </span>
                          <span className="flex items-center gap-1">
                            <CrosshairIcon className="w-3.5 h-3.5 text-rose-500 dark:text-rose-400" />
                            <span>Precision: {m.mAP_val} mAP</span>
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {isActive ? (
                          <button
                            disabled
                            className="rounded-xl bg-slate-200 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 px-4 py-2 text-xs font-semibold text-slate-700 dark:text-slate-300 opacity-90 cursor-default"
                          >
                            Active
                          </button>
                        ) : m.is_installed ? (
                          <>
                            <button
                              onClick={() => handleSelectModel(m)}
                              disabled={activating || deletingModel === m.name}
                              className="rounded-xl bg-white dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 px-4 py-2 text-xs font-semibold text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-700 transition-colors shadow-xs cursor-pointer"
                            >
                              {activating ? "Switching..." : "Activate"}
                            </button>
                            {m.name !== "yolo26n" && (
                              <button
                                onClick={() => handleDeleteWeights(m)}
                                disabled={deletingModel === m.name || activating}
                                data-testid={`delete-weights-${m.name}`}
                                title={`Delete downloaded weights for ${m.name}`}
                                className="flex items-center gap-1.5 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 px-3 py-2 text-xs font-semibold text-rose-700 dark:text-rose-300 transition-colors cursor-pointer"
                              >
                                <TrashIcon className="w-3.5 h-3.5" />
                                <span>{deletingModel === m.name ? "Deleting..." : "Delete Weights"}</span>
                              </button>
                            )}
                          </>
                        ) : (
                          <button
                            onClick={() => handleSelectModel(m)}
                            disabled={downloadingModel !== null}
                            className="rounded-xl bg-slate-900 dark:bg-white hover:bg-black dark:hover:bg-slate-100 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white dark:text-slate-950 transition-all shadow-sm cursor-pointer"
                          >
                            Download & Switch
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          ) : (
            <form onSubmit={handleUsbUpload} className="space-y-4">
              <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/40 p-3.5 text-xs text-slate-600 dark:text-slate-400 space-y-1">
                <div className="font-semibold text-slate-800 dark:text-slate-200">
                  Air-Gapped / USB Weight Installation
                </div>
                <p>
                  For installations without internet connectivity, copy verified{" "}
                  <code>.onnx</code> weights from your USB storage device and upload them directly.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Target Model Architecture
                </label>
                <select
                  value={uploadTargetVariant}
                  onChange={(e) => setUploadTargetVariant(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 focus:border-slate-500 focus:outline-none cursor-pointer"
                >
                  <option value="yolo26s">YOLO26 Small (yolo26s.onnx)</option>
                  <option value="yolo26m">YOLO26 Medium (yolo26m.onnx)</option>
                  <option value="yolo26l">YOLO26 Large (yolo26l.onnx)</option>
                  <option value="yolo26x">YOLO26 Extra-Large (yolo26x.onnx)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  ONNX Weight File
                </label>
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    const file = e.dataTransfer.files?.[0];
                    if (file) {
                      if (!file.name.toLowerCase().endsWith(".onnx")) {
                        setActionError("Only .onnx model files are supported.");
                        return;
                      }
                      setUploadFile(file);
                      setActionError("");
                      // Auto-select target variant based on file name if recognized
                      const lower = file.name.toLowerCase();
                      if (lower.includes("yolo26s")) setUploadTargetVariant("yolo26s");
                      else if (lower.includes("yolo26m")) setUploadTargetVariant("yolo26m");
                      else if (lower.includes("yolo26l")) setUploadTargetVariant("yolo26l");
                      else if (lower.includes("yolo26x")) setUploadTargetVariant("yolo26x");
                    }
                  }}
                  className={`border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer ${
                    isDragging
                      ? "border-slate-900 dark:border-white bg-slate-100/80 dark:bg-slate-800/80"
                      : uploadFile
                      ? "border-emerald-500/50 bg-emerald-50/30 dark:bg-emerald-950/20"
                      : "border-slate-300 dark:border-slate-700 hover:border-slate-400 dark:hover:border-slate-600 bg-slate-50/40 dark:bg-slate-950/30"
                  }`}
                  onClick={() => document.getElementById("usb-file-input")?.click()}
                >
                  <input
                    id="usb-file-input"
                    type="file"
                    accept=".onnx"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        setUploadFile(file);
                        setActionError("");
                        const lower = file.name.toLowerCase();
                        if (lower.includes("yolo26s")) setUploadTargetVariant("yolo26s");
                        else if (lower.includes("yolo26m")) setUploadTargetVariant("yolo26m");
                        else if (lower.includes("yolo26l")) setUploadTargetVariant("yolo26l");
                        else if (lower.includes("yolo26x")) setUploadTargetVariant("yolo26x");
                      }
                    }}
                  />
                  <div className="flex flex-col items-center gap-2">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                      <UploadIcon className="w-5 h-5" />
                    </div>
                    {uploadFile ? (
                      <div>
                        <p className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                          {uploadFile.name}
                        </p>
                        <p className="text-[11px] text-slate-500 dark:text-slate-400">
                          {(uploadFile.size / (1024 * 1024)).toFixed(2)} MB — Click or drop another to replace
                        </p>
                      </div>
                    ) : (
                      <div>
                        <p className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                          Click to select or drag & drop USB .onnx weights here
                        </p>
                        <p className="text-[11px] text-slate-500 dark:text-slate-400">
                          Supported architectures: YOLO26s, YOLO26m, YOLO26l, YOLO26x
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setActiveTab("models")}
                  className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-200 transition-colors cursor-pointer"
                >
                  Back
                </button>
                <button
                  type="submit"
                  disabled={uploading || !uploadFile}
                  className="rounded-xl bg-slate-900 dark:bg-white hover:bg-black dark:hover:bg-slate-100 px-5 py-2 text-xs font-semibold text-white dark:text-slate-950 disabled:opacity-50 transition-all shadow-sm cursor-pointer"
                >
                  {uploading ? "Importing Weights..." : "Import Model Weights"}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Confirmation Modal for Undownloaded Model */}
        {selectedForDownload && (
          <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 dark:bg-black/75 backdrop-blur-sm p-4">
            <div className="w-full max-w-sm rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5 shadow-2xl space-y-4 text-slate-900 dark:text-slate-100">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-lg">
                  <DownloadIcon className="w-5 h-5 text-slate-700 dark:text-slate-300" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    Install Model Weights?
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {selectedForDownload.name} ({selectedForDownload.size_mb} MB)
                  </p>
                </div>
              </div>

              <p className="text-xs text-slate-600 dark:text-slate-300">
                This neural model is not cached locally yet. Would you like to download and
                activate <strong>{selectedForDownload.name}</strong> now?
              </p>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={() => setSelectedForDownload(null)}
                  className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-200 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDownload}
                  className="rounded-xl bg-slate-900 dark:bg-white hover:bg-black dark:hover:bg-slate-100 px-4 py-2 text-xs font-semibold text-white dark:text-slate-950 transition-all shadow-sm cursor-pointer"
                >
                  Yes, Download
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
