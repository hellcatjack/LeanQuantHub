export const formatRealizedPnlValue = (value: number | null | undefined, fallback: string) => {
  if (value === null || value === undefined) {
    return fallback;
  }
  if (Number.isNaN(Number(value))) {
    return fallback;
  }
  return Number(value).toFixed(2);
};
