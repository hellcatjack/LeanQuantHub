import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";

export type TrainingCurveSeries = {
  key: string;
  label: string;
  values: number[];
};

type ChartPoint = { time: number; value: number };

type HoverState = {
  timeLabel: string;
  values: Record<string, number | undefined>;
};

const COLOR_MAP: Record<string, string> = {
  "ndcg@10": "#2563eb",
  "ndcg@50": "#16a34a",
  "ndcg@100": "#f59e0b",
};

const toLineData = (points: ChartPoint[]) =>
  points
    .filter((item) => Number.isFinite(item.value))
    .map((item) => ({ time: item.time as Time, value: item.value } as LineData));

const findNearestValue = (points: ChartPoint[], time: number) => {
  if (!points.length) {
    return undefined;
  }
  if (time <= points[0].time) {
    return points[0].value;
  }
  const last = points[points.length - 1];
  if (time >= last.time) {
    return last.value;
  }
  let left = 0;
  let right = points.length - 1;
  while (left <= right) {
    const mid = Math.floor((left + right) / 2);
    const midTime = points[mid].time;
    if (midTime === time) {
      return points[mid].value;
    }
    if (midTime < time) {
      left = mid + 1;
    } else {
      right = mid - 1;
    }
  }
  return points[Math.max(0, right)].value;
};

const formatIter = (time: number) => `Iter ${time}`;

const formatValue = (value?: number) =>
  Number.isFinite(value ?? NaN) ? Number(value).toFixed(4) : "-";

interface MlTrainingCurveChartProps {
  iterations: number[];
  series: TrainingCurveSeries[];
}

export default function MlTrainingCurveChart({
  iterations,
  series,
}: MlTrainingCurveChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<Record<string, ISeriesApi<"Line">>>({});
  const seriesPointsRef = useRef<Record<string, ChartPoint[]>>({});
  const [hover, setHover] = useState<HoverState | null>(null);

  const prepared = useMemo(() => {
    const keys = series.map((item) => item.key);
    return series.map((item) => {
      const length = Math.min(iterations.length, item.values.length);
      const points: ChartPoint[] = [];
      for (let i = 0; i < length; i += 1) {
        points.push({ time: iterations[i] ?? i + 1, value: item.values[i] });
      }
      return { ...item, points };
    });
  }, [iterations, series]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || chartRef.current) {
      return;
    }
    const chart = createChart(container, {
      height: 260,
      layout: {
        background: { color: "#ffffff" },
        textColor: "#0f172a",
        fontFamily: '"IBM Plex Sans", "Noto Sans SC", "Segoe UI", sans-serif',
      },
      grid: {
        vertLines: { color: "#eef2f7" },
        horzLines: { color: "#eef2f7" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#e2e8f0", visible: true },
      timeScale: { borderColor: "#e2e8f0" },
    });
    chartRef.current = chart;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(container);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || typeof param.time !== "number") {
        setHover(null);
        return;
      }
      const time = param.time;
      const values: Record<string, number | undefined> = {};
      for (const [key, points] of Object.entries(seriesPointsRef.current)) {
        values[key] = findNearestValue(points, time);
      }
      setHover({ timeLabel: formatIter(time), values });
    });

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = {};
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) {
      return;
    }
    const chart = chartRef.current;
    const nextKeys = new Set(prepared.map((item) => item.key));
    for (const key of Object.keys(seriesRefs.current)) {
      if (!nextKeys.has(key)) {
        chart.removeSeries(seriesRefs.current[key]);
        delete seriesRefs.current[key];
      }
    }
    seriesPointsRef.current = {};
    for (const item of prepared) {
      let line = seriesRefs.current[item.key];
      if (!line) {
        line = chart.addLineSeries({
          color: COLOR_MAP[item.key] || "#475569",
          lineWidth: 2.2,
        });
        seriesRefs.current[item.key] = line;
      }
      line.setData(toLineData(item.points));
      seriesPointsRef.current[item.key] = item.points;
    }
  }, [prepared]);

  const latestValues = useMemo(() => {
    const values: Record<string, number | undefined> = {};
    for (const item of prepared) {
      values[item.key] = item.points.length
        ? item.points[item.points.length - 1].value
        : undefined;
    }
    return values;
  }, [prepared]);

  return (
    <div className="ml-training-curve">
      <div className="ml-training-curve-header">
        <div className="ml-training-curve-title">NDCG 曲线（验证集）</div>
        <div className="ml-training-curve-legend">
          {(hover ? prepared : prepared).map((item) => (
            <span key={item.key} className={`ml-training-curve-legend-item ${item.key}`}>
              {item.label}: {formatValue(hover?.values[item.key] ?? latestValues[item.key])}
            </span>
          ))}
          {hover && <span className="ml-training-curve-time">{hover.timeLabel}</span>}
        </div>
      </div>
      <div ref={containerRef} className="ml-training-curve-canvas" />
    </div>
  );
}
