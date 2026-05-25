import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "@/components/Layout";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { ProjectPage } from "@/pages/ProjectPage";
import { RunsPage } from "@/pages/RunsPage";
import { UploadPage } from "@/pages/UploadPage";
import { DiscoveryPage } from "@/pages/DiscoveryPage";
import { ExtractPage } from "@/pages/ExtractPage";
import { ReviewPage } from "@/pages/ReviewPage";
import { RunPage } from "@/pages/RunPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { SettingsPage } from "@/pages/SettingsPage";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/projects/:projectId" element={<ProjectPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/run/:runId" element={<RunPage />} />
            <Route path="/run/:runId/discovery" element={<DiscoveryPage />} />
            <Route path="/run/:runId/extract" element={<ExtractPage />} />
            <Route path="/run/:runId/review" element={<ReviewPage />} />
            <Route path="/run/:runId/dashboard" element={<DashboardPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
