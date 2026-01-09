import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type AreaData,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useI18n } from "../i18n";

type ChartPoint = { time: number; value: number };

interface BacktestPerformanceChartProps {
  equityPoints: ChartPoint[];
  drawdownPoints: ChartPoint[];
  benchmarkPoints: ChartPoint[];
  longExposurePoints: ChartPoint[];
  shortExposurePoints: ChartPoint[];
  defensiveExposurePoints: ChartPoint[];
  loading?: boolean;
  errorKey?: string;
}

type LegendState = {
  timeText: string;
  equity?: number;
  drawdown?: number;
  benchmark?: number;
  benchmarkDrawdown?: number;
  long?: number;
  defensive?: number;
  cash?: number;
};

const toSafePoints = (points: ChartPoint[]) =>
  points
    .filter((item) => Number.isFinite(item.time) && Number.isFinite(item.value))
    .sort((a, b) => a.time - b.time);

const toReturnSeries = (points: ChartPoint[]) => {
  const safe = toSafePoints(points);
  if (safe.length < 2) {
    return [];
  }
  const base = safe[0].value;
  if (!Number.isFinite(base) || base === 0) {
    return [];
  }
  return safe.map((item) => ({
    time: item.time,
    value: ((item.value / base) - 1) * 100,
  }));
};

const normalizePercentSeries = (points: ChartPoint[]) => {
  const safe = toSafePoints(points);
  if (!safe.length) {
    return [];
  }
  const maxAbs = Math.max(...safe.map((item) => Math.abs(item.value)));
  if (maxAbs <= 1.5) {
    return safe.map((item) => ({ time: item.time, value: item.value * 100 }));
  }
  return safe;
};

const toDrawdownSeries = (points: ChartPoint[]) => {
  const safe = toSafePoints(points);
  if (!safe.length) {
    return [];
  }
  let peak = safe[0].value;
  return safe.map((item) => {
    if (item.value > peak) {
      peak = item.value;
    }
    const drawdown = peak > 0 ? ((item.value / peak) - 1) * 100 : 0;
    return { time: item.time, value: drawdown };
  });
};

const buildMap = (points: ChartPoint[]) =>
  new Map(points.map((item) => [item.time, item.value]));

const toLineData = (points: ChartPoint[]) =>
  points
    .filter((item) => Number.isFinite(item.value))
    .map((item) => ({ time: item.time as Time, value: item.value } as LineData));

const toAreaData = (points: ChartPoint[]) =>
  points
    .filter((item) => Number.isFinite(item.value))
    .map((item) => ({ time: item.time as Time, value: item.value } as AreaData));

const timeToNumber = (time: Time) => {
  if (typeof time === "number") {
    return time;
  }
  if (time && typeof time === "object" && "year" in time) {
    const year = Number(time.year);
    const month = Number(time.month || 1);
    const day = Number(time.day || 1);
    return Math.floor(Date.UTC(year, month - 1, day) / 1000);
  }
  return null;
};

const hasValidRange = (range: { from: Time | null; to: Time | null } | null | undefined) =>
  !!(range && range.from != null && range.to != null);

