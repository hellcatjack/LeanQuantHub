const toNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const cleaned = value.replace(/[%$,]/g, "").trim();
    if (!cleaned) {
      return null;
    }
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const formatPercent = (value: number): string => `${(value * 100).toFixed(2)}%`;

export const formatNetProfitPercent = (
  metrics?: Record<string, unknown> | null
): string => {
  if (!metrics) {
    return "-";
  }
  const raw = metrics["Net Profit"] ?? metrics["NetProfit"];
  if (typeof raw === "string" && raw.trim().endsWith("%")) {
    return raw.trim();
  }
  const start = toNumber(metrics["Start Equity"]);
  const end = toNumber(metrics["End Equity"]);
  if (start && end && start !== 0) {
    return formatPercent((end - start) / start);
  }
  const numeric = toNumber(raw);
  if (numeric === null) {
    return "-";
  }
  if (Math.abs(numeric) <= 1) {
    return formatPercent(numeric);
  }
  if (Math.abs(numeric) <= 100) {
    return `${numeric.toFixed(2)}%`;
  }
  return `${numeric.toFixed(2)}%`;
};
