import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ConnectPhone } from "./pages/ConnectPhone";
import { EmptyState } from "./pages/EmptyState";
import { Monitor } from "./pages/Monitor";

const qc = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<EmptyState />} />
          <Route path="/connect/phone" element={<ConnectPhone />} />
          <Route path="/use/footage" element={<div className="p-8">Upload footage — Phase 2 (quarantine → promote)</div>} />
          <Route path="/monitor" element={<Monitor />} />
          <Route path="*" element={<EmptyState />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
