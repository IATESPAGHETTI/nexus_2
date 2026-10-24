import { Route, Routes } from "react-router-dom";
import { AgentControlProvider } from "./context/AgentControlContext";
import { AppShell } from "./components/layout/AppShell";
import { MissionControlPage } from "./pages/MissionControlPage";
import { InvestigationPage } from "./pages/InvestigationPage";
import { PresentationPage } from "./pages/PresentationPage";
import { ResearchPage } from "./pages/ResearchPage";

export default function App() {
  return (
    <AgentControlProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<MissionControlPage />} />
          <Route path="/incidents/:incidentId" element={<InvestigationPage />} />
          <Route path="/presentation" element={<PresentationPage />} />
          <Route path="/research" element={<ResearchPage />} />
        </Routes>
      </AppShell>
    </AgentControlProvider>
  );
}
