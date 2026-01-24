import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import LiveTradePage from "./LiveTradePage";

describe("LiveTradePage", () => {
  it("renders market snapshot card", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.snapshotTitle");
  });

  it("renders execute trade run form", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.executeRunId");
    expect(html).toContain("trade.executeSubmit");
  });

  it("renders symbol summary and fills table", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.symbolSummaryTitle");
    expect(html).toContain("trade.fillsTitle");
  });
});
