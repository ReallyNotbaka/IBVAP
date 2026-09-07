import React, { useState, useEffect } from "react";
import {
  useWatchlist,
  enrollSuspect,
  deleteSuspect,
  type ThreatLevel,
  type WatchlistEntry,
} from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";

interface WatchlistModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTarget?: {
    trackId?: string;
    label?: string;
    confidence?: number;
    thumbnail?: string | null;
  } | null;
}

export function WatchlistModal({ isOpen, onClose, initialTarget }: WatchlistModalProps) {
  const qc = useQueryClient();
  const { data: suspects = [], isLoading } = useWatchlist();
  const [activeTab, setActiveTab] = useState<"list" | "enroll">("list");

  // Form State
  const [name, setName] = useState("");
  const [threatLevel, setThreatLevel] = useState<ThreatLevel>("HIGH");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [photoPreviews, setPhotoPreviews] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  // Handle auto-population from 1-click Quick Inspector
  useEffect(() => {
    if (isOpen && initialTarget) {
      setActiveTab("enroll");
      setName(initialTarget.trackId ? `Person #${initialTarget.trackId}` : "Subject");
      setNotes(
        `Flagged from live monitoring feed (Track #${initialTarget.trackId || "N/A"})${
          initialTarget.confidence
            ? ` - ${Math.round(initialTarget.confidence * 100)}% detection confidence`
            : ""
        }`
      );
      if (initialTarget.thumbnail) {
        setPhotoPreviews([initialTarget.thumbnail]);
        try {
          const parts = initialTarget.thumbnail.split(",");
          if (parts.length === 2) {
            const mime = parts[0].match(/:(.*?);/)?.[1] || "image/jpeg";
            const byteChars = atob(parts[1]);
            const byteNumbers = new Uint8Array(byteChars.length);
            for (let i = 0; i < byteChars.length; i++) {
              byteNumbers[i] = byteChars.charCodeAt(i);
            }
            const blob = new Blob([byteNumbers], { type: mime });
            const file = new File(
              [blob],
              `target_${initialTarget.trackId || "snapshot"}.jpg`,
              { type: mime }
            );
            setPhotos([file]);
          } else {
            throw new Error("Not data URL");
          }
        } catch {
          fetch(initialTarget.thumbnail)
            .then((res) => res.blob())
            .then((blob) => {
              const file = new File(
                [blob],
                `target_${initialTarget.trackId || "snapshot"}.jpg`,
                { type: "image/jpeg" }
              );
              setPhotos([file]);
            })
            .catch((err) => console.warn("Thumbnail blob creation failed", err));
        }
      }
    }
  }, [isOpen, initialTarget]);

  if (!isOpen) return null;

  const handlePhotoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const files = Array.from(e.target.files);
    const combined = [...photos, ...files].slice(0, 5);
    setPhotos(combined);

    // Generate object URLs for preview
    const urls = combined.map((f) => URL.createObjectURL(f));
    setPhotoPreviews(urls);
    setErrorMessage("");
  };

  const handleRemovePhoto = (index: number) => {
    const updated = photos.filter((_, i) => i !== index);
    setPhotos(updated);
    const urls = updated.map((f) => URL.createObjectURL(f));
    setPhotoPreviews(urls);
  };

  const handleEnroll = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setErrorMessage("Subject name is required.");
      return;
    }
    if (photos.length === 0) {
      setErrorMessage("Please select at least 1 facial reference photo.");
      return;
    }

    setSubmitting(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const formData = new FormData();
      formData.append("name", name.trim());
      formData.append("threat_level", threatLevel);
      formData.append("notes", notes.trim());
      for (const p of photos) {
        formData.append("photos", p);
      }

      await enrollSuspect(formData);
      await qc.invalidateQueries({ queryKey: ["watchlist"] });
      setSuccessMessage(`Successfully enrolled profile "${name}".`);
      setName("");
      setNotes("");
      setPhotos([]);
      setPhotoPreviews([]);
      setTimeout(() => {
        setActiveTab("list");
        setSuccessMessage("");
      }, 1200);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Enrollment failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string, suspectName: string) => {
    if (!confirm(`Are you sure you want to remove "${suspectName}" from the watchlist?`)) {
      return;
    }
    try {
      await deleteSuspect(id);
      await qc.invalidateQueries({ queryKey: ["watchlist"] });
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to remove subject from watchlist");
    }
  };

  const getThreatBadge = (level: ThreatLevel) => {
    switch (level) {
      case "CRITICAL":
        return "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30";
      case "HIGH":
        return "bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30";
      case "MEDIUM":
        return "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30";
      default:
        return "bg-slate-500/15 text-slate-600 dark:text-slate-400 border border-slate-500/30";
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 dark:bg-black/80 backdrop-blur-md p-4 modal-backdrop-animate">
      <div className="modal-content-animate relative w-full max-w-2xl rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden flex flex-col max-h-[90vh] text-slate-900 dark:text-slate-100">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-rose-50 dark:bg-rose-950/80 border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 text-lg shadow-sm">
              🎯
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Biometric Watchlist & Target Tracking
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Identify and track registered subjects across camera feeds with multi-photo facial recognition matrices
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-100 dark:border-slate-800 bg-slate-50/30 dark:bg-slate-950/30 px-6">
          <button
            onClick={() => setActiveTab("list")}
            className={`py-3 px-4 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === "list"
                ? "border-slate-900 dark:border-white text-slate-900 dark:text-white"
                : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
            }`}
          >
            Targets Enrolled ({suspects.length})
          </button>
          <button
            onClick={() => setActiveTab("enroll")}
            className={`py-3 px-4 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === "enroll"
                ? "border-slate-900 dark:border-white text-slate-900 dark:text-white"
                : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
            }`}
          >
            + Enroll New Target
          </button>
        </div>

        {/* Modal Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {activeTab === "list" ? (
            <div className="space-y-3">
              {isLoading ? (
                <div className="py-12 text-center text-xs text-slate-400">
                  Loading watchlist entries...
                </div>
              ) : suspects.length === 0 ? (
                <div className="py-12 text-center space-y-3">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800 text-2xl">
                    👤
                  </div>
                  <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                    No profiles currently enrolled
                  </div>
                  <p className="text-xs text-slate-500 max-w-xs mx-auto">
                    Add reference photos of a person to begin tracking them across camera feeds.
                  </p>
                  <button
                    onClick={() => setActiveTab("enroll")}
                    className="inline-flex items-center gap-2 rounded-xl bg-slate-900 dark:bg-white px-4 py-2 text-xs font-semibold text-white dark:text-slate-950 hover:bg-black dark:hover:bg-slate-100 transition-all shadow-sm cursor-pointer"
                  >
                    + Enroll First Target
                  </button>
                </div>
              ) : (
                suspects.map((s: WatchlistEntry) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 p-3.5 hover:border-slate-300 dark:hover:border-slate-700 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      {s.thumbnail_b64 ? (
                        <img
                          src={`data:image/jpeg;base64,${s.thumbnail_b64}`}
                          alt={s.name}
                          className="h-12 w-12 rounded-xl object-cover border border-slate-200 dark:border-slate-700 shadow-xs"
                        />
                      ) : (
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-lg">
                          👤
                        </div>
                      )}
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                            {s.name}
                          </span>
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${getThreatBadge(
                              s.threat_level
                            )}`}
                          >
                            {s.threat_level}
                          </span>
                        </div>
                        <div className="flex items-center gap-2.5 mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                          <span>📸 {s.photo_count} angles</span>
                          <span>•</span>
                          <span>👁️ Sighted {s.sight_count} times</span>
                          {s.notes && (
                            <>
                              <span>•</span>
                              <span className="truncate max-w-[200px] text-slate-400 dark:text-slate-500">
                                {s.notes}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDelete(s.id, s.name)}
                      className="rounded-lg px-3 py-1 text-xs font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/50 border border-rose-200 dark:border-rose-900/50 transition-colors cursor-pointer"
                    >
                      Remove
                    </button>
                  </div>
                ))
              )}
            </div>
          ) : (
            <form onSubmit={handleEnroll} className="space-y-4">
              {errorMessage && (
                <div className="rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 p-3 text-xs text-rose-700 dark:text-rose-300">
                  ⚠️ {errorMessage}
                </div>
              )}
              {successMessage && (
                <div className="rounded-xl border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/40 p-3 text-xs text-emerald-700 dark:text-emerald-300">
                  ✅ {successMessage}
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Subject / Profile Name *
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. John Doe / Subject #401"
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-rose-500 focus:outline-none"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Priority Level
                  </label>
                  <select
                    value={threatLevel}
                    onChange={(e) => setThreatLevel(e.target.value as ThreatLevel)}
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 focus:border-slate-500 focus:outline-none cursor-pointer"
                  >
                    <option value="LOW">LOW — Routine Profile</option>
                    <option value="MEDIUM">MEDIUM — Watchlist Alert</option>
                    <option value="HIGH">HIGH — Priority Alert</option>
                    <option value="CRITICAL">CRITICAL — Urgent Security Alert</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Operational & Subject Notes
                </label>
                <input
                  type="text"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="e.g. Last seen at North Gate, wearing dark jacket"
                  className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-slate-500 focus:outline-none"
                />
              </div>

              {/* Multi-Photo Dropzone */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Facial Reference Photos (1 to 5 images) *
                </label>
                <div className="relative rounded-xl border-2 border-dashed border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-950/60 p-4 text-center hover:border-slate-300 dark:hover:border-slate-600 transition-colors">
                  <input
                    type="file"
                    multiple
                    accept="image/*"
                    onChange={handlePhotoSelect}
                    className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
                    disabled={photos.length >= 5}
                  />
                  <div className="space-y-1">
                    <div className="text-2xl">📸</div>
                    <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
                      Drag & drop multiple photos or click to browse
                    </div>
                    <div className="text-[11px] text-slate-500">
                      Tip: Include frontal, 30° left, and 30° right profile shots for maximum
                      accuracy.
                    </div>
                  </div>
                </div>

                {/* Previews */}
                {photoPreviews.length > 0 && (
                  <div className="grid grid-cols-5 gap-2 mt-3">
                    {photoPreviews.map((src, i) => (
                      <div
                        key={i}
                        className="relative group rounded-xl overflow-hidden border border-slate-200 dark:border-slate-700 shadow-xs"
                      >
                        <img src={src} alt="preview" className="h-20 w-full object-cover" />
                        <button
                          type="button"
                          onClick={() => handleRemovePhoto(i)}
                          className="absolute top-1 right-1 h-5 w-5 rounded-full bg-rose-600 text-white text-[10px] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                        >
                          ✕
                        </button>
                        <div className="absolute bottom-0 inset-x-0 bg-black/60 text-[9px] text-center text-white py-0.5">
                          Photo {i + 1}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setActiveTab("list")}
                  className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-200 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || photos.length === 0}
                  className="rounded-xl bg-slate-900 dark:bg-white hover:bg-black dark:hover:bg-slate-100 px-5 py-2 text-xs font-semibold text-white dark:text-slate-950 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm cursor-pointer"
                >
                  {submitting ? "Extracting SFace Biometrics..." : "Enroll in Watchlist"}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
