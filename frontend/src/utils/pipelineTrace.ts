export const parsePretradeRunId = (traceId?: string | null): number | null => {
  if (!traceId || !traceId.startsWith("pretrade:")) {
    return null;
  }
  const parts = traceId.split(":");
  if (parts.length < 2 || !parts[1]) {
    return null;
  }
  const parsed = Number(parts[1]);
  return Number.isFinite(parsed) ? parsed : null;
};
