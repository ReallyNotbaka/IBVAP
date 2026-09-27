import React, { useState, useEffect, useRef } from "react";
import {
  useWatchlist,
  enrollSuspect,
  enrollPlateTarget,
  deleteSuspect,
  type ThreatLevel,
  type WatchlistEntry,
} from "../lib/api";
import { useQueryClient } from "@tanstack/react-query";
import {
  CrosshairIcon,
  CloseIcon,
  UserIcon,
  CameraIcon,
  EyeIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  LicensePlateIcon,
} from "./Icons";

interface WatchlistModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTarget?: {
    trackId?: string;
    label?: string;
    confidence?: number;
    thumbnail?: string | null;
    targetType?: "face" | "plate";
    plateNumber?: string;
    vehicleClass?: string;
  } | null;
}

// Revoke only blob: object URLs we created (never data-URLs or remote URLs).
function revokeObjectUrls(urls: string[]) {
  for (const u of urls) {
    if (u.startsWith("blob:")) {
      try {
        URL.revokeObjectURL(u);
      } catch {
        // ignore double-revoke / invalid URL errors
      }
    }
  }
}

export function WatchlistModal({ isOpen, onClose, initialTarget }: WatchlistModalProps) {
  const qc = useQueryClient();
  const { data: suspects = [], isLoading } = useWatchlist();
  const [activeTab, setActiveTab] = useState<"list" | "enroll">("list");
  const [listFilter, setListFilter] = useState<"all" | "face" | "plate">("all");

  // Form State
  const [targetType, setTargetType] = useState<"face" | "plate">("face");
  const [name, setName] = useState("");
  const [plateNumber, setPlateNumber] = useState("");
  const [vehicleDescription, setVehicleDescription] = useState("");
  const [threatLevel, setThreatLevel] = useState<ThreatLevel>("HIGH");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [photoPreviews, setPhotoPreviews] = useState<string[]>([]);
  const previewsRef = useRef<string[]>([]);
  useEffect(() => {
    previewsRef.current = photoPreviews;
  }, [photoPreviews]);

  // Revoke any lingering object URLs on unmount (leak guard).
  useEffect(() => {
    return () => {
      revokeObjectUrls(previewsRef.current);
    };
  }, []);
  const [plateThumbnail, setPlateThumbnail] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  // Handle auto-population from 1-click Quick Inspector
  useEffect(() => {
    if (isOpen && initialTarget) {
      setActiveTab("enroll");
      const isPlateTarget =
        initialTarget.targetType === "plate" ||
        Boolean(initialTarget.plateNumber) ||
        Boolean(initialTarget.label?.toLowerCase().includes("plate"));

      if (isPlateTarget) {
        setTargetType("plate");
        const cleanPlate = (
          initialTarget.plateNumber ||
          (initialTarget.label ? initialTarget.label.replace(/^NUMBER PLATE:\s*/i, "").trim() : "")
        ).toUpperCase();
        setPlateNumber(cleanPlate);
        setName(
          initialTarget.vehicleClass
            ? `${initialTarget.vehicleClass.toUpperCase()} [${cleanPlate}]`
            : `Vehicle [${cleanPlate}]`
        );
        setVehicleDescription(
          initialTarget.vehicleClass ? initialTarget.vehicleClass.toUpperCase() : ""
        );
        setNotes(
          `Flagged from ANPR camera stream (Track #${initialTarget.trackId || "N/A"})${
            initialTarget.confidence
              ? ` - ${Math.round(initialTarget.confidence * 100)}% OCR confidence`
              : ""
          }`
        );
        if (initialTarget.thumbnail) {
          setPlateThumbnail(initialTarget.thumbnail);
        }
      } else {
        setTargetType("face");
        const cleanLabel = initialTarget.label
          ? initialTarget.label.replace(/^(MATCH|SUSPECT|WATCHLIST|TARGET|CRITICAL):\s*/i, "").trim()
          : "";
        const isGeneric = !cleanLabel || cleanLabel.toLowerCase() === "face" || cleanLabel.toLowerCase() === "person";
        const defaultName = !isGeneric
          ? cleanLabel
          : initialTarget.trackId
          ? `Person #${initialTarget.trackId}`
          : "Subject";
        setName(defaultName);
        setNotes(
          `Flagged from source feed (Track #${initialTarget.trackId || "N/A"})${
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
    }
  }, [isOpen, initialTarget]);

  if (!isOpen) return null;

  const handlePhotoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const files = Array.from(e.target.files);
    const combined = [...photos, ...files].slice(0, 5);
    setPhotos(combined);

    // Revoke previous previews before replacing (object-URL leak fix).
    revokeObjectUrls(photoPreviews);
    // Generate object URLs for preview
    const urls = combined.map((f) => URL.createObjectURL(f));
    setPhotoPreviews(urls);
    setErrorMessage("");
  };

  const handleRemovePhoto = (index: number) => {
    // Revoke the removed preview; keep existing URLs for retained photos
    // (do NOT regenerate object URLs for files we already have).
    revokeObjectUrls(photoPreviews.slice(index, index + 1));
    const updated = photos.filter((_, i) => i !== index);
    setPhotos(updated);
    setPhotoPreviews(photoPreviews.filter((_, i) => i !== index));
  };

  const handleEnroll = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage("");
    setSuccessMessage("");

    if (targetType === "face") {
      if (!name.trim()) {
        setErrorMessage("Subject name is required.");
        return;
      }
      if (photos.length === 0) {
        setErrorMessage("Please select at least 1 facial reference photo.");
        return;
      }

      setSubmitting(true);
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
        revokeObjectUrls(photoPreviews);
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
    } else {
      // Plate enrollment
      const cleanPlate = plateNumber.trim().toUpperCase();
      if (!cleanPlate) {
        setErrorMessage("License plate number is required.");
        return;
      }

      setSubmitting(true);
      try {
        const profileName = name.trim() || `Vehicle [${cleanPlate}]`;
        let b64: string | undefined = undefined;
        if (plateThumbnail) {
          const match = plateThumbnail.match(/^data:image\/[^;]+;base64,(.+)$/);
          b64 = match ? match[1] : undefined;
        }

        await enrollPlateTarget({
          name: profileName,
          plate_number: cleanPlate,
          threat_level: threatLevel,
          vehicle_description: vehicleDescription.trim() || undefined,
          notes: notes.trim() || undefined,
          thumbnail_b64: b64,
        });

        await qc.invalidateQueries({ queryKey: ["watchlist"] });
        setSuccessMessage(`Successfully enrolled vehicle hotlist target "${cleanPlate}".`);
        setName("");
        setPlateNumber("");
        setVehicleDescription("");
        setNotes("");
        setPlateThumbnail(null);
        setTimeout(() => {
          setActiveTab("list");
          setSuccessMessage("");
        }, 1200);
      } catch (err: unknown) {
        setErrorMessage(err instanceof Error ? err.message : "Plate enrollment failed.");
      } finally {
        setSubmitting(false);
      }
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

  const filteredSuspects = suspects.filter((s: WatchlistEntry) => {
    const isPlate = s.target_type === "plate" || Boolean(s.plate_number);
    if (listFilter === "plate") return isPlate;
    if (listFilter === "face") return !isPlate;
    return true;
  });

  const faceCount = suspects.filter((s) => s.target_type !== "plate" && !s.plate_number).length;
  const plateCount = suspects.filter((s) => s.target_type === "plate" || Boolean(s.plate_number)).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 dark:bg-black/80 backdrop-blur-md p-4 modal-backdrop-animate">
      <div className="modal-content-animate relative w-full max-w-2xl rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden flex flex-col max-h-[90vh] text-slate-900 dark:text-slate-100">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-rose-50 dark:bg-rose-950/80 border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 text-lg shadow-sm">
              <CrosshairIcon className="w-5 h-5 text-rose-600 dark:text-rose-400" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Unified Watchlist & Hotlist Registry
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Register persons of interest and vehicle license plate hotlists across all camera streams
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
              {/* Category Filter Pills */}
              <div className="flex items-center gap-1.5 pb-1">
                <button
                  onClick={() => setListFilter("all")}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                    listFilter === "all"
                      ? "bg-slate-900 dark:bg-white text-white dark:text-slate-950 shadow-xs"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                  }`}
                >
                  All ({suspects.length})
                </button>
                <button
                  onClick={() => setListFilter("face")}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                    listFilter === "face"
                      ? "bg-slate-900 dark:bg-white text-white dark:text-slate-950 shadow-xs"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                  }`}
                >
                  <UserIcon className="w-3.5 h-3.5" />
                  <span>Faces ({faceCount})</span>
                </button>
                <button
                  onClick={() => setListFilter("plate")}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                    listFilter === "plate"
                      ? "bg-slate-900 dark:bg-white text-white dark:text-slate-950 shadow-xs"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                  }`}
                >
                  <LicensePlateIcon className="w-3.5 h-3.5" />
                  <span>Plates ({plateCount})</span>
                </button>
              </div>

              {isLoading ? (
                <div className="py-12 text-center text-xs text-slate-400">
                  Loading watchlist entries...
                </div>
              ) : filteredSuspects.length === 0 ? (
                <div className="py-12 text-center space-y-3">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500">
                    {listFilter === "plate" ? (
                      <LicensePlateIcon className="w-6 h-6 text-amber-500" />
                    ) : (
                      <UserIcon className="w-6 h-6" />
                    )}
                  </div>
                  <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                    {listFilter === "plate"
                      ? "No vehicle plates enrolled on hotlist"
                      : listFilter === "face"
                      ? "No facial profiles currently enrolled"
                      : "No targets currently enrolled"}
                  </div>
                  <p className="text-xs text-slate-500 max-w-xs mx-auto">
                    {listFilter === "plate"
                      ? "Add a vehicle license plate number to trigger automatic ANPR hotlist alarms."
                      : "Add reference photos of a person to begin tracking them across camera feeds."}
                  </p>
                  <button
                    onClick={() => {
                      if (listFilter === "plate") setTargetType("plate");
                      if (listFilter === "face") setTargetType("face");
                      setActiveTab("enroll");
                    }}
                    className="inline-flex items-center gap-2 rounded-xl bg-slate-900 dark:bg-white px-4 py-2 text-xs font-semibold text-white dark:text-slate-950 hover:bg-black dark:hover:bg-slate-100 transition-all shadow-sm cursor-pointer"
                  >
                    + Enroll Target
                  </button>
                </div>
              ) : (
                filteredSuspects.map((s: WatchlistEntry) => {
                  const isPlate = s.target_type === "plate" || Boolean(s.plate_number);
                  return (
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
                        ) : isPlate ? (
                          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800/60 text-amber-600 dark:text-amber-400">
                            <LicensePlateIcon className="w-6 h-6" />
                          </div>
                        ) : (
                          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-400 dark:text-slate-500">
                            <UserIcon className="w-6 h-6" />
                          </div>
                        )}
                        <div>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                              {s.name}
                            </span>
                            {isPlate && s.plate_number && (
                              <span className="font-mono text-xs font-bold tracking-widest text-amber-700 dark:text-amber-300 bg-amber-100/90 dark:bg-amber-950/80 border border-amber-300 dark:border-amber-700/60 rounded px-2 py-0.5">
                                {s.plate_number}
                              </span>
                            )}
                            <span
                              className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${getThreatBadge(
                                s.threat_level
                              )}`}
                            >
                              {s.threat_level}
                            </span>
                          </div>
                          <div className="flex items-center gap-2.5 mt-1 text-[11px] text-slate-500 dark:text-slate-400 flex-wrap">
                            {isPlate ? (
                              <span className="flex items-center gap-1">
                                <LicensePlateIcon className="w-3.5 h-3.5 text-amber-500" />
                                <span>ANPR Hotlist</span>
                              </span>
                            ) : (
                              <span className="flex items-center gap-1">
                                <CameraIcon className="w-3.5 h-3.5 text-slate-400" />
                                <span>{s.photo_count} angles</span>
                              </span>
                            )}
                            <span>•</span>
                            <span className="flex items-center gap-1">
                              <EyeIcon className="w-3.5 h-3.5 text-slate-400" />
                              <span>Sighted {s.sight_count} times</span>
                            </span>
                            {s.vehicle_description && (
                              <>
                                <span>•</span>
                                <span className="text-slate-600 dark:text-slate-300 font-medium">
                                  {s.vehicle_description}
                                </span>
                              </>
                            )}
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
                  );
                })
              )}
            </div>
          ) : (
            <form onSubmit={handleEnroll} className="space-y-4">
              {errorMessage && (
                <div className="flex items-center gap-2 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 p-3 text-xs text-rose-700 dark:text-rose-300">
                  <AlertTriangleIcon className="w-4 h-4 flex-shrink-0 text-rose-600 dark:text-rose-400" />
                  <span>{errorMessage}</span>
                </div>
              )}
              {successMessage && (
                <div className="flex items-center gap-2 rounded-xl border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/40 p-3 text-xs text-emerald-700 dark:text-emerald-300">
                  <CheckCircleIcon className="w-4 h-4 flex-shrink-0 text-emerald-600 dark:text-emerald-400" />
                  <span>{successMessage}</span>
                </div>
              )}

              {/* Target Type Selector Segment */}
              <div className="flex rounded-xl bg-slate-100 dark:bg-slate-950 p-1 border border-slate-200 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setTargetType("face")}
                  className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                    targetType === "face"
                      ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-xs"
                      : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                  }`}
                >
                  <UserIcon className="w-4 h-4 text-rose-500" />
                  <span>Person / Facial Target</span>
                </button>
                <button
                  type="button"
                  onClick={() => setTargetType("plate")}
                  className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                    targetType === "plate"
                      ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-xs"
                      : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                  }`}
                >
                  <LicensePlateIcon className="w-4 h-4 text-amber-500" />
                  <span>Vehicle / License Plate Hotlist</span>
                </button>
              </div>

              {targetType === "face" ? (
                /* Face Enrollment Form */
                <>
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
                        <CameraIcon className="w-7 h-7 text-slate-400 mx-auto" />
                        <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
                          Drag & drop multiple photos or click to browse
                        </div>
                        <div className="text-[11px] text-slate-500">
                          Tip: Multiple angles (frontal and profile) improve match accuracy across varied lighting and orientations.
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
                              aria-label="Remove photo"
                              className="absolute top-1 right-1 h-5 w-5 rounded-full bg-rose-600 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                            >
                              <CloseIcon className="w-3 h-3 text-white" />
                            </button>
                            <div className="absolute bottom-0 inset-x-0 bg-black/60 text-[9px] text-center text-white py-0.5">
                              Photo {i + 1}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              ) : (
                /* Plate Enrollment Form */
                <>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                        License Plate Number *
                      </label>
                      <div className="relative">
                        <input
                          type="text"
                          value={plateNumber}
                          onChange={(e) => setPlateNumber(e.target.value.toUpperCase())}
                          placeholder="e.g. DL01AB1234 / KA05MH9988"
                          className="w-full rounded-xl border border-amber-300 dark:border-amber-700/70 bg-amber-50/30 dark:bg-amber-950/20 px-3 py-2 text-xs font-mono font-bold tracking-wider text-amber-900 dark:text-amber-200 placeholder-amber-400/60 focus:border-amber-500 focus:outline-none uppercase"
                          required
                        />
                        <div className="absolute right-2.5 top-2.5 text-amber-600 dark:text-amber-400">
                          <LicensePlateIcon className="w-4 h-4" />
                        </div>
                      </div>
                      <p className="text-[10px] text-slate-400 mt-1">
                        ANPR OCR fuzzy matching will automatically match similar characters (0/O, 1/I, 8/B).
                      </p>
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                        Priority Threat Level
                      </label>
                      <select
                        value={threatLevel}
                        onChange={(e) => setThreatLevel(e.target.value as ThreatLevel)}
                        className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 focus:border-slate-500 focus:outline-none cursor-pointer"
                      >
                        <option value="LOW">LOW — Routine Sighting Log</option>
                        <option value="MEDIUM">MEDIUM — Watchlist Alert</option>
                        <option value="HIGH">HIGH — High Threat Alert</option>
                        <option value="CRITICAL">CRITICAL — Immediate Intercept / BOLOS</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                        Target / Owner / Alias (Optional)
                      </label>
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="e.g. Suspect Getaway Car / Jane Smith"
                        className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-slate-500 focus:outline-none"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                        Vehicle Description (Make / Model / Color)
                      </label>
                      <input
                        type="text"
                        value={vehicleDescription}
                        onChange={(e) => setVehicleDescription(e.target.value)}
                        placeholder="e.g. Silver Toyota Fortuner / White Hyundai i20"
                        className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-slate-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                      Incident / BOLOS / Case Notes
                    </label>
                    <input
                      type="text"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder="e.g. Wanted for perimeter trespassing near sector 4 gate"
                      className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-slate-500 focus:outline-none"
                    />
                  </div>

                  {plateThumbnail && (
                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                        Detection Reference Snapshot
                      </label>
                      <div className="relative inline-block rounded-xl overflow-hidden border border-amber-300 dark:border-amber-700/60 shadow-xs">
                        <img src={plateThumbnail} alt="Plate crop" className="h-24 object-contain bg-black/40" />
                        <button
                          type="button"
                          onClick={() => setPlateThumbnail(null)}
                          className="absolute top-1 right-1 h-5 w-5 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-rose-600 transition-colors cursor-pointer"
                          title="Remove snapshot"
                        >
                          <CloseIcon className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}

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
                  disabled={submitting || (targetType === "face" && photos.length === 0) || (targetType === "plate" && !plateNumber.trim())}
                  className="rounded-xl bg-slate-900 dark:bg-white hover:bg-black dark:hover:bg-slate-100 px-5 py-2 text-xs font-semibold text-white dark:text-slate-950 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm cursor-pointer"
                >
                  {submitting
                    ? "Enrolling Target..."
                    : targetType === "plate"
                    ? "Enroll License Plate Hotlist"
                    : "Enroll in Watchlist"}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
