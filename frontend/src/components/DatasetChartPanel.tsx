import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
} from "lightweight-charts";
import { api } from "../api";
import { useI18n } from "../i18n";
import { DatasetSummary } from "../types";

type ChartMode = "raw" | "adjusted" | "both";
type Granularity = "auto" | "day" | "week" | "month";

interface DatasetSeriesResponse {
  dataset_id: number;
  mode: ChartMode;
  start?: string | null;
  end?: string | null;
  candles: Array<{
    time: number;
    open: number | null;
    high: number | null;
    low: number | null;
    close: number | null;
    volume: number | null;
  }>;
  adjusted: Array<{
    time: number;
    value: number;
  }>;
}

interface DatasetChartPanelProps {
  dataset: DatasetSummary;
  datasets?: DatasetSummary[];
  selectedId?: number;
  onSelect?: (datasetId: number) => void;
  openUrl?: string;
  markers?: Array<{
    time: number;
    position: "aboveBar" | "belowBar";
    color: string;
    shape: "arrowUp" | "arrowDown";
    text?: string;
    label?: string;
  }>;
}

const RANGE_PRESETS = [
  { key: "1M", days: 30 },
  { key: "3M", days: 90 },
  { key: "6M", days: 180 },
  { key: "1Y", days: 365 },
  { key: "5Y", days: 365 * 5 },
  { key: "MAX", days: null },
];

const toDateInput = (value?: string | null) => {
  if (!value) {
    return "";
  }
  return value.slice(0, 10);
};

const shiftDate = (value: string, days: number) => {
  const base = new Date(value);
  if (Number.isNaN(base.getTime())) {
    return "";
  }
  base.setDate(base.getDate() - days);
  return base.toISOString().slice(0, 10);
};

const toUtcDate = (time: number) => new Date(time * 1000);

const startOfWeek = (date: Date) => {
  const day = date.getUTCDay() || 7;
  const start = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  start.setUTCDate(start.getUTCDate() - (day - 1));
  return start;
};

const startOfMonth = (date: Date) =>
  new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));

const buildBucketKey = (date: Date, granularity: Granularity) => {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  if (granularity === "week") {
    const start = startOfWeek(date);
    return start.toISOString().slice(0, 10);
  }
  if (granularity === "month") {
    return `${year}-${month}`;
  }
  return `${year}-${month}-${day}`;
};

const bucketTime = (date: Date, granularity: Granularity) => {
  if (granularity === "week") {
    return Math.floor(startOfWeek(date).getTime() / 1000);
  }
  if (granularity === "month") {
    return Math.floor(startOfMonth(date).getTime() / 1000);
  }
  return Math.floor(
    Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) / 1000
  );
};

