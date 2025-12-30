import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import BacktestsPage from "./pages/BacktestsPage";
import DataPage from "./pages/DataPage";
import AlgorithmsPage from "./pages/AlgorithmsPage";
import ProjectsPage from "./pages/ProjectsPage";
import ReportsPage from "./pages/ReportsPage";
import AuditLogsPage from "./pages/AuditLogsPage";

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <Routes>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/algorithms" element={<AlgorithmsPage />} />
        <Route path="/backtests" element={<BacktestsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/data" element={<DataPage />} />
        <Route path="/audit-logs" element={<AuditLogsPage />} />
      </Routes>
    </div>
  );
}
