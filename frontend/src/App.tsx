import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import BacktestsPage from "./pages/BacktestsPage";
import DataPage from "./pages/DataPage";
import AlgorithmsPage from "./pages/AlgorithmsPage";
import ProjectsPage from "./pages/ProjectsPage";
import ThemesPage from "./pages/ThemesPage";
import AuditLogsPage from "./pages/AuditLogsPage";
import DatasetChartPage from "./pages/DatasetChartPage";
import LiveTradePage from "./pages/LiveTradePage";
import LeanBridgePoolPage from "./pages/LeanBridgePoolPage";

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <Routes>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/themes" element={<ThemesPage />} />
        <Route path="/algorithms" element={<AlgorithmsPage />} />
        <Route path="/backtests" element={<BacktestsPage />} />
        <Route path="/reports" element={<Navigate to="/backtests?tab=reports" replace />} />
        <Route path="/live-trade" element={<LiveTradePage />} />
        <Route path="/live-trade/bridge-pool" element={<LeanBridgePoolPage />} />
        <Route path="/data" element={<DataPage />} />
        <Route path="/data/charts/:datasetId" element={<DatasetChartPage />} />
        <Route path="/audit-logs" element={<AuditLogsPage />} />
      </Routes>
    </div>
  );
}
