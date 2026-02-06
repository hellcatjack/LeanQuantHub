import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "../i18n";
import LiveTradePage, { TradeIntentMismatchCard } from "./LiveTradePage";

const PipelineLabel = () => {
  const { t } = useI18n();
  return React.createElement("span", null, t("trade.pipelineTab"));
};

const TradeStatusLabel = () => {
  const { t } = useI18n();
  return React.createElement("span", null, t("trade.statusLabel"));
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

  it("renders TWS status label translation", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(TradeStatusLabel)
      )
    );
    expect(html).toContain("TWS 状态");
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

  it("filters pipeline runs by keyword and highlights events", () => {
    const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
    expect(html).toContain("pipeline-keyword-input");
    expect(html).toContain("pipeline-event-highlight");
  });

  it("renders intent/order mismatch card with symbols", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(TradeIntentMismatchCard, {
          mismatch: {
            missing_symbols: ["AXON", "KLAC"],
            extra_symbols: ["TSLA"],
            missing_count: 2,
            extra_count: 1,
            intent_path: "/tmp/intent_orders.json",
          },
        })
      )
    );
    expect(html).toContain("订单意图与创建订单不一致");
    expect(html).toContain("AXON");
    expect(html).toContain("TSLA");
    expect(html).toContain("意图文件");
    expect(html).toContain("intent_orders.json");
  });
});
