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

export const buildTickIndices = (total: number, count: number): number[] => {
  if (!Number.isFinite(total) || total <= 0) {
    return [];
  }
  const cappedCount = Math.max(1, Math.min(Math.floor(count), total));
  if (cappedCount === 1) {
    return [0];
  }
  const span = total - 1;
  const indices: number[] = [];
  const seen = new Set<number>();
  for (let i = 0; i < cappedCount; i += 1) {
    const raw = Math.round((span * i) / (cappedCount - 1));
    const index = Math.max(0, Math.min(span, raw));
    if (!seen.has(index)) {
      seen.add(index);
      indices.push(index);
    }
  }
  if (!seen.has(0)) {
    indices.unshift(0);
    seen.add(0);
  }
  if (!seen.has(span)) {
    indices.push(span);
    seen.add(span);
  }
  if (indices.length < cappedCount) {
    for (let i = 0; i <= span && indices.length < cappedCount; i += 1) {
      if (!seen.has(i)) {
        seen.add(i);
        indices.push(i);
      }
    }
  }
  return indices.sort((a, b) => a - b);
};

export const buildMinorTickIndices = (
  total: number,
  majorTicks: number[]
): number[] => {
  if (!Number.isFinite(total) || total <= 1) {
    return [];
  }
  const span = total - 1;
  const majors = [...new Set(majorTicks)]
    .map((idx) => Math.max(0, Math.min(span, idx)))
    .sort((a, b) => a - b);
  const minors = new Set<number>();
  for (let i = 0; i < majors.length - 1; i += 1) {
    const start = majors[i];
    const end = majors[i + 1];
    if (end - start <= 1) {
      continue;
    }
    const mid = Math.round((start + end) / 2);
    if (mid !== start && mid !== end) {
      minors.add(mid);
    }
  }
  return Array.from(minors).sort((a, b) => a - b);
};

export const buildMinorTickValues = (values: number[]): number[] => {
  if (!Array.isArray(values) || values.length < 2) {
    return [];
  }
  const minors: number[] = [];
  for (let i = 0; i < values.length - 1; i += 1) {
    const start = values[i];
    const end = values[i + 1];
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      continue;
    }
    const mid = (start + end) / 2;
    if (Number.isFinite(mid)) {
      minors.push(mid);
    }
  }
  return minors;
};

type NdcgSeries = {
  key: string;
  label: string;
  values: number[];
};

export const extractNdcgCurves = (
  metrics?: Record<string, any> | null
): { iterations: number[]; series: NdcgSeries[] } | null => {
  if (!metrics) {
    return null;
  }
  const curve =
    metrics.curve_ndcg ||
    metrics.walk_forward?.curve_ndcg ||
    metrics.walkForward?.curve_ndcg;
  if (!curve || typeof curve !== "object") {
    return null;
  }
  const iterations = Array.isArray(curve.iterations) ? curve.iterations : [];
  const valid = curve.valid as Record<string, any> | undefined;
  if (!valid || typeof valid !== "object") {
    return null;
  }
  const order = [
    { key: "ndcg@10", label: "NDCG@10" },
    { key: "ndcg@50", label: "NDCG@50" },
    { key: "ndcg@100", label: "NDCG@100" },
  ];
  const series: NdcgSeries[] = [];
  for (const entry of order) {
    const values = valid[entry.key];
    if (Array.isArray(values) && values.length) {
      series.push({ ...entry, values: values.map((item) => Number(item)) });
    }
  }
  if (!series.length) {
    return null;
  }
  const lengths = series.map((item) => item.values.length).filter((len) => len > 0);
  if (!lengths.length) {
    return null;
  }
  let minLen = Math.min(...lengths);
  if (iterations.length) {
    minLen = Math.min(minLen, iterations.length);
  }
  if (minLen <= 0) {
    return null;
  }
  const trimmedIterations = iterations.length
    ? iterations.slice(0, minLen)
    : Array.from({ length: minLen }, (_, idx) => idx + 1);
  return {
    iterations: trimmedIterations,
    series: series.map((item) => ({ ...item, values: item.values.slice(0, minLen) })),
  };
};
