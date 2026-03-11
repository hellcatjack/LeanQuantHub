import type { HistogramData, LineData } from "lightweight-charts";

import type {
  PositionChartInterval,
  PositionChartBar,
  PositionChartMarker,
  PositionChartPosition,
  PositionChartResponse,
} from "./positionChartTypes";
export { POSITION_CHART_INTERVALS } from "./positionChartTypes";

export interface PositionChartSummary {
  symbol: string;
  quantity: number;
  totalPosition: number;
  avg_cost?: number | null;
  avgCost?: number | null;
  market_price?: number | null;
  marketPrice?: number | null;
  market_value?: number | null;
  marketValue?: number | null;
  currency?: string | null;
  direction: "long" | "short";
  rowCount: number;
}

const toNumber = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

export const isIntradayInterval = (interval: string | null | undefined) =>
  ["1m", "5m", "15m", "1h"].includes(String(interval || ""));

export const isIntradayChartInterval = isIntradayInterval;

export const supportsLocalFallback = (interval: string | null | undefined) =>
  ["1D", "1W", "1M"].includes(String(interval || ""));

export const buildPositionChartQuery = ({
  symbol,
  interval,
  mode,
  useRth,
}: {
  symbol: string;
  interval: PositionChartInterval;
  mode: string;
  useRth: boolean;
}) => ({
  symbol,
  interval,
  mode: String(mode || "").trim().toLowerCase() || "paper",
  use_rth: useRth,
});

export const buildPositionChartRequestKey = ({
  symbol,
  interval,
  mode,
  useRth,
}: {
  symbol: string;
  interval: PositionChartInterval;
  mode: string;
  useRth: boolean;
}) =>
  [
    String(symbol || "").trim().toUpperCase(),
    interval,
    String(mode || "").trim().toLowerCase() || "paper",
    useRth ? "rth" : "all",
  ].join("::");

export const resolveSelectedChartSymbol = (
  positions: PositionChartPosition[],
  selectedSymbol: string | null | undefined
) => {
  const normalizedSelected = String(selectedSymbol || "").trim().toUpperCase();
  const normalized = positions
    .filter((item) => String(item.symbol || "").trim())
    .map((item) => ({
      ...item,
      symbol: String(item.symbol || "").trim().toUpperCase(),
    }));
  if (normalizedSelected && normalized.some((item) => item.symbol === normalizedSelected)) {
    return normalizedSelected;
  }
  const actionable = normalized.find((item) => Math.abs(Number(item.position || 0)) > 1e-9);
  if (actionable) {
    return actionable.symbol;
  }
  return normalized[0]?.symbol || null;
};

export const summarizeChartPosition = (
  positions: PositionChartPosition[],
  symbol: string | null | undefined
): PositionChartSummary | null => {
  const normalizedSymbol = String(symbol || "").trim().toUpperCase();
  if (!normalizedSymbol) {
    return null;
  }
  const matches = positions.filter(
    (item) => String(item.symbol || "").trim().toUpperCase() === normalizedSymbol
  );
  if (!matches.length) {
    return null;
  }
  let quantity = 0;
  let weightedCost = 0;
  let weightedPrice = 0;
  let weightBase = 0;
  let marketValue = 0;
  let hasMarketValue = false;
  let currency: string | null = null;
  matches.forEach((match) => {
    const qty = Number(match.position || 0);
    const absQty = Math.abs(qty);
    quantity += qty;
    if (absQty > 0) {
      if (match.avg_cost != null) {
        weightedCost += Number(match.avg_cost) * absQty;
      }
      if (match.market_price != null) {
        weightedPrice += Number(match.market_price) * absQty;
      }
      weightBase += absQty;
    }
    if (match.market_value != null) {
      marketValue += Number(match.market_value);
      hasMarketValue = true;
    }
    if (!currency && match.currency) {
      currency = match.currency;
    }
  });
  const avgCost = weightBase > 0 ? weightedCost / weightBase : null;
  const marketPrice = weightBase > 0 ? weightedPrice / weightBase : null;
  return {
    symbol: normalizedSymbol,
    quantity,
    totalPosition: quantity,
    avg_cost: avgCost,
    avgCost,
    market_price: marketPrice,
    marketPrice,
    market_value: hasMarketValue ? marketValue : null,
    marketValue: hasMarketValue ? marketValue : null,
    currency,
    direction: quantity >= 0 ? "long" : "short",
    rowCount: matches.length,
  };
};

export const computeMovingAverage = <T extends Pick<PositionChartBar, "time" | "close">>(
  bars: T[],
  period: number
): LineData<number>[] => {
  if (!Number.isFinite(period) || period <= 1 || bars.length < period) {
    return [];
  }
  const result: LineData<number>[] = [];
  let sum = 0;
  for (let index = 0; index < bars.length; index += 1) {
    sum += Number(bars[index].close || 0);
    if (index >= period) {
      sum -= Number(bars[index - period].close || 0);
    }
    if (index >= period - 1) {
      result.push({
        time: bars[index].time,
        value: Number((sum / period).toFixed(4)),
      });
    }
  }
  return result;
};

