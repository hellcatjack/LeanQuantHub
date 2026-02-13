export type AutoRefreshKey =
  | "connection"
  | "bridge"
  | "project"
  | "account"
  | "positions"
  | "monitor"
  | "snapshot"
  | "execution";

export type ManualRefreshKey = "health" | "contracts";

export type RefreshKey = AutoRefreshKey | ManualRefreshKey;

export const REFRESH_INTERVALS: Record<AutoRefreshKey, number> = {
  connection: 10_000,
  bridge: 15_000,
  project: 60_000,
  account: 60_000,
  positions: 15_000,
  monitor: 15_000,
  snapshot: 10_000,
  execution: 20_000,
};

const FAST_REFRESH_OVERRIDES: Partial<Record<AutoRefreshKey, number>> = {
  monitor: 3_000,
  execution: 5_000,
  positions: 5_000,
};

const ACTIVE_TRADE_ORDER_STATUSES = new Set(["NEW", "SUBMITTED", "PARTIAL", "CANCEL_REQUESTED"]);
const TERMINAL_TRADE_ORDER_STATUSES = new Set([
  "FILLED",
  "CANCELED",
  "CANCELLED",
  "REJECTED",
  "INVALID",
  "SKIPPED",
]);

const TERMINAL_TRADE_RUN_STATUSES = new Set([
  "done",
  "partial",
  "failed",
  "terminated",
  "canceled",
  "cancelled",
]);

export const MANUAL_REFRESH_KEYS: ManualRefreshKey[] = ["health", "contracts"];

export const isAutoRefreshKey = (key: RefreshKey): key is AutoRefreshKey =>
  key in REFRESH_INTERVALS;

export const resolveRefreshIntervals = (
  options: { hotExecution?: boolean } = {}
): Record<AutoRefreshKey, number> => {
  if (!options.hotExecution) {
    return REFRESH_INTERVALS;
  }
  return {
    ...REFRESH_INTERVALS,
    ...FAST_REFRESH_OVERRIDES,
  };
};

export const hasActiveTradeOrderStatus = (status?: string | null): boolean => {
  const normalized = String(status || "").trim().toUpperCase();
  if (!normalized) {
    return false;
  }
  if (ACTIVE_TRADE_ORDER_STATUSES.has(normalized)) {
    return true;
  }
  if (TERMINAL_TRADE_ORDER_STATUSES.has(normalized)) {
    return false;
  }
  return true;
};

export const hasActiveTradeRunStatus = (status?: string | null): boolean => {
  const normalized = String(status || "").trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return !TERMINAL_TRADE_RUN_STATUSES.has(normalized);
};

export const buildSymbolListKey = (
  symbols?: Array<string | null | undefined> | null
): string => {
  if (!Array.isArray(symbols) || symbols.length === 0) {
    return "";
  }
  return symbols
    .map((symbol) => String(symbol || "").trim().toUpperCase())
    .filter((symbol) => symbol.length > 0)
    .join("|");
};
