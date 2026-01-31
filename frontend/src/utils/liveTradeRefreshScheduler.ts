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
  positions: 60_000,
  monitor: 15_000,
  snapshot: 10_000,
  execution: 20_000,
};

export const MANUAL_REFRESH_KEYS: ManualRefreshKey[] = ["health", "contracts"];

export const isAutoRefreshKey = (key: RefreshKey): key is AutoRefreshKey =>
  key in REFRESH_INTERVALS;
