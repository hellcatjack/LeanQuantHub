import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import IdChip from "./IdChip";

describe("IdChip", () => {
  it("renders label and copy button", () => {
    const html = ReactDOMServer.renderToString(<IdChip label="Run" value={123} />);
    expect(html).toContain("Run#123");
    expect(html).toContain("Copy ID");
  });
});
