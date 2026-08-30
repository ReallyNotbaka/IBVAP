import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Navbar } from "./components/Navbar";
import { Alerts } from "./pages/Alerts";
import { ConnectPhone } from "./pages/ConnectPhone";
import { EmptyState } from "./pages/EmptyState";
import { Health } from "./pages/Health";
import { Monitor } from "./pages/Monitor";
import { Overview } from "./pages/Overview";

const qc = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Navbar />
        <Routes>
          <Route path="/" element={<EmptyState />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/connect/phone" element={<ConnectPhone />} />
          <Route path="/use/footage" element={<div className="p-8">Upload footage — Phase 2 (quarantine → promote)</div>} />
          <Route path="/monitor" element={<Monitor />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/health" element={<Health />} />
          <Route path="*" element={<EmptyState />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