const formatTime = (time: Time) => {
  if (typeof time === "number") {
    return new Date(time * 1000).toISOString().slice(0, 10);
  }
  if (time && typeof time === "object" && "year" in time) {
    const year = Number(time.year);
    const month = String(time.month || 1).padStart(2, "0");
    const day = String(time.day || 1).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
  return "";
};

const formatPercent = (value?: number) => {
  if (!Number.isFinite(value ?? NaN)) {
    return "-";
  }
  return `${Number(value).toFixed(2)}%`;
};

const formatAmount = (value?: number) => {
  if (!Number.isFinite(value ?? NaN)) {
    return "-";
  }
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

const findNearestValue = (points: ChartPoint[], time: number | null) => {
  if (!points.length || time === null) {
    return undefined;
  }
  if (time <= points[0].time) {
    return points[0].value;
  }
  const last = points[points.length - 1];
  if (time >= last.time) {
    return last.value;
  }
  let left = 0;
  let right = points.length - 1;
  while (left <= right) {
    const mid = Math.floor((left + right) / 2);
    const midTime = points[mid].time;
    if (midTime === time) {
      return points[mid].value;
    }
    if (midTime < time) {
      left = mid + 1;
    } else {
      right = mid - 1;
    }
  }
  return points[Math.max(0, right)].value;
};

export default function BacktestPerformanceChart({
  equityPoints,
  drawdownPoints,
  benchmarkPoints,
  longExposurePoints,
  shortExposurePoints,
  defensiveExposurePoints,
  loading,
  errorKey,
}: BacktestPerformanceChartProps) {
  const { t } = useI18n();
  const mainRef = useRef<HTMLDivElement | null>(null);
  const exposureRef = useRef<HTMLDivElement | null>(null);
  const mainChartRef = useRef<IChartApi | null>(null);
  const exposureChartRef = useRef<IChartApi | null>(null);
  const equitySeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const drawdownSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const benchmarkSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const benchmarkDrawdownSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const longSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const defensiveSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const cashSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const [hover, setHover] = useState<LegendState | null>(null);
  const [showEquity, setShowEquity] = useState(true);
  const [showDrawdown, setShowDrawdown] = useState(true);
  const [showBenchmark, setShowBenchmark] = useState(true);
  const [showBenchmarkDrawdown, setShowBenchmarkDrawdown] = useState(false);
  const [showExposure, setShowExposure] = useState(false);
  const [exposureMode, setExposureMode] = useState<"ratio" | "value">("ratio");
  const equityReturnRef = useRef<ChartPoint[]>([]);
  const drawdownDataRef = useRef<ChartPoint[]>([]);
  const benchmarkReturnRef = useRef<ChartPoint[]>([]);
  const benchmarkDrawdownRef = useRef<ChartPoint[]>([]);
  const exposureLongRef = useRef<ChartPoint[]>([]);
  const exposureDefensiveRef = useRef<ChartPoint[]>([]);
  const exposureCashRef = useRef<ChartPoint[]>([]);
  const exposureHasDataRef = useRef(false);
  const showExposureRef = useRef(showExposure);

  const equityReturn = useMemo(() => toReturnSeries(equityPoints), [equityPoints]);
  const benchmarkReturn = useMemo(() => toReturnSeries(benchmarkPoints), [benchmarkPoints]);
  const benchmarkDrawdownSeries = useMemo(
    () => toDrawdownSeries(benchmarkPoints),
    [benchmarkPoints]
  );
  const drawdownSeries = useMemo(
    () => normalizePercentSeries(drawdownPoints),
    [drawdownPoints]
  );

  const exposureRatio = useMemo(() => {
    const longPoints = toSafePoints(longExposurePoints);
    const shortPoints = toSafePoints(shortExposurePoints);
    const defensivePoints = toSafePoints(defensiveExposurePoints);
    if (!longPoints.length) {
      return { long: [], defensive: [], cash: [] };
    }
    const shortMap = buildMap(shortPoints);
    const hasDefensive = defensivePoints.length > 0;
    const defensiveSeries = hasDefensive
      ? longPoints.map((item) => {
          const raw = findNearestValue(defensivePoints, item.time) ?? 0;
          const value = Math.min(Math.max(raw, 0), item.value);
          return { time: item.time, value };
        })
      : [];
    const cashPoints = longPoints.map((item) => {
      const shortValue = Math.abs(shortMap.get(item.time) ?? 0);
      const cashRatio = Math.max(0, 1 - item.value - shortValue);
      return { time: item.time, value: cashRatio };
    });
    return {
      long: normalizePercentSeries(longPoints),
      defensive: normalizePercentSeries(defensiveSeries),
      cash: normalizePercentSeries(cashPoints),
    };
  }, [longExposurePoints, shortExposurePoints, defensiveExposurePoints]);

  const exposureValue = useMemo(() => {
    const longPoints = toSafePoints(longExposurePoints);
    const shortPoints = toSafePoints(shortExposurePoints);
    const defensivePoints = toSafePoints(defensiveExposurePoints);
    const equityMap = buildMap(toSafePoints(equityPoints));
    if (!longPoints.length || !equityMap.size) {
      return { long: [], defensive: [], cash: [] };
    }
    const shortMap = buildMap(shortPoints);
    const hasDefensive = defensivePoints.length > 0;
    const longValue = longPoints
      .map((item) => {
        const equity = equityMap.get(item.time);
        if (!Number.isFinite(equity)) {
          return null;
        }
        return { time: item.time, value: (equity ?? 0) * item.value };
      })
      .filter(Boolean) as ChartPoint[];
    const defensiveValue = hasDefensive
      ? longPoints
          .map((item) => {
            const equity = equityMap.get(item.time);
            if (!Number.isFinite(equity)) {
              return null;
            }
            const raw = findNearestValue(defensivePoints, item.time) ?? 0;
            const defensiveRatio = Math.min(Math.max(raw, 0), item.value);
            return { time: item.time, value: (equity ?? 0) * defensiveRatio };
          })
          .filter(Boolean) as ChartPoint[]
      : [];
    const cashValue = longPoints
      .map((item) => {
        const equity = equityMap.get(item.time);
        if (!Number.isFinite(equity)) {
          return null;
        }
        const shortValue = Math.abs(shortMap.get(item.time) ?? 0);
        const cashRatio = Math.max(0, 1 - item.value - shortValue);
        return { time: item.time, value: (equity ?? 0) * cashRatio };
      })
      .filter(Boolean) as ChartPoint[];
    return { long: longValue, defensive: defensiveValue, cash: cashValue };
  }, [equityPoints, longExposurePoints, shortExposurePoints, defensiveExposurePoints]);

  const exposureSeries = exposureMode === "ratio" ? exposureRatio : exposureValue;

  const hasData =
    equityReturn.length > 0 ||
    drawdownSeries.length > 0 ||
    benchmarkReturn.length > 0 ||
    benchmarkDrawdownSeries.length > 0 ||
    exposureSeries.long.length > 0;

  useEffect(() => {
    if (!mainRef.current || !exposureRef.current) {
      return;
    }
    if (mainChartRef.current || exposureChartRef.current) {
      return;
    }
    const mainContainer = mainRef.current;
    const exposureContainer = exposureRef.current;
    mainContainer.style.position = "relative";
    exposureContainer.style.position = "relative";
    const mainChart = createChart(mainContainer, {
      layout: {
        background: { color: "#ffffff" },
        textColor: "#0f172a",
        fontFamily: "\"IBM Plex Sans\", \"Noto Sans SC\", \"Segoe UI\", sans-serif",
      },
      grid: {
        vertLines: { color: "#eef2f7" },
        horzLines: { color: "#eef2f7" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { borderColor: "#e2e8f0" },
      rightPriceScale: { borderColor: "#e2e8f0", visible: false },
      leftPriceScale: { borderColor: "#e2e8f0", visible: true },
      height: 320,
    });

    const equitySeries = mainChart.addLineSeries({
      color: "#2563eb",
      lineWidth: 2.5,
      priceScaleId: "left",
    });
    const drawdownSeries = mainChart.addLineSeries({
      color: "#dc2626",
      lineWidth: 2,
      priceScaleId: "left",
    });
    const benchmarkSeries = mainChart.addLineSeries({
      color: "#64748b",
      lineWidth: 2,
      lineStyle: LineStyle.Dotted,
      priceScaleId: "left",
    });
    const benchmarkDrawdownSeries = mainChart.addLineSeries({
      color: "#f59e0b",
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceScaleId: "left",
    });

    const exposureChart = createChart(exposureContainer, {
      layout: {
        background: { color: "#ffffff" },
        textColor: "#0f172a",
        fontFamily: "\"IBM Plex Sans\", \"Noto Sans SC\", \"Segoe UI\", sans-serif",
      },
      grid: {
        vertLines: { color: "#eef2f7" },
        horzLines: { color: "#eef2f7" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { borderColor: "#e2e8f0" },
      rightPriceScale: { borderColor: "#e2e8f0", visible: false },
      leftPriceScale: { borderColor: "#e2e8f0", visible: true },
      height: 190,
    });

    const longSeries = exposureChart.addAreaSeries({
      lineColor: "#16a34a",
      topColor: "rgba(22, 163, 74, 0.35)",
      bottomColor: "rgba(22, 163, 74, 0.05)",
      lineWidth: 2,
      priceScaleId: "left",
    });
    const cashSeries = exposureChart.addAreaSeries({
      lineColor: "#0ea5e9",
      topColor: "rgba(14, 165, 233, 0.35)",
      bottomColor: "rgba(14, 165, 233, 0.05)",
      lineWidth: 2,
      priceScaleId: "left",
    });
    const defensiveSeries = exposureChart.addLineSeries({
      color: "#f97316",
      lineWidth: 2,
      priceScaleId: "left",
    });

    mainChartRef.current = mainChart;
    exposureChartRef.current = exposureChart;
    equitySeriesRef.current = equitySeries;
    drawdownSeriesRef.current = drawdownSeries;
    benchmarkSeriesRef.current = benchmarkSeries;
    benchmarkDrawdownSeriesRef.current = benchmarkDrawdownSeries;
    longSeriesRef.current = longSeries;
    defensiveSeriesRef.current = defensiveSeries;
    cashSeriesRef.current = cashSeries;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        mainChart.applyOptions({ width: entry.contentRect.width });
        exposureChart.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(mainContainer);
    resizeObserver.observe(exposureContainer);

    let syncing = false;
    mainChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (!hasValidRange(range) || syncing) {
        return;
      }
      if (!showExposureRef.current) {
        return;
      }
      syncing = true;
      try {
        exposureChart.timeScale().setVisibleRange(range);
      } finally {
        syncing = false;
      }
    });
    exposureChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (!hasValidRange(range) || syncing) {
        return;
      }
      if (!showExposureRef.current) {
        return;
      }
      syncing = true;
      try {
        mainChart.timeScale().setVisibleRange(range);
      } finally {
        syncing = false;
      }
    });

    const updateLegend = (time: Time) => {
      const timeNumber = timeToNumber(time);
      setHover({
        timeText: formatTime(time),
        equity: findNearestValue(equityReturnRef.current, timeNumber),
        drawdown: findNearestValue(drawdownDataRef.current, timeNumber),
        benchmark: findNearestValue(benchmarkReturnRef.current, timeNumber),
        benchmarkDrawdown: findNearestValue(benchmarkDrawdownRef.current, timeNumber),
        long: findNearestValue(exposureLongRef.current, timeNumber),
        defensive: findNearestValue(exposureDefensiveRef.current, timeNumber),
        cash: findNearestValue(exposureCashRef.current, timeNumber),
      });
    };

    mainChart.subscribeCrosshairMove((param) => {
      if (!param.time) {
        setHover(null);
        return;
      }
      updateLegend(param.time);
    });
    exposureChart.subscribeCrosshairMove((param) => {
      if (!param.time) {
        return;
      }
      updateLegend(param.time);
    });

    return () => {
      resizeObserver.disconnect();
      mainChart.remove();
      exposureChart.remove();
      mainChartRef.current = null;
      exposureChartRef.current = null;
      equitySeriesRef.current = null;
      drawdownSeriesRef.current = null;
      benchmarkSeriesRef.current = null;
      benchmarkDrawdownSeriesRef.current = null;
      longSeriesRef.current = null;
      defensiveSeriesRef.current = null;
      cashSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mainChartRef.current || !exposureChartRef.current) {
      return;
    }
    if (
      !equitySeriesRef.current ||
      !drawdownSeriesRef.current ||
      !benchmarkSeriesRef.current ||
      !benchmarkDrawdownSeriesRef.current
    ) {
      return;
    }
    equityReturnRef.current = equityReturn;
    drawdownDataRef.current = drawdownSeries;
    benchmarkReturnRef.current = benchmarkReturn;
    benchmarkDrawdownRef.current = benchmarkDrawdownSeries;
    exposureLongRef.current = exposureSeries.long;
    exposureDefensiveRef.current = exposureSeries.defensive;
    exposureCashRef.current = exposureSeries.cash;
    exposureHasDataRef.current =
      exposureSeries.long.length > 0 || exposureSeries.defensive.length > 0;
    equitySeriesRef.current.setData(toLineData(equityReturn));
    drawdownSeriesRef.current.setData(toLineData(drawdownSeries));
    benchmarkSeriesRef.current.setData(toLineData(benchmarkReturn));
    benchmarkDrawdownSeriesRef.current.setData(toLineData(benchmarkDrawdownSeries));
    equitySeriesRef.current.applyOptions({ visible: showEquity });
    drawdownSeriesRef.current.applyOptions({ visible: showDrawdown });
    benchmarkSeriesRef.current.applyOptions({ visible: showBenchmark });
    benchmarkDrawdownSeriesRef.current.applyOptions({ visible: showBenchmarkDrawdown });
    if (longSeriesRef.current && defensiveSeriesRef.current && cashSeriesRef.current) {
      const priceFormat =
        exposureMode === "ratio"
          ? { type: "percent", precision: 2, minMove: 0.01 }
          : { type: "price", precision: 2, minMove: 0.01 };
      longSeriesRef.current.setData(toAreaData(exposureSeries.long));
      defensiveSeriesRef.current.setData(toLineData(exposureSeries.defensive));
      cashSeriesRef.current.setData(toAreaData(exposureSeries.cash));
      longSeriesRef.current.applyOptions({ visible: showExposure, priceFormat });
      defensiveSeriesRef.current.applyOptions({ visible: showExposure, priceFormat });
      cashSeriesRef.current.applyOptions({ visible: showExposure, priceFormat });
    }
    mainChartRef.current.timeScale().fitContent();
    const mainRange = mainChartRef.current.timeScale().getVisibleRange();
    if (showExposure && hasValidRange(mainRange)) {
      exposureChartRef.current.timeScale().setVisibleRange(mainRange);
    }
    setHover(null);
  }, [
    equityReturn,
    drawdownSeries,
    benchmarkReturn,
    benchmarkDrawdownSeries,
    exposureSeries,
    showEquity,
    showDrawdown,
    showBenchmark,
    showBenchmarkDrawdown,
    showExposure,
    exposureMode,
  ]);

  useEffect(() => {
    showExposureRef.current = showExposure;
    if (!showExposure) {
      return;
    }
    if (!mainChartRef.current || !exposureChartRef.current) {
      return;
    }
    const mainRange = mainChartRef.current.timeScale().getVisibleRange();
    if (hasValidRange(mainRange)) {
      exposureChartRef.current.timeScale().setVisibleRange(mainRange);
    }
  }, [showExposure]);

  const latestLegend = useMemo((): LegendState => {
    const last = (points: ChartPoint[]) => (points.length ? points[points.length - 1] : null);
    const equity = last(equityReturn);
    const drawdown = last(drawdownSeries);
    const benchmark = last(benchmarkReturn);
    const benchmarkDrawdown = last(benchmarkDrawdownSeries);
    const longVal = last(exposureSeries.long);
    const defensiveVal = last(exposureSeries.defensive);
    const cashVal = last(exposureSeries.cash);
    return {
      timeText: equity?.time ? formatTime(equity.time as Time) : "",
      equity: equity?.value,
      drawdown: drawdown?.value,
      benchmark: benchmark?.value,
      benchmarkDrawdown: benchmarkDrawdown?.value,
      long: longVal?.value,
      defensive: defensiveVal?.value,
      cash: cashVal?.value,
    };
  }, [equityReturn, drawdownSeries, benchmarkReturn, benchmarkDrawdownSeries, exposureSeries]);

  const legend = hover ?? latestLegend;
  const exposureUnit = exposureMode === "ratio" ? "percent" : "amount";
  const showDefensive = showExposure && exposureSeries.defensive.length > 0;

  return (
    <div className="performance-chart">
      <div className="performance-chart-header">
        <div>
          <div className="card-title">{t("charts.performanceTitle")}</div>
          <div className="card-meta">{t("charts.performanceMeta")}</div>
        </div>
        <div className="performance-chart-controls">
          <label className="performance-chart-toggle">
            <input
              type="checkbox"
              checked={showEquity}
              onChange={(event) => setShowEquity(event.target.checked)}
            />
            {t("charts.toggleEquity")}
          </label>
          <label className="performance-chart-toggle">
            <input
              type="checkbox"
              checked={showDrawdown}
              onChange={(event) => setShowDrawdown(event.target.checked)}
            />
            {t("charts.toggleDrawdown")}
          </label>
          <label className="performance-chart-toggle">
            <input
              type="checkbox"
              checked={showBenchmark}
              onChange={(event) => setShowBenchmark(event.target.checked)}
            />
            {t("charts.toggleBenchmark")}
          </label>
          <label className="performance-chart-toggle">
            <input
              type="checkbox"
              checked={showBenchmarkDrawdown}
              onChange={(event) => setShowBenchmarkDrawdown(event.target.checked)}
            />
            {t("charts.toggleBenchmarkDrawdown")}
          </label>
          <label className="performance-chart-toggle">
            <input
              type="checkbox"
              checked={showExposure}
              onChange={(event) => setShowExposure(event.target.checked)}
            />
            {t("charts.toggleExposure")}
          </label>
          {showExposure && (
            <select
              className="form-select performance-chart-select"
              value={exposureMode}
              onChange={(event) =>
                setExposureMode(event.target.value as "ratio" | "value")
              }
            >
              <option value="ratio">{t("charts.exposureModeRatio")}</option>
              <option value="value">{t("charts.exposureModeValue")}</option>
            </select>
          )}
        </div>
      </div>
      <div className="performance-chart-main" ref={mainRef} />
      <div
        className={`performance-chart-exposure${showExposure ? "" : " is-hidden"}`}
        ref={exposureRef}
      />
      {loading && <div className="performance-chart-status">{t("common.status.loading")}</div>}
      {!loading && errorKey && (
        <div className="performance-chart-status danger">{t(errorKey)}</div>
      )}
      {!loading && !errorKey && !hasData && (
        <div className="performance-chart-status">{t("charts.noData")}</div>
      )}
      <div className="performance-chart-legend">
        <span className="performance-legend-item">
          <span className="performance-legend-label">{t("charts.legendDate")}</span>
          <strong>{legend.timeText || "-"}</strong>
        </span>
        {showEquity && (
          <span className="performance-legend-item">
            <span className="performance-legend-dot equity" />
            <span>{t("charts.seriesEquity")}</span>
            <strong>{formatPercent(legend.equity)}</strong>
          </span>
        )}
        {showDrawdown && (
          <span className="performance-legend-item">
            <span className="performance-legend-dot drawdown" />
            <span>{t("charts.seriesDrawdown")}</span>
            <strong>{formatPercent(legend.drawdown)}</strong>
          </span>
        )}
        {showBenchmark && benchmarkReturn.length > 0 && (
          <span className="performance-legend-item">
            <span className="performance-legend-dot benchmark" />
            <span>{t("charts.seriesBenchmark")}</span>
            <strong>{formatPercent(legend.benchmark)}</strong>
          </span>
        )}
        {showBenchmarkDrawdown && benchmarkDrawdownSeries.length > 0 && (
          <span className="performance-legend-item">
            <span className="performance-legend-dot benchmark-dd" />
            <span>{t("charts.seriesBenchmarkDrawdown")}</span>
            <strong>{formatPercent(legend.benchmarkDrawdown)}</strong>
          </span>
        )}
        {showExposure && (
          <>
            <span className="performance-legend-item">
              <span className="performance-legend-dot exposure" />
              <span>{t("charts.seriesLongExposure")}</span>
              <strong>
                {exposureUnit === "percent"
                  ? formatPercent(legend.long)
                  : formatAmount(legend.long)}
              </strong>
            </span>
            {showDefensive && (
              <span className="performance-legend-item">
                <span className="performance-legend-dot defensive" />
                <span>{t("charts.seriesDefensiveExposure")}</span>
                <strong>
                  {exposureUnit === "percent"
                    ? formatPercent(legend.defensive)
                    : formatAmount(legend.defensive)}
                </strong>
              </span>
            )}
            <span className="performance-legend-item">
              <span className="performance-legend-dot cash" />
              <span>{t("charts.seriesCashExposure")}</span>
              <strong>
                {exposureUnit === "percent"
                  ? formatPercent(legend.cash)
                  : formatAmount(legend.cash)}
              </strong>
            </span>
          </>
        )}
      </div>
    </div>
  );
}
