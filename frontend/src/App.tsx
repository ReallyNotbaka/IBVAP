import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Topbar } from "./components/Topbar";
import { ConnectModal } from "./components/ConnectModal";
import { WatchlistModal } from "./components/WatchlistModal";
import { ModelSelectorModal } from "./components/ModelSelectorModal";
import { Alerts } from "./pages/Alerts";
import { EmptyState } from "./pages/EmptyState";
import { Health } from "./pages/Health";
import { Monitor } from "./pages/Monitor";
import { Cockpit } from "./pages/Cockpit";
import { UseFootage } from "./pages/UseFootage";
import { useCameras } from "./lib/api";
import { VideoIcon } from "./components/Icons";
import type { TargetInspectData } from "./components/CameraTile";

const qc = new QueryClient();

function SourceState({ error, onRetry }: { error?: boolean; onRetry?: () => void }) {
  return (
    <div className="flex-1 flex items-center justify-center min-h-[calc(100vh-8rem)] px-4 py-8">
      <div className="w-full max-w-md rounded-2xl border border-slate-200/80 dark:border-white/10 bg-white/90 dark:bg-slate-900/95 p-8 text-center shadow-xl backdrop-blur-xl">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200">
          <VideoIcon className={`h-5 w-5 ${error ? "" : "animate-pulse"}`} />
        </div>
        <h1 className="mt-5 text-lg font-semibold text-slate-900 dark:text-slate-100">
          {error ? "Sources are temporarily unavailable" : "Preparing your operations view"}
        </h1>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500 dark:text-slate-400">
          {error
            ? "The source list could not be reached. Your footage is safe; try again when the service is ready."
            : "Syncing your video source and getting the live workspace ready."}
        </p>
        {error && onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-6 inline-flex h-10 items-center justify-center rounded-xl bg-slate-900 px-5 text-sm font-semibold text-white transition-colors hover:bg-black dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100"
          >
            Try again
          </button>
        )}
        {!error && <div className="mx-auto mt-6 h-1.5 w-24 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"><div className="h-full w-1/2 animate-pulse rounded-full bg-slate-700 dark:bg-slate-200" /></div>}
      </div>
    </div>
  );
}

function AppShell() {
  const { data: cameras, isLoading, isFetching, isError, refetch } = useCameras();
  const navigate = useNavigate();
  const [watchlistOpen, setWatchlistOpen] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [initialTarget, setInitialTarget] = useState<TargetInspectData | null>(null);

  const cameraList = cameras ?? [];
  const showSourceLoading = !isError && (isLoading || (isFetching && cameraList.length === 0));
  const showSourceError = isError && cameraList.length === 0;
  const showOnboarding = !showSourceLoading && !showSourceError && cameraList.length === 0;

  const renderSourceRoute = (modalOpen = false) => {
    if (showSourceLoading) return <SourceState />;
    if (showSourceError) return <SourceState error onRetry={() => void refetch()} />;
    if (showOnboarding) return <EmptyState onConnect={() => navigate("/connect/phone")} />;
    return (
      <Cockpit
        modalOpen={modalOpen}
        onOpenWatchlist={handleOpenWatchlist}
        onInspectTarget={handleInspectTarget}
      />
    );
  };

  const handleOpenWatchlist = () => {
    setInitialTarget(null);
    setWatchlistOpen(true);
  };

  const handleInspectTarget = (target: TargetInspectData) => {
    setInitialTarget(target);
    setWatchlistOpen(true);
  };

  return (
    <div className="app-shell cockpit-shell">
      <Topbar
        onAddPhone={() => navigate("/connect/phone")}
        onOpenWatchlist={handleOpenWatchlist}
        onOpenModels={() => setModelsOpen(true)}
      />
      <main className="content-area">
        <Routes>
          <Route
            path="/"
            element={renderSourceRoute()}
          />
          <Route
            path="/connect/phone"
            element={renderSourceRoute(true)}
          />
          <Route path="/overview" element={<Navigate to="/" replace />} />
          <Route path="/monitor" element={<Navigate to="/" replace />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/health" element={<Health />} />
          <Route path="/use/footage" element={<UseFootage />} />
          <Route path="/monitor-legacy" element={<Monitor />} />
          <Route path="/overview-legacy" element={<Navigate to="/" replace />} />
          <Route
            path="*"
            element={renderSourceRoute()}
          />
        </Routes>
      </main>
      <ConnectModal />
      <WatchlistModal
        isOpen={watchlistOpen}
        onClose={() => {
          setWatchlistOpen(false);
          setInitialTarget(null);
        }}
        initialTarget={initialTarget}
      />
      <ModelSelectorModal isOpen={modelsOpen} onClose={() => setModelsOpen(false)} />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
