import { useEffect, useState } from "react";
import { api } from "../api";
import BacktestChartPanel from "./BacktestChartPanel";
import { useI18n } from "../i18n";

interface ReportItem {
  id: number;
  report_type: string;
}

type ChartPoint = { x: number; y: number };

const apiBase = import.meta.env.VITE_API_BASE_URL || "";

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

interface BacktestInlinePreviewProps {
  runId: number | null;
  activeTab: "charts" | "trades";
  onTabChange: (tab: "charts" | "trades") => void;
}

export default function BacktestInlinePreview({
  runId,
  activeTab,
  onTabChange,
}: BacktestInlinePreviewProps) {
  const { t } = useI18n();
  const [equityPoints, setEquityPoints] = useState<ChartPoint[]>([]);
  const [drawdownPoints, setDrawdownPoints] = useState<ChartPoint[]>([]);
  const [reportHtmlId, setReportHtmlId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorKey, setErrorKey] = useState("");

  useEffect(() => {
    const load = async () => {
      if (!runId) {
        setEquityPoints([]);
        setDrawdownPoints([]);
        setReportHtmlId(null);
        setErrorKey("");
        return;
      }
      setLoading(true);
      setErrorKey("");
      try {
        const res = await api.get<ReportItem[]>("/api/reports", {
          params: { run_id: runId },
        });
        const htmlReport = res.data.find((item) => item.report_type === "html");
        const resultReport = res.data.find((item) => item.report_type === "result");
        setReportHtmlId(htmlReport?.id ?? null);
        if (!resultReport) {
          setEquityPoints([]);
          setDrawdownPoints([]);
          setErrorKey("reports.charts.errorNotFound");
          return;
        }
        const fileRes = await fetch(`${apiBase}/api/reports/${resultReport.id}/file`);
        const payload = await fileRes.json();
        setEquityPoints(extractSeries(payload, "Strategy Equity", "Equity"));
        setDrawdownPoints(extractSeries(payload, "Drawdown", "Equity Drawdown"));
      } catch (err) {
        setEquityPoints([]);
        setDrawdownPoints([]);
        setErrorKey("reports.charts.errorLoad");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [runId]);

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

  if (!runId) {
    return (
      <div className="card">
        <div className="card-title">{t("backtests.preview.title")}</div>
        <div className="card-meta">{t("backtests.preview.empty")}</div>
      </div>
    );
  }

  return (
    <div className="card backtest-preview">
      <div className="backtest-preview-header">
        <div>
          <div className="card-title">{t("backtests.preview.title")}</div>
          <div className="card-meta">{t("backtests.preview.meta")}</div>
        </div>
        <div className="backtest-preview-actions">
          {reportHtmlId && (
            <a
              className="link-button"
              href={`${apiBase}/api/reports/${reportHtmlId}/file`}
              target="_blank"
              rel="noreferrer"
            >
              {t("reports.preview.open")}
            </a>
          )}
        </div>
      </div>
      <div className="project-tabs backtest-preview-tabs">
        {[
          { key: "charts", label: t("backtests.preview.charts") },
          { key: "trades", label: t("backtests.preview.trades") },
        ].map((tab) => (
          <button
            key={tab.key}
            className={activeTab === tab.key ? "tab-button active" : "tab-button"}
            onClick={() => onTabChange(tab.key as "charts" | "trades")}
          >
            {tab.label}
          </button>
        ))}
        {loading && <span className="form-hint">{t("common.status.loading")}</span>}
        {errorKey && <span className="form-hint danger">{t(errorKey)}</span>}
      </div>
      {activeTab === "charts" ? (
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
      ) : (
        <BacktestChartPanel runId={runId} />
      )}
    </div>
  );
}
