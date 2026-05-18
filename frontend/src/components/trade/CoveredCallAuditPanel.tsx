import React from "react";
import { useI18n } from "../../i18n";

export interface CoveredCallAuditRecentItem {
  review_id: string;
  created_at?: string | null;
  symbol?: string | null;
  status?: string | null;
  timeline_state?: string | null;
  latest_command_id?: string | null;
}

export interface CoveredCallAuditStage {
  label: string;
  status?: string | null;
  at?: string | null;
}

export interface CoveredCallAuditPayload {
  mode: string;
  status?: string | null;
  timeline_state?: string | null;
  review_id: string;
  review?: Record<string, any> | null;
  submit?: Record<string, any> | null;
  receipt?: Record<string, any> | null;
  timeline?: {
    status?: string | null;
    timeline_state?: string | null;
    review_id: string;
    latest_submit?: Record<string, any> | null;
    latest_receipt?: Record<string, any> | null;
    stages?: CoveredCallAuditStage[] | null;
    artifacts?: Record<string, string | null> | null;
  } | null;
  artifacts?: Record<string, string | null> | null;
}

interface CoveredCallAuditPanelProps {
  recentItems: CoveredCallAuditRecentItem[];
  selectedReviewId: string | null;
  recentQuery: string;
  recentOffset: number;
  recentLimit: number;
  recentTotal: number;
  recentHasMore: boolean;
  recentLoading: boolean;
  auditLoading: boolean;
  recentError: string;
  auditError: string;
  audit: CoveredCallAuditPayload | null;
  onSelectReview: (reviewId: string) => void;
  onRecentQueryChange: (value: string) => void;
  onPreviousPage: () => void;
  onNextPage: () => void;
  onRefreshRecent: () => void;
  onRefreshAudit: () => void;
}

const renderValue = (value: unknown) => {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
};

