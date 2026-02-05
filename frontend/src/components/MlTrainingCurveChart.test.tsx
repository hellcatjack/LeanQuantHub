import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";

import MlTrainingCurveChart, { formatEpochTick } from "./MlTrainingCurveChart";

describe("MlTrainingCurveChart", () => {
  it("renders training curve chart wrapper", () => {
    const html = ReactDOMServer.renderToString(
      <MlTrainingCurveChart
        iterations={[1, 2]}
        series={[{ key: "ndcg@10", label: "NDCG@10", values: [0.1, 0.2] }]}
      />
    );
    expect(html).toContain("ml-training-curve");
  });

  it("shows best value with earliest epoch in legend", () => {
    const html = ReactDOMServer.renderToString(
      <MlTrainingCurveChart
        iterations={[1, 2, 3, 4]}
        series={[
          { key: "ndcg@10", label: "NDCG@10", values: [0.3, 0.5, 0.5, 0.4] },
        ]}
      />
    );
    expect(html.replace(/\s+/g, "").replace(/<!---->/g, "")).toContain(
      "NDCG@10:0.4000（最佳0.5000@Iter2）"
    );
  });

  it("formats epoch ticks as integers", () => {
    expect(formatEpochTick(220)).toBe("220");
  });
});
