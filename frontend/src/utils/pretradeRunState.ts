const PRETRADE_ACTIVE_STATUSES = new Set(["queued", "running"]);

export const isPretradeRunActive = (status?: string | null): boolean => {
  if (!status) {
    return false;
  }
  return PRETRADE_ACTIVE_STATUSES.has(status);
};

export const findActivePretradeRun = <T extends { status?: string | null }>(
  runs: T[]
): T | undefined => runs.find((run) => isPretradeRunActive(run.status));
