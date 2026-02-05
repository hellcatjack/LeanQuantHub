import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";

import MlTrainingCurveChart from "./MlTrainingCurveChart";

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
});