export const buildVolumeSeries = (bars: PositionChartBar[]): HistogramData<number>[] =>
  bars.map((bar) => ({
    time: bar.time,
    value: Number(bar.volume || 0),
    color:
      Number(bar.close) >= Number(bar.open)
        ? "rgba(15, 157, 88, 0.32)"
        : "rgba(214, 69, 69, 0.3)",
  }));

export const buildSyntheticPositionMarkers = (
  position: PositionChartPosition | null,
  bars: PositionChartBar[]
): PositionChartMarker[] => {
  if (!position || !bars.length) {
    return [];
  }
  const quantity = Number(position.position || 0);
  if (!Number.isFinite(quantity) || Math.abs(quantity) <= 1e-9) {
    return [];
  }
  const lastBar = bars[bars.length - 1];
  return [
    {
      time: lastBar.time,
      position: quantity >= 0 ? "belowBar" : "aboveBar",
      shape: quantity >= 0 ? "arrowUp" : "arrowDown",
      color: quantity >= 0 ? "#0f9d58" : "#d64545",
      text: quantity >= 0 ? `LONG ${Math.abs(quantity)}` : `SHORT ${Math.abs(quantity)}`,
    },
  ];
};

export const buildPositionMarkers = (
  bars: PositionChartBar[],
  backendMarkers: PositionChartMarker[],
  summary: PositionChartSummary | null
) => {
  if (backendMarkers.length) {
    return backendMarkers;
  }
  if (!summary || !bars.length) {
    return [];
  }
  const lastBar = bars[bars.length - 1];
  return [
    {
      time: lastBar.time,
      position: summary.direction === "long" ? "belowBar" : "aboveBar",
      shape: summary.direction === "long" ? "arrowUp" : "arrowDown",
      color: summary.direction === "long" ? "#0f9d58" : "#d64545",
      text: "POS",
    },
  ] satisfies PositionChartMarker[];
};

export const mergeChartMarkers = (
  response: PositionChartResponse | null,
  position: PositionChartPosition | null
) => {
  if (response?.markers?.length) {
    return response.markers;
  }
  return buildSyntheticPositionMarkers(position, response?.bars || []);
};

export const normalizePriceChartPayload = (payload: any): PositionChartResponse => {
  const bars = Array.isArray(payload?.bars)
    ? payload.bars
        .map((item: any) => ({
          time: Number(item?.time),
          open: Number(item?.open),
          high: Number(item?.high),
          low: Number(item?.low),
          close: Number(item?.close),
          volume: toNumber(item?.volume),
        }))
        .filter(
          (item) =>
            Number.isFinite(item.time) &&
            [item.open, item.high, item.low, item.close].every((value) => Number.isFinite(value))
        )
    : [];
  const markers = Array.isArray(payload?.markers)
    ? payload.markers
        .map((item: any) => ({
          time: Number(item?.time),
          position: item?.position === "aboveBar" ? "aboveBar" : "belowBar",
          shape: item?.shape === "arrowDown" ? "arrowDown" : "arrowUp",
          color: String(item?.color || "#0f62fe"),
          text: item?.text != null ? String(item.text) : null,
        }))
        .filter((item) => Number.isFinite(item.time))
    : [];
  return {
    symbol: String(payload?.symbol || "").trim().toUpperCase(),
    interval: String(payload?.interval || "1D"),
    source: String(payload?.source || "unavailable"),
    fallback_used: Boolean(payload?.fallback_used),
    stale: Boolean(payload?.stale),
    bars,
    markers,
    meta: payload?.meta
      ? {
          price_precision: toNumber(payload.meta.price_precision),
          currency: payload.meta.currency != null ? String(payload.meta.currency) : null,
          range_label: payload.meta.range_label != null ? String(payload.meta.range_label) : null,
          last_bar_at: payload.meta.last_bar_at != null ? String(payload.meta.last_bar_at) : null,
        }
      : null,
    error: payload?.error != null ? String(payload.error) : null,
  };
};

export const formatChartTimestamp = (time: number | null | undefined) => {
  if (!Number.isFinite(time)) {
    return "";
  }
  return new Date(Number(time) * 1000).toISOString().replace("T", " ").slice(0, 16);
};

export const formatCompactNumber = (value: number | null | undefined, digits = 2) => {
  if (!Number.isFinite(Number(value))) {
    return "--";
  }
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

export const resolveChartStateMessage = (
  response: PositionChartResponse | null,
  requestError: string,
  t: (key: string) => string
) => {
  if (requestError) {
    return requestError;
  }
  if (!response) {
    return "";
  }
  if (response.error === "ib_history_unavailable") {
    return isIntradayInterval(response.interval)
      ? t("trade.positionChartIntradayUnavailable")
      : t("trade.positionChartLoadError");
  }
  if (response.error === "local_history_missing") {
    return t("trade.positionChartLocalMissing");
  }
  if (response.error) {
    return t("trade.positionChartLoadError");
  }
  return "";
};
