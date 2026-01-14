import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import BacktestInlinePreview from "../components/BacktestInlinePreview";
import PaginationBar from "../components/PaginationBar";
import ReportsPanel from "../components/ReportsPanel";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { Paginated } from "../types";

interface Backtest {
  id: number;
  project_id: number;
  status: string;
  params?: Record<string, unknown> | null;
  metrics?: Record<string, unknown> | null;
  report_id?: number | null;
  created_at: string;
  ended_at?: string | null;
}

interface BacktestProgress {
  run_id: number;
  status?: string | null;
  progress?: number | null;
  as_of?: string | null;
}

const apiBase = import.meta.env.VITE_API_BASE_URL || "http://localhost:8021";

export default function BacktestsPage() {
  const { t, formatDateTime } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<"runs" | "reports">("runs");
  const [runs, setRuns] = useState<Backtest[]>([]);
  const [runTotal, setRunTotal] = useState(0);
  const [runPage, setRunPage] = useState(1);
  const [runPageSize, setRunPageSize] = useState(10);
  const [projectId, setProjectId] = useState("");
  const [params, setParams] = useState("{}");
  const [previewReportId, setPreviewReportId] = useState<number | null>(null);
  const [progressMap, setProgressMap] = useState<Record<number, BacktestProgress>>({});
  const [previewRunId, setPreviewRunId] = useState<number | null>(null);
  const [previewTab, setPreviewTab] = useState<"charts" | "trades">("charts");
  const previewRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const tab = new URLSearchParams(location.search).get("tab");
    if (tab === "reports") {
      setActiveTab("reports");
      return;
    }
    if (tab === "runs") {
      setActiveTab("runs");
    }
  }, [location.search]);

  const setBacktestTab = (tab: "runs" | "reports") => {
    setActiveTab(tab);
    const params = new URLSearchParams(location.search);
    if (tab === "reports") {
      params.set("tab", "reports");
    } else {
      params.delete("tab");
    }
    const nextSearch = params.toString();
    navigate(
      {
        pathname: "/backtests",
        search: nextSearch ? `?${nextSearch}` : "",
      },
      { replace: true }
    );
  };

  const metricItems = useMemo(
    () => [
      { key: "Compounding Annual Return", label: t("metrics.cagr") },
      { key: "Drawdown", label: t("metrics.drawdown") },
      { key: "Sharpe Ratio", label: t("metrics.sharpe") },
      { key: "Net Profit", label: t("metrics.netProfit") },
      { key: "Total Fees", label: t("metrics.totalFees") },
      { key: "Portfolio Turnover", label: t("metrics.turnover") },
      { key: "Turnover_week", label: t("metrics.turnoverWeekAvg") },
      { key: "Turnover_sanity_ratio", label: t("metrics.turnoverSanityRatio") },
      { key: "Risk Status", label: t("metrics.riskStatus") },
    ],
    [t]
  );

  const parseDateParts = (raw: unknown) => {
    const text = String(raw ?? "").trim();
    if (!text) {
      return null;
    }
    const match = text.match(/(\d{4})[-/](\d{2})[-/](\d{2})/);
    if (!match) {
      return null;
    }
    return {
      full: `${match[1]}-${match[2]}-${match[3]}`,
      short: `${match[1]}-${match[2]}`,
    };
  };

  const resolveBacktestRange = (run: Backtest) => {
    const params = (run.params ?? {}) as Record<string, unknown>;
    const algoParams =
      params && typeof params.algorithm_parameters === "object"
        ? (params.algorithm_parameters as Record<string, unknown>)
        : {};
    const startRaw =
      algoParams.backtest_start ?? params.backtest_start ?? params.backtestStart;
    const endRaw =
      algoParams.backtest_end ?? params.backtest_end ?? params.backtestEnd;
    const start = parseDateParts(startRaw);
    const end = parseDateParts(endRaw);
    if (!start && !end) {
      return { text: t("common.none"), title: "" };
    }
    const text = `${start?.short ?? "--"}~${end?.short ?? "--"}`;
    const title = `${start?.full ?? "--"} ~ ${end?.full ?? "--"}`;
    return { text, title };
  };

  const loadProgress = async (items: Backtest[]) => {
    const activeRuns = items.filter(
      (run) => run.status !== "success" && run.status !== "failed"
    );
    if (!activeRuns.length) {
      setProgressMap({});
      return;
    }
    const progressItems = await Promise.all(
      activeRuns.map(async (run) => {
        try {
          const res = await api.get<BacktestProgress>(`/api/backtests/${run.id}/progress`);
          return res.data;
        } catch {
          return null;
        }
      })
    );
    const nextMap: Record<number, BacktestProgress> = {};
    progressItems.forEach((item) => {
      if (item) {
        nextMap[item.run_id] = item;
      }
    });
    setProgressMap(nextMap);
  };

  const loadRuns = async (pageOverride?: number, pageSizeOverride?: number) => {
    const nextPage = pageOverride ?? runPage;
    const nextSize = pageSizeOverride ?? runPageSize;
    const res = await api.get<Paginated<Backtest>>("/api/backtests/page", {
      params: { page: nextPage, page_size: nextSize },
    });
    const items = [...res.data.items].sort((a, b) => b.id - a.id);
    setRuns(items);
    setRunTotal(res.data.total);
    await loadProgress(items);
  };

  useEffect(() => {
    loadRuns();
    const timer = window.setInterval(() => {
      loadRuns();
    }, 8000);
    return () => window.clearInterval(timer);
  }, [runPage, runPageSize]);

  const createRun = async () => {
    if (!projectId.trim()) {
      return;
    }
    let parsed: Record<string, unknown> | null = null;
    try {
      parsed = JSON.parse(params);
    } catch {
      parsed = null;
    }
    await api.post("/api/backtests", {
      project_id: Number(projectId),
      params: parsed,
    });
    setProjectId("");
    setParams("{}");
    setRunPage(1);
    loadRuns(1, runPageSize);
  };

  const renderStatus = (value: string) => t(`common.status.${value}`) || value;
  const renderProgress = (run: Backtest) => {
    const progress = progressMap[run.id];
    if (!progress || progress.progress == null) {
      return t("common.none");
    }
    const percent = `${(progress.progress * 100).toFixed(2)}%`;
    return (
      <div>
        <div>{percent}</div>
        {progress.as_of && <div className="form-hint">{progress.as_of}</div>}
      </div>
    );
  };

  const openPreview = (runId: number, tab: "charts" | "trades") => {
    setPreviewRunId(runId);
    setPreviewTab(tab);
    window.setTimeout(() => {
      previewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  };

  return (
    <div className="main">
      <TopBar title={t("backtests.title")} />
      <div className="content">
        <div className="project-tabs">
          {[
            { key: "runs", label: t("backtests.tabs.runs") },
            { key: "reports", label: t("backtests.tabs.reports") },
          ].map((tab) => (
            <button
              key={tab.key}
              className={activeTab === tab.key ? "tab-button active" : "tab-button"}
              onClick={() => setBacktestTab(tab.key as "runs" | "reports")}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {activeTab === "reports" ? (
          <ReportsPanel />
        ) : (
          <>
        <div className="card">
          <div className="card-title">{t("backtests.launch.title")}</div>
          <div className="card-meta">{t("backtests.launch.meta")}</div>
          <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
            <input
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder={t("backtests.launch.projectId")}
              style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
            />
            <textarea
              value={params}
              onChange={(e) => setParams(e.target.value)}
              rows={4}
              placeholder='{"costs": {"fee_bps": 1.0, "slippage_open_bps": 8.0, "slippage_close_bps": 8.0}, "risk": {"max_drawdown": 0.35, "min_sharpe": 0.5}}'
              style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
            />
            <button
              onClick={createRun}
              style={{
                padding: "10px",
                borderRadius: "10px",
                border: "none",
                background: "#0f62fe",
                color: "#fff",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {t("common.actions.run")}
            </button>
          </div>
        </div>

        <table className="table backtest-table">
          <thead>
            <tr>
              <th className="backtest-id">{t("backtests.table.id")}</th>
              <th className="backtest-project">{t("backtests.table.project")}</th>
              <th className="backtest-status">{t("backtests.table.status")}</th>
              <th className="backtest-progress">{t("backtests.table.progress")}</th>
              <th className="backtest-range-cell">{t("backtests.table.range")}</th>
              {metricItems.map((item) => (
                <th key={item.key} className="backtest-metric">
                  {item.label}
                </th>
              ))}
              <th className="backtest-report">{t("backtests.table.report")}</th>
              <th className="backtest-actions">{t("backtests.table.actions")}</th>
              <th className="backtest-created">{t("backtests.table.createdAt")}</th>
              <th className="backtest-ended">{t("backtests.table.endedAt")}</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td className="backtest-id">{run.id}</td>
                <td className="backtest-project">{run.project_id}</td>
                <td className="backtest-status">
                  <span className={`pill ${run.status === "success" ? "success" : "danger"}`}>
                    {renderStatus(run.status)}
                  </span>
                </td>
                <td className="backtest-progress">{renderProgress(run)}</td>
                <td className="backtest-range-cell">
                  {(() => {
                    const range = resolveBacktestRange(run);
                    return (
                      <span className="backtest-range-text" title={range.title}>
                        {range.text}
                      </span>
                    );
                  })()}
                </td>
                {metricItems.map((item) => (
                  <td key={item.key} className="backtest-metric">
                    {run.metrics?.[item.key] ?? t("common.none")}
                  </td>
                ))}
                <td className="backtest-report">
                  {run.report_id ? (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setPreviewReportId(run.report_id ?? null)}
                    >
                      {t("common.actions.view")}
                    </button>
                  ) : (
                    t("common.none")
                  )}
                </td>
                <td className="backtest-actions">
                  <div className="table-actions">
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => openPreview(run.id, "charts")}
                    >
                      {t("backtests.actions.viewCharts")}
                    </button>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => openPreview(run.id, "trades")}
                    >
                      {t("backtests.actions.viewTrades")}
                    </button>
                  </div>
                </td>
                <td className="backtest-created">{formatDateTime(run.created_at)}</td>
                <td className="backtest-ended">
                  {run.ended_at ? formatDateTime(run.ended_at) : t("common.none")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <PaginationBar
          page={runPage}
          pageSize={runPageSize}
          total={runTotal}
          onPageChange={setRunPage}
          onPageSizeChange={(size) => {
            setRunPage(1);
            setRunPageSize(size);
          }}
        />
        <div className="card">
          <div className="card-title">{t("reports.preview.title")}</div>
          <div className="card-meta">{t("reports.preview.meta")}</div>
          {previewReportId ? (
            <>
              <div className="preview-toolbar">
                <a
                  href={`${apiBase}/api/reports/${previewReportId}/file`}
                  target="_blank"
                  rel="noreferrer"
                  className="link-button"
                >
                  {t("reports.preview.open")}
                </a>
              </div>
              <iframe
                title="backtest-report-preview"
                src={`${apiBase}/api/reports/${previewReportId}/file`}
                className="preview-frame"
              />
            </>
          ) : (
            <div className="empty-state">{t("reports.preview.empty")}</div>
          )}
        </div>
        <div ref={previewRef}>
          <BacktestInlinePreview
            runId={previewRunId}
            activeTab={previewTab}
            onTabChange={setPreviewTab}
          />
        </div>
          </>
        )}
      </div>
    </div>
  );
}
