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
import { api } from "../../api";
import { useI18n } from "../../i18n";
import type {
  PositionChartBar,
  PositionChartPositionRow,
  PositionChartResponse,
  PositionChartSymbolSummary,
  PriceChartInterval,
} from "./positionChartTypes";
import {
  POSITION_CHART_INTERVALS,
  buildPositionChartQuery,
  buildPositionChartRequestKey,
  buildPositionMarkers,
  computeMovingAverage,
  isIntradayChartInterval,
  normalizePriceChartPayload,
  summarizeChartPosition,
  supportsLocalFallback,
} from "./positionChartUtils";

interface PositionChartWorkspaceProps {
  positions: PositionChartPositionRow[];
  selectedSymbol: string | null;
  mode: string;
  gatewayRuntimeState?: string | null;
  positionsLoading?: boolean;
}

const UP_COLOR = "#0f9f6e";
const DOWN_COLOR = "#d64545";
const GRID_COLOR = "rgba(15, 23, 42, 0.08)";
const SURFACE_COLOR = "#fbfdff";
const MA20_COLOR = "#2563eb";
const MA60_COLOR = "#f59e0b";

const formatValue = (value: number | null | undefined, digits = 2): string => {
  if (value == null || !Number.isFinite(Number(value))) {
    return "--";
  }
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
};

const intervalLabelKey = (interval: PriceChartInterval) =>
  `trade.positionChartInterval.${interval}`;

const sourceLabelKey = (source?: string | null) => {
  if (String(source || "").trim().toLowerCase() === "ib") {
    return "trade.positionChartSourceIb";
  }
  if (String(source || "").trim().toLowerCase() === "local") {
    return "trade.positionChartSourceLocal";
  }
  return "trade.positionChartSourceUnavailable";
};

