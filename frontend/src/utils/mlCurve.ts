export type AxisRange = {
  min: number;
  max: number;
  span: number;
  rawMin: number;
  rawMax: number;
};

export const computePaddedRange = (
  values: number[],
  options: { minSpanRatio?: number; padRatio?: number } = {}
): AxisRange | null => {
  const finite = values.filter((value) => Number.isFinite(value));
  if (!finite.length) {
    return null;
  }
  const rawMin = Math.min(...finite);
  const rawMax = Math.max(...finite);
  const rawSpan = rawMax - rawMin;
  const base = Math.max(Math.abs(rawMin), Math.abs(rawMax), 1);
  const minSpan = base * (options.minSpanRatio ?? 0.02);
  const span = Math.max(rawSpan, minSpan);
  const pad = span * (options.padRatio ?? 0.1);
  return {
    rawMin,
    rawMax,
    min: rawMin - pad,
    max: rawMax + pad,
    span: span + pad * 2,
  };
};

export const formatAxisValue = (value: number, span: number): string => {
  if (!Number.isFinite(value)) {
    return "-";
  }
  const absSpan = Math.abs(span);
  if (absSpan < 0.01) {
    return value.toFixed(5);
  }
  if (absSpan < 0.1) {
    return value.toFixed(4);
  }
  if (absSpan < 1) {
    return value.toFixed(3);
  }
  return value.toFixed(2);
};
