import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { EmptyState } from "./pages/EmptyState";

const qc = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<EmptyState />} />
          <Route path="/connect/phone" element={<div className="p-8">Phone connect wizard — Phase 2</div>} />
          <Route path="/use/footage" element={<div className="p-8">Upload footage — Phase 2</div>} />
          <Route path="*" element={<EmptyState />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
