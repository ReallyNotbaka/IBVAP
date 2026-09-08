import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { createCamera, finalizeUpload, uploadFootage } from "../lib/api";
import { VideoIcon, UploadIcon } from "../components/Icons";

export function UseFootage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("Choose a video file to analyze.");
  const [statusKind, setStatusKind] = useState<"info" | "error">("info");
  const [isBusy, setIsBusy] = useState(false);

  async function handleUseFootage() {
    if (!file) {
      setStatusKind("error");
      setStatus("Please choose a supported video file first.");
      return;
    }

    const supportedExtension = /\.(mp4|mov|avi|mkv|webm)$/i.test(file.name);
    if (!supportedExtension) {
      setStatusKind("error");
      setStatus("Choose an MP4, MOV, AVI, MKV, or WEBM file.");
      return;
    }

    setIsBusy(true);
    setStatusKind("info");
    setStatus("Uploading footage...");

    try {
      const upload = await uploadFootage(file);
      setStatus("Finalizing footage...");
      const finalized = await finalizeUpload(upload.upload_id);
      setStatus("Configuring footage source...");

      await createCamera({
        name: file.name,
        site_id: "00000000-0000-0000-0000-000000000001",
        source_type: "video_footage",
        protocol: "file",
        endpoint: finalized.path,
        site_cidr_allowlist: [],
        temporary: true,
      });

      setStatus("Refreshing camera list...");
      await queryClient.invalidateQueries({ queryKey: ["cameras"] });
      setStatus(`Footage ready: ${file.name}`);
      navigate("/");
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : "Unable to use the selected footage.";
      setStatusKind("error");
      setStatus(message);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-8rem)] py-8 px-4 w-full">
      <div className="w-full max-w-xl rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white dark:bg-slate-900/95 backdrop-blur-xl p-8 shadow-xl transition-all">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 shadow-sm">
            <VideoIcon className="w-5 h-5 text-slate-700 dark:text-slate-300" />
          </div>
          <div>
            <h1 className="text-[20px] font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Use video footage
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Analyze recorded video clip as a live camera source
            </p>
          </div>
        </div>

        <p className="mt-4 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Upload a local MP4, MOV, AVI, MKV, or WEBM clip and process it through the vision pipeline.
        </p>

        <label className="mt-6 block rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950/60 p-6 text-sm text-slate-600 dark:text-slate-300 cursor-pointer hover:border-slate-300 dark:hover:border-slate-600 transition-colors">
          <input
            type="file"
            accept=".mp4,.mov,.avi,.mkv,.webm,video/*"
            className="hidden"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setStatusKind("info");
              setStatus("Ready to upload.");
            }}
          />
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 min-w-0">
              <UploadIcon className="w-4 h-4 text-slate-400 flex-shrink-0" />
              <span className="truncate">{file ? file.name : "Choose a video file"}</span>
            </div>
            <span className="rounded-full bg-slate-200 dark:bg-slate-800 px-3 py-1 text-xs font-semibold text-slate-700 dark:text-slate-300 flex-shrink-0">
              Browse
            </span>
          </div>
        </label>

        <div className="mt-5 flex gap-3">
          <button
            type="button"
            onClick={handleUseFootage}
            disabled={!file || isBusy}
            className="primary-button flex-1 disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
          >
            {isBusy ? "Processing..." : statusKind === "error" ? "Try again" : "Use footage"}
          </button>
          <button
            type="button"
            onClick={() => navigate("/")}
            className="secondary-button border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 cursor-pointer"
          >
            Cancel
          </button>
        </div>

        <div
          role="status"
          aria-live="polite"
          className={`mt-5 rounded-xl border p-3 text-xs font-mono ${
            statusKind === "error"
              ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300"
              : "border-slate-200/80 bg-slate-50 dark:border-slate-800 dark:bg-slate-950/60 text-slate-600 dark:text-slate-400"
          }`}
        >
          {status}
        </div>
      </div>
    </div>
  );
}
