import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createCamera, finalizeUpload, uploadFootage } from "../lib/api";

export function UseFootage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("Choose a video file to analyze.");
  const [isBusy, setIsBusy] = useState(false);

  async function handleUseFootage() {
    if (!file) {
      setStatus("Please choose a supported video file first.");
      return;
    }

    setIsBusy(true);
    setStatus("Uploading footage to quarantine…");

    try {
      const upload = await uploadFootage(file);
      setStatus("Finalizing uploaded footage…");
      const finalized = await finalizeUpload(upload.upload_id);
      setStatus("Promoting footage to camera source…");

      await createCamera({
        name: file.name,
        site_id: "00000000-0000-0000-0000-000000000001",
        source_type: "video_footage",
        protocol: "file",
        endpoint: finalized.path,
        site_cidr_allowlist: [],
      });

      setStatus(`Footage ready: ${file.name}`);
      navigate("/");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to use the selected footage.";
      setStatus(message);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-8rem)] py-8 px-4 w-full">
      <div className="w-full max-w-xl rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white dark:bg-[#131720]/95 backdrop-blur-xl p-8 shadow-xl transition-all">

        <h1 className="text-[22px] font-bold tracking-tight text-slate-900 dark:text-slate-100">
          Use video footage
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Upload a local MP4, MOV, AVI, MKV, or WEBM clip and analyze it as a camera source.
        </p>

        <label className="mt-6 block rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950/60 p-6 text-sm text-slate-600 dark:text-slate-300 cursor-pointer hover:border-slate-300 dark:hover:border-slate-600 transition-colors">
          <input
            type="file"
            accept=".mp4,.mov,.avi,.mkv,.webm,video/*"
            className="hidden"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <div className="flex items-center justify-between gap-4">
            <span className="truncate">{file ? file.name : "Choose a video file"}</span>
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
            className="primary-button flex-1 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isBusy ? "Working…" : "Use footage"}
          </button>
          <button
            type="button"
            onClick={() => navigate("/")}
            className="secondary-button border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
          >
            Cancel
          </button>
        </div>

        <div className="mt-5 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200/80 dark:border-slate-800 p-3 text-xs font-mono text-slate-600 dark:text-slate-400">
          {status}
        </div>
      </div>
    </div>
  );
}
