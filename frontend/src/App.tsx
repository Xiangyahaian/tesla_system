import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { CabinFrame } from "@/components/layout/CabinFrame";
import { DrivePage } from "@/pages/DrivePage";
import { AppsPage } from "@/pages/AppsPage";
import { AgentPage } from "@/pages/AgentPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<CabinFrame />}>
          <Route index element={<DrivePage />} />
          <Route path="apps" element={<AppsPage />} />
          <Route path="agent" element={<AgentPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