export default function DatasetChartPanel({
  dataset,
  datasets,
  selectedId,
  onSelect,
  openUrl,
  markers,
}: DatasetChartPanelProps) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const markerLabelRef = useRef<Map<number, string[]>>(new Map());
  const labelLayerRef = useRef<HTMLDivElement | null>(null);
  const markersRef = useRef<
    Array<{
      time: number;
      position: "aboveBar" | "belowBar";
      color: string;
      shape: "arrowUp" | "arrowDown";
      label?: string;
      text?: string;
    }>
  >([]);
  const priceMapRef = useRef<Map<number, number>>(new Map());
  const timeListRef = useRef<number[]>([]);
  const renderLabelsRef = useRef<() => void>(() => {});
  const [mode, setMode] = useState<ChartMode>("both");
  const [preset, setPreset] = useState("1Y");
  const [granularity, setGranularity] = useState<Granularity>("auto");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [series, setSeries] = useState<DatasetSeriesResponse | null>(null);
  const [initialized, setInitialized] = useState(false);

  const datasetFrequency = (dataset.frequency || "").toLowerCase();
  const frequencyLabel = datasetFrequency.includes("minute")
    ? t("data.frequency.minute")
    : t("data.frequency.daily");

  const coverageLabel = useMemo(() => {
    const start = dataset.coverage_start || t("common.none");
    const end = dataset.coverage_end || t("common.none");
    return `${start} ~ ${end}`;
  }, [dataset.coverage_start, dataset.coverage_end, t]);

  const displaySeries = useMemo(() => {
    const rawCandles = series?.candles || [];
    const rawAdjusted = series?.adjusted || [];
    if (granularity === "day" || granularity === "auto") {
      return {
        candles: rawCandles,
        adjusted: rawAdjusted,
      };
    }
    const candleBuckets = new Map<
      string,
      {
        time: number;
        open: number;
        high: number;
        low: number;
        close: number;
        volume: number;
        lastTime: number;
      }
    >();
    for (const candle of rawCandles) {
      const date = toUtcDate(candle.time);
      const key = buildBucketKey(date, granularity);
      const existing = candleBuckets.get(key);
      if (!existing) {
        candleBuckets.set(key, {
          time: bucketTime(date, granularity),
          open: candle.open ?? 0,
          high: candle.high ?? 0,
          low: candle.low ?? 0,
          close: candle.close ?? 0,
          volume: candle.volume ?? 0,
          lastTime: candle.time,
        });
      } else {
        existing.high = Math.max(existing.high, candle.high ?? existing.high);
        existing.low = Math.min(existing.low, candle.low ?? existing.low);
        if (candle.time >= existing.lastTime) {
          existing.close = candle.close ?? existing.close;
          existing.lastTime = candle.time;
        }
        existing.volume += candle.volume ?? 0;
      }
    }
    const candles = Array.from(candleBuckets.values())
      .sort((a, b) => a.time - b.time)
      .map((item) => ({
        time: item.time,
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close,
        volume: item.volume,
      }));

    const lineBuckets = new Map<string, { time: number; value: number; lastTime: number }>();
    for (const point of rawAdjusted) {
      const date = toUtcDate(point.time);
      const key = buildBucketKey(date, granularity);
      const existing = lineBuckets.get(key);
      if (!existing || point.time >= existing.lastTime) {
        lineBuckets.set(key, {
          time: bucketTime(date, granularity),
          value: point.value,
          lastTime: point.time,
        });
      }
    }
    const adjusted = Array.from(lineBuckets.values())
      .sort((a, b) => a.time - b.time)
      .map((item) => ({
        time: item.time,
        value: item.value,
      }));
    return { candles, adjusted };
  }, [series, granularity]);

  const applyPreset = (nextPreset: string) => {
    const endValue = toDateInput(dataset.coverage_end) || endDate;
    setPreset(nextPreset);
    if (nextPreset === "MAX") {
      setStartDate("");
      setEndDate(endValue);
      return;
    }
    const presetConfig = RANGE_PRESETS.find((item) => item.key === nextPreset);
    if (!presetConfig || presetConfig.days === null || !endValue) {
      setStartDate("");
      setEndDate(endValue);
      return;
    }
    setStartDate(shiftDate(endValue, presetConfig.days));
    setEndDate(endValue);
  };

  useEffect(() => {
    const defaultPreset = datasetFrequency.includes("minute") ? "1M" : "1Y";
    setPreset(defaultPreset);
    setGranularity(datasetFrequency.includes("minute") ? "auto" : "day");
    const endValue = toDateInput(dataset.coverage_end);
    if (endValue) {
      const presetConfig = RANGE_PRESETS.find((item) => item.key === defaultPreset);
      if (presetConfig?.days) {
        setStartDate(shiftDate(endValue, presetConfig.days));
      } else {
        setStartDate("");
      }
      setEndDate(endValue);
    } else {
      setStartDate("");
      setEndDate("");
    }
    setInitialized(true);
  }, [dataset.id, dataset.coverage_end, datasetFrequency]);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const container = containerRef.current;
    container.style.position = "relative";
    const chart = createChart(container, {
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
      rightPriceScale: { borderColor: "#e2e8f0" },
      height: 320,
    });
    const candleSeries = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#10b981",
      wickDownColor: "#ef4444",
      wickUpColor: "#10b981",
    });
    const lineSeries = chart.addLineSeries({
      color: "#2563eb",
      lineWidth: 2,
    });
    const volumeSeries = chart.addHistogramSeries({
      color: "#94a3b8",
      priceFormat: { type: "volume" },
      priceScaleId: "",
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    chartRef.current = chart;
    candleRef.current = candleSeries;
    lineRef.current = lineSeries;
    volumeRef.current = volumeSeries;

    const tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    tooltip.style.display = "none";
    container.appendChild(tooltip);
    tooltipRef.current = tooltip;

    const labelLayer = document.createElement("div");
    labelLayer.className = "chart-label-layer";
    container.appendChild(labelLayer);
    labelLayerRef.current = labelLayer;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
        renderLabelsRef.current();
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      tooltip.remove();
      labelLayer.remove();
      chartRef.current = null;
      candleRef.current = null;
      lineRef.current = null;
      volumeRef.current = null;
      tooltipRef.current = null;
      labelLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const timeScale = chart?.timeScale();
    if (!chart || !timeScale) {
      return;
    }
    const handler = () => renderLabelsRef.current();
    timeScale.subscribeVisibleTimeRangeChange(handler);
    return () => {
      timeScale.unsubscribeVisibleTimeRangeChange(handler);
    };
  }, []);

  const renderLabels = () => {
    const layer = labelLayerRef.current;
    const chart = chartRef.current;
    const lineSeries = lineRef.current;
    if (!layer || !chart || !lineSeries) {
      return;
    }
    layer.innerHTML = "";
    const markers = markersRef.current || [];
    if (!markers.length) {
      return;
    }
    const times = timeListRef.current;
    const priceMap = priceMapRef.current;
    const timeScale = chart.timeScale();
    const range = timeScale.getVisibleRange();
    const from = range ? Number(range.from) : null;
    const to = range ? Number(range.to) : null;

    const findNearestTime = (time: number) => {
      if (!times.length) {
        return null;
      }
      let lo = 0;
      let hi = times.length - 1;
      while (lo <= hi) {
        const mid = Math.floor((lo + hi) / 2);
        const value = times[mid];
        if (value === time) {
          return value;
        }
        if (value < time) {
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      if (hi < 0) {
        return times[0];
      }
      if (lo >= times.length) {
        return times[times.length - 1];
      }
      return time - times[hi] <= times[lo] - time ? times[hi] : times[lo];
    };

    for (const marker of markers) {
      const label = marker.label ?? marker.text;
      if (!label) {
        continue;
      }
      if (from !== null && to !== null && (marker.time < from || marker.time > to)) {
        continue;
      }
      const mappedTime = priceMap.has(marker.time)
        ? marker.time
        : findNearestTime(marker.time);
      if (mappedTime == null) {
        continue;
      }
      const price = priceMap.get(mappedTime);
      if (price == null) {
        continue;
      }
      const x = timeScale.timeToCoordinate(mappedTime);
      const y = lineSeries.priceToCoordinate(price);
      if (x == null || y == null) {
        continue;
      }
      const tag = document.createElement("div");
      const sideClass = marker.shape === "arrowUp" ? "buy" : "sell";
      tag.className = `chart-marker-label ${sideClass}`.trim();
      tag.textContent = label;
      tag.style.background = marker.color;
      layer.appendChild(tag);
      const tagRect = tag.getBoundingClientRect();
      const layerRect = layer.getBoundingClientRect();
      let left = x - tagRect.width / 2;
      let top = marker.position === "aboveBar" ? y - tagRect.height - 6 : y + 6;
      left = Math.min(Math.max(4, left), layerRect.width - tagRect.width - 4);
      top = Math.min(Math.max(4, top), layerRect.height - tagRect.height - 4);
      tag.style.left = `${left}px`;
      tag.style.top = `${top}px`;
    }
  };

  renderLabelsRef.current = renderLabels;

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleRef.current;
    const lineSeries = lineRef.current;
    const tooltip = tooltipRef.current;
    const container = containerRef.current;
    if (!chart || !tooltip || !container) {
      return;
    }

    const toEpoch = (time: any) => {
      if (time == null) {
        return null;
      }
      if (typeof time === "number") {
        return time;
      }
      if (typeof time === "object" && "year" in time) {
        const year = Number(time.year);
        const month = Number(time.month || 1);
        const day = Number(time.day || 1);
        return Math.floor(Date.UTC(year, month - 1, day) / 1000);
      }
      return null;
    };

    const formatPrice = (value: number) => {
      if (!Number.isFinite(value)) {
        return "";
      }
      if (value >= 100) {
        return value.toFixed(2);
      }
      if (value >= 1) {
        return value.toFixed(4);
      }
      return value.toFixed(6);
    };

    const handler = (param: any) => {
      if (!param?.time || !param?.point) {
        tooltip.style.display = "none";
        return;
      }
      const lineData = lineSeries ? param.seriesData.get(lineSeries) : null;
      const candleData = candleSeries ? param.seriesData.get(candleSeries) : null;
      const price =
        typeof lineData?.value === "number"
          ? lineData.value
          : typeof candleData?.close === "number"
            ? candleData.close
            : null;
      if (price == null) {
        tooltip.style.display = "none";
        return;
      }
      const timeKey = toEpoch(param.time);
      const labels = timeKey != null ? markerLabelRef.current.get(timeKey) : undefined;
      const labelText = labels && labels.length ? labels.join(" / ") : "";
      const timeValue = toEpoch(param.time);
      const timeText = timeValue ? new Date(timeValue * 1000).toISOString().slice(0, 10) : "";
      tooltip.innerHTML = `
        <div class="chart-tooltip-price">${formatPrice(price)}</div>
        ${timeText ? `<div class="chart-tooltip-time">${timeText}</div>` : ""}
        ${labelText ? `<div class="chart-tooltip-label">${labelText}</div>` : ""}
      `;
      tooltip.style.display = "block";
      const containerRect = container.getBoundingClientRect();
      const tooltipRect = tooltip.getBoundingClientRect();
      const x = Math.min(
        Math.max(8, param.point.x + 12),
        containerRect.width - tooltipRect.width - 8
      );
      const y = Math.min(
        Math.max(8, param.point.y + 12),
        containerRect.height - tooltipRect.height - 8
      );
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${y}px`;
    };

    chart.subscribeCrosshairMove(handler);
    return () => {
      chart.unsubscribeCrosshairMove(handler);
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    if (granularity === "auto") {
      chart.applyOptions({ timeScale: { tickMarkFormatter: undefined } });
      return;
    }
    const formatter = (time: any) => {
      let date: Date | null = null;
      if (typeof time === "number") {
        date = new Date(time * 1000);
      } else if (time && typeof time === "object" && "year" in time) {
        const year = Number(time.year);
        const month = Number(time.month || 1);
        const day = Number(time.day || 1);
        date = new Date(Date.UTC(year, month - 1, day));
      }
      if (!date || Number.isNaN(date.getTime())) {
        return "";
      }
      const year = date.getUTCFullYear();
      const month = String(date.getUTCMonth() + 1).padStart(2, "0");
      const day = String(date.getUTCDate()).padStart(2, "0");
      if (granularity === "month") {
        return `${year}-${month}`;
      }
      if (granularity === "week") {
        const tmp = new Date(Date.UTC(year, date.getUTCMonth(), date.getUTCDate()));
        const dayNum = tmp.getUTCDay() || 7;
        tmp.setUTCDate(tmp.getUTCDate() + 4 - dayNum);
        const weekYear = tmp.getUTCFullYear();
        const yearStart = new Date(Date.UTC(weekYear, 0, 1));
        const week = Math.ceil((((tmp.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
        return `${weekYear}-W${String(week).padStart(2, "0")}`;
      }
      return `${year}-${month}-${day}`;
    };
    chart.applyOptions({ timeScale: { tickMarkFormatter: formatter } });
  }, [granularity]);

  useEffect(() => {
    if (!initialized) {
      return;
    }
    const loadSeries = async () => {
      setLoading(true);
      setError("");
      try {
        const res = await api.get<DatasetSeriesResponse>(
          `/api/datasets/${dataset.id}/series`,
          {
            params: {
              mode: "both",
              start: startDate || undefined,
              end: endDate || undefined,
            },
          }
        );
        setSeries(res.data);
      } catch (err: any) {
        setError(t("data.chart.error"));
        setSeries(null);
      } finally {
        setLoading(false);
      }
    };
    void loadSeries();
  }, [dataset.id, startDate, endDate, initialized, t]);

  useEffect(() => {
    const candleSeries = candleRef.current;
    const lineSeries = lineRef.current;
    const volumeSeries = volumeRef.current;
    const chart = chartRef.current;
    if (!candleSeries || !lineSeries || !volumeSeries || !chart) {
      return;
    }
    const candleData = (displaySeries.candles || [])
      .filter((item) =>
        [item.open, item.high, item.low, item.close].every(
          (value) => typeof value === "number"
        )
      )
      .map(
        (item) =>
          ({
            time: item.time,
            open: item.open as number,
            high: item.high as number,
            low: item.low as number,
            close: item.close as number,
          }) satisfies CandlestickData
      );
    const lineData = (displaySeries.adjusted || []).map(
      (item) =>
        ({
          time: item.time,
          value: item.value,
        }) satisfies LineData
    );
    const volumeData = (displaySeries.candles || [])
      .filter((item) => typeof item.volume === "number")
      .map(
        (item) =>
          ({
            time: item.time,
            value: item.volume as number,
            color:
              typeof item.close === "number" && typeof item.open === "number"
                ? item.close >= item.open
                  ? "rgba(16, 185, 129, 0.4)"
                  : "rgba(239, 68, 68, 0.4)"
                : "rgba(148, 163, 184, 0.35)",
          }) satisfies HistogramData
      );

    const markerRangeSource =
      displaySeries.adjusted && displaySeries.adjusted.length
        ? displaySeries.adjusted
        : displaySeries.candles || [];
    const markerTimes = markerRangeSource.map((item) => item.time);
    const minMarkerTime = markerTimes.length ? Math.min(...markerTimes) : null;
    const maxMarkerTime = markerTimes.length ? Math.max(...markerTimes) : null;
    const filteredMarkers =
      markers && minMarkerTime !== null && maxMarkerTime !== null
        ? markers.filter(
            (marker) => marker.time >= minMarkerTime && marker.time <= maxMarkerTime
          )
        : markers || [];
    const normalizedMarkers = filteredMarkers.map((marker) => ({
      ...marker,
      text: undefined,
    }));
    const priceMap = new Map<number, number>();
    for (const point of lineData) {
      priceMap.set(point.time as number, point.value as number);
    }
    priceMapRef.current = priceMap;
    timeListRef.current = lineData.map((point) => point.time as number);
    markersRef.current = normalizedMarkers;
    const labelMap = new Map<number, string[]>();
    for (const marker of normalizedMarkers) {
      const label = marker.label ?? marker.text;
      if (!label) {
        continue;
      }
      const list = labelMap.get(marker.time) || [];
      list.push(label);
      labelMap.set(marker.time, list);
    }
    markerLabelRef.current = labelMap;

    candleSeries.setData(candleData);
    lineSeries.setData(lineData);
    volumeSeries.setData(volumeData);
    candleSeries.applyOptions({ visible: mode !== "adjusted" });
    lineSeries.applyOptions({ visible: mode !== "raw" });
    candleSeries.setMarkers([]);
    lineSeries.setMarkers(normalizedMarkers);
    chart.timeScale().fitContent();
    renderLabelsRef.current();
  }, [displaySeries, mode, markers]);

  const canSelect = datasets && datasets.length > 1 && onSelect;

  return (
    <div
      className="dataset-chart"
      data-testid="dataset-chart"
      data-granularity={granularity}
      data-candles={displaySeries.candles.length}
      data-adjusted={displaySeries.adjusted.length}
    >
      <div className="dataset-chart-header">
        <div>
          <div className="dataset-chart-title">{dataset.name}</div>
          <div className="dataset-chart-meta">
            {t("data.chart.meta", { frequency: frequencyLabel, coverage: coverageLabel })}
          </div>
        </div>
        <div className="dataset-chart-controls">
          {canSelect && (
            <select
              className="dataset-chart-select"
              value={selectedId ?? dataset.id}
              onChange={(event) => onSelect?.(Number(event.target.value))}
            >
              {(datasets || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.frequency?.toLowerCase().includes("minute")
                    ? t("data.frequency.minute")
                    : t("data.frequency.daily")}
                </option>
              ))}
            </select>
          )}
          <select
            className="dataset-chart-select"
            value={mode}
            onChange={(event) => setMode(event.target.value as ChartMode)}
          >
            <option value="both">{t("data.chart.mode.both")}</option>
            <option value="raw">{t("data.chart.mode.raw")}</option>
            <option value="adjusted">{t("data.chart.mode.adjusted")}</option>
          </select>
          <select
            className="dataset-chart-select"
            value={granularity}
            onChange={(event) => setGranularity(event.target.value as Granularity)}
          >
            <option value="auto">{t("data.chart.granularity.auto")}</option>
            <option value="day">{t("data.chart.granularity.day")}</option>
            <option value="week">{t("data.chart.granularity.week")}</option>
            <option value="month">{t("data.chart.granularity.month")}</option>
          </select>
          <div className="dataset-chart-range">
            {RANGE_PRESETS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={preset === item.key ? "active" : ""}
                onClick={() => applyPreset(item.key)}
              >
                {item.key === "MAX" ? t("data.chart.range.max") : item.key}
              </button>
            ))}
          </div>
          <div className="dataset-chart-dates">
            <input
              type="date"
              value={startDate}
              onChange={(event) => {
                setPreset("CUSTOM");
                setStartDate(event.target.value);
              }}
            />
            <span>~</span>
            <input
              type="date"
              value={endDate}
              onChange={(event) => {
                setPreset("CUSTOM");
                setEndDate(event.target.value);
              }}
            />
          </div>
          {openUrl && (
            <a href={openUrl} target="_blank" rel="noreferrer" className="link-button">
              {t("data.chart.open")}
            </a>
          )}
        </div>
      </div>
      <div className="dataset-chart-legend">
        <span>
          <span className="legend-dot raw" />
          {t("data.chart.legend.raw")}
        </span>
        <span>
          <span className="legend-dot adjusted" />
          {t("data.chart.legend.adjusted")}
        </span>
      </div>
      <div className="dataset-chart-canvas" ref={containerRef} />
      {loading && <div className="dataset-chart-status">{t("data.chart.loading")}</div>}
      {!loading && error && <div className="dataset-chart-error">{error}</div>}
      {!loading && !error && series && !series.candles.length && !series.adjusted.length && (
        <div className="dataset-chart-status">{t("data.chart.empty")}</div>
      )}
    </div>
  );
}
