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

export const MANUAL_REFRESH_KEYS: ManualRefreshKey[] = ["health", "contracts"];

export const isAutoRefreshKey = (key: RefreshKey): key is AutoRefreshKey =>
  key in REFRESH_INTERVALS;

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
