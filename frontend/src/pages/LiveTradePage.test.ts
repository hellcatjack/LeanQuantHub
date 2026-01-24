import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import LiveTradePage from "./LiveTradePage";

describe("LiveTradePage", () => {
  it("renders market snapshot card", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.snapshotTitle");
  });
});
