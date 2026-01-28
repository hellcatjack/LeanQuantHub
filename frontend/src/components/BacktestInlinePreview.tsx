import { useEffect, useState } from "react";
import { api, apiBaseUrl } from "../api";
import BacktestChartPanel from "./BacktestChartPanel";
import BacktestPerformanceChart from "./BacktestPerformanceChart";
import { useI18n } from "../i18n";

interface ReportItem {
  id: number;
  report_type: string;
}

type ChartPoint = { time: number; value: number };

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
      const time = Number(entry[0]);
      const value = Number(entry[1]);
      if (!Number.isFinite(value)) {
        return null;
      }
      return { time: Number.isFinite(time) ? time : index, value };
    })
    .filter(Boolean) as ChartPoint[];
};

const isFlatSeries = (points: ChartPoint[]) => {
  if (points.length < 2) {
    return true;
  }
  const values = points.map((item) => item.value).filter((value) => Number.isFinite(value));
  if (values.length < 2) {
    return true;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const base = Math.abs(max) || 1;
  return span / base < 1e-6;
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
  const [benchmarkPoints, setBenchmarkPoints] = useState<ChartPoint[]>([]);
  const [longExposurePoints, setLongExposurePoints] = useState<ChartPoint[]>([]);
  const [shortExposurePoints, setShortExposurePoints] = useState<ChartPoint[]>([]);
  const [defensiveExposurePoints, setDefensiveExposurePoints] = useState<ChartPoint[]>([]);
  const [reportHtmlId, setReportHtmlId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorKey, setErrorKey] = useState("");

  useEffect(() => {
    const load = async () => {
      if (!runId) {
        setEquityPoints([]);
        setDrawdownPoints([]);
        setBenchmarkPoints([]);
        setLongExposurePoints([]);
        setShortExposurePoints([]);
        setDefensiveExposurePoints([]);
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
          setBenchmarkPoints([]);
          setLongExposurePoints([]);
          setShortExposurePoints([]);
          setDefensiveExposurePoints([]);
          setErrorKey("reports.charts.errorNotFound");
          return;
        }
        const fileRes = await fetch(`${apiBaseUrl}/api/reports/${resultReport.id}/file`);
        const payload = await fileRes.json();
        const nextEquity = extractSeries(payload, "Strategy Equity", "Equity");
        const nextDrawdown = extractSeries(payload, "Drawdown", "Equity Drawdown");
        const reportBenchmark = extractSeries(payload, "Benchmark", "Benchmark");
        const nextLong = extractSeries(payload, "Exposure", "Equity - Long Ratio");
        const nextShort = extractSeries(payload, "Exposure", "Equity - Short Ratio");
        const nextDefensive = extractSeries(payload, "Exposure Extra", "Defensive Ratio");
        setEquityPoints(nextEquity);
        setDrawdownPoints(nextDrawdown);
        setLongExposurePoints(nextLong);
        setShortExposurePoints(nextShort);
        setDefensiveExposurePoints(nextDefensive);

        let resolvedBenchmark = reportBenchmark;
        if (isFlatSeries(reportBenchmark)) {
          try {
            const runRes = await api.get(`/api/backtests/${runId}`);
            const runParams = (runRes.data as any)?.params || {};
            const algoParams = runParams.algorithm_parameters || {};
            const benchmarkSymbol =
              runParams.benchmark || algoParams.benchmark || "SPY";
            const start =
              algoParams.backtest_start ||
              algoParams.start_date ||
              algoParams.start ||
              undefined;
            const end =
              algoParams.backtest_end ||
              algoParams.end_date ||
              algoParams.end ||
              undefined;
            const chartRes = await api.get(`/api/backtests/${runId}/chart`, {
              params: { symbol: String(benchmarkSymbol).toUpperCase() },
            });
            const dataset = (chartRes.data as any)?.dataset;
            if (dataset?.id) {
              const seriesRes = await api.get(`/api/datasets/${dataset.id}/series`, {
                params: { mode: "adjusted", start, end },
              });
              const adjusted = (seriesRes.data as any)?.adjusted || [];
              const candles = (seriesRes.data as any)?.candles || [];
              const pointsFromAdjusted = adjusted
                .map((item: any) => ({
                  time: Number(item.time),
                  value: Number(item.value),
                }))
                .filter((item: ChartPoint) => Number.isFinite(item.value));
              if (pointsFromAdjusted.length) {
                resolvedBenchmark = pointsFromAdjusted;
              } else if (candles.length) {
                const pointsFromCandles = candles
                  .map((item: any) => ({
                    time: Number(item.time),
                    value: Number(item.close),
                  }))
                  .filter((item: ChartPoint) => Number.isFinite(item.value));
                resolvedBenchmark = pointsFromCandles;
              }
            }
          } catch {
            // fall back to report benchmark
          }
        }
        setBenchmarkPoints(resolvedBenchmark);
      } catch (err) {
        setEquityPoints([]);
        setDrawdownPoints([]);
        setBenchmarkPoints([]);
        setLongExposurePoints([]);
        setShortExposurePoints([]);
        setDefensiveExposurePoints([]);
        setErrorKey("reports.charts.errorLoad");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [runId]);

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
              href={`${apiBaseUrl}/api/reports/${reportHtmlId}/file`}
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
        <BacktestPerformanceChart
          equityPoints={equityPoints}
          drawdownPoints={drawdownPoints}
          benchmarkPoints={benchmarkPoints}
          longExposurePoints={longExposurePoints}
          shortExposurePoints={shortExposurePoints}
          defensiveExposurePoints={defensiveExposurePoints}
          loading={loading}
          errorKey={errorKey}
        />
      ) : (
        <BacktestChartPanel runId={runId} />
      )}
    </div>
  );
}