const renderJson = (value: unknown) => {
  if (value === null || value === undefined) {
    return "-";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

export default function CoveredCallAuditPanel({
  recentItems,
  selectedReviewId,
  recentQuery,
  recentOffset,
  recentLimit,
  recentTotal,
  recentHasMore,
  recentLoading,
  auditLoading,
  recentError,
  auditError,
  audit,
  onSelectReview,
  onRecentQueryChange,
  onPreviousPage,
  onNextPage,
  onRefreshRecent,
  onRefreshAudit,
}: CoveredCallAuditPanelProps) {
  const { t } = useI18n();
  const currentFrom = recentItems.length ? recentOffset + 1 : 0;
  const currentTo = recentItems.length ? recentOffset + recentItems.length : 0;
  return (
    <div className="card covered-call-audit-panel" data-testid="covered-call-audit-panel">
      <div className="card-title">{t("trade.coveredCall.title")}</div>
      <div className="card-meta">{t("trade.coveredCall.meta")}</div>
      <div className="covered-call-audit-toolbar">
        <span className="covered-call-audit-badge">{t("trade.coveredCall.paperOnly")}</span>
        <div className="covered-call-audit-actions">
          <button type="button" className="button-secondary button-compact" onClick={onRefreshRecent}>
            {t("trade.coveredCall.refreshRecent")}
          </button>
          <button type="button" className="button-secondary button-compact" onClick={onRefreshAudit}>
            {t("trade.coveredCall.refreshAudit")}
          </button>
        </div>
      </div>
      {recentError ? <div className="form-hint danger">{recentError}</div> : null}
      {auditError ? <div className="form-hint danger">{auditError}</div> : null}
      <div className="covered-call-audit-grid">
        <div className="covered-call-audit-list">
          <div className="form-label">{t("trade.coveredCall.recentTitle")}</div>
          <div className="covered-call-audit-list-toolbar">
            <input
              type="text"
              className="form-input covered-call-audit-search"
              placeholder={t("trade.coveredCall.searchPlaceholder")}
              value={recentQuery}
              onChange={(event) => onRecentQueryChange(event.target.value)}
            />
            <div className="covered-call-audit-pagination">
              <span className="covered-call-audit-page-summary">
                {t("trade.coveredCall.pageSummary", {
                  from: currentFrom,
                  to: currentTo,
                  total: recentTotal,
                })}
              </span>
              <button
                type="button"
                className="button-secondary button-compact"
                onClick={onPreviousPage}
                disabled={recentOffset <= 0 || recentLoading}
              >
                {t("trade.coveredCall.previousPage")}
              </button>
              <button
                type="button"
                className="button-secondary button-compact"
                onClick={onNextPage}
                disabled={!recentHasMore || recentLoading || recentItems.length < Math.min(recentLimit, recentTotal || recentLimit)}
              >
                {t("trade.coveredCall.nextPage")}
              </button>
            </div>
          </div>
          {recentLoading ? <div className="form-hint">{t("common.actions.loading")}</div> : null}
          {!recentLoading && !recentItems.length ? (
            <div className="empty-state">{t("trade.coveredCall.emptyRecent")}</div>
          ) : null}
          {recentItems.map((item) => (
            <button
              key={item.review_id}
              type="button"
              className={item.review_id === selectedReviewId ? "covered-call-audit-item active" : "covered-call-audit-item"}
              onClick={() => onSelectReview(item.review_id)}
            >
              <div className="covered-call-audit-item-title">{item.review_id}</div>
              <div className="covered-call-audit-item-meta">{renderValue(item.symbol)} · {renderValue(item.status)}</div>
              <div className="covered-call-audit-item-meta">{renderValue(item.timeline_state)}</div>
              <div className="covered-call-audit-item-meta">{renderValue(item.latest_command_id)}</div>
              <div className="covered-call-audit-item-meta">{renderValue(item.created_at)}</div>
            </button>
          ))}
        </div>
        <div className="covered-call-audit-detail">
          <div className="form-label">{t("trade.coveredCall.detailTitle")}</div>
          {auditLoading ? <div className="form-hint">{t("common.actions.loading")}</div> : null}
          {!auditLoading && !audit ? (
            <div className="empty-state">{t("trade.coveredCall.emptyAudit")}</div>
          ) : null}
          {audit ? (
            <>
              <div className="meta-list" style={{ marginTop: "8px" }}>
                <div className="meta-row"><span>{t("trade.coveredCall.reviewId")}</span><strong>{renderValue(audit.review_id)}</strong></div>
                <div className="meta-row"><span>{t("common.labels.status")}</span><strong>{renderValue(audit.status)}</strong></div>
                <div className="meta-row"><span>{t("trade.coveredCall.timelineState")}</span><strong>{renderValue(audit.timeline_state)}</strong></div>
                <div className="meta-row"><span>{t("trade.coveredCall.latestCommandId")}</span><strong>{renderValue(audit.timeline?.latest_submit?.command_id ?? audit.submit?.command_id ?? null)}</strong></div>
              </div>
              <div className="covered-call-audit-stage-list">
                {(audit.timeline?.stages || []).map((stage) => (
                  <div key={`${stage.label}-${stage.at || "na"}`} className="covered-call-audit-stage">
                    <strong>{stage.label}</strong>
                    <span>{renderValue(stage.status)}</span>
                    <span>{renderValue(stage.at)}</span>
                  </div>
                ))}
              </div>
              <div className="covered-call-audit-artifacts">
                <div className="form-label">{t("trade.coveredCall.artifactsTitle")}</div>
                <div>{renderValue(audit.artifacts?.summary)}</div>
                <div>{renderValue(audit.artifacts?.review_bundle)}</div>
                <div>{renderValue(audit.artifacts?.timeline_summary)}</div>
                <div>{renderValue(audit.artifacts?.latest_submit_summary)}</div>
                <div>{renderValue(audit.artifacts?.latest_receipt_summary)}</div>
              </div>
              <details className="covered-call-audit-json">
                <summary>{t("trade.coveredCall.reviewPayloadTitle")}</summary>
                <pre>{renderJson(audit.review)}</pre>
              </details>
              <details className="covered-call-audit-json">
                <summary>{t("trade.coveredCall.submitPayloadTitle")}</summary>
                <pre>{renderJson(audit.submit)}</pre>
              </details>
              <details className="covered-call-audit-json">
                <summary>{t("trade.coveredCall.receiptPayloadTitle")}</summary>
                <pre>{renderJson(audit.receipt)}</pre>
              </details>
              <details className="covered-call-audit-json">
                <summary>{t("trade.coveredCall.timelinePayloadTitle")}</summary>
                <pre>{renderJson(audit.timeline)}</pre>
              </details>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
