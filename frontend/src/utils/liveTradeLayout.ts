export const LIVE_TRADE_REFRESH_MS = {
  connection: 10000,
  monitor: 15000,
  account: 60000,
};

export type LiveTradeSectionKey =
  | "connection"
  | "project"
  | "account"
  | "positions"
  | "monitor"
  | "config"
  | "marketHealth"
  | "contracts"
  | "history"
  | "guard"
  | "execution"
  | "symbolSummary";

export const getLiveTradeSections = () => ({
  main: ["connection", "project", "account", "positions", "monitor"] as LiveTradeSectionKey[],
  advanced: [
    "config",
    "marketHealth",
    "contracts",
    "history",
    "guard",
    "execution",
    "symbolSummary",
  ] as LiveTradeSectionKey[],
});
