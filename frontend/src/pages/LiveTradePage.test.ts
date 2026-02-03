import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "../i18n";
import LiveTradePage from "./LiveTradePage";

const PipelineLabel = () => {
  const { t } = useI18n();
  return React.createElement("span", null, t("trade.pipelineTab"));
};

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

  it("renders account summary section", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.accountSummaryTitle");
  });

  it("renders symbol summary and fills table", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.symbolSummaryTitle");
    expect(html).toContain("trade.fillsTitle");
  });

  it("renders client order id column", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.orderTable.clientOrderId");
  });

  it("renders orders pagination controls", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("pagination.pageSize");
  });

  it("renders translated account summary tags with i18n provider", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(LiveTradePage)
      )
    );
    expect(html).toContain("净清算值");
  });

  it("renders pipeline tab label translation", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(PipelineLabel)
      )
    );
    expect(html).toContain("Pipeline");
  });

  it("renders pipeline view container", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("pipeline-view");
  });

  it("renders pipeline filters labels", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("trade.pipeline.filters.project");
  });

  it("renders pipeline event list", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("pipeline-events");
  });

  it("renders pipeline stage lanes and event drawer", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("pipeline-stage-lanes");
    expect(html).toContain("pipeline-event-drawer");
  });
});
