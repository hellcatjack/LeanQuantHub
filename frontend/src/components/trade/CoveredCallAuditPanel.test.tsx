import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "../../i18n";
import CoveredCallAuditPanel from "./CoveredCallAuditPanel";

describe("CoveredCallAuditPanel", () => {
  it("renders recent review items and audit summary", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(CoveredCallAuditPanel, {
          recentItems: [
            {
              review_id: "review-1",
              created_at: "2026-04-08T12:00:00Z",
              symbol: "AAPL",
              status: "ready",
              timeline_state: "awaiting_submit",
              latest_command_id: "cmd-1",
            },
          ],
          selectedReviewId: "review-1",
          recentQuery: "review",
          recentOffset: 0,
          recentLimit: 10,
          recentTotal: 2,
          recentHasMore: true,
          recentLoading: false,
          auditLoading: false,
          recentError: "",
          auditError: "",
          audit: {
            mode: "paper",
            status: "ready",
            timeline_state: "awaiting_submit",
            review_id: "review-1",
            review: { status: "ready", approval_expires_at: "2026-04-08T13:00:00Z" },
            submit: { status: "queued", command_id: "cmd-1" },
            receipt: { status: "accepted", broker_order_id: "ib-123" },
            timeline: {
              status: "ready",
              timeline_state: "awaiting_submit",
              review_id: "review-1",
              latest_submit: { command_id: "cmd-1" },
              latest_receipt: { status: "accepted" },
              stages: [
                { label: "review", status: "ready", at: "2026-04-08T12:00:00Z" },
              ],
              artifacts: { summary: "/tmp/summary.json" },
            },
            artifacts: {
              summary: "/tmp/summary.json",
              review_bundle: "/tmp/review_bundle.json",
              timeline_summary: "/tmp/timeline.json",
              latest_submit_summary: null,
              latest_receipt_summary: null,
            },
          },
          onSelectReview: () => undefined,
          onRecentQueryChange: () => undefined,
          onPreviousPage: () => undefined,
          onNextPage: () => undefined,
          onRefreshRecent: () => undefined,
          onRefreshAudit: () => undefined,
        })
      )
    );
    expect(html).toContain("Covered Call Pilot");
    expect(html).toContain("review-1");
    expect(html).toContain("AAPL");
    expect(html).toContain("2026-04-08T12:00:00Z");
    expect(html).toContain("awaiting_submit");
    expect(html).toContain("cmd-1");
    expect(html).toContain("/tmp/summary.json");
    expect(html).toContain("approval_expires_at");
    expect(html).toContain("broker_order_id");
    expect(html).toContain("Artifacts");
    expect(html).toContain("搜索审核记录");
    expect(html).toContain("1-1 / 2");
    expect(html).toContain("上一页");
    expect(html).toContain("下一页");
  });

  it("renders empty state without recent items", () => {
    const html = ReactDOMServer.renderToString(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(CoveredCallAuditPanel, {
          recentItems: [],
          selectedReviewId: null,
          recentQuery: "",
          recentOffset: 0,
          recentLimit: 10,
          recentTotal: 0,
          recentHasMore: false,
          recentLoading: false,
          auditLoading: false,
          recentError: "",
          auditError: "",
          audit: null,
          onSelectReview: () => undefined,
          onRecentQueryChange: () => undefined,
          onPreviousPage: () => undefined,
          onNextPage: () => undefined,
          onRefreshRecent: () => undefined,
          onRefreshAudit: () => undefined,
        })
      )
    );
    expect(html).toContain("暂无 covered call 审核记录");
  });
});
