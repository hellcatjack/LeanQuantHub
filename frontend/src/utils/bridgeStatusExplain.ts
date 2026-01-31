export const getBridgeRefreshHintKey = (
  result?: string | null,
  reason?: string | null
) => {
  const normalizedResult = String(result || "").toLowerCase();
  const normalizedReason = String(reason || "").toLowerCase();
  if (normalizedResult === "skipped" && normalizedReason === "rate_limited") {
    return "trade.refreshHint.rateLimited";
  }
  if (normalizedResult === "skipped" && normalizedReason === "fresh") {
    return "trade.refreshHint.fresh";
  }
  if (normalizedResult === "failed") {
    return "trade.refreshHint.failed";
  }
  return "trade.refreshHint.generic";
};

export const getHeartbeatAgeSeconds = (
  timestamp?: string | null,
  now: Date = new Date()
) => {
  if (!timestamp) {
    return null;
  }
  const text = String(timestamp).replace("Z", "+00:00");
  const value = new Date(text);
  if (Number.isNaN(value.getTime())) {
    return null;
  }
  const delta = Math.max(0, Math.floor((now.getTime() - value.getTime()) / 1000));
  return delta;
};

export const resolveConnectionReasonKey = (message?: string | null) => {
  if (!message) {
    return null;
  }
  const normalized = String(message).toLowerCase();
  if (normalized.includes("lean bridge ok")) {
    return null;
  }
  if (normalized.includes("lean bridge stale")) {
    return "trade.statusReason.bridgeStale";
  }
  if (normalized.includes("lean bridge")) {
    return "trade.statusReason.bridgeIssue";
  }
  return null;
};

export const getNextAllowedRefreshAt = (
  lastRefreshAt?: string | null,
  cooldownSeconds: number = 10
) => {
  if (!lastRefreshAt) {
    return null;
  }
  const text = String(lastRefreshAt).replace("Z", "+00:00");
  const value = new Date(text);
  if (Number.isNaN(value.getTime())) {
    return null;
  }
  return new Date(value.getTime() + cooldownSeconds * 1000).toISOString();
};