export default function PositionChartWorkspace({
  positions,
  selectedSymbol,
  mode,
  gatewayRuntimeState,
  positionsLoading = false,
}: PositionChartWorkspaceProps) {
  const { t, formatDateTime } = useI18n();
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ma60SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const cacheRef = useRef<Map<string, PositionChartResponse>>(new Map());
  const requestSeqRef = useRef(0);
  const [interval, setInterval] = useState<PriceChartInterval>("1D");
  const [response, setResponse] = useState<PositionChartResponse | null>(null);
  const [requestError, setRequestError] = useState("");
  const [loading, setLoading] = useState(false);
  const [hoveredBar, setHoveredBar] = useState<PositionChartBar | null>(null);

  const normalizedSelectedSymbol = useMemo(
    () => String(selectedSymbol || "").trim().toUpperCase() || null,
    [selectedSymbol]
  );
  const positionSummary = useMemo<PositionChartSymbolSummary | null>(
    () => summarizeChartPosition(positions, normalizedSelectedSymbol),
    [positions, normalizedSelectedSymbol]
  );
  const requestKey = useMemo(() => {
    if (!normalizedSelectedSymbol) {
      return "";
    }
    return buildPositionChartRequestKey({
      symbol: normalizedSelectedSymbol,
      interval,
      mode,
      useRth: true,
    });
  }, [interval, mode, normalizedSelectedSymbol]);

  useEffect(() => {
    if (!normalizedSelectedSymbol) {
      setResponse(null);
      setRequestError("");
      setLoading(false);
      setHoveredBar(null);
      return;
    }
    const cached = cacheRef.current.get(requestKey) || null;
    if (cached) {
      setResponse(cached);
      setHoveredBar(cached.bars[cached.bars.length - 1] || null);
      setRequestError("");
    }
    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;
    setLoading(true);
    void api
      .get<PositionChartResponse>("/api/brokerage/history/chart", {
        params: buildPositionChartQuery({
          symbol: normalizedSelectedSymbol,
          interval,
          mode,
          useRth: true,
        }),
      })
      .then((res) => {
        if (seq !== requestSeqRef.current) {
          return;
        }
        const payload = normalizePriceChartPayload(res.data);
        cacheRef.current.set(requestKey, payload);
        setResponse(payload);
        setHoveredBar(payload.bars[payload.bars.length - 1] || null);
        setRequestError("");
      })
      .catch((err: any) => {
        if (seq !== requestSeqRef.current) {
          return;
        }
        const detail = err?.response?.data?.detail || err?.message || t("trade.positionChartLoadError");
        setRequestError(String(detail));
        if (!cached) {
          setResponse(null);
          setHoveredBar(null);
        }
      })
      .finally(() => {
        if (seq === requestSeqRef.current) {
          setLoading(false);
        }
      });
  }, [interval, mode, normalizedSelectedSymbol, requestKey, t]);

  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container) {
      return undefined;
    }
    const chart = createChart(container, {
      autoSize: true,
      height: 420,
      layout: {
        background: { color: SURFACE_COLOR },
        textColor: "#0f172a",
      },
      grid: {
        vertLines: { color: GRID_COLOR },
        horzLines: { color: GRID_COLOR },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(37, 99, 235, 0.26)",
          width: 1,
          labelBackgroundColor: "#1d4ed8",
        },
        horzLine: {
          color: "rgba(15, 23, 42, 0.18)",
          width: 1,
          labelBackgroundColor: "#0f172a",
        },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: {
          top: 0.08,
          bottom: 0.3,
        },
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
      },
    });
    const candleSeries = chart.addCandlestickSeries({
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderVisible: false,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: {
        type: "volume",
      },
      priceScaleId: "volume",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: {
        top: 0.78,
        bottom: 0.02,
      },
      borderVisible: false,
    });
    const ma20Series = chart.addLineSeries({
      color: MA20_COLOR,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ma60Series = chart.addLineSeries({
      color: MA60_COLOR,
      lineWidth: 2,
      lineStyle: 2 as any,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.subscribeCrosshairMove((param: any) => {
      if (!param?.time) {
        return;
      }
      const seriesData = param.seriesData?.get(candleSeries) as CandlestickData<number> | undefined;
      if (!seriesData) {
        return;
      }
      setHoveredBar((current) => ({
        time: Number(param.time),
        open: Number(seriesData.open ?? 0),
        high: Number(seriesData.high ?? 0),
        low: Number(seriesData.low ?? 0),
        close: Number(seriesData.close ?? 0),
        volume: current?.volume ?? null,
      }));
    });
    const handleDoubleClick = () => {
      chart.timeScale().fitContent();
    };
    container.addEventListener("dblclick", handleDoubleClick);

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => {
        chart.applyOptions({ width: container.clientWidth });
      });
      resizeObserver.observe(container);
    }

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    ma20SeriesRef.current = ma20Series;
    ma60SeriesRef.current = ma60Series;

    return () => {
      container.removeEventListener("dblclick", handleDoubleClick);
      resizeObserver?.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ma20SeriesRef.current = null;
      ma60SeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const bars = response?.bars || [];
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    const ma20Series = ma20SeriesRef.current;
    const ma60Series = ma60SeriesRef.current;
    if (!candleSeries || !volumeSeries || !ma20Series || !ma60Series) {
      return;
    }
    const candleData: CandlestickData<number>[] = bars.map((bar) => ({
      time: bar.time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    const volumeData: HistogramData<number>[] = bars.map((bar) => ({
      time: bar.time,
      value: Number(bar.volume ?? 0),
      color: bar.close >= bar.open ? "rgba(15, 159, 110, 0.4)" : "rgba(214, 69, 69, 0.4)",
    }));
    const ma20Data: LineData<number>[] = computeMovingAverage(bars, 20).map((item) => ({
      time: item.time,
      value: item.value,
    }));
    const ma60Data: LineData<number>[] = computeMovingAverage(bars, 60).map((item) => ({
      time: item.time,
      value: item.value,
    }));
    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    ma20Series.setData(ma20Data);
    ma60Series.setData(ma60Data);
    const mergedMarkers = buildPositionMarkers(bars, response?.markers || [], positionSummary);
    (candleSeries as any).setMarkers?.(mergedMarkers);
    if (bars.length > 0) {
      setHoveredBar(bars[bars.length - 1]);
      chartRef.current?.timeScale().fitContent();
    }
  }, [positionSummary, response]);

  const statusMessage = useMemo(() => {
    if (!normalizedSelectedSymbol) {
      return t("trade.positionChartSelectPrompt");
    }
    if (requestError) {
      return requestError;
    }
    if (response?.source === "unavailable" && isIntradayChartInterval(interval)) {
      return t("trade.positionChartIntradayUnavailable");
    }
    if (response?.error === "local_history_missing") {
      return t("trade.positionChartLocalMissing");
    }
    if (positionsLoading || loading) {
      return t("trade.positionChartLoading");
    }
    if (!response?.bars?.length) {
      return t("trade.positionChartEmpty");
    }
    return "";
  }, [interval, loading, normalizedSelectedSymbol, positionsLoading, requestError, response, t]);

  const latestBar = hoveredBar || response?.bars?.[response.bars.length - 1] || null;
  const infoTimeLabel = latestBar
    ? formatDateTime(new Date(latestBar.time * 1000).toISOString())
    : t("common.none");
  const sourceLabel = response ? t(sourceLabelKey(response.source)) : t("trade.positionChartSourceUnavailable");
  const fallbackActive = Boolean(response?.fallback_used);
  const showGatewayFallbackHint =
    fallbackActive &&
    supportsLocalFallback(interval) &&
    String(gatewayRuntimeState || "").trim().length > 0 &&
    String(gatewayRuntimeState || "").trim().toLowerCase() !== "healthy";

  return (
    <div className="position-chart-workspace" data-testid="position-chart-workspace">
      <div className="position-chart-header">
        <div>
          <div className="position-chart-kicker">{t("trade.positionChartTitle")}</div>
          <div className="position-chart-symbol-line">
            <strong data-testid="position-chart-symbol-label">
              {normalizedSelectedSymbol || t("common.none")}
            </strong>
            {positionSummary && (
              <span className="position-chart-summary-pill">
                {t("trade.positionChartPositionLabel", {
                  qty: formatValue(positionSummary.totalPosition, 4),
                })}
              </span>
            )}
            <span className="position-chart-source-badge">{sourceLabel}</span>
            {fallbackActive && (
              <span
                className="position-chart-source-badge is-fallback"
                data-testid="position-chart-fallback-badge"
              >
                {t("trade.positionChartFallbackBadge")}
              </span>
            )}
          </div>
        </div>
        <div className="position-chart-header-meta">
          <div className="position-chart-header-meta-row">
            <span>{t("trade.positionChartRangeLabel")}</span>
            <strong>{response?.meta?.range_label || t("common.none")}</strong>
          </div>
          <div className="position-chart-header-meta-row">
            <span>{t("trade.positionChartLastBarAt")}</span>
            <strong>{response?.meta?.last_bar_at ? formatDateTime(response.meta.last_bar_at) : t("common.none")}</strong>
          </div>
        </div>
      </div>

      <div className="position-chart-toolbar" data-testid="position-chart-toolbar">
        {POSITION_CHART_INTERVALS.map((item) => (
          <button
            key={item}
            type="button"
            className={`position-chart-interval-button${interval === item ? " is-active" : ""}`}
            data-testid={`position-chart-interval-${item}`}
            onClick={() => setInterval(item)}
          >
            {t(intervalLabelKey(item))}
          </button>
        ))}
      </div>

      {(fallbackActive || showGatewayFallbackHint) && (
        <div className="position-chart-status-banner" data-testid="position-chart-status-banner">
          {showGatewayFallbackHint
            ? t("trade.positionChartGatewayFallbackHint")
            : t("trade.positionChartFallbackHint")}
        </div>
      )}

      <div className="position-chart-stat-strip">
        <div className="position-chart-stat-item">
          <span>{t("trade.positionChartInfo.time")}</span>
          <strong>{infoTimeLabel}</strong>
        </div>
        <div className="position-chart-stat-item">
          <span>{t("trade.positionChartInfo.open")}</span>
          <strong>{formatValue(latestBar?.open)}</strong>
        </div>
        <div className="position-chart-stat-item">
          <span>{t("trade.positionChartInfo.high")}</span>
          <strong>{formatValue(latestBar?.high)}</strong>
        </div>
        <div className="position-chart-stat-item">
          <span>{t("trade.positionChartInfo.low")}</span>
          <strong>{formatValue(latestBar?.low)}</strong>
        </div>
        <div className="position-chart-stat-item">
          <span>{t("trade.positionChartInfo.close")}</span>
          <strong>{formatValue(latestBar?.close)}</strong>
        </div>
        <div className="position-chart-stat-item">
          <span>{t("trade.positionChartInfo.volume")}</span>
          <strong>{formatValue(latestBar?.volume ?? null, 0)}</strong>
        </div>
      </div>

      <div className="position-chart-surface">
        <div className="position-chart-canvas" ref={chartContainerRef} />
        {(loading || statusMessage) && (
          <div
            className={`position-chart-overlay${loading ? " is-loading" : ""}`}
            data-testid="position-chart-overlay"
          >
            <div className="position-chart-overlay-card">
              <strong>{normalizedSelectedSymbol || t("trade.positionChartTitle")}</strong>
              <div>{statusMessage || t("trade.positionChartLoading")}</div>
            </div>
          </div>
        )}
      </div>

      <div className="position-chart-footer">
        <div className="position-chart-footer-item">
          <span>{t("trade.positionChartFooter.avgCost")}</span>
          <strong>{formatValue(positionSummary?.avgCost)}</strong>
        </div>
        <div className="position-chart-footer-item">
          <span>{t("trade.positionChartFooter.marketPrice")}</span>
          <strong>{formatValue(positionSummary?.marketPrice)}</strong>
        </div>
        <div className="position-chart-footer-item">
          <span>{t("trade.positionChartFooter.marketValue")}</span>
          <strong>{formatValue(positionSummary?.marketValue)}</strong>
        </div>
        <div className="position-chart-footer-item">
          <span>{t("trade.positionChartFooter.rows")}</span>
          <strong>{positionSummary?.rowCount ?? 0}</strong>
        </div>
      </div>
    </div>
  );
}
