import { useEffect, useMemo, useState } from "react";
import { api, apiBaseUrl } from "../api";
import PaginationBar from "./PaginationBar";
import BacktestChartPanel from "./BacktestChartPanel";
import { useI18n } from "../i18n";
import { Paginated } from "../types";

interface Report {
  id: number;
  run_id: number;
  report_type: string;
  path: string;
  created_at: string;
}

interface CompareItem {
  id: number;
  project_id: number;
  project_name?: string | null;
  status: string;
  metrics?: Record<string, unknown> | null;
  created_at: string;
  ended_at?: string | null;
}

type ChartPoint = { x: number; y: number };

const extractSeries = (data: any, chartName: string, seriesName: string): ChartPoint[] => {
  const charts = data?.charts || {};
  const chart = charts[chartName];
  const series = chart?.series?.[seriesName];
  const values = Array.isArray(series?.values) ? series.values : [];
  return values
    .map((entry: any, index: number) => {
      if (!Array.isArray(entry) || entry.length < 2) {
        return null;
      }
      const x = Number(entry[0]);
      const y = Number(entry[1]);
      if (!Number.isFinite(y)) {
        return null;
      }
      return { x: Number.isFinite(x) ? x : index, y };
    })
    .filter(Boolean) as ChartPoint[];
};

