import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "../i18n";
import LiveTradePage, {
  filterActionablePositions,
  isGatewayRuntimeRecovering,
  isPositionActionable,
  resolveAccountPositionsErrorState,
  resolveAccountPositionsResponseState,
  resolveGatewayTradeBlockState,
  resolvePositionChartFloatingLayout,
  TradeIntentMismatchCard,
  WeeklyRebalancePanel,
  type WeeklyRebalanceStatus,
  resolveSessionByEasternTime,
} from "./LiveTradePage";

const PipelineLabel = () => {
  const { t } = useI18n();
  return React.createElement("span", null, t("trade.pipelineTab"));
};

const TradeStatusLabel = () => {
  const { t } = useI18n();
  return React.createElement(
    "span",
    null,
    t("trade.statusLabel", { system: t("data.ib.workstationTypeTws") }),
  );
};

const GatewayRecoveryLabel = () => {
  const { t } = useI18n();
  return React.createElement(
    "span",
    null,
    `${t("trade.gatewayRuntimeLabel")} ${t("trade.accountPositionsTrustedFallbackHint")}`,
  );
};

describe("LiveTradePage", () => {
  it("infers eastern trading session from clock", () => {
    expect(resolveSessionByEasternTime(new Date("2026-01-15T15:00:00Z"))).toBe(
      "rth",
    );
    expect(resolveSessionByEasternTime(new Date("2026-01-15T11:00:00Z"))).toBe(
      "pre",
    );
    expect(resolveSessionByEasternTime(new Date("2026-01-15T22:00:00Z"))).toBe(
      "post",
    );
    expect(resolveSessionByEasternTime(new Date("2026-01-15T02:00:00Z"))).toBe(
      "night",
    );
    expect(resolveSessionByEasternTime(new Date("2026-01-17T16:00:00Z"))).toBe(
      "night",
    );
  });

  it("marks zero positions as non-actionable for liquidation", () => {
    expect(isPositionActionable({ position: 0 })).toBe(false);
    expect(isPositionActionable({ position: 1e-12 })).toBe(false);
    expect(isPositionActionable({ position: 10 })).toBe(true);
    expect(isPositionActionable({ position: -3 })).toBe(true);
  });

  it("filters liquidation targets to non-zero positions only", () => {
    const rows = [
      { symbol: "A", position: 0 },
      { symbol: "B", position: 5 },
      { symbol: "C", position: -2 },
      { symbol: "D", position: 0 },
    ];
    const actionable = filterActionablePositions(rows);
    expect(actionable).toHaveLength(2);
    expect(actionable.map((item) => item.symbol)).toEqual(["B", "C"]);
  });

  it("keeps last trusted positions when stale refresh returns empty", () => {
    const fresh = resolveAccountPositionsResponseState({
      response: {
        items: [
          { symbol: "AAPL", position: 10, account: "DU1", currency: "USD" },
        ],
        refreshed_at: "2026-03-10T14:00:00Z",
        stale: false,
      },
    });
    const stale = resolveAccountPositionsResponseState({
      response: {
        items: [],
        refreshed_at: "2026-03-10T14:05:00Z",
        stale: true,
      },
      trustedItems: fresh.trustedItems,
      trustedUpdatedAt: fresh.trustedUpdatedAt,
    });
    expect(stale.usingTrustedFallback).toBe(true);
    expect(stale.displayItems).toEqual(fresh.trustedItems);
    expect(stale.displayUpdatedAt).toBe("2026-03-10T14:00:00Z");
  });

  it("keeps last trusted positions when refresh request fails", () => {
    const fresh = resolveAccountPositionsResponseState({
      response: {
        items: [
          { symbol: "MSFT", position: 3, account: "DU1", currency: "USD" },
        ],
        refreshed_at: "2026-03-10T14:00:00Z",
        stale: false,
      },
    });
    const failed = resolveAccountPositionsErrorState({
      trustedItems: fresh.trustedItems,
      trustedUpdatedAt: fresh.trustedUpdatedAt,
    });
    expect(failed.usingTrustedFallback).toBe(true);
    expect(failed.displayItems).toEqual(fresh.trustedItems);
    expect(failed.displayUpdatedAt).toBe("2026-03-10T14:00:00Z");
    expect(failed.displayStale).toBe(true);
  });

  it("marks gateway degraded states as blocked and recovering", () => {
    expect(resolveGatewayTradeBlockState({ state: "gateway_degraded" })).toBe(
      "gateway_degraded",
    );
    expect(resolveGatewayTradeBlockState({ state: "gateway_restarting" })).toBe(
      "gateway_restarting",
    );
    expect(resolveGatewayTradeBlockState({ state: "recovering" })).toBeNull();
    expect(isGatewayRuntimeRecovering({ state: "recovering" })).toBe(true);
    expect(isGatewayRuntimeRecovering({ state: "healthy" })).toBe(false);
  });

  it("renders weekly rebalance schedule and manual controls", () => {
    const status: WeeklyRebalanceStatus = {
      project_id: 18,
      generated_at: "2026-05-12T12:00:00Z",
      schedules: [
        {
          phase: "prepare",
          timer_unit: "stocklean-weekly-rebalance-prepare.timer",
          service_unit: "stocklean-weekly-rebalance-prepare.service",
          on_calendar: "Mon *-*-* 08:00:00",
          active_state: "active",
          sub_state: "waiting",
          next_elapse_at: "2026-05-18T12:00:00Z",
          last_trigger_at: "2026-05-11T12:00:00Z",
        },
      ],
      history: [
        {
          project_id: 18,
          week_key: "2026-W20",
          phase: "execute",
          pretrade_run_id: 11,
          pretrade_status: "success",
          pretrade_created_at: "2026-05-11T12:00:00Z",
          trade_run_id: 22,
          trade_status: "running",
          trade_created_at: "2026-05-11T13:35:00Z",
        },
      ],
    };
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(WeeklyRebalancePanel, {
          selectedProjectId: "18",
          status,
          loading: false,
          actionLoading: null,
          error: "",
          result: "",
          force: false,
          dryRun: false,
          onForceChange: () => undefined,
          onDryRunChange: () => undefined,
          onRefresh: () => undefined,
          onTrigger: () => undefined,
          formatStatus: (value) => String(value || "-"),
          formatDateTime: (value) => String(value || "-"),
        }),
      ),
    );

    expect(html).toContain("周度自动调仓");
    expect(html).toContain("stocklean-weekly-rebalance-prepare.timer");
    expect(html).toContain("手工运行 PreTrade");
    expect(html).toContain("2026-W20");
    expect(html).toContain("#11");
    expect(html).toContain("#22");
  });

  it("resolves floating chart below selected row on wide viewports", () => {
    expect(
      resolvePositionChartFloatingLayout({
        viewportWidth: 1600,
        cardWidth: 1480,
        cardHeight: 1100,
        selectedRowTop: 220,
        selectedRowHeight: 42,
      }),
    ).toMatchObject({
      floating: true,
      placement: "below-row",
    });
  });

  it("resolves floating chart above selected row when lower space is tight", () => {
    expect(
      resolvePositionChartFloatingLayout({
        viewportWidth: 1600,
        cardWidth: 1480,
        cardHeight: 1100,
        selectedRowTop: 860,
        selectedRowHeight: 42,
      }),
    ).toMatchObject({
      floating: true,
      placement: "above-row",
    });
  });

  it("resolves snapped floating chart layout from persisted top-right anchor", () => {
    expect(
      resolvePositionChartFloatingLayout({
        viewportWidth: 1600,
        cardWidth: 1480,
        cardHeight: 1100,
        selectedRowTop: 220,
        selectedRowHeight: 42,
        persistedWindow: {
          anchor: "top-right",
          minimized: false,
          offsetX: 18,
          offsetY: 24,
          width: 460,
          height: 520,
        },
      }),
    ).toMatchObject({
      floating: true,
      placement: "top-right",
      left: 1002,
      top: 272,
      width: 460,
      height: 520,
      minimized: false,
      userAnchored: true,
    });
  });

  it("sanitizes invalid persisted floating chart layout back to automatic placement", () => {
    expect(
      resolvePositionChartFloatingLayout({
        viewportWidth: 1600,
        cardWidth: 1480,
        cardHeight: 1100,
        selectedRowTop: 220,
        selectedRowHeight: 42,
        persistedWindow: {
          anchor: "sideways",
          minimized: false,
          offsetX: -20,
          offsetY: -5,
          width: 9999,
          height: 100,
        } as any,
      }),
    ).toMatchObject({
      floating: true,
      placement: "below-row",
      minimized: false,
      userAnchored: false,
    });
  });

  it("keeps minimized floating chart as a compact snapped strip", () => {
    expect(
      resolvePositionChartFloatingLayout({
        viewportWidth: 1600,
        cardWidth: 1480,
        cardHeight: 1100,
        selectedRowTop: 220,
        selectedRowHeight: 42,
        persistedWindow: {
          anchor: "bottom-right",
          minimized: true,
          offsetX: 18,
          offsetY: 20,
          width: 520,
          height: 560,
        },
      }),
    ).toMatchObject({
      floating: true,
      placement: "bottom-right",
      minimized: true,
      userAnchored: true,
      height: 68,
    });
  });

  it("stacks chart on narrower viewports", () => {
    expect(
      resolvePositionChartFloatingLayout({
        viewportWidth: 1180,
        cardWidth: 1080,
        cardHeight: 900,
        selectedRowTop: 240,
        selectedRowHeight: 42,
      }),
    ).toMatchObject({
      floating: false,
      placement: "stacked",
    });
  });

  it("renders market snapshot card", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("trade.snapshotTitle");
  });

  it("renders execute trade run form", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("trade.executeRunId");
    expect(html).toContain("trade.executeSubmit");
  });

  it("renders account summary section", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("trade.accountSummaryTitle");
  });

  it("renders symbol summary and fills table", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("trade.symbolSummaryTitle");
    expect(html).toContain("trade.fillsTitle");
  });

  it("renders decision basis markers in execution view", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("trade.decisionBasisTitle");
    expect(html).toContain("trade.decisionBasisEffectivePitDate");
    expect(html).toContain("trade.decisionBasisSummaryLine");
  });

  it("renders client order id column", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("trade.orderTable.clientOrderId");
  });

  it("renders orders pagination controls", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("pagination.pageSize");
  });

  it("renders translated account summary tags with i18n provider", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(LiveTradePage),
      ),
    );
    expect(html).toContain("净清算值");
  });

  it("renders new gateway recovery translations with i18n provider", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(GatewayRecoveryLabel),
      ),
    );
    expect(html).toContain("Gateway 运行状态");
    expect(html).toContain("最后一次可信持仓");
  });

  it("renders pipeline tab label translation", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(PipelineLabel),
      ),
    );
    expect(html).toContain("Pipeline");
  });

  it("renders status label translation with system name", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(TradeStatusLabel),
      ),
    );
    expect(html).toContain("TWS 状态");
  });

  it("renders pipeline view container", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("pipeline-view");
  });

  it("renders pipeline filters labels", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("trade.pipeline.filters.project");
  });

  it("renders pipeline event list", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("pipeline-events");
  });

  it("renders pipeline stage lanes and event drawer", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
    expect(html).toContain("pipeline-stage-lanes");
    expect(html).toContain("pipeline-event-drawer");
  });

  it("filters pipeline runs by keyword and highlights events", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(LiveTradePage),
    );
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
        }),
      ),
    );
    expect(html).toContain("订单意图与创建订单不一致");
    expect(html).toContain("AXON");
    expect(html).toContain("TSLA");
    expect(html).toContain("意图文件");
    expect(html).toContain("intent_orders.json");
  });

  it("renders covered call read-only panel shell with i18n provider", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(LiveTradePage),
      ),
    );
    expect(html).toContain("Covered Call Pilot");
    expect(html).toContain("Paper Only");
  });
});
