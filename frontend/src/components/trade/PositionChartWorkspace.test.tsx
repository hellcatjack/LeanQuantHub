import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n";
import PositionChartWorkspace from "./PositionChartWorkspace";
import {
  buildPositionMarkers,
  computeMovingAverage,
  normalizePriceChartPayload,
  resolveSelectedChartSymbol,
  summarizeChartPosition,
} from "./positionChartUtils";

vi.mock("lightweight-charts", () => ({
  CrosshairMode: { Normal: 0 },
  createChart: () => ({
    addCandlestickSeries: () => ({
      setData: () => undefined,
      setMarkers: () => undefined,
    }),
    addHistogramSeries: () => ({
      setData: () => undefined,
    }),
    addLineSeries: () => ({
      setData: () => undefined,
    }),
    subscribeCrosshairMove: () => undefined,
    priceScale: () => ({
      applyOptions: () => undefined,
    }),
    timeScale: () => ({
      fitContent: () => undefined,
    }),
    applyOptions: () => undefined,
    remove: () => undefined,
  }),
}));

describe("PositionChartWorkspace", () => {
  it("selects the first actionable position when current symbol is absent", () => {
    expect(
      resolveSelectedChartSymbol(
        [
          { symbol: "CASH", position: 0 },
          { symbol: "AAPL", position: 10 },
          { symbol: "MSFT", position: -3 },
        ],
        null
      )
    ).toBe("AAPL");
  });

  it("computes moving averages from bars", () => {
    const series = computeMovingAverage(
      [
        { time: 1, open: 1, high: 1, low: 1, close: 10, volume: 1 },
        { time: 2, open: 1, high: 1, low: 1, close: 20, volume: 1 },
        { time: 3, open: 1, high: 1, low: 1, close: 30, volume: 1 },
      ],
      2
    );
    expect(series).toEqual([
      { time: 2, value: 15 },
      { time: 3, value: 25 },
    ]);
  });

  it("builds a position marker from latest bar", () => {
    const summary = summarizeChartPosition(
      [
        { symbol: "AAPL", position: 10, avg_cost: 180, market_price: 182, market_value: 1820 },
      ],
      "AAPL"
    );
    const markers = buildPositionMarkers(
      [{ time: 100, open: 1, high: 2, low: 0.5, close: 1.5, volume: 50 }],
      [],
      summary
    );
    expect(markers).toHaveLength(1);
    expect(markers[0].text).toBe("POS");
  });

  it("normalizes chart payload structure", () => {
    const payload = normalizePriceChartPayload({
      symbol: "aapl",
      interval: "1D",
      source: "local",
      fallback_used: true,
      stale: false,
      bars: [{ time: "100", open: "1", high: "2", low: "0.5", close: "1.5", volume: "10" }],
      markers: [{ time: "100", position: "belowBar", shape: "arrowUp", color: "#10b981" }],
      meta: { range_label: "6M" },
      error: null,
    });
    expect(payload.symbol).toBe("AAPL");
    expect(payload.bars[0].close).toBe(1.5);
    expect(payload.fallback_used).toBe(true);
  });

  it("renders workspace shell with selected symbol and interval toolbar", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(PositionChartWorkspace, {
          positions: [{ symbol: "AAPL", position: 10, avg_cost: 180, market_price: 182 }],
          selectedSymbol: "AAPL",
          mode: "paper",
          gatewayRuntimeState: "healthy",
          positionsLoading: false,
        })
      )
    );
    expect(html).toContain("AAPL");
    expect(html).toContain("position-chart-workspace");
    expect(html).toContain("日线");
    expect(html).toContain("分钟");
  });
});
