import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { createCamera, finalizeUpload, uploadFootage } from "../lib/api";
import { UploadIcon } from "../components/Icons";

export function UseFootage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [customPath, setCustomPath] = useState("");
  const [status, setStatus] = useState("Select a video file to analyze.");
  const [statusKind, setStatusKind] = useState<"info" | "error">("info");
  const [isBusy, setIsBusy] = useState(false);

  async function handleUseFootage() {
    const cleanPath = customPath.trim().replace(/^["']|["']$/g, "").trim();
    if (!file && !cleanPath) {
      setStatusKind("error");
      setStatus("Please choose a video file or enter a file path.");
      return;
    }

    if (cleanPath) {
      const supportedExtension = /\.(mp4|mov|avi|mkv|webm)$/i.test(cleanPath);
      if (!supportedExtension) {
        setStatusKind("error");
        setStatus("Enter a path to an MP4, MOV, AVI, MKV, or WEBM file.");
        return;
      }
      setIsBusy(true);
      setStatusKind("info");
      setStatus("Configuring footage source...");
      try {
        const name = cleanPath.split(/[/\\]/).pop() || cleanPath;
        await createCamera({
          name,
          site_id: "00000000-0000-0000-0000-000000000001",
          source_type: "video_footage",
          protocol: "file",
          endpoint: cleanPath,
          site_cidr_allowlist: [],
          temporary: true,
        });
        await queryClient.invalidateQueries({ queryKey: ["cameras"] });
        navigate("/");
      } catch (error) {
        const message = error instanceof Error && error.message ? error.message : "Unable to use the selected footage.";
        setStatusKind("error");
        setStatus(message);
      } finally {
        setIsBusy(false);
      }
      return;
    }

    const supportedExtension = /\.(mp4|mov|avi|mkv|webm)$/i.test(file!.name);
    if (!supportedExtension) {
      setStatusKind("error");
      setStatus("Choose an MP4, MOV, AVI, MKV, or WEBM file.");
      return;
    }

    setIsBusy(true);
    setStatusKind("info");
    setStatus("Uploading footage...");

    try {
      const upload = await uploadFootage(file!);
      setStatus("Finalizing footage...");
      const finalized = await finalizeUpload(upload.upload_id);
      setStatus("Configuring footage source...");

      await createCamera({
        name: file!.name,
        site_id: "00000000-0000-0000-0000-000000000001",
        source_type: "video_footage",
        protocol: "file",
        endpoint: finalized.path,
        site_cidr_allowlist: [],
        temporary: true,
      });

      await queryClient.invalidateQueries({ queryKey: ["cameras"] });
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
    <div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-5rem)] p-4 w-full">
      <div className="liquid-glass-window w-full max-w-md p-7">
        <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100">
          Use video footage
        </h1>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Upload a recorded video clip or specify a local file path.
        </p>

        <label className="mt-4 block liquid-glass-input border-dashed p-4 text-xs text-slate-600 dark:text-slate-300 cursor-pointer hover:border-blue-400 transition-colors">
          <input
            type="file"
            accept=".mp4,.mov,.avi,.mkv,.webm,video/*"
            className="hidden"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              if (event.target.files?.[0]) setCustomPath("");
              setStatusKind("info");
              setStatus("Ready to upload.");
            }}
          />
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <UploadIcon className="w-4 h-4 text-slate-400 flex-shrink-0" />
              <span className="truncate">{file ? file.name : "Choose a video file (MP4, MOV, MKV)"}</span>
            </div>
            <span className="liquid-glass-pill !h-7 !px-3 text-[11px] font-medium flex-shrink-0">
              Browse
            </span>
          </div>
        </label>

        <div className="my-3.5 flex items-center gap-3">
          <div className="flex-1 border-t border-slate-100 dark:border-white/10" />
          <span className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">or local path</span>
          <div className="flex-1 border-t border-slate-100 dark:border-white/10" />
        </div>

        <input
          type="text"
          placeholder="path/to/footage.mp4"
          value={customPath}
          onChange={(e) => {
            setCustomPath(e.target.value);
            if (e.target.value) setFile(null);
            setStatusKind("info");
            setStatus("Ready to configure footage.");
          }}
          className="w-full liquid-glass-input px-3.5 py-2 text-xs font-mono text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none"
        />

        <div
          role="status"
          aria-live="polite"
          className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
            statusKind === "error"
              ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300"
              : "border-slate-100 bg-slate-50 text-slate-500 dark:border-white/5 dark:bg-slate-950 dark:text-slate-400"
          }`}
        >
          {status}
        </div>

        <div className="mt-4 pt-3 border-t border-slate-100 dark:border-white/10 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => navigate("/")}
            className="ghost-button"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleUseFootage}
            disabled={(!file && !customPath.trim()) || isBusy}
            className="liquid-glass-cta disabled:opacity-40"
          >
            {isBusy ? "Processing..." : statusKind === "error" ? "Try again" : "Use footage"}
          </button>
        </div>
      </div>
    </div>
  );
}