const LineChart = ({
  title,
  points,
  stroke = "#0f62fe",
  summary,
  emptyText,
}: {
  title: string;
  points: ChartPoint[];
  stroke?: string;
  summary: string;
  emptyText: string;
}) => {
  if (!points.length) {
    return (
      <div className="card">
        <div className="card-title">{title}</div>
        <div className="card-meta">{emptyText}</div>
      </div>
    );
  }

  const width = 640;
  const height = 220;
  const padding = 28;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const scaleX = (value: number) =>
    padding + ((value - minX) / spanX) * (width - padding * 2);
  const scaleY = (value: number) =>
    height - padding - ((value - minY) / spanY) * (height - padding * 2);

  const path = points
    .map((point, idx) => {
      const x = scaleX(point.x);
      const y = scaleY(point.y);
      return `${idx === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className="card-meta">{summary}</div>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height}>
        <rect x="0" y="0" width={width} height={height} fill="#ffffff" />
        <line
          x1={padding}
          y1={height - padding}
          x2={width - padding}
          y2={height - padding}
          stroke="#e3e6ee"
        />
        <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="#e3e6ee" />
        <path d={path} fill="none" stroke={stroke} strokeWidth={2} />
      </svg>
    </div>
  );
};

export default function ReportsPanel() {
  const { t, formatDateTime } = useI18n();
  const [reports, setReports] = useState<Report[]>([]);
  const [reportTotal, setReportTotal] = useState(0);
  const [reportPage, setReportPage] = useState(1);
  const [reportPageSize, setReportPageSize] = useState(10);
  const [compareInput, setCompareInput] = useState("");
  const [compareItems, setCompareItems] = useState<CompareItem[]>([]);
  const [compareErrorKey, setCompareErrorKey] = useState("");
  const [chartInput, setChartInput] = useState("");
  const [chartErrorKey, setChartErrorKey] = useState("");
  const [equityPoints, setEquityPoints] = useState<ChartPoint[]>([]);
  const [drawdownPoints, setDrawdownPoints] = useState<ChartPoint[]>([]);
  const [tradeChartInput, setTradeChartInput] = useState("");
  const [tradeChartRunId, setTradeChartRunId] = useState<number | null>(null);
  const [previewReportId, setPreviewReportId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

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

  const loadReports = async (pageOverride?: number, pageSizeOverride?: number) => {
    const nextPage = pageOverride ?? reportPage;
    const nextSize = pageSizeOverride ?? reportPageSize;
    const res = await api.get<Paginated<Report>>("/api/reports/page", {
      params: { page: nextPage, page_size: nextSize },
    });
    setReports(res.data.items);
    setReportTotal(res.data.total);
  };

  useEffect(() => {
    loadReports();
  }, [reportPage, reportPageSize]);

  const runCompare = async () => {
    const ids = compareInput
      .split(/[,\s]+/)
      .map((value) => value.trim())
      .filter(Boolean)
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value));
    if (!ids.length) {
      setCompareErrorKey("reports.compare.empty");
      setCompareItems([]);
      return;
    }
    setCompareErrorKey("");
    try {
      const res = await api.post<CompareItem[]>("/api/backtests/compare", {
        run_ids: ids,
      });
      setCompareItems(res.data);
    } catch (err: any) {
      setCompareErrorKey("reports.compare.error");
      setCompareItems([]);
    }
  };

  const loadCharts = async () => {
    const runId = Number(chartInput);
    if (!Number.isFinite(runId)) {
      setChartErrorKey("reports.compare.empty");
      setEquityPoints([]);
      setDrawdownPoints([]);
      return;
    }
    setChartErrorKey("");
    try {
      const res = await api.get<Report[]>("/api/reports", {
        params: { run_id: runId },
      });
      const resultReport = res.data.find((report) => report.report_type === "result");
      if (!resultReport) {
        setChartErrorKey("reports.charts.errorNotFound");
        setEquityPoints([]);
        setDrawdownPoints([]);
        return;
      }
      const fileRes = await fetch(`${apiBaseUrl}/api/reports/${resultReport.id}/file`);
      const payload = await fileRes.json();
      const equity = extractSeries(payload, "Strategy Equity", "Equity");
      const drawdown = extractSeries(payload, "Drawdown", "Equity Drawdown");
      setEquityPoints(equity);
      setDrawdownPoints(drawdown);
    } catch (err) {
      setChartErrorKey("reports.charts.errorLoad");
      setEquityPoints([]);
      setDrawdownPoints([]);
    }
  };

  const formatChartSummary = (points: ChartPoint[]) => {
    if (!points.length) {
      return "";
    }
    const startValue = points[0].y.toFixed(2);
    const endValue = points[points.length - 1].y.toFixed(2);
    return t("charts.pointsSummary", {
      count: points.length,
      start: startValue,
      end: endValue,
    });
  };

  return (
    <>
      <div className="card">
        <div className="card-title">{t("reports.latest.title")}</div>
        <div className="card-meta">{t("reports.latest.meta")}</div>
      </div>

      <div className="card" style={{ border: "1px solid #f5c2c7", background: "#fff5f5" }}>
        <div className="card-title">{t("reports.risk.title")}</div>
        <div className="card-meta">{t("reports.risk.meta")}</div>
      </div>

      <div className="card">
        <div className="card-title">{t("reports.compare.title")}</div>
        <div className="card-meta">{t("reports.compare.meta")}</div>
        <div style={{ marginTop: "12px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <input
            value={compareInput}
            onChange={(e) => setCompareInput(e.target.value)}
            placeholder={t("reports.compare.placeholder")}
            style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee", minWidth: 220 }}
          />
          <button
            onClick={runCompare}
            style={{
              padding: "10px 16px",
              borderRadius: "10px",
              border: "none",
              background: "#0f62fe",
              color: "#fff",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {t("common.actions.compare")}
          </button>
        </div>
        {compareErrorKey && (
          <div style={{ marginTop: "10px", color: "#d64545", fontSize: "13px" }}>
            {t(compareErrorKey)}
          </div>
        )}
      </div>

      {compareItems.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>{t("reports.table.runId")}</th>
              <th>{t("backtests.table.project")}</th>
              <th>{t("backtests.table.status")}</th>
              {metricItems.map((item) => (
                <th key={item.key}>{item.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {compareItems.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.project_name || item.project_id}</td>
                <td>{item.status}</td>
                {metricItems.map((metric) => (
                  <td key={metric.key}>{item.metrics?.[metric.key] ?? t("common.none")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="card">
        <div className="card-title">{t("reports.charts.title")}</div>
        <div className="card-meta">{t("reports.charts.meta")}</div>
        <div style={{ marginTop: "12px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <input
            value={chartInput}
            onChange={(e) => setChartInput(e.target.value)}
            placeholder={t("reports.charts.placeholder")}
            style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee", minWidth: 180 }}
          />
          <button
            onClick={loadCharts}
            style={{
              padding: "10px 16px",
              borderRadius: "10px",
              border: "none",
              background: "#0f62fe",
              color: "#fff",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {t("common.actions.loadCharts")}
          </button>
        </div>
        {chartErrorKey && (
          <div style={{ marginTop: "10px", color: "#d64545", fontSize: "13px" }}>
            {t(chartErrorKey)}
          </div>
        )}
      </div>

      {(equityPoints.length > 0 || drawdownPoints.length > 0) && (
        <div className="grid-2">
          <LineChart
            title={t("charts.equityCurve")}
            points={equityPoints}
            summary={formatChartSummary(equityPoints)}
            emptyText={t("charts.noData")}
          />
          <LineChart
            title={t("charts.drawdownCurve")}
            points={drawdownPoints}
            summary={formatChartSummary(drawdownPoints)}
            emptyText={t("charts.noData")}
            stroke="#d64545"
          />
        </div>
      )}

      <div className="card">
        <div className="card-title">{t("reports.trades.title")}</div>
        <div className="card-meta">{t("reports.trades.meta")}</div>
        <div style={{ marginTop: "12px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <input
            value={tradeChartInput}
            onChange={(e) => setTradeChartInput(e.target.value)}
            placeholder={t("reports.trades.placeholder")}
            style={{
              padding: "10px",
              borderRadius: "10px",
              border: "1px solid #e3e6ee",
              minWidth: 180,
            }}
          />
          <button
            onClick={() => {
              const nextId = Number(tradeChartInput);
              if (Number.isFinite(nextId)) {
                setTradeChartRunId(nextId);
              } else {
                setTradeChartRunId(null);
              }
            }}
            style={{
              padding: "10px 16px",
              borderRadius: "10px",
              border: "none",
              background: "#0f62fe",
              color: "#fff",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {t("reports.trades.load")}
          </button>
        </div>
      </div>

      {tradeChartRunId && <BacktestChartPanel runId={tradeChartRunId} />}

      <table className="table">
        <thead>
          <tr>
            <th>{t("reports.table.id")}</th>
            <th>{t("reports.table.runId")}</th>
            <th>{t("reports.table.type")}</th>
            <th>{t("reports.table.path")}</th>
            <th>{t("reports.table.actions")}</th>
            <th>{t("reports.table.createdAt")}</th>
          </tr>
        </thead>
        <tbody>
          {reports.map((report) => (
            <tr key={report.id}>
              <td>{report.id}</td>
              <td>{report.run_id}</td>
              <td>{report.report_type}</td>
              <td>{report.path}</td>
              <td>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => {
                    setPreviewReportId(report.id);
                    setDrawerOpen(true);
                  }}
                >
                  {t("common.actions.view")}
                </button>
                <span style={{ margin: "0 6px", color: "#c1c7d0" }}>|</span>
                {report.report_type === "html" ? (
                  <a
                    href={`${apiBaseUrl}/api/reports/${report.id}/file`}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "#0f62fe", fontWeight: 600 }}
                  >
                    {t("reports.preview.open")}
                  </a>
                ) : (
                  <a
                    href={`${apiBaseUrl}/api/reports/${report.id}/file?download=1`}
                    download
                    style={{ color: "#0f62fe", fontWeight: 600 }}
                  >
                    {t("common.actions.download")}
                  </a>
                )}
              </td>
              <td>{formatDateTime(report.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <PaginationBar
        page={reportPage}
        pageSize={reportPageSize}
        total={reportTotal}
        onPageChange={setReportPage}
        onPageSizeChange={(size) => {
          setReportPage(1);
          setReportPageSize(size);
        }}
      />

      <div className="card">
        <div className="card-title">{t("reports.preview.title")}</div>
        <div className="card-meta">{t("reports.preview.meta")}</div>
        {!drawerOpen && previewReportId ? (
          <>
            <div className="preview-toolbar">
              <a
                href={`${apiBaseUrl}/api/reports/${previewReportId}/file`}
                target="_blank"
                rel="noreferrer"
                className="link-button"
              >
                {t("reports.preview.open")}
              </a>
            </div>
              <iframe
                title="report-preview"
                src={`${apiBaseUrl}/api/reports/${previewReportId}/file`}
                className="preview-frame"
              />
            </>
          ) : (
            <div className="empty-state">{t("reports.preview.empty")}</div>
          )}
      </div>
      {drawerOpen && previewReportId && (
        <div className="report-drawer-overlay" onClick={() => setDrawerOpen(false)}>
          <div className="report-drawer" onClick={(event) => event.stopPropagation()}>
            <div className="report-drawer-header">
              <div className="report-drawer-title">{t("reports.preview.title")}</div>
              <div className="report-drawer-actions">
                <a
                  href={`${apiBaseUrl}/api/reports/${previewReportId}/file`}
                  target="_blank"
                  rel="noreferrer"
                  className="link-button"
                >
                  {t("reports.preview.open")}
                </a>
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => setDrawerOpen(false)}
                >
                  {t("common.actions.close")}
                </button>
              </div>
            </div>
            <iframe
              title="report-drawer-preview"
              src={`${apiBaseUrl}/api/reports/${previewReportId}/file`}
              className="report-drawer-frame"
            />
          </div>
        </div>
      )}
    </>
  );
}
