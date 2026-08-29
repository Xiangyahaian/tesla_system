import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { CabinFrame } from "@/components/layout/CabinFrame";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<CabinFrame />}>
          <Route index element={null} />
          <Route path="apps" element={null} />
          <Route path="agent" element={null} />
          <Route path="settings" element={null} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
