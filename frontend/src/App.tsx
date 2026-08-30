import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Topbar } from "./components/Topbar";
import { ConnectModal } from "./components/ConnectModal";
import { Alerts } from "./pages/Alerts";
import { ConnectPhone } from "./pages/ConnectPhone";
import { EmptyState } from "./pages/EmptyState";
import { Health } from "./pages/Health";
import { Overview } from "./pages/Overview";
import { Monitor } from "./pages/Monitor";
import { Cockpit } from "./pages/Cockpit";
import { useCameras } from "./lib/api";

const qc = new QueryClient();

function AppShell() {
  const { data: cameras = [], isLoading } = useCameras();
  const navigate = useNavigate();
  const showOnboarding = !isLoading && cameras.length === 0;

  if (showOnboarding) {
    return (
      <Routes>
        <Route path="*" element={<EmptyState onConnect={() => navigate("/connect/phone")} />} />
        <Route path="/connect/phone" element={
          <>
            <EmptyState onConnect={() => navigate("/connect/phone")} />
            <ConnectModal />
          </>
        } />
        <Route path="/use/footage" element={<div className="panel p-8"><h2>Use footage</h2><p>Upload footage — Phase 2 (quarantine → promote)</p></div>} />
      </Routes>
    );
  }

  return (
    <div className="app-shell cockpit-shell">
      <Topbar onAddPhone={() => navigate("/connect/phone")} />
      <main className="content-area">
        <Routes>
          <Route path="/" element={<Cockpit />} />
          <Route path="/connect/phone" element={<Cockpit modalOpen />} />
          <Route path="/overview" element={<Navigate to="/" replace />} />
          <Route path="/monitor" element={<Navigate to="/" replace />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/health" element={<Health />} />
          <Route path="/use/footage" element={<div className="panel"><h2>Use footage</h2><p>Upload footage — Phase 2 (quarantine → promote)</p></div>} />
          <Route path="/monitor-legacy" element={<Monitor />} />
          <Route path="/overview-legacy" element={<Overview />} />
          <Route path="*" element={<Cockpit />} />
        </Routes>
      </main>
      <ConnectModal />
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
