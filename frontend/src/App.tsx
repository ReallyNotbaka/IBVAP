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
import type { TargetInspectData } from "./components/CameraTile";

const qc = new QueryClient();

function AppShell() {
  const { data: cameras = [], isLoading } = useCameras();
  const navigate = useNavigate();
  const [watchlistOpen, setWatchlistOpen] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [initialTarget, setInitialTarget] = useState<TargetInspectData | null>(null);

  const showOnboarding = !isLoading && cameras.length === 0;

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
            element={
              showOnboarding ? (
                <EmptyState onConnect={() => navigate("/connect/phone")} />
              ) : (
                <Cockpit
                  onOpenWatchlist={handleOpenWatchlist}
                  onInspectTarget={handleInspectTarget}
                />
              )
            }
          />
          <Route
            path="/connect/phone"
            element={
              showOnboarding ? (
                <EmptyState onConnect={() => navigate("/connect/phone")} />
              ) : (
                <Cockpit
                  modalOpen
                  onOpenWatchlist={handleOpenWatchlist}
                  onInspectTarget={handleInspectTarget}
                />
              )
            }
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
            element={
              showOnboarding ? (
                <EmptyState onConnect={() => navigate("/connect/phone")} />
              ) : (
                <Cockpit
                  onOpenWatchlist={handleOpenWatchlist}
                  onInspectTarget={handleInspectTarget}
                />
              )
            }
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
