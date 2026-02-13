export const BACKOFF_BASE_MS = 3_000;
export const BACKOFF_MAX_MS = 30_000;

const BACKOFF_ERROR_CODES = new Set(["ECONNABORTED", "ERR_NETWORK", "ETIMEDOUT"]);

export const computeBackendBackoffMs = (
  consecutiveFailures: number,
  baseMs: number = BACKOFF_BASE_MS,
  maxMs: number = BACKOFF_MAX_MS
): number => {
  const failures = Math.max(0, Math.floor(Number(consecutiveFailures) || 0));
  if (failures <= 0) {
    return 0;
  }
  const delay = baseMs * Math.pow(2, failures - 1);
  return Math.min(maxMs, Math.max(baseMs, Math.floor(delay)));
};

export const isBackendBackoffEligibleError = ({
  hasResponse,
  status,
  code,
}: {
  hasResponse: boolean;
  status?: number;
  code?: string;
}): boolean => {
  if (!hasResponse) {
    return true;
  }
  const numericStatus = Number(status);
  if (Number.isFinite(numericStatus) && (numericStatus >= 500 || numericStatus === 429 || numericStatus === 408)) {
    return true;
  }
  const normalizedCode = String(code || "").trim().toUpperCase();
  return normalizedCode.length > 0 && BACKOFF_ERROR_CODES.has(normalizedCode);
};

