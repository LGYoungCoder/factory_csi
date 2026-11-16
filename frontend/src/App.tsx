import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import WorkspacePage from "@/pages/WorkspacePage";
import ReportPage from "@/pages/ReportPage";
import { I18nProvider } from "@/i18n";

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } } });

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <I18nProvider>
      <Tooltip.Provider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<WorkspacePage />} />
            <Route path="/cases/:id/report" element={<ReportPage />} />
          </Routes>
        </BrowserRouter>
      </Tooltip.Provider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
