export const resolveAccountSummaryLabel = (key: string, rawMap?: unknown): string => {
  if (!rawMap || typeof rawMap !== "object") {
    return key;
  }
  const value = (rawMap as Record<string, unknown>)[key];
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return key;
};
