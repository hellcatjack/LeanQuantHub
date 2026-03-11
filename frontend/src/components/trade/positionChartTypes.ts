export type PositionChartInterval = "1m" | "5m" | "15m" | "1h" | "1D" | "1W" | "1M";
export type PriceChartInterval = PositionChartInterval;

export interface PositionChartBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
}

export interface PositionChartMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown";
  color: string;
  text?: string | null;
}

export interface PositionChartMeta {
  price_precision?: number | null;
  currency?: string | null;
  range_label?: string | null;
  last_bar_at?: string | null;
}

export interface PositionChartResponse {
  symbol: string;
  interval: PositionChartInterval | string;
  source: string;
  fallback_used: boolean;
  stale: boolean;
  bars: PositionChartBar[];
  markers: PositionChartMarker[];
  meta?: PositionChartMeta | null;
  error?: string | null;
}

export interface PositionChartPosition {
  symbol: string;
  position: number;
  avg_cost?: number | null;
  market_price?: number | null;
  market_value?: number | null;
  currency?: string | null;
}

export type PositionChartPositionRow = PositionChartPosition;

export interface PositionChartSymbolSummary {
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

export interface PositionChartToolbarOption {
  value: PositionChartInterval;
  label: string;
}

export const POSITION_CHART_INTERVALS: PositionChartInterval[] = [
  "1m",
  "5m",
  "15m",
  "1h",
  "1D",
  "1W",
  "1M",
];
