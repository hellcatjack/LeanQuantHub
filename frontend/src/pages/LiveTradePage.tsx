import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import TopBar from "../components/TopBar";
import IdChip from "../components/IdChip";
import PaginationBar from "../components/PaginationBar";
import { api, apiLong, getBackendBackoffUntilMs } from "../api";
import { useI18n } from "../i18n";
import { resolveAccountSummaryLabel } from "../utils/accountSummary";
import { buildManualOrderTag } from "../utils/orderTag";
import { getLiveTradeSections, type LiveTradeSectionKey } from "../utils/liveTradeLayout";
import {
  REFRESH_INTERVALS,
  MANUAL_REFRESH_KEYS,
  buildSymbolListKey,
  isAutoRefreshKey,
  type AutoRefreshKey,
  type RefreshKey,
} from "../utils/liveTradeRefreshScheduler";
import { refreshAllWithBridgeForce } from "../utils/liveTradeRefreshAll";
import {
  getHeartbeatAgeSeconds,
  getNextAllowedRefreshAt,
  resolveConnectionReasonKey,
} from "../utils/bridgeStatusExplain";
import {
  formatBridgeRefreshReason,
  formatBridgeRefreshResult,
  getBridgeRefreshHint,
} from "../utils/bridgeRefreshHint";
import { formatRealizedPnlValue } from "../utils/formatters";
import { parsePretradeRunId } from "../utils/pipelineTrace";

interface IBSettings {
  id: number;
  host: string;
  port: number;
  client_id: number;
  account_id?: string | null;
  mode: string;
  market_data_type: string;
  api_mode: string;
  use_regulatory_snapshot: boolean;
  created_at: string;
  updated_at: string;
}

interface IBConnectionState {
  id: number;
  status: string;
  message?: string | null;
  last_heartbeat?: string | null;
  updated_at: string;
}

interface IBContractRefreshResult {
  total: number;
  updated: number;
  skipped: number;
  errors: string[];
  duration_sec: number;
}

interface IBMarketHealthResult {
  status: string;
  total: number;
  success: number;
  missing_symbols: string[];
  errors: string[];
}

interface IBMarketSnapshotItem {
  symbol: string;
  data?: Record<string, any> | null;
  error?: string | null;
}

interface IBStreamSnapshotOut {
  symbol: string;
  data?: Record<string, any> | null;
  error?: string | null;
}

interface IBHistoryJob {
  id: number;
  status: string;
  total_symbols?: number | null;
  processed_symbols?: number | null;
  success_symbols?: number | null;
  failed_symbols?: number | null;
  message?: string | null;
  created_at: string;
  updated_at: string;
}

interface IBStreamStatus {
  status: string;
  last_heartbeat?: string | null;
  subscribed_symbols: string[];
  ib_error_count: number;
  last_error?: string | null;
  market_data_type?: string | null;
}

interface IBBridgeStatusOut {
  status?: string | null;
  stale?: boolean;
  last_heartbeat?: string | null;
  updated_at?: string | null;
  last_error?: string | null;
  last_refresh_at?: string | null;
  last_refresh_result?: string | null;
  last_refresh_reason?: string | null;
  last_refresh_message?: string | null;
}

interface IBBridgeRefreshOut {
  bridge_status: IBBridgeStatusOut;
}

interface IBAccountSummary {
  items: Record<string, any>;
  refreshed_at?: string | null;
  source?: string | null;
  stale: boolean;
  full: boolean;
}

interface IBAccountPosition {
  symbol: string;
  position: number;
  avg_cost?: number | null;
  market_price?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  realized_pnl?: number | null;
  account?: string | null;
  currency?: string | null;
}

interface IBAccountPositionsOut {
  items: IBAccountPosition[];
  refreshed_at?: string | null;
  stale: boolean;
}

interface ProjectSummary {
  id: number;
  name: string;
  description?: string | null;
}

interface DecisionSnapshotSummary {
  id: number;
  project_id: number;
  status?: string | null;
  snapshot_date?: string | null;
  summary?: Record<string, any> | null;
}

interface TradeRun {
  id: number;
  project_id: number;
  decision_snapshot_id?: number | null;
  mode: string;
  status: string;
  params?: Record<string, any> | null;
  message?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
  updated_at?: string | null;
  last_progress_at?: string | null;
  progress_stage?: string | null;
  progress_reason?: string | null;
  stalled_at?: string | null;
  stalled_reason?: string | null;
}

interface TradeRunExecuteOut {
  run_id: number;
  status: string;
  filled: number;
  cancelled: number;
  rejected: number;
  skipped: number;
  message?: string | null;
  dry_run: boolean;
}

interface TradeOrder {
  id: number;
  run_id?: number | null;
  client_order_id?: string | null;
  symbol: string;
  side: string;
  quantity: number;
  order_type?: string | null;
  limit_price?: number | null;
  status: string;
  realized_pnl?: number | null;
  created_at: string;
}

interface TradeFillDetail {
  id: number;
  order_id: number;
  symbol?: string | null;
  side?: string | null;
  exec_id?: string | null;
  fill_quantity: number;
  fill_price: number;
  commission?: number | null;
  realized_pnl?: number | null;
  fill_time?: string | null;
  currency?: string | null;
  exchange?: string | null;
}

interface TradeReceipt {
  time?: string | null;
  kind: string;
  order_id?: number | null;
  client_order_id?: string | null;
  symbol?: string | null;
  side?: string | null;
  quantity?: number | null;
  filled_quantity?: number | null;
  fill_price?: number | null;
  exec_id?: string | null;
  status?: string | null;
  commission?: number | null;
  realized_pnl?: number | null;
  source: string;
}

interface TradeReceiptPage {
  items: TradeReceipt[];
  total: number;
  warnings?: string[];
}

interface PipelineRunItem {
  trace_id: string;
  run_type: string;
  project_id: number;
  status: string;
  mode?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
}

interface PipelineEvent {
  event_id: string;
  task_type: string;
  task_id?: number | null;
  stage?: string | null;
  status?: string | null;
  message?: string | null;
  error_code?: string | null;
  log_path?: string | null;
  parent_id?: string | null;
  retry_of?: string | null;
  tags?: string[];
  params_snapshot?: Record<string, any> | null;
  artifact_paths?: Record<string, any> | null;
  started_at?: string | null;
  ended_at?: string | null;
}

interface PipelineTraceDetail {
  trace_id: string;
  events: PipelineEvent[];
  warnings?: string[];
}

interface TradeDirectOrderOut {
  order_id: number;
  status: string;
  execution_status: string;
  bridge_status?: IBBridgeStatusOut | null;
  refresh_result?: string | null;
}

interface TradeRunDetail {
  run: TradeRun;
  orders: TradeOrder[];
  fills: TradeFillDetail[];
  last_update_at?: string | null;
}

interface IntentOrderMismatch {
  missing_symbols?: string[];
  extra_symbols?: string[];
  missing_count?: number;
  extra_count?: number;
  intent_path?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

interface TradeSymbolSummary {
  symbol: string;
  target_weight?: number | null;
  target_value?: number | null;
  current_qty?: number | null;
  current_value?: number | null;
  current_weight?: number | null;
  filled_qty: number;
  avg_fill_price?: number | null;
  filled_value: number;
  pending_qty: number;
  last_status?: string | null;
  delta_value?: number | null;
  delta_weight?: number | null;
  fill_ratio?: number | null;
}

interface TradeSymbolSummaryPage {
  items: TradeSymbolSummary[];
  last_update_at?: string | null;
}

interface TradeGuardState {
  id: number;
  project_id: number;
  trade_date: string;
  mode: string;
  status: string;
  halt_reason?: Record<string, any> | null;
  risk_triggers: number;
  order_failures: number;
  market_data_errors: number;
  day_start_equity?: number | null;
  equity_peak?: number | null;
  last_equity?: number | null;
  last_valuation_ts?: string | null;
  valuation_source?: string | null;
  cooldown_until?: string | null;
  created_at: string;
  updated_at: string;
}

interface TradeSettings {
  id: number;
  risk_defaults?: Record<string, any> | null;
  execution_data_source?: string | null;
  created_at: string;
  updated_at: string;
}

type TradeSessionValue = "rth" | "pre" | "post" | "night";

export const resolveSessionByEasternTime = (date: Date = new Date()): TradeSessionValue => {
  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    const parts = formatter.formatToParts(date);
    let weekday = "";
    let hour = 0;
    let minute = 0;
    parts.forEach((part) => {
      if (part.type === "weekday") {
        weekday = part.value;
      } else if (part.type === "hour") {
        hour = Number(part.value) || 0;
      } else if (part.type === "minute") {
        minute = Number(part.value) || 0;
      }
    });
    if (weekday === "Sat" || weekday === "Sun") {
      return "night";
    }
    const totalMinutes = hour * 60 + minute;
    if (totalMinutes >= 9 * 60 + 30 && totalMinutes < 16 * 60) {
      return "rth";
    }
    if (totalMinutes >= 4 * 60 && totalMinutes < 9 * 60 + 30) {
      return "pre";
    }
    if (totalMinutes >= 16 * 60 && totalMinutes < 20 * 60) {
      return "post";
    }
    return "night";
  } catch {
    return "rth";
  }
};

const resolveDefaultOrderTypeBySession = (session: string) =>
  String(session || "").trim().toLowerCase() === "rth" ? "ADAPTIVE_LMT" : "LMT";

const maskAccount = (value?: string | null) => {
  if (!value) {
    return "";
  }
  if (value.length <= 4) {
    return `${value[0] ?? ""}***`;
  }
  return `${value.slice(0, 2)}****${value.slice(-2)}`;
};

const normalizeSymbols = (raw: string) =>
  raw
    .split(/[,\\s]+/)
    .map((item) => item.trim().toUpperCase())
    .filter((item) => item.length > 0);

const normalizeSymbolList = (raw: unknown) => {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((item) => String(item ?? "").trim().toUpperCase())
    .filter((item) => item.length > 0);
};

export const TradeIntentMismatchCard = ({
  mismatch,
  message,
}: {
  mismatch?: IntentOrderMismatch | null;
  message?: string | null;
}) => {
  const { t } = useI18n();
  const hasMismatch = Boolean(mismatch) || message === "intent_order_mismatch";
  if (!hasMismatch) {
    return null;
  }
  const missingSymbols = normalizeSymbolList(mismatch?.missing_symbols);
  const extraSymbols = normalizeSymbolList(mismatch?.extra_symbols);
  const missingCount =
    typeof mismatch?.missing_count === "number"
      ? mismatch.missing_count
      : missingSymbols.length;
  const extraCount =
    typeof mismatch?.extra_count === "number" ? mismatch.extra_count : extraSymbols.length;
  const intentPath = mismatch?.intent_path ? String(mismatch.intent_path) : "";
  return (
    <div
      className="form-hint danger"
      style={{
        marginTop: "12px",
        padding: "10px 12px",
        borderRadius: "12px",
        border: "1px solid rgba(214, 69, 69, 0.35)",
        background: "rgba(214, 69, 69, 0.08)",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: "6px" }}>
        {t("trade.runIntentMismatchTitle")}
      </div>
      <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
        <span>
          {t("trade.runIntentMismatchSummary", {
            missing: missingCount,
            extra: extraCount,
          })}
        </span>
        {intentPath ? (
          <span>{t("trade.runIntentMismatchPath", { path: intentPath })}</span>
        ) : null}
      </div>
      {missingSymbols.length ? (
        <div style={{ marginTop: "10px" }}>
          <div style={{ marginBottom: "6px" }}>{t("trade.runIntentMismatchMissing")}</div>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {missingSymbols.map((symbol) => (
              <span key={`missing-${symbol}`} className="pill danger">
                {symbol}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {extraSymbols.length ? (
        <div style={{ marginTop: "10px" }}>
          <div style={{ marginBottom: "6px" }}>{t("trade.runIntentMismatchExtra")}</div>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {extraSymbols.map((symbol) => (
              <span key={`extra-${symbol}`} className="pill warn">
                {symbol}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {!missingSymbols.length && !extraSymbols.length ? (
        <div style={{ marginTop: "8px" }}>{t("trade.runIntentMismatchEmpty")}</div>
      ) : null}
    </div>
  );
};

export default function LiveTradePage() {
  const { t, formatDateTime, getMessage } = useI18n();
  const [ibSettings, setIbSettings] = useState<IBSettings | null>(null);
  const [ibSettingsForm, setIbSettingsForm] = useState({
    host: "127.0.0.1",
    port: "7497",
    client_id: "1",
    account_id: "",
    mode: "paper",
    market_data_type: "realtime",
    api_mode: "ib",
    use_regulatory_snapshot: false,
  });
  const [ibSettingsSaving, setIbSettingsSaving] = useState(false);
  const [ibSettingsResult, setIbSettingsResult] = useState("");
  const [ibSettingsError, setIbSettingsError] = useState("");
  const [ibState, setIbState] = useState<IBConnectionState | null>(null);
  const [ibStateLoading, setIbStateLoading] = useState(false);
  const [ibStateResult, setIbStateResult] = useState("");
  const [ibStateError, setIbStateError] = useState("");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectError, setProjectError] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [snapshot, setSnapshot] = useState<DecisionSnapshotSummary | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");
  const [accountSummary, setAccountSummary] = useState<IBAccountSummary | null>(null);
  const [accountSummaryFull, setAccountSummaryFull] = useState<IBAccountSummary | null>(null);
  const [accountSummaryLoading, setAccountSummaryLoading] = useState(false);
  const [accountSummaryFullLoading, setAccountSummaryFullLoading] = useState(false);
  const [accountSummaryError, setAccountSummaryError] = useState("");
  const [accountSummaryFullError, setAccountSummaryFullError] = useState("");
  const [accountPositions, setAccountPositions] = useState<IBAccountPosition[]>([]);
  const [accountPositionsUpdatedAt, setAccountPositionsUpdatedAt] = useState<string | null>(null);
  const [accountPositionsStale, setAccountPositionsStale] = useState(false);
  const [accountPositionsLoading, setAccountPositionsLoading] = useState(false);
  const [accountPositionsError, setAccountPositionsError] = useState("");
  const [positionSelections, setPositionSelections] = useState<Record<string, boolean>>({});
  const [positionQuantities, setPositionQuantities] = useState<Record<string, string>>({});
  const [positionSessions, setPositionSessions] = useState<Record<string, string>>({});
  const [positionOrderTypes, setPositionOrderTypes] = useState<Record<string, string>>({});
  const [positionLimitPrices, setPositionLimitPrices] = useState<Record<string, string>>({});
  const [positionActionLoading, setPositionActionLoading] = useState(false);
  const [positionActionError, setPositionActionError] = useState("");
  const [positionActionResult, setPositionActionResult] = useState("");
  const [positionActionWarning, setPositionActionWarning] = useState("");
  const [ibContractForm, setIbContractForm] = useState({
    symbols: "SPY",
    use_project_symbols: false,
  });
  const [ibContractLoading, setIbContractLoading] = useState(false);
  const [ibContractResult, setIbContractResult] =
    useState<IBContractRefreshResult | null>(null);
  const [ibContractError, setIbContractError] = useState("");
  const [ibMarketHealthForm, setIbMarketHealthForm] = useState({
    symbols: "SPY",
    use_project_symbols: false,
    min_success_ratio: "1.0",
    fallback_history: true,
    history_duration: "5 D",
    history_bar_size: "1 day",
    history_use_rth: true,
  });
  const [ibMarketHealthLoading, setIbMarketHealthLoading] = useState(false);
  const [ibMarketHealthResult, setIbMarketHealthResult] =
    useState<IBMarketHealthResult | null>(null);
  const [ibMarketHealthError, setIbMarketHealthError] = useState("");
  const [marketHealthUpdatedAt, setMarketHealthUpdatedAt] = useState<string | null>(null);
  const [ibHistoryForm, setIbHistoryForm] = useState({
    symbols: "SPY",
    use_project_symbols: false,
    duration: "30 D",
    bar_size: "1 day",
    use_rth: true,
    store: true,
    min_delay_seconds: "0.2",
  });
  const [ibHistoryJobs, setIbHistoryJobs] = useState<IBHistoryJob[]>([]);
  const [ibHistoryLoading, setIbHistoryLoading] = useState(false);
  const [ibHistoryError, setIbHistoryError] = useState("");
  const [ibHistoryActionLoading, setIbHistoryActionLoading] = useState(false);
  const [ibStreamStatus, setIbStreamStatus] = useState<IBStreamStatus | null>(null);
  const [ibStreamForm, setIbStreamForm] = useState({
    project_id: "",
    decision_snapshot_id: "",
    max_symbols: "",
    market_data_type: "delayed",
  });
  const [ibStreamLoading, setIbStreamLoading] = useState(false);
  const [ibStreamActionLoading, setIbStreamActionLoading] = useState(false);
  const [ibStreamError, setIbStreamError] = useState("");
  const [bridgeStatus, setBridgeStatus] = useState<IBBridgeStatusOut | null>(null);
  const [bridgeStatusLoading, setBridgeStatusLoading] = useState(false);
  const [bridgeStatusError, setBridgeStatusError] = useState("");
  const [marketSnapshot, setMarketSnapshot] = useState<IBMarketSnapshotItem | null>(null);
  const [marketSnapshotSymbol, setMarketSnapshotSymbol] = useState("");
  const [marketSnapshotLoading, setMarketSnapshotLoading] = useState(false);
  const [marketSnapshotError, setMarketSnapshotError] = useState("");
  const [tradeRuns, setTradeRuns] = useState<TradeRun[]>([]);
  const [tradeOrders, setTradeOrders] = useState<TradeOrder[]>([]);
  const [orderCancelLoading, setOrderCancelLoading] = useState<Record<number, boolean>>({});
  const [orderCancelError, setOrderCancelError] = useState("");
  const [orderCancelResult, setOrderCancelResult] = useState("");
  const [ordersPage, setOrdersPage] = useState(1);
  const [ordersPageSize, setOrdersPageSize] = useState(20);
  const [ordersTotal, setOrdersTotal] = useState(0);
  const [tradeActivityUpdatedAt, setTradeActivityUpdatedAt] = useState<string | null>(null);
  const [tradeReceipts, setTradeReceipts] = useState<TradeReceipt[]>([]);
  const [receiptsPage, setReceiptsPage] = useState(1);
  const [receiptsPageSize, setReceiptsPageSize] = useState(20);
  const [receiptsTotal, setReceiptsTotal] = useState(0);
  const [receiptsUpdatedAt, setReceiptsUpdatedAt] = useState<string | null>(null);
  const [receiptsWarnings, setReceiptsWarnings] = useState<string[]>([]);
  const [receiptsLoading, setReceiptsLoading] = useState(false);
  const [receiptsError, setReceiptsError] = useState("");
  const [guardState, setGuardState] = useState<TradeGuardState | null>(null);
  const [tradeSettings, setTradeSettings] = useState<TradeSettings | null>(null);
  const [tradeSettingsError, setTradeSettingsError] = useState("");
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runDetail, setRunDetail] = useState<TradeRunDetail | null>(null);
  const [symbolSummary, setSymbolSummary] = useState<TradeSymbolSummary[]>([]);
  const [symbolSummaryUpdatedAt, setSymbolSummaryUpdatedAt] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<"orders" | "fills" | "receipts">("orders");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [executeForm, setExecuteForm] = useState({
    run_id: "",
    live_confirm_token: "",
  });
  const [executeLoading, setExecuteLoading] = useState(false);
  const [executeError, setExecuteError] = useState("");
  const [executeResult, setExecuteResult] = useState("");
  const [runActionReason, setRunActionReason] = useState("");
  const [runActionLoading, setRunActionLoading] = useState(false);
  const [runActionError, setRunActionError] = useState("");
  const [runActionResult, setRunActionResult] = useState("");
  const [createRunLoading, setCreateRunLoading] = useState(false);
  const [createRunError, setCreateRunError] = useState("");
  const [createRunResult, setCreateRunResult] = useState("");
  const [guardLoading, setGuardLoading] = useState(false);
  const [guardError, setGuardError] = useState("");
  const [tradeError, setTradeError] = useState("");
  const [loading, setLoading] = useState(false);
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [mainTab, setMainTab] = useState<"overview" | "pipeline">("overview");
  const [pipelineRuns, setPipelineRuns] = useState<PipelineRunItem[]>([]);
  const [pipelineRunsLoading, setPipelineRunsLoading] = useState(false);
  const [pipelineRunsError, setPipelineRunsError] = useState("");
  const [pipelineTraceId, setPipelineTraceId] = useState<string | null>(null);
  const [pipelineDetail, setPipelineDetail] = useState<PipelineTraceDetail | null>(null);
  const [pipelineDetailLoading, setPipelineDetailLoading] = useState(false);
  const [pipelineDetailError, setPipelineDetailError] = useState("");
  const [pipelineActionLoading, setPipelineActionLoading] = useState<Record<string, boolean>>(
    {}
  );
  const [pipelineActionError, setPipelineActionError] = useState("");
  const [pipelineActionResult, setPipelineActionResult] = useState("");
  const [pipelineStatusFilter, setPipelineStatusFilter] = useState("");
  const [pipelineTypeFilter, setPipelineTypeFilter] = useState("");
  const [pipelineModeFilter, setPipelineModeFilter] = useState("");
  const [pipelineDateFrom, setPipelineDateFrom] = useState("");
  const [pipelineDateTo, setPipelineDateTo] = useState("");
  const [pipelineKeyword, setPipelineKeyword] = useState("");
  const [pipelineSelectedEvent, setPipelineSelectedEvent] = useState<PipelineEvent | null>(
    null
  );
  const defaultSession = resolveSessionByEasternTime();
  const [refreshMeta, setRefreshMeta] = useState<
    Record<RefreshKey, { intervalMs: number | null; lastAt: string | null; nextAt: string | null }>
  >(() => {
    const now = Date.now();
    const entries: [RefreshKey, { intervalMs: number | null; lastAt: string | null; nextAt: string | null }][] =
      (Object.keys(REFRESH_INTERVALS) as AutoRefreshKey[]).map((key) => {
        const intervalMs = REFRESH_INTERVALS[key];
        const nextAt = new Date(now + intervalMs).toISOString();
        return [key, { intervalMs, lastAt: null, nextAt }];
      });
    MANUAL_REFRESH_KEYS.forEach((key) => {
      entries.push([key, { intervalMs: null, lastAt: null, nextAt: null }]);
    });
    return Object.fromEntries(entries) as Record<
      RefreshKey,
      { intervalMs: number | null; lastAt: string | null; nextAt: string | null }
    >;
  });

  const updateIbSettingsForm = (key: keyof typeof ibSettingsForm, value: string | boolean) => {
    setIbSettingsForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateIbContractForm = (key: keyof typeof ibContractForm, value: any) => {
    setIbContractForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateIbMarketHealthForm = (key: keyof typeof ibMarketHealthForm, value: any) => {
    setIbMarketHealthForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateIbHistoryForm = (key: keyof typeof ibHistoryForm, value: any) => {
    setIbHistoryForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateIbStreamForm = (key: keyof typeof ibStreamForm, value: any) => {
    setIbStreamForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateExecuteForm = (key: keyof typeof executeForm, value: string) => {
    setExecuteForm((prev) => ({ ...prev, [key]: value }));
  };

  const refreshTimersRef = useRef<Record<AutoRefreshKey, number>>({});
  const refreshInFlightRef = useRef<Set<RefreshKey>>(new Set());
  const streamSymbolKey = useMemo(
    () => buildSymbolListKey(ibStreamStatus?.subscribed_symbols),
    [ibStreamStatus?.subscribed_symbols]
  );
  const primaryStreamSymbol = useMemo(() => {
    const [first] = streamSymbolKey.split("|");
    return first || undefined;
  }, [streamSymbolKey]);

  const formatIntervalLabel = useCallback(
    (intervalMs: number | null) => {
      if (!intervalMs) {
        return t("trade.refreshManual");
      }
      if (intervalMs % 60000 === 0) {
        return `${intervalMs / 60000}m`;
      }
      return `${intervalMs / 1000}s`;
    },
    [t]
  );

  const formatNextRefresh = useCallback(
    (
      meta:
        | { intervalMs: number | null; nextAt: string | null; lastAt?: string | null }
        | undefined
    ) => {
      if (!meta) {
        return t("common.none");
      }
      if (!meta.intervalMs) {
        return t("trade.refreshManual");
      }
      if (!autoRefreshEnabled) {
        return t("trade.autoUpdateOff");
      }
      const computedNextAt =
        meta.lastAt && meta.intervalMs
          ? new Date(new Date(meta.lastAt).getTime() + meta.intervalMs).toISOString()
          : meta.nextAt;
      if (!computedNextAt) {
        return t("common.none");
      }
      return formatDateTime(computedNextAt);
    },
    [autoRefreshEnabled, formatDateTime, t]
  );

  const markRefreshed = useCallback(
    (key: RefreshKey) => {
      setRefreshMeta((prev) => {
        const intervalMs =
          prev[key]?.intervalMs ?? (isAutoRefreshKey(key) ? REFRESH_INTERVALS[key] : null);
        const lastAt = new Date().toISOString();
        const nextAt =
          isAutoRefreshKey(key) && autoRefreshEnabled && intervalMs
            ? new Date(Date.now() + intervalMs).toISOString()
            : null;
        return {
          ...prev,
          [key]: {
            intervalMs,
            lastAt,
            nextAt,
          },
        };
      });
    },
    [autoRefreshEnabled]
  );

  const markRefreshDeferred = useCallback((key: RefreshKey, deferUntilMs: number) => {
    setRefreshMeta((prev) => {
      const intervalMs =
        prev[key]?.intervalMs ?? (isAutoRefreshKey(key) ? REFRESH_INTERVALS[key] : null);
      const existingNextAt = prev[key]?.nextAt ? new Date(prev[key].nextAt as string).getTime() : 0;
      const targetMs = Math.max(existingNextAt, Math.max(Date.now(), Number(deferUntilMs) || 0));
      return {
        ...prev,
        [key]: {
          intervalMs,
          lastAt: prev[key]?.lastAt ?? null,
          nextAt: targetMs > 0 ? new Date(targetMs).toISOString() : null,
        },
      };
    });
  }, []);

  const createTradeRun = async () => {
    setCreateRunError("");
    setCreateRunResult("");
    if (!selectedProjectId) {
      setCreateRunError(t("trade.executeBlockedProject"));
      return;
    }
    if (!snapshot?.id) {
      setCreateRunError(t("trade.snapshotMissing"));
      return;
    }
    if (!snapshotReady) {
      const raw = String(snapshot?.status || "").trim();
      const key = raw ? `common.status.${raw}` : "";
      const translated = key ? t(key) : "";
      const normalized =
        translated && !translated.startsWith("common.status.") ? translated : raw || "unknown";
      setCreateRunError(t("trade.snapshotNotReady", { status: normalized }));
      return;
    }
    setCreateRunLoading(true);
    try {
      const mode = (ibSettings?.mode || ibSettingsForm.mode || "paper").toLowerCase();
      const payload = {
        project_id: Number(selectedProjectId),
        decision_snapshot_id: snapshot?.id ?? undefined,
        mode,
        live_confirm_token:
          mode === "live" ? executeForm.live_confirm_token || undefined : undefined,
      };
      const res = await api.post<TradeRun>("/api/trade/runs", payload);
      if (res.data?.id) {
        setExecuteForm((prev) => ({ ...prev, run_id: String(res.data.id) }));
        setSelectedRunId(res.data.id);
      }
      setCreateRunResult(t("trade.createRunSuccess"));
      await loadTradeActivity();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.createRunError");
      setCreateRunError(String(detail));
    } finally {
      setCreateRunLoading(false);
    }
  };

  const loadIbSettings = async () => {
    try {
      const res = await api.get<IBSettings>("/api/brokerage/settings");
      setIbSettings(res.data);
      setIbSettingsForm({
        host: res.data.host || "127.0.0.1",
        port: String(res.data.port ?? 7497),
        client_id: String(res.data.client_id ?? 1),
        account_id: "",
        mode: res.data.mode || "paper",
        market_data_type: res.data.market_data_type || "realtime",
        api_mode: res.data.api_mode || "ib",
        use_regulatory_snapshot: !!res.data.use_regulatory_snapshot,
      });
      setIbSettingsError("");
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.loadError");
      setIbSettingsError(String(detail));
      setIbSettings(null);
    }
  };

  const loadProjects = async () => {
    try {
      const res = await api.get("/api/projects/page", { params: { page: 1, page_size: 200 } });
      const items = (res.data?.items || []) as ProjectSummary[];
      setProjects(items);
      setProjectError("");
      setSelectedProjectId((prev) => {
        if (prev && items.some((item) => String(item.id) === prev)) {
          return prev;
        }
        return items.length ? String(items[0].id) : "";
      });
    } catch (err) {
      setProjects([]);
      setProjectError(t("trade.projectLoadError"));
    }
  };

  const loadLatestSnapshot = async (projectId: string) => {
    if (!projectId) {
      setSnapshot(null);
      setSnapshotError("");
      return;
    }
    setSnapshotLoading(true);
    setSnapshotError("");
    try {
      const res = await api.get<DecisionSnapshotSummary>("/api/decisions/latest", {
        params: { project_id: Number(projectId) },
      });
      setSnapshot(res.data);
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setSnapshot(null);
        setSnapshotError(t("trade.snapshotMissing"));
      } else {
        setSnapshot(null);
        setSnapshotError(t("trade.snapshotLoadError"));
      }
    } finally {
      setSnapshotLoading(false);
    }
  };

  const loadAccountSummary = async (full = false) => {
    if (full) {
      setAccountSummaryFullLoading(true);
      setAccountSummaryFullError("");
    } else {
      setAccountSummaryLoading(true);
      setAccountSummaryError("");
    }
    try {
      const res = await api.get<IBAccountSummary>("/api/brokerage/account/summary", {
        params: {
          mode: ibSettings?.mode || ibSettingsForm.mode || "paper",
          full,
        },
      });
      if (full) {
        setAccountSummaryFull(res.data);
      } else {
        setAccountSummary(res.data);
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.accountSummaryError");
      if (full) {
        setAccountSummaryFullError(String(detail));
      } else {
        setAccountSummaryError(String(detail));
      }
    } finally {
      if (full) {
        setAccountSummaryFullLoading(false);
      } else {
        setAccountSummaryLoading(false);
      }
    }
  };

  const loadAccountPositions = async (forceRefresh = false) => {
    setAccountPositionsLoading(true);
    setAccountPositionsError("");
    try {
      const res = await api.get<IBAccountPositionsOut>("/api/brokerage/account/positions", {
        params: {
          mode: ibSettings?.mode || ibSettingsForm.mode || "paper",
          force_refresh: forceRefresh,
        },
      });
      setAccountPositions(res.data.items || []);
      setAccountPositionsUpdatedAt(res.data.refreshed_at || null);
      setAccountPositionsStale(Boolean(res.data.stale));
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.accountPositionsError");
      setAccountPositionsError(String(detail));
      setAccountPositions([]);
      setAccountPositionsUpdatedAt(null);
      setAccountPositionsStale(false);
    } finally {
      setAccountPositionsLoading(false);
    }
  };

  const updatePositionSelection = (key: string, selected: boolean) => {
    setPositionSelections((prev) => ({ ...prev, [key]: selected }));
  };

  const updatePositionQuantity = (key: string, value: string) => {
    setPositionQuantities((prev) => ({ ...prev, [key]: value }));
  };

  const normalizeTradeSession = (value: string) => {
    const normalized = String(value || "").trim().toLowerCase();
    if (!normalized) {
      return "rth";
    }
    if (["rth", "regular", "regular_hours"].includes(normalized)) {
      return "rth";
    }
    if (["pre", "premarket", "pre_market"].includes(normalized)) {
      return "pre";
    }
    if (["post", "after", "afterhours", "after_hours"].includes(normalized)) {
      return "post";
    }
    if (["night", "overnight"].includes(normalized)) {
      return "night";
    }
    return "rth";
  };

  const normalizeOrderType = (value: string) => {
    const normalized = String(value || "").trim().toUpperCase();
    if (!normalized) {
      return "MKT";
    }
    const cleaned = normalized
      .replace(/\(.*?\)/g, "")
      .replace(/[\s-]+/g, "_")
      .trim();
    if (["MKT", "MARKET", "MARKET_ORDER"].includes(cleaned)) {
      return "MKT";
    }
    if (["LMT", "LIMIT", "LIMIT_ORDER"].includes(cleaned)) {
      return "LMT";
    }
    if (["ADAPTIVE", "ADAPTIVE_LMT", "ADAPTIVELMT", "ADAPTIVE_LIMIT"].includes(cleaned)) {
      return "ADAPTIVE_LMT";
    }
    if (["PEG_MID", "PEGMID", "MIDPOINT", "PEG_MIDPOINT"].includes(cleaned)) {
      return "PEG_MID";
    }
    return cleaned;
  };

  const formatOrderTypeLabel = (value?: string | null) => {
    const normalized = normalizeOrderType(String(value || ""));
    if (normalized === "MKT") {
      return t("trade.orderType.mkt");
    }
    if (normalized === "LMT") {
      return t("trade.orderType.lmt");
    }
    if (normalized === "ADAPTIVE_LMT") {
      return t("trade.orderType.adaptiveLmt");
    }
    if (normalized === "PEG_MID") {
      return t("trade.orderType.pegMid");
    }
    return normalized || t("common.none");
  };

  const isLimitLikeOrderType = (value: string) => {
    const normalized = normalizeOrderType(value);
    return normalized === "LMT" || normalized === "PEG_MID";
  };

  const updatePositionSession = (row: IBAccountPosition, key: string, session: string) => {
    const normalized = normalizeTradeSession(session);
    setPositionSessions((prev) => ({ ...prev, [key]: normalized }));
    if (normalized === "rth") {
      return;
    }
    setPositionOrderTypes((prev) => ({ ...prev, [key]: "LMT" }));
    setPositionLimitPrices((prev) => {
      const existing = prev[key];
      if (existing != null && String(existing).trim() !== "") {
        return prev;
      }
      const fallback = Number(row.market_price ?? null);
      if (!Number.isFinite(fallback) || fallback <= 0) {
        return prev;
      }
      return { ...prev, [key]: String(fallback) };
    });
  };

  const updatePositionOrderType = (row: IBAccountPosition, key: string, orderType: string) => {
    const normalized = normalizeOrderType(orderType);
    setPositionOrderTypes((prev) => ({ ...prev, [key]: normalized }));
    if (!isLimitLikeOrderType(normalized)) {
      return;
    }
    setPositionLimitPrices((prev) => {
      const existing = prev[key];
      if (existing != null && String(existing).trim() !== "") {
        return prev;
      }
      const fallback = Number(row.market_price ?? null);
      if (!Number.isFinite(fallback) || fallback <= 0) {
        return prev;
      }
      return { ...prev, [key]: String(fallback) };
    });
  };

  const updatePositionLimitPrice = (key: string, value: string) => {
    setPositionLimitPrices((prev) => ({ ...prev, [key]: value }));
  };

  const resolvePositionLimitPrice = (row: IBAccountPosition, key: string) => {
    const raw = positionLimitPrices[key];
    if (raw != null && raw !== "") {
      const parsed = Number(raw);
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed;
      }
      return null;
    }
    const fallback = Number(row.market_price ?? null);
    return Number.isFinite(fallback) && fallback > 0 ? fallback : null;
  };

  const formatTradeSessionLabel = (session: string) => {
    const normalized = normalizeTradeSession(session);
    if (normalized === "pre") {
      return t("trade.manualSession.pre");
    }
    if (normalized === "post") {
      return t("trade.manualSession.post");
    }
    if (normalized === "night") {
      return t("trade.manualSession.night");
    }
    return t("trade.manualSession.rth");
  };

  const toggleSelectAllPositions = () => {
    if (allPositionsSelected) {
      setPositionSelections({});
      return;
    }
    const next: Record<string, boolean> = {};
    accountPositions.forEach((row) => {
      next[buildPositionKey(row)] = true;
    });
    setPositionSelections(next);
  };

  const resolvePositionQuantity = (row: IBAccountPosition, key: string) => {
    const raw = positionQuantities[key];
    if (raw != null && raw !== "") {
      const parsed = Number(raw);
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed;
      }
      return null;
    }
    const fallback = Math.abs(row.position ?? 0);
    return fallback > 0 ? fallback : 1;
  };

  const submitPositionOrders = async (orders: Array<Record<string, any>>) => {
    if (!orders.length) {
      setPositionActionError(t("trade.positionActionErrorNoSelection"));
      return;
    }
    const projectId = Number(selectedProjectId) || latestTradeRun?.project_id || 0;
    if (!projectId) {
      setPositionActionError(t("trade.directOrderProjectRequired"));
      return;
    }
    const mode = (ibSettings?.mode || ibSettingsForm.mode || "paper").toLowerCase();
    const basePayload: Record<string, any> = { project_id: projectId, mode };
    if (mode === "live" && executeForm.live_confirm_token) {
      basePayload.live_confirm_token = executeForm.live_confirm_token;
    }
    setPositionActionLoading(true);
    setPositionActionError("");
    setPositionActionResult("");
    setPositionActionWarning("");
    try {
      const responses = await Promise.all(
        orders.map((payload) =>
          api.post<TradeDirectOrderOut>("/api/trade/orders/direct", {
            ...basePayload,
            ...payload,
          })
        )
      );
      const warnings = new Set<string>();
      responses.forEach((res) => {
        const status = res.data?.bridge_status;
        if (status?.stale) {
          warnings.add(t("trade.bridgeOrderWarningStale"));
        }
        const refreshResult = status?.last_refresh_result || res.data?.refresh_result;
        if (refreshResult && refreshResult !== "success") {
          warnings.add(
            t("trade.bridgeOrderWarningRefresh", {
              result: formatBridgeRefreshResult(t, refreshResult),
              reason: formatBridgeRefreshReason(t, status?.last_refresh_reason),
            })
          );
        }
      });
      if (warnings.size) {
        setPositionActionWarning(Array.from(warnings).join(" "));
      }
      setPositionActionResult(t("trade.positionActionResult", { count: orders.length }));
      await Promise.all([loadTradeActivity(), loadAccountPositions(true)]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.tradeError");
      setPositionActionError(String(detail));
    } finally {
      setPositionActionLoading(false);
    }
  };

  const handlePositionOrder = async (
    row: IBAccountPosition,
    side: "BUY" | "SELL",
    index: number
  ) => {
    const key = buildPositionKey(row);
    const quantity = resolvePositionQuantity(row, key);
    if (!quantity) {
      setPositionActionError(t("trade.positionActionErrorInvalidQty"));
      return;
    }
    const session = normalizeTradeSession(positionSessions[key] ?? defaultSession);
    const isExtended = session !== "rth";
    const rawOrderType = normalizeOrderType(
      positionOrderTypes[key] ?? resolveDefaultOrderTypeBySession(session)
    );
    const orderType = isExtended ? "LMT" : rawOrderType;
    const needsLimit = isLimitLikeOrderType(orderType);
    const limitPrice = needsLimit ? resolvePositionLimitPrice(row, key) : null;
    if (needsLimit && !limitPrice) {
      setPositionActionError(t("trade.positionActionErrorInvalidLimitPrice"));
      return;
    }
    const confirmed = window.confirm(
      needsLimit
        ? t("trade.positionOrderConfirmLimit", {
            side,
            symbol: row.symbol,
            qty: formatNumber(quantity ?? null),
            session: formatTradeSessionLabel(session),
            price: formatNumber(limitPrice, 4),
          })
        : t("trade.positionOrderConfirm", {
            side,
            symbol: row.symbol,
            qty: formatNumber(quantity ?? null),
          })
    );
    if (!confirmed) {
      return;
    }
    const payload = {
      client_order_id: buildManualOrderTag(index),
      symbol: row.symbol,
      side,
      quantity,
      order_type: orderType,
      limit_price: needsLimit ? limitPrice : undefined,
      params: {
        account: row.account || undefined,
        currency: row.currency || undefined,
        source: "manual",
        project_id: selectedProjectId ? Number(selectedProjectId) : undefined,
        mode: ibSettings?.mode || ibSettingsForm.mode || "paper",
        session,
        allow_outside_rth: isExtended,
      },
    };
    await submitPositionOrders([payload]);
  };

  const handleClosePosition = async (row: IBAccountPosition, index: number) => {
    const key = buildPositionKey(row);
    const qtyValue = Math.abs(row.position ?? 0);
    if (!qtyValue) {
      setPositionActionError(t("trade.positionActionErrorNoSelection"));
      return;
    }
    const side: "BUY" | "SELL" = (row.position ?? 0) >= 0 ? "SELL" : "BUY";
    const session = normalizeTradeSession(positionSessions[key] ?? defaultSession);
    const isExtended = session !== "rth";
    const rawOrderType = normalizeOrderType(
      positionOrderTypes[key] ?? resolveDefaultOrderTypeBySession(session)
    );
    const orderType = isExtended ? "LMT" : rawOrderType;
    const needsLimit = isLimitLikeOrderType(orderType);
    const limitPrice = needsLimit ? resolvePositionLimitPrice(row, key) : null;
    if (needsLimit && !limitPrice) {
      setPositionActionError(t("trade.positionActionErrorInvalidLimitPrice"));
      return;
    }
    const confirmed = window.confirm(
      needsLimit
        ? t("trade.positionOrderConfirmLimit", {
            side,
            symbol: row.symbol,
            qty: formatNumber(qtyValue ?? null),
            session: formatTradeSessionLabel(session),
            price: formatNumber(limitPrice, 4),
          })
        : t("trade.positionOrderConfirm", {
            side,
            symbol: row.symbol,
            qty: formatNumber(qtyValue ?? null),
          })
    );
    if (!confirmed) {
      return;
    }
    const payload = {
      client_order_id: buildManualOrderTag(index),
      symbol: row.symbol,
      side,
      quantity: qtyValue,
      order_type: orderType,
      limit_price: needsLimit ? limitPrice : undefined,
      params: {
        account: row.account || undefined,
        currency: row.currency || undefined,
        source: "manual",
        project_id: selectedProjectId ? Number(selectedProjectId) : undefined,
        mode: ibSettings?.mode || ibSettingsForm.mode || "paper",
        session,
        allow_outside_rth: isExtended,
      },
    };
    await submitPositionOrders([payload]);
  };

  const handleClosePositions = async (rows: IBAccountPosition[], skipConfirm = false) => {
    const positions = rows.filter((row) => Math.abs(row.position ?? 0) > 0);
    if (!positions.length) {
      setPositionActionError(t("trade.positionActionErrorNoSelection"));
      return;
    }
    if (!skipConfirm) {
      const confirmed = window.confirm(
        t("trade.positionBatchCloseConfirm", { count: positions.length })
      );
      if (!confirmed) {
        return;
      }
    }
    const orders: Array<Record<string, any>> = [];
    for (const [idx, row] of positions.entries()) {
      const key = buildPositionKey(row);
      const session = normalizeTradeSession(positionSessions[key] ?? defaultSession);
      const isExtended = session !== "rth";
      const rawOrderType = normalizeOrderType(
        positionOrderTypes[key] ?? resolveDefaultOrderTypeBySession(session)
      );
      const orderType = isExtended ? "LMT" : rawOrderType;
      const needsLimit = isLimitLikeOrderType(orderType);
      const limitPrice = needsLimit ? resolvePositionLimitPrice(row, key) : null;
      if (needsLimit && !limitPrice) {
        setPositionActionError(t("trade.positionActionErrorInvalidLimitPrice"));
        return;
      }
      orders.push({
        client_order_id: buildManualOrderTag(idx),
        symbol: row.symbol,
        side: row.position >= 0 ? "SELL" : "BUY",
        quantity: Math.abs(row.position ?? 0),
        order_type: orderType,
        limit_price: needsLimit ? limitPrice : undefined,
        params: {
          account: row.account || undefined,
          currency: row.currency || undefined,
          source: "manual",
          project_id: selectedProjectId ? Number(selectedProjectId) : undefined,
          mode: ibSettings?.mode || ibSettingsForm.mode || "paper",
          session,
          allow_outside_rth: isExtended,
        },
      });
    }
    await submitPositionOrders(orders);
  };

  const handleLiquidateAll = async () => {
    if (!accountPositions.length) {
      setPositionActionError(t("trade.positionActionErrorNoSelection"));
      return;
    }
    const confirmed = window.confirm(
      t("trade.positionLiquidateAllConfirm", { count: accountPositions.length })
    );
    if (!confirmed) {
      return;
    }
    await handleClosePositions(accountPositions, true);
  };

  const loadIbState = async (silent = false) => {
    if (!silent) {
      setIbStateLoading(true);
      setIbStateError("");
    }
    try {
      const res = await api.get<IBConnectionState>("/api/brokerage/state");
      setIbState(res.data);
      if (!silent) {
        setIbStateResult("");
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.stateLoadError");
      if (!silent) {
        setIbStateError(String(detail));
      }
    } finally {
      if (!silent) {
        setIbStateLoading(false);
      }
    }
  };

  const probeIbState = async () => {
    setIbStateLoading(true);
    setIbStateError("");
    setIbStateResult("");
    try {
      const res = await api.post<IBConnectionState>("/api/brokerage/state/probe");
      setIbState(res.data);
      setIbStateResult(t("data.ib.probeOk"));
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.probeError");
      setIbStateError(String(detail));
    } finally {
      setIbStateLoading(false);
    }
  };

  const saveIbSettings = async () => {
    setIbSettingsSaving(true);
    setIbSettingsResult("");
    setIbSettingsError("");
    try {
      const payload = {
        host: ibSettingsForm.host,
        port: Number.parseInt(ibSettingsForm.port, 10) || 0,
        client_id: Number.parseInt(ibSettingsForm.client_id, 10) || 0,
        account_id: ibSettingsForm.account_id || undefined,
        mode: ibSettingsForm.mode,
        market_data_type: ibSettingsForm.market_data_type,
        api_mode: ibSettingsForm.api_mode,
        use_regulatory_snapshot: ibSettingsForm.use_regulatory_snapshot,
      };
      const res = await api.post<IBSettings>("/api/brokerage/settings", payload);
      setIbSettings(res.data);
      setIbSettingsResult(t("data.ib.saved"));
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.saveError");
      setIbSettingsError(String(detail));
    } finally {
      setIbSettingsSaving(false);
    }
  };

  const refreshIbContracts = async () => {
    setIbContractLoading(true);
    setIbContractError("");
    setIbContractResult(null);
    try {
      const symbols = normalizeSymbols(ibContractForm.symbols);
      const payload = {
        symbols: symbols.length ? symbols : undefined,
        use_project_symbols: ibContractForm.use_project_symbols,
      };
      const res = await api.post<IBContractRefreshResult>("/api/brokerage/contracts/refresh", payload);
      setIbContractResult(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.contractsError");
      setIbContractError(String(detail));
    } finally {
      markRefreshed("contracts");
      setIbContractLoading(false);
    }
  };

  const checkIbMarketHealth = async () => {
    setIbMarketHealthLoading(true);
    setIbMarketHealthError("");
    setIbMarketHealthResult(null);
    try {
      const symbols = normalizeSymbols(ibMarketHealthForm.symbols);
      const payload = {
        symbols: symbols.length ? symbols : undefined,
        use_project_symbols: ibMarketHealthForm.use_project_symbols,
        min_success_ratio: Number(ibMarketHealthForm.min_success_ratio) || 1.0,
        fallback_history: ibMarketHealthForm.fallback_history,
        history_duration: ibMarketHealthForm.history_duration,
        history_bar_size: ibMarketHealthForm.history_bar_size,
        history_use_rth: ibMarketHealthForm.history_use_rth,
      };
      const res = await api.post<IBMarketHealthResult>("/api/brokerage/market/health", payload);
      setIbMarketHealthResult(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.healthError");
      setIbMarketHealthError(String(detail));
    } finally {
      setMarketHealthUpdatedAt(new Date().toISOString());
      markRefreshed("health");
      setIbMarketHealthLoading(false);
    }
  };

  const loadIbHistoryJobs = async () => {
    setIbHistoryLoading(true);
    try {
      const res = await api.get<IBHistoryJob[]>("/api/brokerage/history-jobs", {
        params: { limit: 10, offset: 0 },
      });
      setIbHistoryJobs(res.data || []);
      setIbHistoryError("");
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.historyLoadError");
      setIbHistoryError(String(detail));
    } finally {
      setIbHistoryLoading(false);
    }
  };

  const createIbHistoryJob = async () => {
    setIbHistoryActionLoading(true);
    setIbHistoryError("");
    try {
      const symbols = normalizeSymbols(ibHistoryForm.symbols);
      const payload = {
        symbols: symbols.length ? symbols : undefined,
        use_project_symbols: ibHistoryForm.use_project_symbols,
        duration: ibHistoryForm.duration,
        bar_size: ibHistoryForm.bar_size,
        use_rth: ibHistoryForm.use_rth,
        store: ibHistoryForm.store,
        min_delay_seconds: Number(ibHistoryForm.min_delay_seconds) || 0,
      };
      await api.post("/api/brokerage/history-jobs", payload);
      await loadIbHistoryJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.historyStartError");
      setIbHistoryError(String(detail));
    } finally {
      setIbHistoryActionLoading(false);
    }
  };

  const cancelIbHistoryJob = async (jobId: number) => {
    setIbHistoryActionLoading(true);
    setIbHistoryError("");
    try {
      await api.post(`/api/brokerage/history-jobs/${jobId}/cancel`);
      await loadIbHistoryJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.historyCancelError");
      setIbHistoryError(String(detail));
    } finally {
      setIbHistoryActionLoading(false);
    }
  };

  const loadIbStreamStatus = async (silent = false) => {
    if (!silent) {
      setIbStreamLoading(true);
      setIbStreamError("");
    }
    try {
      const res = await api.get<IBStreamStatus>("/api/brokerage/stream/status");
      setIbStreamStatus(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.streamLoadError");
      setIbStreamError(String(detail));
      setIbStreamStatus(null);
    } finally {
      if (!silent) {
        setIbStreamLoading(false);
      }
    }
  };

  const loadBridgeStatus = async (silent = false) => {
    if (!silent) {
      setBridgeStatusLoading(true);
      setBridgeStatusError("");
    }
    try {
      const res = await api.get<IBBridgeStatusOut>("/api/brokerage/bridge/status");
      setBridgeStatus(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.bridgeStatusLoadError");
      setBridgeStatusError(String(detail));
      setBridgeStatus(null);
    } finally {
      if (!silent) {
        setBridgeStatusLoading(false);
      }
    }
  };

  const refreshBridgeStatus = async (reason: string, force: boolean) => {
    setBridgeStatusError("");
    try {
      const mode = (ibSettings?.mode || ibSettingsForm.mode || "paper").toLowerCase();
      const res = await api.post<IBBridgeRefreshOut>(
        "/api/brokerage/bridge/refresh",
        null,
        {
          params: { mode, reason, force },
        }
      );
      setBridgeStatus(res.data?.bridge_status || null);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.bridgeRefreshError");
      setBridgeStatusError(String(detail));
    }
  };

  const loadMarketSnapshot = async (symbol?: string) => {
    const target =
      symbol || ibStreamStatus?.subscribed_symbols?.[0] || marketSnapshotSymbol || "";
    if (!target) {
      setMarketSnapshot(null);
      setMarketSnapshotSymbol("");
      return;
    }
    setMarketSnapshotLoading(true);
    setMarketSnapshotError("");
    try {
      const res = await api.get<IBStreamSnapshotOut>("/api/brokerage/stream/snapshot", {
        params: { symbol: target },
      });
      const item = res.data ? { symbol: res.data.symbol, data: res.data.data, error: res.data.error } : null;
      setMarketSnapshotSymbol(res.data?.symbol || target);
      setMarketSnapshot(item);
      if (item?.error) {
        setMarketSnapshotError(String(item.error));
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.snapshotError");
      setMarketSnapshotError(String(detail));
      setMarketSnapshot(null);
    } finally {
      setMarketSnapshotLoading(false);
    }
  };

  const startIbStream = async () => {
    setIbStreamActionLoading(true);
    setIbStreamError("");
    const projectId = Number(ibStreamForm.project_id);
    if (!projectId) {
      setIbStreamError(t("data.ib.streamProjectRequired"));
      setIbStreamActionLoading(false);
      return;
    }
    const decisionSnapshotId = Number(ibStreamForm.decision_snapshot_id);
    const maxSymbols = Number(ibStreamForm.max_symbols);
    const payload = {
      project_id: projectId,
      decision_snapshot_id: Number.isNaN(decisionSnapshotId) ? undefined : decisionSnapshotId,
      max_symbols: Number.isNaN(maxSymbols) ? undefined : maxSymbols,
      market_data_type: ibStreamForm.market_data_type || undefined,
    };
    try {
      const res = await api.post<IBStreamStatus>("/api/brokerage/stream/start", payload);
      setIbStreamStatus(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.streamStartError");
      setIbStreamError(String(detail));
    } finally {
      setIbStreamActionLoading(false);
    }
  };

  const stopIbStream = async () => {
    setIbStreamActionLoading(true);
    setIbStreamError("");
    try {
      const res = await api.post<IBStreamStatus>("/api/brokerage/stream/stop");
      setIbStreamStatus(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.ib.streamStopError");
      setIbStreamError(String(detail));
    } finally {
      setIbStreamActionLoading(false);
    }
  };

  const loadTradeGuard = async (projectId: number, mode: string) => {
    setGuardLoading(true);
    setGuardError("");
    try {
      const res = await api.get<TradeGuardState>("/api/trade/guard", {
        params: { project_id: projectId, mode },
      });
      setGuardState(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.guardError");
      setGuardError(String(detail));
      setGuardState(null);
    } finally {
      setGuardLoading(false);
    }
  };

  const loadTradeActivity = async (
    page: number = ordersPage,
    pageSize: number = ordersPageSize
  ) => {
    setTradeError("");
    setGuardError("");
    let latestRun: TradeRun | null = null;
    const [runsResult, ordersResult] = await Promise.allSettled([
      apiLong.get<TradeRun[]>("/api/trade/runs", { params: { limit: 5, offset: 0 } }),
      apiLong.get<TradeOrder[]>("/api/trade/orders", {
        params: { limit: pageSize, offset: (page - 1) * pageSize },
      }),
    ]);

    if (runsResult.status === "fulfilled") {
      const runs = runsResult.value.data || [];
      setTradeRuns(runs);
      latestRun = runs[0] || null;
    } else {
      // Keep existing state so transient backend issues don't wipe the UI.
      setTradeError(t("trade.tradeError"));
    }

    if (ordersResult.status === "fulfilled") {
      setTradeOrders(ordersResult.value.data || []);
      const totalHeader = Number(ordersResult.value.headers?.["x-total-count"]);
      setOrdersTotal(Number.isFinite(totalHeader) ? totalHeader : 0);
    } else {
      setTradeError(t("trade.tradeError"));
      // Keep previous orders on failure.
    }

    try {
      if (latestRun?.project_id) {
        await loadTradeGuard(latestRun.project_id, latestRun.mode || "paper");
      } else {
        setGuardState(null);
      }
    } catch {
      // loadTradeGuard already sets guardError; avoid throwing from here.
    } finally {
      setTradeActivityUpdatedAt(new Date().toISOString());
    }
  };

  const cancelTradeOrder = async (order: TradeOrder) => {
      const orderId = Number(order?.id || 0);
      if (!Number.isFinite(orderId) || orderId <= 0) {
        return;
      }
      const normalizedStatus = String(order?.status || "").toUpperCase();
      if (!normalizedStatus || ["FILLED", "CANCELED", "CANCELLED", "REJECTED", "SKIPPED"].includes(normalizedStatus)) {
        return;
      }

      const symbol = order?.symbol || t("common.none");
      const side = formatSide(order?.side);
      const qty = formatNumber(order?.quantity ?? null, 4);
      const type = formatOrderTypeLabel(order?.order_type);
      const limit =
        order?.limit_price != null ? ` @ ${formatNumber(order.limit_price, 4)}` : "";
      const confirmText = t("trade.orderCancelConfirm", {
        id: orderId,
        symbol,
        side,
        qty,
        type: `${type}${limit}`,
      });
      if (!window.confirm(confirmText)) {
        return;
      }

      setOrderCancelError("");
      setOrderCancelResult("");
      setOrderCancelLoading((prev) => ({ ...prev, [orderId]: true }));
      try {
        const res = await api.post<TradeOrder>(`/api/trade/orders/${orderId}/cancel`);
        const updated = res.data;
        setTradeOrders((prev) =>
          prev.map((row) => (row.id === orderId ? { ...row, ...updated } : row))
        );
        setOrderCancelResult(t("trade.orderCancelSuccess", { id: orderId }));
      } catch (err: any) {
        const detail = err?.response?.data?.detail || t("trade.orderCancelError");
        setOrderCancelError(String(detail));
      } finally {
        setOrderCancelLoading((prev) => {
          const next = { ...prev };
          delete next[orderId];
          return next;
        });
        loadTradeActivity(ordersPage, ordersPageSize);
      }
  };

  const loadTradeReceipts = async (
    page: number = receiptsPage,
    pageSize: number = receiptsPageSize
  ) => {
    setReceiptsLoading(true);
    setReceiptsError("");
    setReceiptsWarnings([]);
    try {
      const res = await api.get<TradeReceiptPage>("/api/trade/receipts", {
        params: { limit: pageSize, offset: (page - 1) * pageSize },
      });
      setTradeReceipts(res.data?.items || []);
      setReceiptsWarnings(res.data?.warnings || []);
      const totalHeader = Number(res.headers?.["x-total-count"]);
      const total = Number.isFinite(totalHeader) ? totalHeader : Number(res.data?.total || 0);
      setReceiptsTotal(total);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.receiptsLoadError");
      setReceiptsError(String(detail));
      setTradeReceipts([]);
      setReceiptsTotal(0);
      setReceiptsWarnings([]);
    } finally {
      setReceiptsUpdatedAt(new Date().toISOString());
      setReceiptsLoading(false);
    }
  };

  const loadTradeSettings = async () => {
    try {
      const res = await api.get<TradeSettings>("/api/trade/settings");
      setTradeSettings(res.data);
      setTradeSettingsError("");
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.tradeSettingsError");
      setTradeSettingsError(String(detail));
      setTradeSettings(null);
    }
  };

  const resolvePipelineDate = (value: string, isEnd: boolean) => {
    if (!value) {
      return null;
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return null;
    }
    if (isEnd) {
      date.setHours(23, 59, 59, 999);
    } else {
      date.setHours(0, 0, 0, 0);
    }
    return date.toISOString();
  };

  const loadPipelineRuns = async () => {
    if (!selectedProjectId) {
      setPipelineRuns([]);
      setPipelineTraceId(null);
      setPipelineDetail(null);
      setPipelineSelectedEvent(null);
      return;
    }
    setPipelineRunsLoading(true);
    setPipelineRunsError("");
    try {
      const params: Record<string, any> = {
        project_id: Number(selectedProjectId),
      };
      if (pipelineStatusFilter) {
        params.status = pipelineStatusFilter;
      }
      if (pipelineTypeFilter) {
        params.type = pipelineTypeFilter;
      }
      if (pipelineModeFilter) {
        params.mode = pipelineModeFilter;
      }
      if (pipelineKeyword.trim()) {
        params.keyword = pipelineKeyword.trim();
      }
      const from = resolvePipelineDate(pipelineDateFrom, false);
      const to = resolvePipelineDate(pipelineDateTo, true);
      if (from) {
        params.started_from = from;
      }
      if (to) {
        params.started_to = to;
      }
      const res = await api.get<PipelineRunItem[]>("/api/pipeline/runs", {
        params,
      });
      const items = res.data || [];
      setPipelineRuns(items);
      setPipelineDetail(null);
      setPipelineSelectedEvent(null);
      const existing =
        pipelineTraceId && items.some((item) => item.trace_id === pipelineTraceId)
          ? pipelineTraceId
          : null;
      setPipelineTraceId(existing || items[0]?.trace_id || null);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.pipeline.errors.loadRuns");
      setPipelineRunsError(String(detail));
      setPipelineRuns([]);
      setPipelineTraceId(null);
      setPipelineDetail(null);
    } finally {
      setPipelineRunsLoading(false);
    }
  };

  const loadPipelineDetail = async (traceId: string) => {
    setPipelineDetailLoading(true);
    setPipelineDetailError("");
    try {
      const res = await api.get<PipelineTraceDetail>(`/api/pipeline/runs/${traceId}`);
      setPipelineDetail(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.pipeline.errors.loadDetail");
      setPipelineDetailError(String(detail));
      setPipelineDetail(null);
    } finally {
      setPipelineDetailLoading(false);
    }
  };

  const runPipelineAction = async (
    actionKey: string,
    action: () => Promise<void>,
    successMessage: string
  ) => {
    setPipelineActionError("");
    setPipelineActionResult("");
    setPipelineActionLoading((prev) => ({ ...prev, [actionKey]: true }));
    try {
      await action();
      setPipelineActionResult(successMessage);
      await loadPipelineRuns();
      if (pipelineTraceId) {
        await loadPipelineDetail(pipelineTraceId);
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.pipeline.errors.actionFailed");
      setPipelineActionError(String(detail));
    } finally {
      setPipelineActionLoading((prev) => {
        const next = { ...prev };
        delete next[actionKey];
        return next;
      });
    }
  };

  const retryPipelineStep = async (stepId: number) => {
    if (!pipelinePretradeRunId) {
      return;
    }
    await runPipelineAction(
      `pretrade-step-${stepId}`,
      async () => {
        await api.post(`/api/pretrade/runs/${pipelinePretradeRunId}/steps/${stepId}/retry`);
      },
      t("trade.pipeline.actions.retryStepSuccess")
    );
  };

  const resumePipelineRun = async () => {
    if (!pipelinePretradeRunId) {
      return;
    }
    await runPipelineAction(
      `pretrade-run-${pipelinePretradeRunId}`,
      async () => {
        await api.post(`/api/pretrade/runs/${pipelinePretradeRunId}/resume`);
      },
      t("trade.pipeline.actions.resumeSuccess")
    );
  };

  const executePipelineTrade = async (runId: number) => {
    await runPipelineAction(
      `trade-run-${runId}`,
      async () => {
        await api.post(`/api/trade/runs/${runId}/execute`, {
          dry_run: false,
          force: false,
          live_confirm_token: executeForm.live_confirm_token || undefined,
        });
      },
      t("trade.pipeline.actions.executeSuccess")
    );
  };

  const handleOrdersPageChange = (page: number) => {
    setOrdersPage(page);
    loadTradeActivity(page, ordersPageSize);
  };

  const handleOrdersPageSizeChange = (size: number) => {
    setOrdersPageSize(size);
    setOrdersPage(1);
    loadTradeActivity(1, size);
  };

  const handleReceiptsPageChange = (page: number) => {
    setReceiptsPage(page);
    loadTradeReceipts(page, receiptsPageSize);
  };

  const handleReceiptsPageSizeChange = (size: number) => {
    setReceiptsPageSize(size);
    setReceiptsPage(1);
    loadTradeReceipts(1, size);
  };

  const loadTradeRunData = async (runId: number) => {
    setDetailLoading(true);
    setDetailError("");
    try {
      const [detailRes, symbolsRes] = await Promise.all([
        api.get<TradeRunDetail>(`/api/trade/runs/${runId}/detail`, {
          params: { limit: 50, offset: 0 },
        }),
        api.get<TradeSymbolSummaryPage>(`/api/trade/runs/${runId}/symbols`),
      ]);
      setRunDetail(detailRes.data);
      setSymbolSummary(symbolsRes.data?.items || []);
      setSymbolSummaryUpdatedAt(
        symbolsRes.data?.last_update_at || detailRes.data?.last_update_at || null
      );
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.detailError");
      setDetailError(String(detail));
      setRunDetail(null);
      setSymbolSummary([]);
      setSymbolSummaryUpdatedAt(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const executeTradeRun = async () => {
    setExecuteLoading(true);
    setExecuteError("");
    setExecuteResult("");
    const runId = Number.parseInt(executeForm.run_id, 10);
    if (!runId) {
      setExecuteError(t("trade.executeRunRequired"));
      setExecuteLoading(false);
      return;
    }
    try {
      const payload = {
        dry_run: false,
        force: false,
        live_confirm_token: executeForm.live_confirm_token || undefined,
      };
      // Execution may take longer than 10s (IB checks, order builds, Lean submit), so use long-timeout client.
      const res = await apiLong.post<TradeRunExecuteOut>(
        `/api/trade/runs/${runId}/execute`,
        payload
      );
      setExecuteResult(t("trade.executeSuccess"));
      setTradeError("");
      if (res.data?.status) {
        await loadTradeActivity();
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.executeError");
      setExecuteError(String(detail));
    } finally {
      setExecuteLoading(false);
    }
  };

  const handleRunAction = async (action: "sync" | "resume" | "terminate") => {
    setRunActionLoading(true);
    setRunActionError("");
    setRunActionResult("");
    const runId = activeTradeRun?.id;
    if (!runId) {
      setRunActionError(t("trade.runActionMissing"));
      setRunActionLoading(false);
      return;
    }
    try {
      const reason = runActionReason.trim();
      const payload = reason ? { reason } : undefined;
      await api.post(`/api/trade/runs/${runId}/${action}`, payload);
      setRunActionResult(t("trade.runActionSuccess", { action: t(`trade.runAction.${action}`) }));
      setRunActionReason("");
      await Promise.all([loadTradeActivity(), loadTradeRunData(runId)]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.runActionError");
      setRunActionError(String(detail));
    } finally {
      setRunActionLoading(false);
    }
  };

  const refreshHandlers = useMemo<Partial<Record<RefreshKey, () => Promise<void>>>>(
    () => ({
      connection: async () => {
        await Promise.all([loadIbSettings(), loadIbState(true), loadIbStreamStatus(true)]);
      },
      bridge: async () => {
        await loadBridgeStatus(true);
      },
      project: async () => {
        await loadProjects();
        if (selectedProjectId) {
          await loadLatestSnapshot(selectedProjectId);
        }
      },
      account: async () => {
        await Promise.all([loadAccountSummary(false), loadAccountSummary(true)]);
      },
      positions: async () => {
        await loadAccountPositions();
      },
      monitor: async () => {
        await Promise.all([
          loadTradeActivity(ordersPage, ordersPageSize),
          loadTradeReceipts(receiptsPage, receiptsPageSize),
          loadIbHistoryJobs(),
        ]);
      },
      snapshot: async () => {
        await loadMarketSnapshot(primaryStreamSymbol);
      },
      execution: async () => {
        await loadTradeSettings();
        if (selectedRunId) {
          await loadTradeRunData(selectedRunId);
        }
      },
      health: async () => {
        await checkIbMarketHealth();
      },
      contracts: async () => {
        await refreshIbContracts();
      },
    }),
    [
      ordersPage,
      ordersPageSize,
      primaryStreamSymbol,
      receiptsPage,
      receiptsPageSize,
      selectedProjectId,
      selectedRunId,
    ]
  );

  const triggerRefresh = useCallback(
    async (key: RefreshKey, options?: { source?: "auto" | "manual" }) => {
      const handler = refreshHandlers[key];
      if (!handler) {
        return;
      }
      const source = options?.source || "manual";
      if (source === "auto") {
        const deferUntil = getBackendBackoffUntilMs();
        if (deferUntil > Date.now()) {
          markRefreshDeferred(key, deferUntil);
          return;
        }
      }
      if (refreshInFlightRef.current.has(key)) {
        return;
      }
      refreshInFlightRef.current.add(key);
      try {
        await handler();
      } finally {
        refreshInFlightRef.current.delete(key);
        markRefreshed(key);
      }
    },
    [markRefreshed, markRefreshDeferred, refreshHandlers]
  );

  const refreshAll = async (forceBridge: boolean = false) => {
    setLoading(true);
    try {
      await refreshAllWithBridgeForce({
        refreshHandlers,
        triggerRefresh,
        forceBridge: forceBridge ? async () => refreshBridgeStatus("manual", true) : undefined,
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshAll(false);
  }, []);

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    loadLatestSnapshot(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    setSelectedRunId(null);
    setExecuteForm((prev) => ({ ...prev, run_id: "" }));
  }, [selectedProjectId]);

  useEffect(() => {
    if (!autoRefreshEnabled) {
      return undefined;
    }
    setRefreshMeta((prev) => {
      const now = Date.now();
      const nextMeta: typeof prev = { ...prev };
      (Object.keys(REFRESH_INTERVALS) as AutoRefreshKey[]).forEach((key) => {
        const intervalMs = REFRESH_INTERVALS[key];
        if (!intervalMs || intervalMs <= 0) {
          return;
        }
        nextMeta[key] = {
          ...nextMeta[key],
          intervalMs,
          nextAt: new Date(now + intervalMs).toISOString(),
        };
      });
      return nextMeta;
    });
    return undefined;
  }, [autoRefreshEnabled]);

  useEffect(() => {
    Object.values(refreshTimersRef.current).forEach((timer) => {
      window.clearInterval(timer);
    });
    refreshTimersRef.current = {};
    if (!autoRefreshEnabled) {
      return undefined;
    }
    (Object.keys(REFRESH_INTERVALS) as AutoRefreshKey[]).forEach((key) => {
      const intervalMs = REFRESH_INTERVALS[key];
      if (!intervalMs || intervalMs <= 0) {
        return;
      }
      const timer = window.setInterval(() => {
        triggerRefresh(key, { source: "auto" });
      }, intervalMs);
      refreshTimersRef.current[key] = timer;
    });
    return () => {
      Object.values(refreshTimersRef.current).forEach((timer) => {
        window.clearInterval(timer);
      });
      refreshTimersRef.current = {};
    };
  }, [autoRefreshEnabled, triggerRefresh]);

  useEffect(() => {
    setPositionSelections((prev) => {
      const next: Record<string, boolean> = {};
      accountPositions.forEach((row) => {
        const key = buildPositionKey(row);
        if (prev[key]) {
          next[key] = true;
        }
      });
      return next;
    });
    setPositionQuantities((prev) => {
      const next: Record<string, string> = {};
      accountPositions.forEach((row) => {
        const key = buildPositionKey(row);
        if (prev[key] != null) {
          next[key] = prev[key];
        }
      });
      return next;
    });
    setPositionSessions((prev) => {
      const next: Record<string, string> = {};
      accountPositions.forEach((row) => {
        const key = buildPositionKey(row);
        const value = prev[key];
        if (value) {
          next[key] = normalizeTradeSession(value);
        }
      });
      return next;
    });
    setPositionLimitPrices((prev) => {
      const next: Record<string, string> = {};
      accountPositions.forEach((row) => {
        const key = buildPositionKey(row);
        if (prev[key] != null) {
          next[key] = prev[key];
        }
      });
      return next;
    });
  }, [accountPositions]);

  const filteredTradeRuns = useMemo(() => {
    if (!selectedProjectId) {
      return tradeRuns;
    }
    return tradeRuns.filter((run) => String(run.project_id) === selectedProjectId);
  }, [selectedProjectId, tradeRuns]);

  const pipelineTypeOptions = useMemo(() => {
    return Array.from(new Set(pipelineRuns.map((item) => item.run_type).filter(Boolean))).sort();
  }, [pipelineRuns]);

  const pipelineStatusOptions = useMemo(() => {
    return Array.from(new Set(pipelineRuns.map((item) => item.status).filter(Boolean))).sort();
  }, [pipelineRuns]);

  const pipelineModeOptions = useMemo(() => {
    return Array.from(new Set(pipelineRuns.map((item) => item.mode).filter(Boolean))).sort();
  }, [pipelineRuns]);

  const filteredPipelineRuns = useMemo(() => {
    let items = pipelineRuns;
    if (pipelineTypeFilter) {
      items = items.filter((item) => item.run_type === pipelineTypeFilter);
    }
    if (pipelineStatusFilter) {
      items = items.filter((item) => item.status === pipelineStatusFilter);
    }
    if (pipelineModeFilter) {
      items = items.filter((item) => item.mode === pipelineModeFilter);
    }
    if (pipelineDateFrom || pipelineDateTo) {
      const from = pipelineDateFrom ? new Date(pipelineDateFrom).getTime() : null;
      const to = pipelineDateTo ? new Date(pipelineDateTo).getTime() : null;
      items = items.filter((item) => {
        if (!item.created_at) {
          return false;
        }
        const ts = new Date(item.created_at).getTime();
        if (Number.isNaN(ts)) {
          return false;
        }
        if (from && ts < from) {
          return false;
        }
        if (to && ts > to) {
          return false;
        }
        return true;
      });
    }
    if (pipelineKeyword.trim()) {
      const keyword = pipelineKeyword.trim().toLowerCase();
      items = items.filter((item) => {
        if (item.trace_id.toLowerCase().includes(keyword)) {
          return true;
        }
        if (item.run_type.toLowerCase().includes(keyword)) {
          return true;
        }
        if (item.status.toLowerCase().includes(keyword)) {
          return true;
        }
        return item.mode ? item.mode.toLowerCase().includes(keyword) : false;
      });
    }
    return items;
  }, [
    pipelineDateFrom,
    pipelineDateTo,
    pipelineKeyword,
    pipelineModeFilter,
    pipelineRuns,
    pipelineStatusFilter,
    pipelineTypeFilter,
  ]);

  const pipelinePretradeRunId = useMemo(() => {
    return parsePretradeRunId(pipelineTraceId);
  }, [pipelineTraceId]);

  const pipelineKeywordValue = useMemo(() => {
    return pipelineKeyword.trim().toLowerCase();
  }, [pipelineKeyword]);

  const latestTradeRun = filteredTradeRuns[0];
  const activeTradeRun = runDetail?.run ?? latestTradeRun ?? null;
  const canResumeRun = activeTradeRun?.status === "stalled";
  const canTerminateRun = !!activeTradeRun && !["done", "partial", "failed"].includes(activeTradeRun.status);
  const intentOrderMismatch = useMemo(() => {
    const raw = activeTradeRun?.params?.intent_order_mismatch;
    if (!raw || typeof raw !== "object") {
      return null;
    }
    return raw as IntentOrderMismatch;
  }, [activeTradeRun?.params]);

  useEffect(() => {
    if (latestTradeRun?.project_id && !ibStreamForm.project_id) {
      setIbStreamForm((prev) => ({ ...prev, project_id: String(latestTradeRun.project_id) }));
    }
  }, [latestTradeRun?.project_id, ibStreamForm.project_id]);

  useEffect(() => {
    if (latestTradeRun?.id && !executeForm.run_id) {
      setExecuteForm((prev) => ({ ...prev, run_id: String(latestTradeRun.id) }));
    }
  }, [latestTradeRun?.id, executeForm.run_id]);

  useEffect(() => {
    if (latestTradeRun?.id && selectedRunId === null) {
      setSelectedRunId(latestTradeRun.id);
    }
  }, [latestTradeRun?.id, selectedRunId]);

  useEffect(() => {
    if (selectedRunId) {
      loadTradeRunData(selectedRunId);
    } else {
      setRunDetail(null);
      setSymbolSummary([]);
      setSymbolSummaryUpdatedAt(null);
    }
  }, [selectedRunId]);

  useEffect(() => {
    if (mainTab !== "pipeline") {
      return;
    }
    if (!selectedProjectId) {
      setPipelineRuns([]);
      setPipelineTraceId(null);
      setPipelineDetail(null);
      return;
    }
    loadPipelineRuns();
  }, [
    mainTab,
    pipelineDateFrom,
    pipelineDateTo,
    pipelineKeyword,
    pipelineModeFilter,
    pipelineStatusFilter,
    pipelineTypeFilter,
    selectedProjectId,
  ]);

  useEffect(() => {
    if (mainTab !== "pipeline") {
      return;
    }
    if (!pipelineTraceId) {
      setPipelineDetail(null);
      setPipelineSelectedEvent(null);
      return;
    }
    loadPipelineDetail(pipelineTraceId);
  }, [mainTab, pipelineTraceId]);

  useEffect(() => {
    if (!pipelineDetail?.events?.length) {
      setPipelineSelectedEvent(null);
      return;
    }
    if (
      pipelineSelectedEvent &&
      pipelineDetail.events.some((event) => event.event_id === pipelineSelectedEvent.event_id)
    ) {
      return;
    }
    setPipelineSelectedEvent(null);
  }, [pipelineDetail, pipelineSelectedEvent]);

  useEffect(() => {
    if (ibSettings?.market_data_type) {
      setIbStreamForm((prev) => ({
        ...prev,
        market_data_type: ibSettings.market_data_type,
      }));
    }
  }, [ibSettings?.market_data_type]);

  useEffect(() => {
    if (streamSymbolKey && primaryStreamSymbol) {
      loadMarketSnapshot(primaryStreamSymbol);
    } else {
      setMarketSnapshot(null);
      setMarketSnapshotSymbol("");
    }
  }, [primaryStreamSymbol, streamSymbolKey]);

  const isConfigured = useMemo(() => {
    if (!ibSettings) {
      return false;
    }
    return Boolean(ibSettings.host && ibSettings.port);
  }, [ibSettings]);

  const bridgeIsStale = useMemo(() => {
    if (bridgeStatus?.stale !== undefined) {
      return Boolean(bridgeStatus.stale);
    }
    if (accountSummary?.stale === true) {
      return true;
    }
    if (accountPositionsStale) {
      return true;
    }
    if (ibStreamStatus?.status && ibStreamStatus.status !== "connected") {
      return true;
    }
    return false;
  }, [accountSummary?.stale, accountPositionsStale, bridgeStatus?.stale, ibStreamStatus?.status]);

  const bridgeStatusLabel = useMemo(() => {
    if (bridgeIsStale) {
      return t("trade.bridgeStatus.stale");
    }
    if (bridgeStatus?.status || ibStreamStatus?.status || accountSummary?.refreshed_at) {
      return t("trade.bridgeStatus.ok");
    }
    return t("trade.bridgeStatus.unknown");
  }, [bridgeIsStale, bridgeStatus?.status, ibStreamStatus?.status, accountSummary?.refreshed_at, t]);

  const bridgeSource = useMemo(() => {
    return accountSummary?.source || "lean_bridge";
  }, [accountSummary?.source]);

  const bridgeUpdatedAt = useMemo(() => {
    return (
      bridgeStatus?.last_heartbeat ||
      bridgeStatus?.updated_at ||
      ibStreamStatus?.last_heartbeat ||
      accountPositionsUpdatedAt ||
      accountSummary?.refreshed_at ||
      null
    );
  }, [
    bridgeStatus?.last_heartbeat,
    bridgeStatus?.updated_at,
    ibStreamStatus?.last_heartbeat,
    accountPositionsUpdatedAt,
    accountSummary?.refreshed_at,
  ]);

  const bridgeHeartbeatAge = useMemo(() => {
    return getHeartbeatAgeSeconds(
      bridgeStatus?.last_heartbeat || bridgeStatus?.updated_at || null
    );
  }, [bridgeStatus?.last_heartbeat, bridgeStatus?.updated_at]);

  const connectionReason = useMemo(() => {
    const key = resolveConnectionReasonKey(ibState?.message || null);
    if (key) {
      return t(key);
    }
    if (ibState?.message) {
      return ibState.message;
    }
    return t("trade.statusReason.unknown");
  }, [ibState?.message, t]);

  const bridgeRefreshHint = useMemo(() => {
    return getBridgeRefreshHint(
      t,
      bridgeStatus?.last_refresh_result || null,
      bridgeStatus?.last_refresh_reason || null
    );
  }, [
    bridgeStatus?.last_refresh_result,
    bridgeStatus?.last_refresh_reason,
    t,
  ]);

  const bridgeRefreshNextAllowedAt = useMemo(() => {
    if (bridgeStatus?.last_refresh_reason !== "rate_limited") {
      return null;
    }
    return getNextAllowedRefreshAt(bridgeStatus?.last_refresh_at || null);
  }, [bridgeStatus?.last_refresh_at, bridgeStatus?.last_refresh_reason]);

  const positionsStale = useMemo(() => {
    if (accountPositionsStale) {
      return true;
    }
    return !accountPositionsLoading && accountPositions.length === 0 && bridgeIsStale;
  }, [accountPositions.length, accountPositionsLoading, accountPositionsStale, bridgeIsStale]);

  const selectedProject = useMemo(() => {
    if (!selectedProjectId) {
      return null;
    }
    return projects.find((project) => String(project.id) === selectedProjectId) || null;
  }, [projects, selectedProjectId]);

  const snapshotReady = useMemo(() => {
    if (!snapshot?.id) {
      return false;
    }
    return String(snapshot.status || "").toLowerCase() === "success";
  }, [snapshot?.id, snapshot?.status]);

  const snapshotStatusText = useMemo(() => {
    if (snapshotLoading) {
      return t("common.actions.loading");
    }
    if (!snapshot?.id) {
      return t("trade.snapshotMissing");
    }
    if (String(snapshot.status || "").toLowerCase() === "success") {
      return t("trade.snapshotReady");
    }
    const raw = String(snapshot.status || "").trim();
    const key = raw ? `common.status.${raw}` : "";
    const translated = key ? t(key) : "";
    const normalized =
      translated && !translated.startsWith("common.status.") ? translated : raw || "unknown";
    return t("trade.snapshotNotReady", { status: normalized });
  }, [snapshot?.id, snapshot?.status, snapshotLoading, t]);

  const canExecute = useMemo(
    () => Boolean(selectedProjectId && snapshot?.id && snapshotReady),
    [selectedProjectId, snapshot?.id, snapshotReady]
  );

  const statusLabel = useMemo(() => {
    if (!isConfigured) {
      return t("trade.status.unconfigured");
    }
    if (!ibState?.status) {
      return t("trade.status.unknown");
    }
    if (ibState.status === "connected") {
      return t("trade.status.connected");
    }
    if (ibState.status === "disconnected") {
      return t("trade.status.disconnected");
    }
    return ibState.status;
  }, [ibState?.status, isConfigured, t]);

  const modeLabel = useMemo(() => {
    const mode = ibSettings?.mode?.toLowerCase();
    if (mode === "live") {
      return t("trade.mode.live");
    }
    if (mode === "paper") {
      return t("trade.mode.paper");
    }
    return ibSettings?.mode || t("common.none");
  }, [ibSettings?.mode, t]);

  const formatStatus = (value?: string | null) => {
    if (!value) {
      return t("common.none");
    }
    const raw = String(value);
    const key = `common.status.${raw}`;
    const translated = t(key);
    if (translated !== key) {
      return translated;
    }
    const lowerKey = `common.status.${raw.toLowerCase()}`;
    const lowerTranslated = t(lowerKey);
    return lowerTranslated === lowerKey ? raw : lowerTranslated;
  };

  const formatRunMode = (value?: string | null) => {
    if (!value) {
      return t("common.none");
    }
    const normalized = String(value).toLowerCase();
    if (normalized === "paper") {
      return t("trade.mode.paper");
    }
    if (normalized === "live") {
      return t("trade.mode.live");
    }
    return String(value);
  };

  const formatSide = (value?: string | null) => {
    if (!value) {
      return t("common.none");
    }
    return String(value).toUpperCase();
  };

  const formatReceiptKind = (value?: string | null) => {
    if (!value) {
      return t("common.none");
    }
    const normalized = String(value).toLowerCase();
    const key = `trade.receiptKind.${normalized}`;
    const translated = t(key);
    return translated === key ? String(value).toUpperCase() : translated;
  };

  const formatReceiptSource = (value?: string | null) => {
    if (!value) {
      return t("common.none");
    }
    const normalized = String(value).toLowerCase();
    const key = `trade.receiptSource.${normalized}`;
    const translated = t(key);
    return translated === key ? String(value).toUpperCase() : translated;
  };

  const renderRefreshSchedule = useCallback(
    (key: RefreshKey, testIdSuffix?: string, variant: "stack" | "inline" = "stack") => {
      const meta = refreshMeta[key];
      if (!meta) {
        return null;
      }
      const suffix = testIdSuffix || key;
      const intervalLabel = formatIntervalLabel(meta.intervalMs);
      const lastLabel = meta.lastAt ? formatDateTime(meta.lastAt) : t("common.none");
      const nextLabel = formatNextRefresh({
        intervalMs: meta.intervalMs,
        nextAt: meta.nextAt,
        lastAt: meta.lastAt,
      });
      if (variant === "inline") {
        return (
          <div
            className="refresh-inline"
            style={{ marginTop: "8px" }}
            data-testid={`card-refresh-inline-${suffix}`}
          >
            <span>{t("common.actions.refresh")}</span>
            <span className="refresh-inline-dot">·</span>
            <span>
              {t("trade.refreshInterval")} <strong>{intervalLabel}</strong>
            </span>
            <span className="refresh-inline-dot">·</span>
            <span>
              {t("trade.refreshLast")} <strong>{lastLabel}</strong>
            </span>
            <span className="refresh-inline-dot">·</span>
            <span>
              {t("trade.refreshNext")} <strong>{nextLabel}</strong>
            </span>
          </div>
        );
      }
      return (
        <div className="meta-list" style={{ marginTop: "8px" }}>
          <div className="meta-row">
            <span>{t("trade.refreshInterval")}</span>
            <strong data-testid={`card-refresh-interval-${suffix}`}>{intervalLabel}</strong>
          </div>
          <div className="meta-row">
            <span>{t("trade.refreshNext")}</span>
            <strong data-testid={`card-refresh-next-${suffix}`}>{nextLabel}</strong>
          </div>
          <div className="meta-row">
            <span>{t("trade.refreshLast")}</span>
            <strong data-testid={`card-refresh-last-${suffix}`}>{lastLabel}</strong>
          </div>
        </div>
      );
    },
    [formatIntervalLabel, formatNextRefresh, formatDateTime, refreshMeta, t]
  );

  const marketHealthStatusLabel = useMemo(() => {
    if (ibMarketHealthResult?.status) {
      return formatStatus(ibMarketHealthResult.status);
    }
    if (ibStreamStatus?.status) {
      return formatStatus(ibStreamStatus.status);
    }
    return t("common.none");
  }, [ibMarketHealthResult?.status, ibStreamStatus?.status, t]);

  const marketHealthUpdatedLabel = useMemo(() => {
    return (
      marketHealthUpdatedAt ||
      ibStreamStatus?.last_heartbeat ||
      marketSnapshot?.data?.timestamp ||
      null
    );
  }, [marketHealthUpdatedAt, ibStreamStatus?.last_heartbeat, marketSnapshot?.data?.timestamp]);

  const receiptWarningLabels = useMemo(() => {
    if (!receiptsWarnings.length) {
      return [];
    }
    const mapping: Record<string, string> = {
      lean_logs_missing: t("trade.receiptWarning.leanLogsMissing"),
      lean_logs_read_error: t("trade.receiptWarning.leanLogsReadError"),
      lean_logs_parse_error: t("trade.receiptWarning.leanLogsParseError"),
    };
    return receiptsWarnings.map((code) => mapping[code] || code);
  }, [receiptsWarnings, t]);

  const monitorUpdatedAt = useMemo(() => {
    if (detailTab === "receipts") {
      return receiptsUpdatedAt;
    }
    return tradeActivityUpdatedAt;
  }, [detailTab, receiptsUpdatedAt, tradeActivityUpdatedAt]);

  // Keep live-trade monitor tables deterministic and easy to scan: newest order ids first.
  const sortedTradeOrders = useMemo(() => {
    if (!tradeOrders.length) {
      return [];
    }
    return [...tradeOrders].sort((a, b) => (b.id || 0) - (a.id || 0));
  }, [tradeOrders]);

  const sortedTradeFills = useMemo(() => {
    const fills = runDetail?.fills || [];
    if (!fills.length) {
      return [];
    }
    return [...fills].sort((a, b) => {
      const orderDiff = (b.order_id || 0) - (a.order_id || 0);
      if (orderDiff !== 0) {
        return orderDiff;
      }
      return (b.id || 0) - (a.id || 0);
    });
  }, [runDetail?.fills]);

  const sortedTradeReceipts = useMemo(() => {
    if (!tradeReceipts.length) {
      return [];
    }
    const parseTime = (value?: string | null) => {
      if (!value) {
        return Number.NEGATIVE_INFINITY;
      }
      const parsed = Date.parse(value);
      return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
    };
    return [...tradeReceipts].sort((a, b) => {
      const orderA = a.order_id ?? -1;
      const orderB = b.order_id ?? -1;
      if (orderB !== orderA) {
        return orderB - orderA;
      }
      return parseTime(b.time) - parseTime(a.time);
    });
  }, [tradeReceipts]);

  const buildPositionKey = (row: IBAccountPosition) =>
    `${row.symbol}::${row.account || ""}::${row.currency || ""}`;

  const selectedPositions = useMemo(
    () => accountPositions.filter((row) => positionSelections[buildPositionKey(row)]),
    [accountPositions, positionSelections]
  );

  const allPositionsSelected =
    accountPositions.length > 0 && selectedPositions.length === accountPositions.length;

  const accountSummaryOrder = [
    "NetLiquidation",
    "TotalCashValue",
    "AvailableFunds",
    "BuyingPower",
    "GrossPositionValue",
    "EquityWithLoanValue",
    "UnrealizedPnL",
    "RealizedPnL",
    "InitMarginReq",
    "MaintMarginReq",
    "AccruedCash",
    "CashBalance",
  ];

  const formatAccountValue = (value: any) => {
    if (value === null || value === undefined) {
      return t("common.none");
    }
    if (typeof value === "number") {
      return formatNumber(value);
    }
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return formatNumber(parsed);
    }
    return String(value);
  };

  const formatNumber = (value?: number | null, digits = 2) => {
    if (value === null || value === undefined) {
      return t("common.none");
    }
    if (Number.isNaN(Number(value))) {
      return t("common.none");
    }
    return Number(value).toFixed(digits);
  };

  const formatRealizedPnl = (value?: number | null) => {
    return formatRealizedPnlValue(value ?? null, t("trade.positionTable.realizedMissing"));
  };

  const formatPercent = (value?: number | null, digits = 2) => {
    if (value === null || value === undefined) {
      return t("common.none");
    }
    if (Number.isNaN(Number(value))) {
      return t("common.none");
    }
    return `${(Number(value) * 100).toFixed(digits)}%`;
  };

  const guardEquity = useMemo(() => {
    if (!guardState) {
      return null;
    }
    if (guardState.last_equity !== null && guardState.last_equity !== undefined) {
      return guardState.last_equity;
    }
    if (guardState.day_start_equity !== null && guardState.day_start_equity !== undefined) {
      return guardState.day_start_equity;
    }
    return null;
  }, [guardState]);

  const guardDrawdown = useMemo(() => {
    if (!guardState || guardState.equity_peak === null || guardState.equity_peak === undefined) {
      return null;
    }
    if (guardState.last_equity === null || guardState.last_equity === undefined) {
      return null;
    }
    if (!guardState.equity_peak) {
      return null;
    }
    return (guardState.last_equity - guardState.equity_peak) / guardState.equity_peak;
  }, [guardState]);

  const accountSummaryItems = useMemo(() => {
    const items = accountSummary?.items || {};
    return accountSummaryOrder.map((key) => ({
      key,
      value: items[key],
    }));
  }, [accountSummary, accountSummaryOrder]);

  const accountSummaryTagMap = useMemo(
    () => getMessage("trade.accountSummaryTags"),
    [getMessage]
  );

  const accountSummaryFullItems = useMemo(() => {
    const items = accountSummaryFull?.items || {};
    return Object.entries(items).sort(([a], [b]) => a.localeCompare(b));
  }, [accountSummaryFull]);

  const guardReason = useMemo(() => {
    if (!guardState?.halt_reason) {
      return t("common.none");
    }
    try {
      return JSON.stringify(guardState.halt_reason);
    } catch (err) {
      return t("common.none");
    }
  }, [guardState, t]);

  const streamStatusLabel = useMemo(() => {
    if (!ibStreamStatus?.status) {
      return t("common.none");
    }
    return formatStatus(ibStreamStatus.status);
  }, [ibStreamStatus?.status, t]);

  const streamSymbolCount = useMemo(() => {
    if (!ibStreamStatus?.subscribed_symbols) {
      return 0;
    }
    return ibStreamStatus.subscribed_symbols.length;
  }, [ibStreamStatus?.subscribed_symbols]);

  const streamMarketDataType = useMemo(() => {
    return ibStreamStatus?.market_data_type || ibSettings?.market_data_type || t("common.none");
  }, [ibSettings?.market_data_type, ibStreamStatus?.market_data_type, t]);

  const snapshotData = marketSnapshot?.data || {};
  const snapshotPrice = useMemo(() => {
    const last = Number(snapshotData.last ?? snapshotData.close ?? snapshotData.bid ?? snapshotData.ask);
    return Number.isFinite(last) ? last : null;
  }, [snapshotData]);
  const snapshotPrevClose = useMemo(() => {
    const prev = Number(snapshotData.close ?? snapshotData.open);
    return Number.isFinite(prev) ? prev : null;
  }, [snapshotData]);
  const snapshotChange = useMemo(() => {
    if (snapshotPrice == null || snapshotPrevClose == null) {
      return null;
    }
    return snapshotPrice - snapshotPrevClose;
  }, [snapshotPrice, snapshotPrevClose]);
  const snapshotChangePct = useMemo(() => {
    if (snapshotChange == null || snapshotPrevClose == null || snapshotPrevClose === 0) {
      return null;
    }
    return (snapshotChange / snapshotPrevClose) * 100;
  }, [snapshotChange, snapshotPrevClose]);
  const snapshotVolume = useMemo(() => {
    const volume = Number(snapshotData.volume ?? snapshotData.last_size ?? snapshotData.ask_size);
    return Number.isFinite(volume) ? volume : null;
  }, [snapshotData]);


  const sections = getLiveTradeSections();

  const sectionCards: Record<LiveTradeSectionKey, ReactNode> = {
    connection: (
      <div className="card">
        <div className="card-title">{t("trade.statusTitle")}</div>
        <div className="card-meta">{t("trade.statusMeta")}</div>
        {renderRefreshSchedule("connection", "connection")}
        {ibSettings?.mode === "live" && (
          <div className="form-error" style={{ marginTop: "8px" }}>
            {t("trade.liveWarning")}
          </div>
        )}
        <div className="overview-grid" style={{ marginTop: "12px" }}>
          <div className="overview-card">
            <div className="overview-label">{t("trade.statusLabel")}</div>
            <div className="overview-value">{statusLabel}</div>
            <div className="overview-sub">
              {t("trade.connectionUpdatedAt")} {formatDateTime(ibState?.updated_at)}
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.bridgeLabel")}</div>
            <div className="overview-value">{bridgeStatusLabel}</div>
            <div className="overview-sub">
              {t("trade.bridgeUpdatedAt")} {formatDateTime(bridgeUpdatedAt)}
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.marketHealthTitle")}</div>
            <div className="overview-value">{marketHealthStatusLabel}</div>
            <div className="overview-sub">
              {t("trade.marketHealthUpdatedAt")} {formatDateTime(marketHealthUpdatedLabel)}
            </div>
          </div>
        </div>
        <div className="meta-list" style={{ marginTop: "12px" }}>
          <div className="meta-row">
            <span>{t("trade.modeLabel")}</span>
            <strong>{modeLabel}</strong>
          </div>
          <div className="meta-row">
            <span>{t("trade.marketDataType")}</span>
            <strong>{ibSettings?.market_data_type || t("common.none")}</strong>
          </div>
          <div className="meta-row">
            <span>{t("trade.bridgeSource")}</span>
            <strong>{bridgeSource || t("common.none")}</strong>
          </div>
          {ibSettings?.api_mode && (
            <div className="meta-row">
              <span>{t("data.ib.apiMode")}</span>
              <strong>
                {ibSettings.api_mode === "mock"
                  ? t("data.ib.apiModeMock")
                  : t("data.ib.apiModeIb")}
              </strong>
            </div>
          )}
          <div className="meta-row">
            <span>{t("data.ib.lastHeartbeat")}</span>
            <strong>
              {ibState?.last_heartbeat ? formatDateTime(ibState.last_heartbeat) : "-"}
            </strong>
          </div>
          <div className="meta-row">
            <span>{t("data.ib.stateUpdated")}</span>
            <strong>{ibState?.updated_at ? formatDateTime(ibState.updated_at) : "-"}</strong>
          </div>
          {ibState?.message && (
            <div className="meta-row">
              <span>{t("data.ib.message")}</span>
              <strong>{ibState.message}</strong>
            </div>
          )}
        </div>
        <div className="card-subsection" style={{ marginTop: "12px" }}>
          <div className="form-label">{t("trade.statusExplainTitle")}</div>
          <div className="meta-list" style={{ marginTop: "8px" }}>
            <div className="meta-row">
              <span>{t("trade.statusExplainConnection")}</span>
              <strong>{statusLabel}</strong>
            </div>
            <div className="form-hint">{connectionReason}</div>
            <div className="meta-row" style={{ marginTop: "10px" }}>
              <span>{t("trade.statusExplainDataSource")}</span>
              <strong>{bridgeStatusLabel}</strong>
            </div>
            <div className="form-hint">
              {bridgeHeartbeatAge === null
                ? t("common.none")
                : t("trade.statusExplainHeartbeatAge", { seconds: bridgeHeartbeatAge })}
              {bridgeStatus?.last_heartbeat && (
                <span style={{ marginLeft: "8px" }}>
                  {t("trade.statusExplainLastHeartbeat", {
                    time: formatDateTime(bridgeStatus.last_heartbeat),
                  })}
                </span>
              )}
            </div>
            <div className="meta-row" style={{ marginTop: "10px" }}>
              <span>{t("trade.statusExplainRefresh")}</span>
              <strong>
                {formatBridgeRefreshResult(t, bridgeStatus?.last_refresh_result)}
              </strong>
            </div>
            <div className="form-hint">
              {bridgeRefreshHint}
              {bridgeStatus?.last_refresh_at && (
                <span style={{ marginLeft: "8px" }}>
                  {t("trade.statusExplainLastRefresh", {
                    time: formatDateTime(bridgeStatus.last_refresh_at),
                  })}
                </span>
              )}
              {bridgeRefreshNextAllowedAt && (
                <span style={{ marginLeft: "8px" }}>
                  {t("trade.statusExplainNextAllowed", {
                    time: formatDateTime(bridgeRefreshNextAllowedAt),
                  })}
                </span>
              )}
            </div>
          </div>
        </div>
        {ibStateResult && <div className="form-success">{ibStateResult}</div>}
        {ibStateError && <div className="form-error">{ibStateError}</div>}
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <a className="button-secondary" href="/data">
            {t("trade.openData")}
          </a>
        </div>
        <div
          className="live-trade-status-grid"
          style={{
            marginTop: "16px",
            display: "grid",
            gap: "16px",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          }}
        >
          <div className="card-subsection">
            <div className="form-label">{t("trade.bridgeStatusTitle")}</div>
            {renderRefreshSchedule("bridge", "bridge")}
            {bridgeStatusLoading && <div className="form-hint">{t("common.actions.loading")}</div>}
            {bridgeStatusError && <div className="form-hint">{bridgeStatusError}</div>}
            <div className="meta-list" style={{ marginTop: "12px" }}>
              <div className="meta-row">
                <span>{t("trade.bridgeStatusLabel")}</span>
                <strong>
                  {bridgeStatus?.status ? formatStatus(bridgeStatus.status) : t("common.none")}
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.bridgeHeartbeatAt")}</span>
                <strong>{formatDateTime(bridgeStatus?.last_heartbeat)}</strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.bridgeStaleLabel")}</span>
                <strong>
                  {bridgeStatus?.stale === undefined
                    ? t("common.none")
                    : bridgeStatus.stale
                      ? t("common.boolean.true")
                      : t("common.boolean.false")}
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.bridgeLastRefreshAt")}</span>
                <strong>{formatDateTime(bridgeStatus?.last_refresh_at)}</strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.bridgeRefreshResultLabel")}</span>
                <strong>
                  {formatBridgeRefreshResult(t, bridgeStatus?.last_refresh_result)}
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.bridgeRefreshReasonLabel")}</span>
                <strong>
                  {formatBridgeRefreshReason(t, bridgeStatus?.last_refresh_reason)}
                </strong>
              </div>
              {bridgeStatus?.last_refresh_message && (
                <div className="meta-row">
                  <span>{t("trade.bridgeRefreshMessageLabel")}</span>
                  <strong>{bridgeStatus.last_refresh_message}</strong>
                </div>
              )}
              {bridgeStatus?.last_error && (
                <div className="meta-row">
                  <span>{t("trade.bridgeLastError")}</span>
                  <strong>{bridgeStatus.last_error}</strong>
                </div>
              )}
            </div>
          </div>
          <div className="card-subsection">
            <div className="form-label">{t("trade.projectBindingTitle")}</div>
            {renderRefreshSchedule("project", "project")}
            {projectError && <div className="form-hint">{projectError}</div>}
            <div className="form-grid two-col" style={{ marginTop: "12px" }}>
              <div className="form-row">
                <label className="form-label">{t("trade.projectSelect")}</label>
                <select
                  className="form-select"
                  value={selectedProjectId}
                  onChange={(event) => setSelectedProjectId(event.target.value)}
                  data-testid="live-trade-project-select"
                >
                  <option value="">{t("trade.projectSelectPlaceholder")}</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      #{project.id} · {project.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {!selectedProjectId && <div className="form-hint">{t("trade.projectSelectHint")}</div>}
            <div className="meta-list" style={{ marginTop: "12px" }}>
              <div className="meta-row">
                <span>{t("trade.snapshotStatus")}</span>
                <strong data-testid="live-trade-snapshot-status">{snapshotStatusText}</strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.snapshotDate")}</span>
                <strong data-testid="live-trade-snapshot-date">
                  {snapshot?.snapshot_date || t("common.none")}
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.snapshotId")}</span>
                <strong data-testid="live-trade-snapshot-id">
                  {snapshot?.id ? `#${snapshot.id}` : t("common.none")}
                </strong>
              </div>
            </div>
            {selectedProject && (
              <div className="form-hint" style={{ marginTop: "8px" }}>
                {t("trade.projectBindingSelected", {
                  id: selectedProject.id,
                  name: selectedProject.name,
                })}
              </div>
            )}
            {snapshotError && <div className="form-hint">{snapshotError}</div>}
          </div>
        </div>
      </div>
    ),
    account: (
      <div className="card">
        <div className="card-title">{t("trade.accountSummaryTitle")}</div>
        <div className="card-meta">{t("trade.accountSummaryMeta")}</div>
        {renderRefreshSchedule("account", "account")}
        {accountSummaryError && <div className="form-hint">{accountSummaryError}</div>}
        <div className="overview-grid" style={{ marginTop: "12px" }}>
          {accountSummaryItems.map((item) => (
            <div
              className="overview-card"
              key={item.key}
              data-testid={`account-summary-${item.key}`}
            >
              <div className="overview-label">
                {resolveAccountSummaryLabel(item.key, accountSummaryTagMap)}
              </div>
              <div className="overview-value" data-testid={`account-summary-${item.key}-value`}>
                {formatAccountValue(item.value)}
              </div>
            </div>
          ))}
        </div>
        <div className="meta-list" style={{ marginTop: "12px" }}>
          <div className="meta-row">
            <span>{t("trade.accountSummaryUpdatedAt")}</span>
            <strong>
              {accountSummary?.refreshed_at
                ? formatDateTime(accountSummary.refreshed_at)
                : t("common.none")}
            </strong>
          </div>
          <div className="meta-row">
            <span>{t("trade.accountSummarySource")}</span>
            <strong>{accountSummary?.source || t("common.none")}</strong>
          </div>
          {accountSummary?.stale && (
            <div className="meta-row">
              <span>{t("trade.accountSummaryStale")}</span>
              <strong>{t("common.boolean.true")}</strong>
            </div>
          )}
        </div>
        {accountSummaryFullError && <div className="form-hint">{accountSummaryFullError}</div>}
        <details style={{ marginTop: "12px" }}>
          <summary>{t("trade.accountSummaryFullTitle")}</summary>
          <div className="table-scroll" style={{ marginTop: "8px" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>{t("trade.accountSummaryTag")}</th>
                  <th>{t("trade.accountSummaryValue")}</th>
                </tr>
              </thead>
              <tbody>
                {accountSummaryFullItems.length ? (
                  accountSummaryFullItems.map(([key, value]) => (
                    <tr key={key}>
                      <td>{resolveAccountSummaryLabel(key, accountSummaryTagMap)}</td>
                      <td>{formatAccountValue(value)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={2} className="empty-state">
                      {accountSummaryFullLoading
                        ? t("common.actions.loading")
                        : t("trade.accountSummaryFullEmpty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    ),
    positions: (
      <div className="card live-trade-positions" data-testid="account-positions-card">
        <div className="card-title">{t("trade.accountPositionsTitle")}</div>
        <div className="card-meta">{t("trade.accountPositionsMeta")}</div>
        {renderRefreshSchedule("positions", "positions", "inline")}
        {positionsStale && (
          <div className="form-hint warn" style={{ marginTop: "8px" }}>
            <div>{t("trade.accountPositionsStaleHint")}</div>
            <div className="meta-row" style={{ marginTop: "6px" }}>
              <span>{t("trade.accountPositionsStaleUpdatedAt")}</span>
              <strong>{bridgeUpdatedAt ? formatDateTime(bridgeUpdatedAt) : t("common.none")}</strong>
            </div>
          </div>
        )}
        {accountPositionsError && <div className="form-hint">{accountPositionsError}</div>}
        <div className="meta-list" style={{ marginTop: "12px" }}>
          <div className="meta-row">
            <span>{t("trade.accountPositionsUpdatedAt")}</span>
            <strong>
              {accountPositionsUpdatedAt
                ? formatDateTime(accountPositionsUpdatedAt)
                : t("common.none")}
            </strong>
          </div>
        </div>
        {positionActionError && (
          <div className="form-hint danger" style={{ marginTop: "12px" }}>
            {positionActionError}
          </div>
        )}
        {positionActionWarning && (
          <div className="form-hint warn" style={{ marginTop: "12px" }}>
            {positionActionWarning}
          </div>
        )}
        {positionActionResult && (
          <div className="form-success" style={{ marginTop: "12px" }}>
            {positionActionResult}
          </div>
        )}
        <div
          style={{
            marginTop: "12px",
            display: "flex",
            gap: "10px",
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <div className="meta-row">
            <span>{t("trade.positionActionSelected", { count: selectedPositions.length })}</span>
          </div>
          <button
            className="button-secondary"
            data-testid="positions-batch-close"
            disabled={positionActionLoading || selectedPositions.length === 0}
            onClick={() => handleClosePositions(selectedPositions)}
          >
            {positionActionLoading
              ? t("common.actions.loading")
              : t("trade.positionActionBatchClose")}
          </button>
          <button
            className="danger-button"
            data-testid="positions-liquidate-all"
            disabled={positionActionLoading || accountPositions.length === 0}
            onClick={handleLiquidateAll}
          >
            {t("trade.positionActionLiquidateAll")}
          </button>
        </div>
        <div className="table-scroll" style={{ marginTop: "12px" }}>
          <table className="table positions-table" data-testid="account-positions-table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label={t("trade.positionActionSelectAll")}
                    checked={allPositionsSelected}
                    onChange={toggleSelectAllPositions}
                  />
                </th>
                <th>{t("trade.positionTable.symbol")}</th>
                <th>{t("trade.positionTable.position")}</th>
                <th>{t("trade.positionTable.avgCost")}</th>
                <th>{t("trade.positionTable.marketPrice")}</th>
                <th>{t("trade.positionTable.marketValue")}</th>
                <th>{t("trade.positionTable.unrealized")}</th>
                <th>{t("trade.positionTable.realized")}</th>
                <th>{t("trade.positionTable.account")}</th>
                <th>{t("trade.positionTable.currency")}</th>
                <th>{t("trade.positionTable.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {accountPositions.length ? (
                accountPositions.map((row, index) => {
                  const key = buildPositionKey(row);
                  const qtyValue =
                    positionQuantities[key] ?? String(Math.abs(row.position ?? 0) || 1);
                  const sessionValue = normalizeTradeSession(positionSessions[key] ?? defaultSession);
                  const rawOrderType = normalizeOrderType(
                    positionOrderTypes[key] ?? resolveDefaultOrderTypeBySession(sessionValue)
                  );
                  const orderTypeValue = sessionValue === "rth" ? rawOrderType : "LMT";
                  const fallbackLimit = Number(row.market_price ?? null);
                  const limitValue =
                    positionLimitPrices[key] ??
                    (Number.isFinite(fallbackLimit) && fallbackLimit > 0 ? String(fallbackLimit) : "");
                  return (
                    <tr key={key}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={t("trade.positionActionSelectSymbol", {
                            symbol: row.symbol,
                          })}
                          checked={!!positionSelections[key]}
                          onChange={(event) => updatePositionSelection(key, event.target.checked)}
                        />
                      </td>
                      <td>{row.symbol}</td>
                      <td>{formatNumber(row.position ?? null, 4)}</td>
                      <td>{formatNumber(row.avg_cost ?? null)}</td>
                      <td>{formatNumber(row.market_price ?? null)}</td>
                      <td>{formatNumber(row.market_value ?? null)}</td>
                      <td>{formatNumber(row.unrealized_pnl ?? null)}</td>
                      <td>{formatRealizedPnl(row.realized_pnl ?? null)}</td>
                      <td>{row.account || t("common.none")}</td>
                      <td>{row.currency || t("common.none")}</td>
                      <td>
                        <div className="positions-action-group">
                          <input
                            className="form-input positions-action-input"
                            style={{ width: "90px" }}
                            type="number"
                            min="0"
                            step="1"
                            value={qtyValue}
                            onChange={(event) =>
                              updatePositionQuantity(key, event.target.value)
                            }
                          />
                          <select
                            className="form-select positions-action-select"
                            style={{ width: "110px" }}
                            value={sessionValue}
                            data-testid="positions-action-session"
                            onChange={(event) => updatePositionSession(row, key, event.target.value)}
                          >
                            <option value="rth">{t("trade.manualSession.rth")}</option>
                            <option value="pre">{t("trade.manualSession.pre")}</option>
                            <option value="post">{t("trade.manualSession.post")}</option>
                            <option value="night">{t("trade.manualSession.night")}</option>
                          </select>
                          <select
                            className="form-select positions-action-select"
                            style={{ width: "150px" }}
                            value={orderTypeValue}
                            data-testid="positions-action-order-type"
                            disabled={sessionValue !== "rth"}
                            onChange={(event) =>
                              updatePositionOrderType(row, key, event.target.value)
                            }
                          >
                            <option value="MKT">{formatOrderTypeLabel("MKT")}</option>
                            <option value="LMT">{formatOrderTypeLabel("LMT")}</option>
                            <option value="ADAPTIVE_LMT">
                              {formatOrderTypeLabel("ADAPTIVE_LMT")}
                            </option>
                            <option value="PEG_MID">{formatOrderTypeLabel("PEG_MID")}</option>
                          </select>
                          {isLimitLikeOrderType(orderTypeValue) && (
                            <input
                              className="form-input positions-action-limit"
                              style={{ width: "110px" }}
                              type="number"
                              min="0"
                              step="0.01"
                              placeholder={t("trade.positionLimitPricePlaceholder")}
                              value={limitValue}
                              data-testid="positions-action-limit-price"
                              onChange={(event) =>
                                updatePositionLimitPrice(key, event.target.value)
                              }
                            />
                          )}
                          <button
                            className="button-compact positions-action-button"
                            onClick={() => handlePositionOrder(row, "BUY", index)}
                            disabled={positionActionLoading}
                          >
                            {t("trade.positionActionBuy")}
                          </button>
                          <button
                            className="button-compact positions-action-button"
                            onClick={() => handlePositionOrder(row, "SELL", index)}
                            disabled={positionActionLoading}
                          >
                            {t("trade.positionActionSell")}
                          </button>
                          <button
                            className="button-compact positions-action-button"
                            onClick={() => handleClosePosition(row, index)}
                            disabled={positionActionLoading}
                          >
                            {t("trade.positionActionClose")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={11} className="empty-state">
                    {accountPositionsLoading
                      ? t("common.actions.loading")
                      : t("trade.accountPositionsEmpty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    ),
    monitor: (
      <div className="card span-2">
        <div className="card-title">{t("trade.monitorTitle")}</div>
        <div className="card-meta">{t("trade.monitorMeta")}</div>
        {renderRefreshSchedule("monitor", "monitor")}
        {tradeError && <div className="form-hint">{tradeError}</div>}
        {orderCancelError && (
          <div className="form-hint danger" style={{ marginTop: "12px" }}>
            {orderCancelError}
          </div>
        )}
        {orderCancelResult && (
          <div className="form-success" style={{ marginTop: "12px" }}>
            {orderCancelResult}
          </div>
        )}
        <div className="meta-list" style={{ marginTop: "12px" }}>
          <div className="meta-row">
            <span>{t("trade.sectionUpdatedAt")}</span>
            <strong>{formatDateTime(monitorUpdatedAt)}</strong>
          </div>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <button
            className={detailTab === "orders" ? "button-primary" : "button-secondary"}
            onClick={() => setDetailTab("orders")}
            data-testid="trade-tab-orders"
          >
            {t("trade.ordersTitle")}
          </button>
          <button
            className={detailTab === "fills" ? "button-primary" : "button-secondary"}
            onClick={() => setDetailTab("fills")}
            data-testid="trade-tab-fills"
          >
            {t("trade.fillsTitle")}
          </button>
          <button
            className={detailTab === "receipts" ? "button-primary" : "button-secondary"}
            onClick={() => {
              setDetailTab("receipts");
              loadTradeReceipts();
            }}
            data-testid="trade-tab-receipts"
          >
            {t("trade.receiptsTitle")}
          </button>
        </div>
        {detailTab === "orders" ? (
          <>
            <div className="table-scroll" style={{ marginTop: "12px" }}>
              <table className="table" data-testid="trade-orders-table">
                <thead>
                  <tr>
                    <th>{t("trade.orderTable.id")}</th>
                    <th>{t("trade.orderTable.clientOrderId")}</th>
                    <th>{t("trade.orderTable.symbol")}</th>
                    <th>{t("trade.orderTable.side")}</th>
                    <th>{t("trade.orderTable.qty")}</th>
                    <th>{t("trade.orderTable.type")}</th>
                    <th>{t("trade.orderTable.realizedPnl")}</th>
                    <th>{t("trade.orderTable.status")}</th>
                    <th>{t("trade.orderTable.createdAt")}</th>
                    <th>{t("trade.orderTable.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedTradeOrders.length ? (
                    sortedTradeOrders.map((order) => (
                      <tr key={order.id}>
                        <td>#{order.id}</td>
                        <td>{order.client_order_id || t("common.none")}</td>
                        <td>{order.symbol || t("common.none")}</td>
                        <td>{formatSide(order.side)}</td>
                        <td>{order.quantity ?? t("common.none")}</td>
                        <td>
                          {formatOrderTypeLabel(order.order_type)}
                          {order.limit_price != null ? (
                            <span style={{ opacity: 0.75 }}>
                              {" "}
                              @ {formatNumber(order.limit_price, 4)}
                            </span>
                          ) : null}
                        </td>
                        <td>{formatNumber(order.realized_pnl ?? null)}</td>
                        <td>{formatStatus(order.status)}</td>
                        <td>{formatDateTime(order.created_at)}</td>
                        <td>
                          {(() => {
                            const status = String(order.status || "").toUpperCase();
                            const cancelable = ["NEW", "SUBMITTED", "PARTIAL", "CANCEL_REQUESTED"].includes(status);
                            const pending = status === "CANCEL_REQUESTED";
                            const isLoading = !!orderCancelLoading[order.id];
                            if (!cancelable) {
                              return <span style={{ opacity: 0.6 }}>{t("common.none")}</span>;
                            }
                            return (
                              <button
                                className="danger-button"
                                disabled={isLoading || pending}
                                onClick={() => cancelTradeOrder(order)}
                                data-testid={`trade-order-cancel-${order.id}`}
                              >
                                {isLoading
                                  ? t("common.actions.loading")
                                  : pending
                                    ? t("trade.orderCancelPending")
                                    : t("trade.orderCancel")}
                              </button>
                            );
                          })()}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={10} className="empty-state">
                        {t("trade.orderEmpty")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <PaginationBar
              page={ordersPage}
              pageSize={ordersPageSize}
              total={ordersTotal}
              onPageChange={handleOrdersPageChange}
              onPageSizeChange={handleOrdersPageSizeChange}
              pageSizeOptions={[20, 50, 100]}
            />
          </>
        ) : detailTab === "fills" ? (
          <div className="table-scroll" style={{ marginTop: "12px" }}>
            <table className="table" data-testid="trade-fills-table">
              <thead>
                <tr>
                  <th>{t("trade.fillTable.orderId")}</th>
                  <th>{t("trade.fillTable.symbol")}</th>
                  <th>{t("trade.fillTable.side")}</th>
                  <th>{t("trade.fillTable.execId")}</th>
                  <th>{t("trade.fillTable.qty")}</th>
                  <th>{t("trade.fillTable.price")}</th>
                  <th>{t("trade.fillTable.commission")}</th>
                  <th>{t("trade.fillTable.realizedPnl")}</th>
                  <th>{t("trade.fillTable.exchange")}</th>
                  <th>{t("trade.fillTable.time")}</th>
                </tr>
              </thead>
                  <tbody>
                {sortedTradeFills.length ? (
                  sortedTradeFills.map((fill) => (
                    <tr key={fill.id}>
                      <td>#{fill.order_id}</td>
                      <td>{fill.symbol || t("common.none")}</td>
                      <td>{formatSide(fill.side)}</td>
                      <td>{fill.exec_id || t("common.none")}</td>
                      <td>{formatNumber(fill.fill_quantity, 2)}</td>
                      <td>{formatNumber(fill.fill_price, 4)}</td>
                      <td>{formatNumber(fill.commission ?? null, 4)}</td>
                      <td>{formatNumber(fill.realized_pnl ?? null)}</td>
                      <td>{fill.exchange || t("common.none")}</td>
                      <td>{fill.fill_time ? formatDateTime(fill.fill_time) : t("common.none")}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={10} className="empty-state">
                      {t("trade.fillsEmpty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <>
            {receiptsError && <div className="form-hint">{receiptsError}</div>}
            {receiptWarningLabels.map((label, index) => (
              <div key={`${label}-${index}`} className="form-hint">
                {label}
              </div>
            ))}
            <div className="table-scroll" style={{ marginTop: "12px" }}>
              <table className="table" data-testid="trade-receipts-table">
                <thead>
                  <tr>
                    <th>{t("trade.receiptTable.time")}</th>
                    <th>{t("trade.receiptTable.kind")}</th>
                    <th>{t("trade.receiptTable.orderId")}</th>
                    <th>{t("trade.receiptTable.clientOrderId")}</th>
                    <th>{t("trade.receiptTable.symbol")}</th>
                    <th>{t("trade.receiptTable.side")}</th>
                    <th>{t("trade.receiptTable.qty")}</th>
                    <th>{t("trade.receiptTable.filledQty")}</th>
                    <th>{t("trade.receiptTable.fillPrice")}</th>
                    <th>{t("trade.receiptTable.commission")}</th>
                    <th>{t("trade.receiptTable.realizedPnl")}</th>
                    <th>{t("trade.receiptTable.status")}</th>
                    <th>{t("trade.receiptTable.source")}</th>
                  </tr>
                </thead>
                  <tbody>
                  {sortedTradeReceipts.length ? (
                    sortedTradeReceipts.map((receipt, index) => (
                      <tr key={`${receipt.source}-${receipt.order_id || "na"}-${index}`}>
                        <td>{receipt.time ? formatDateTime(receipt.time) : t("common.none")}</td>
                        <td>{formatReceiptKind(receipt.kind)}</td>
                        <td>{receipt.order_id ? `#${receipt.order_id}` : t("common.none")}</td>
                        <td>{receipt.client_order_id || t("common.none")}</td>
                        <td>{receipt.symbol || t("common.none")}</td>
                        <td>{formatSide(receipt.side)}</td>
                        <td>{formatNumber(receipt.quantity ?? null)}</td>
                        <td>{formatNumber(receipt.filled_quantity ?? null)}</td>
                        <td>{formatNumber(receipt.fill_price ?? null)}</td>
                        <td>{formatNumber(receipt.commission ?? null)}</td>
                        <td>{formatNumber(receipt.realized_pnl ?? null)}</td>
                        <td>{receipt.status ? formatStatus(receipt.status) : t("common.none")}</td>
                        <td>{formatReceiptSource(receipt.source)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={13} className="empty-state">
                        {receiptsLoading ? t("common.actions.loading") : t("trade.receiptsEmpty")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <PaginationBar
              page={receiptsPage}
              pageSize={receiptsPageSize}
              total={receiptsTotal}
              onPageChange={handleReceiptsPageChange}
              onPageSizeChange={handleReceiptsPageSizeChange}
              pageSizeOptions={[20, 50, 100]}
            />
          </>
        )}
      </div>
    ),
    config: (
      <div className="card">
        <div className="card-title">{t("trade.configTitle")}</div>
        <div className="card-meta">{t("trade.configMeta")}</div>
        {renderRefreshSchedule("connection", "config")}
        <div className="overview-grid" style={{ marginTop: "12px" }}>
          <div className="overview-card">
            <div className="overview-label">{t("trade.host")}</div>
            <div className="overview-value">{ibSettings?.host || t("common.none")}</div>
            <div className="overview-sub">
              {t("trade.port")}: {ibSettings?.port ?? t("common.none")}
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.account")}</div>
            <div className="overview-value">{maskAccount(ibSettings?.account_id) || t("common.none")}</div>
            <div className="overview-sub">
              {t("trade.apiMode")}: {ibSettings?.api_mode || t("common.none")}
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.regulatorySnapshot")}</div>
            <div className="overview-value">
              {ibSettings?.use_regulatory_snapshot
                ? t("common.boolean.true")
                : t("common.boolean.false")}
            </div>
            <div className="overview-sub">
              {t("common.labels.updatedAt")} {formatDateTime(ibSettings?.updated_at)}
            </div>
          </div>
        </div>
        {!isConfigured && (
          <div className="form-hint" style={{ marginTop: "8px" }}>
            {t("trade.statusHint")}
          </div>
        )}
        <div className="section-title">{t("data.ib.settingsTitle")}</div>
        <div className="form-grid">
          <div className="form-row">
            <label className="form-label">{t("data.ib.host")}</label>
            <input
              type="text"
              className="form-input"
              value={ibSettingsForm.host}
              onChange={(e) => updateIbSettingsForm("host", e.target.value)}
            />
            <div className="form-hint">{t("data.ib.hostHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.port")}</label>
            <input
              type="number"
              className="form-input"
              value={ibSettingsForm.port}
              onChange={(e) => updateIbSettingsForm("port", e.target.value)}
            />
            <div className="form-hint">{t("data.ib.portHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.clientId")}</label>
            <input
              type="number"
              className="form-input"
              value={ibSettingsForm.client_id}
              onChange={(e) => updateIbSettingsForm("client_id", e.target.value)}
            />
            <div className="form-hint">{t("data.ib.clientIdHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.accountId")}</label>
            <input
              type="text"
              className="form-input"
              value={ibSettingsForm.account_id}
              onChange={(e) => updateIbSettingsForm("account_id", e.target.value)}
              placeholder={t("data.ib.accountIdPlaceholder")}
            />
            {ibSettings?.account_id && (
              <div className="form-hint">
                {t("data.ib.accountIdHint", { account: ibSettings.account_id })}
              </div>
            )}
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.apiMode")}</label>
            <select
              className="form-select"
              value={ibSettingsForm.api_mode}
              onChange={(e) => updateIbSettingsForm("api_mode", e.target.value)}
            >
              <option value="ib">{t("data.ib.apiModeIb")}</option>
              <option value="mock">{t("data.ib.apiModeMock")}</option>
            </select>
            <div className="form-hint">{t("data.ib.apiModeHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.mode")}</label>
            <select
              className="form-select"
              value={ibSettingsForm.mode}
              onChange={(e) => updateIbSettingsForm("mode", e.target.value)}
            >
              <option value="paper">{t("data.ib.modePaper")}</option>
              <option value="live">{t("data.ib.modeLive")}</option>
            </select>
            <div className="form-hint">{t("data.ib.modeHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.marketDataType")}</label>
            <select
              className="form-select"
              value={ibSettingsForm.market_data_type}
              onChange={(e) => updateIbSettingsForm("market_data_type", e.target.value)}
            >
              <option value="realtime">{t("data.ib.marketDataRealtime")}</option>
              <option value="frozen">{t("data.ib.marketDataFrozen")}</option>
              <option value="delayed">{t("data.ib.marketDataDelayed")}</option>
            </select>
            <div className="form-hint">{t("data.ib.marketDataTypeHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.regulatorySnapshot")}</label>
            <label className="switch">
              <input
                type="checkbox"
                checked={ibSettingsForm.use_regulatory_snapshot}
                onChange={(e) => updateIbSettingsForm("use_regulatory_snapshot", e.target.checked)}
              />
              <span className="slider" />
            </label>
            <div className="form-hint">{t("data.ib.regulatorySnapshotHint")}</div>
          </div>
        </div>
        {ibSettingsResult && <div className="form-success">{ibSettingsResult}</div>}
        {ibSettingsError && <div className="form-error">{ibSettingsError}</div>}
        <button className="button-secondary" onClick={saveIbSettings} disabled={ibSettingsSaving}>
          {ibSettingsSaving ? t("common.actions.loading") : t("common.actions.save")}
        </button>
      </div>
    ),
    marketHealth: (
      <>
        <div className="card">
          <div className="card-title">{t("data.ib.streamTitle")}</div>
          <div className="card-meta">{t("data.ib.streamMeta")}</div>
          {renderRefreshSchedule("connection", "stream")}
          <div className="overview-grid" style={{ marginTop: "12px" }}>
            <div className="overview-card">
              <div className="overview-label">{t("data.ib.streamStatus")}</div>
              <div className="overview-value">{streamStatusLabel}</div>
              <div className="overview-sub">
                {t("data.ib.streamLastHeartbeat")}{" "}
                {ibStreamStatus?.last_heartbeat
                  ? formatDateTime(ibStreamStatus.last_heartbeat)
                  : "-"}
              </div>
            </div>
            <div className="overview-card">
              <div className="overview-label">{t("data.ib.streamSubscribed")}</div>
              <div className="overview-value">{streamSymbolCount}</div>
              <div className="overview-sub">
                {(ibStreamStatus?.subscribed_symbols || []).slice(0, 6).join(", ") ||
                  t("common.none")}
              </div>
            </div>
            <div className="overview-card">
              <div className="overview-label">{t("data.ib.streamMarketDataType")}</div>
              <div className="overview-value">{streamMarketDataType}</div>
              <div className="overview-sub">
                {t("data.ib.streamErrorCount")}: {ibStreamStatus?.ib_error_count ?? 0}
              </div>
            </div>
          </div>
          <div className="meta-list" style={{ marginTop: "12px" }}>
            <div className="meta-row">
              <span>{t("data.ib.streamLastError")}</span>
              <strong>{ibStreamStatus?.last_error || "-"}</strong>
            </div>
          </div>
          <div className="form-grid" style={{ marginTop: "12px" }}>
            <div className="form-row">
              <label className="form-label">{t("data.ib.streamProjectId")}</label>
              <input
                type="number"
                className="form-input"
                value={ibStreamForm.project_id}
                onChange={(e) => updateIbStreamForm("project_id", e.target.value)}
              />
              <div className="form-hint">{t("data.ib.streamProjectIdHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.streamDecisionSnapshotId")}</label>
              <input
                type="number"
                className="form-input"
                value={ibStreamForm.decision_snapshot_id}
                onChange={(e) => updateIbStreamForm("decision_snapshot_id", e.target.value)}
              />
              <div className="form-hint">{t("data.ib.streamDecisionSnapshotIdHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.streamMaxSymbols")}</label>
              <input
                type="number"
                className="form-input"
                value={ibStreamForm.max_symbols}
                onChange={(e) => updateIbStreamForm("max_symbols", e.target.value)}
              />
              <div className="form-hint">{t("data.ib.streamMaxSymbolsHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.streamMarketDataType")}</label>
              <select
                className="form-select"
                value={ibStreamForm.market_data_type}
                onChange={(e) => updateIbStreamForm("market_data_type", e.target.value)}
              >
                <option value="realtime">{t("data.ib.marketDataRealtime")}</option>
                <option value="frozen">{t("data.ib.marketDataFrozen")}</option>
                <option value="delayed">{t("data.ib.marketDataDelayed")}</option>
              </select>
              <div className="form-hint">{t("data.ib.streamMarketDataTypeHint")}</div>
            </div>
          </div>
          {ibStreamError && <div className="form-error">{ibStreamError}</div>}
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <button
              className="button-primary"
              onClick={startIbStream}
              disabled={ibStreamActionLoading}
            >
              {ibStreamActionLoading ? t("common.actions.loading") : t("data.ib.streamStart")}
            </button>
            <button
              className="button-secondary"
              onClick={stopIbStream}
              disabled={ibStreamActionLoading}
            >
              {ibStreamActionLoading ? t("common.actions.loading") : t("data.ib.streamStop")}
            </button>
          </div>
        </div>
        <div className="card">
          <div className="card-title">{t("trade.snapshotTitle")}</div>
          <div className="card-meta">{t("trade.snapshotMeta")}</div>
          {renderRefreshSchedule("snapshot", "snapshot")}
          <div className="snapshot-hero" style={{ marginTop: "12px" }}>
            <div className="snapshot-symbol">{marketSnapshotSymbol || t("trade.snapshotEmpty")}</div>
            <div className="snapshot-price">
              {snapshotPrice == null ? "--" : snapshotPrice.toFixed(2)}
            </div>
            <div
              className={`snapshot-change ${
                snapshotChange != null && snapshotChange >= 0 ? "up" : "down"
              }`}
            >
              {snapshotChange == null || snapshotChangePct == null
                ? "--"
                : `${snapshotChange >= 0 ? "+" : ""}${snapshotChange.toFixed(2)} (${snapshotChangePct.toFixed(2)}%)`}
            </div>
          </div>
          <div className="meta-list" style={{ marginTop: "12px" }}>
            <div className="meta-row">
              <span>{t("trade.snapshotVolume")}</span>
              <strong>{snapshotVolume == null ? "-" : snapshotVolume.toLocaleString()}</strong>
            </div>
            <div className="meta-row">
              <span>{t("trade.snapshotUpdatedAt")}</span>
              <strong>{formatDateTime(snapshotData.timestamp)}</strong>
            </div>
          </div>
          {marketSnapshotError && <div className="form-error">{marketSnapshotError}</div>}
        </div>
        <div className="card">
          <div className="card-title">{t("data.ib.healthTitle")}</div>
          {renderRefreshSchedule("health", "health")}
          <div className="form-grid">
            <div className="form-row full">
              <label className="form-label">{t("data.ib.healthSymbols")}</label>
              <input
                type="text"
                className="form-input"
                value={ibMarketHealthForm.symbols}
                onChange={(e) => updateIbMarketHealthForm("symbols", e.target.value)}
                placeholder={t("data.ib.healthSymbolsPlaceholder")}
              />
              <div className="form-hint">{t("data.ib.healthSymbolsHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.healthProjectOnly")}</label>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={ibMarketHealthForm.use_project_symbols}
                  onChange={(e) => updateIbMarketHealthForm("use_project_symbols", e.target.checked)}
                />
                <span className="slider" />
              </label>
              <div className="form-hint">{t("data.ib.healthProjectOnlyHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.healthMinRatio")}</label>
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                className="form-input"
                value={ibMarketHealthForm.min_success_ratio}
                onChange={(e) => updateIbMarketHealthForm("min_success_ratio", e.target.value)}
              />
              <div className="form-hint">{t("data.ib.healthMinRatioHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.healthFallback")}</label>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={ibMarketHealthForm.fallback_history}
                  onChange={(e) => updateIbMarketHealthForm("fallback_history", e.target.checked)}
                />
                <span className="slider" />
              </label>
              <div className="form-hint">{t("data.ib.healthFallbackHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.healthDuration")}</label>
              <select
                className="form-select"
                value={ibMarketHealthForm.history_duration}
                onChange={(e) => updateIbMarketHealthForm("history_duration", e.target.value)}
              >
                <option value="5 D">{t("data.ib.healthDuration5d")}</option>
                <option value="30 D">{t("data.ib.healthDuration30d")}</option>
                <option value="90 D">{t("data.ib.healthDuration90d")}</option>
              </select>
              <div className="form-hint">{t("data.ib.healthDurationHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.healthBarSize")}</label>
              <select
                className="form-select"
                value={ibMarketHealthForm.history_bar_size}
                onChange={(e) => updateIbMarketHealthForm("history_bar_size", e.target.value)}
              >
                <option value="1 day">{t("data.ib.healthBarDay")}</option>
                <option value="1 hour">{t("data.ib.healthBarHour")}</option>
              </select>
              <div className="form-hint">{t("data.ib.healthBarSizeHint")}</div>
            </div>
            <div className="form-row">
              <label className="form-label">{t("data.ib.healthUseRth")}</label>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={ibMarketHealthForm.history_use_rth}
                  onChange={(e) => updateIbMarketHealthForm("history_use_rth", e.target.checked)}
                />
                <span className="slider" />
              </label>
              <div className="form-hint">{t("data.ib.healthUseRthHint")}</div>
            </div>
          </div>
          {ibMarketHealthResult && (
            <div className="form-success">
              {t("data.ib.healthResult", {
                status: ibMarketHealthResult.status,
                success: ibMarketHealthResult.success,
                total: ibMarketHealthResult.total,
              })}
              {ibMarketHealthResult.errors.length > 0 && (
                <div className="form-note">
                  {ibMarketHealthResult.errors.slice(0, 5).join(" | ")}
                </div>
              )}
            </div>
          )}
          {ibMarketHealthError && <div className="form-error">{ibMarketHealthError}</div>}
          <button
            className="button-secondary"
            onClick={checkIbMarketHealth}
            disabled={ibMarketHealthLoading}
          >
            {ibMarketHealthLoading ? t("common.actions.loading") : t("data.ib.healthCheck")}
          </button>
        </div>
      </>
    ),
    contracts: (
      <div className="card">
        <div className="card-title">{t("data.ib.contractsTitle")}</div>
        {renderRefreshSchedule("contracts", "contracts")}
        <div className="form-grid">
          <div className="form-row full">
            <label className="form-label">{t("data.ib.contractsSymbols")}</label>
            <input
              type="text"
              className="form-input"
              value={ibContractForm.symbols}
              onChange={(e) => updateIbContractForm("symbols", e.target.value)}
              placeholder={t("data.ib.contractsSymbolsPlaceholder")}
            />
            <div className="form-hint">{t("data.ib.contractsSymbolsHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.contractsProjectOnly")}</label>
            <label className="switch">
              <input
                type="checkbox"
                checked={ibContractForm.use_project_symbols}
                onChange={(e) => updateIbContractForm("use_project_symbols", e.target.checked)}
              />
              <span className="slider" />
            </label>
            <div className="form-hint">{t("data.ib.contractsProjectOnlyHint")}</div>
          </div>
        </div>
        {ibContractResult && (
          <div className="form-success">
            {t("data.ib.contractsResult", {
              total: ibContractResult.total,
              updated: ibContractResult.updated,
              skipped: ibContractResult.skipped,
              duration: ibContractResult.duration_sec.toFixed(2),
            })}
          </div>
        )}
        {ibContractError && <div className="form-error">{ibContractError}</div>}
        <button
          className="button-secondary"
          onClick={refreshIbContracts}
          disabled={ibContractLoading}
        >
          {ibContractLoading ? t("common.actions.loading") : t("data.ib.contractsSync")}
        </button>
      </div>
    ),
    history: (
      <div className="card">
        <div className="card-title">{t("data.ib.historyTitle")}</div>
        {renderRefreshSchedule("monitor", "history")}
        <div className="form-grid">
          <div className="form-row full">
            <label className="form-label">{t("data.ib.historySymbols")}</label>
            <input
              type="text"
              className="form-input"
              value={ibHistoryForm.symbols}
              onChange={(e) => updateIbHistoryForm("symbols", e.target.value)}
              placeholder={t("data.ib.historySymbolsPlaceholder")}
            />
            <div className="form-hint">{t("data.ib.historySymbolsHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.historyProjectOnly")}</label>
            <label className="switch">
              <input
                type="checkbox"
                checked={ibHistoryForm.use_project_symbols}
                onChange={(e) => updateIbHistoryForm("use_project_symbols", e.target.checked)}
              />
              <span className="slider" />
            </label>
            <div className="form-hint">{t("data.ib.historyProjectOnlyHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.historyDuration")}</label>
            <select
              className="form-select"
              value={ibHistoryForm.duration}
              onChange={(e) => updateIbHistoryForm("duration", e.target.value)}
            >
              <option value="5 D">{t("data.ib.historyDuration5d")}</option>
              <option value="30 D">{t("data.ib.historyDuration30d")}</option>
              <option value="90 D">{t("data.ib.historyDuration90d")}</option>
              <option value="1 Y">{t("data.ib.historyDuration1y")}</option>
            </select>
            <div className="form-hint">{t("data.ib.historyDurationHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.historyBarSize")}</label>
            <select
              className="form-select"
              value={ibHistoryForm.bar_size}
              onChange={(e) => updateIbHistoryForm("bar_size", e.target.value)}
            >
              <option value="1 day">{t("data.ib.historyBarDay")}</option>
              <option value="1 hour">{t("data.ib.historyBarHour")}</option>
            </select>
            <div className="form-hint">{t("data.ib.historyBarSizeHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.historyUseRth")}</label>
            <label className="switch">
              <input
                type="checkbox"
                checked={ibHistoryForm.use_rth}
                onChange={(e) => updateIbHistoryForm("use_rth", e.target.checked)}
              />
              <span className="slider" />
            </label>
            <div className="form-hint">{t("data.ib.historyUseRthHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.historyStore")}</label>
            <label className="switch">
              <input
                type="checkbox"
                checked={ibHistoryForm.store}
                onChange={(e) => updateIbHistoryForm("store", e.target.checked)}
              />
              <span className="slider" />
            </label>
            <div className="form-hint">{t("data.ib.historyStoreHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("data.ib.historyDelay")}</label>
            <input
              type="number"
              min="0"
              step="0.05"
              className="form-input"
              value={ibHistoryForm.min_delay_seconds}
              onChange={(e) => updateIbHistoryForm("min_delay_seconds", e.target.value)}
            />
            <div className="form-hint">{t("data.ib.historyDelayHint")}</div>
          </div>
        </div>
        {ibHistoryError && <div className="form-error">{ibHistoryError}</div>}
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <button
            className="button-secondary"
            onClick={createIbHistoryJob}
            disabled={ibHistoryActionLoading}
          >
            {ibHistoryActionLoading ? t("common.actions.loading") : t("data.ib.historyStart")}
          </button>
        </div>
        {ibHistoryJobs.length > 0 ? (
          <div className="table-scroll" style={{ marginTop: "12px" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>{t("common.labels.id")}</th>
                  <th>{t("common.labels.status")}</th>
                  <th>{t("data.ib.historyProgress")}</th>
                  <th>{t("data.ib.historySuccess")}</th>
                  <th>{t("common.labels.createdAt")}</th>
                  <th>{t("common.labels.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {ibHistoryJobs.map((job) => {
                  const total = job.total_symbols ?? 0;
                  const processed = job.processed_symbols ?? 0;
                  const success = job.success_symbols ?? 0;
                  const failed = job.failed_symbols ?? 0;
                  const canCancel = ["queued", "running"].includes(job.status);
                  return (
                    <tr key={job.id}>
                      <td>{job.id}</td>
                      <td>{formatStatus(job.status)}</td>
                      <td>
                        {processed}/{total}
                      </td>
                      <td>
                        {success}/{failed}
                      </td>
                      <td>{formatDateTime(job.created_at)}</td>
                      <td>
                        <div className="table-actions">
                          <button
                            className="button-link"
                            disabled={!canCancel || ibHistoryActionLoading}
                            onClick={() => cancelIbHistoryJob(job.id)}
                          >
                            {t("data.ib.historyCancel")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">{t("data.ib.historyEmpty")}</div>
        )}
      </div>
    ),
    guard: (
      <div className="card">
        <div className="card-title">{t("trade.guardTitle")}</div>
        <div className="card-meta">{t("trade.guardMeta")}</div>
        {renderRefreshSchedule("monitor", "guard")}
        {guardError && <div className="form-error">{guardError}</div>}
        <div className="overview-grid" style={{ marginTop: "12px" }}>
          <div className="overview-card">
            <div className="overview-label">{t("trade.guardStatus")}</div>
            <div className="overview-value">
              {guardLoading
                ? t("common.actions.loading")
                : guardState
                  ? formatStatus(guardState.status)
                  : t("trade.guardEmpty")}
            </div>
            <div className="overview-sub">
              {guardState
                ? `${t("trade.guardValuationSource")}: ${
                    guardState.valuation_source || t("common.none")
                  } · ${t("trade.guardValuationTime")}: ${
                    guardState.last_valuation_ts
                      ? formatDateTime(guardState.last_valuation_ts)
                      : t("common.none")
                  }`
                : t("common.none")}
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.guardEquity")}</div>
            <div className="overview-value">
              {guardEquity !== null ? formatNumber(guardEquity) : t("common.none")}
            </div>
            <div className="overview-sub">
              {t("trade.guardDrawdown")}: {
                guardDrawdown !== null ? `${(guardDrawdown * 100).toFixed(2)}%` : t("common.none")
              }
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.guardOrderFailures")}</div>
            <div className="overview-value">
              {guardState ? guardState.order_failures : t("common.none")}
            </div>
            <div className="overview-sub">
              {t("trade.guardMarketErrors")}: {guardState ? guardState.market_data_errors : t("common.none")}
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.guardRiskTriggers")}</div>
            <div className="overview-value">
              {guardState ? guardState.risk_triggers : t("common.none")}
            </div>
            <div className="overview-sub">
              {t("trade.guardCooldown")}: {
                guardState?.cooldown_until ? formatDateTime(guardState.cooldown_until) : t("common.none")
              }
            </div>
          </div>
        </div>
        {guardState?.halt_reason ? (
          <div className="form-hint" style={{ marginTop: "8px" }}>
            {t("trade.guardReason")}: {guardReason}
          </div>
        ) : null}
      </div>
    ),
    execution: (
      <div className="card">
        <div className="card-title">{t("trade.executionTitle")}</div>
        <div className="card-meta">{t("trade.executionMeta")}</div>
        {renderRefreshSchedule("execution", "execution")}
        <div className="overview-grid" style={{ marginTop: "12px" }}>
          <div className="overview-card">
            <div className="overview-label">{t("trade.latestRun")}</div>
            <div className="overview-value">
              {latestTradeRun ? (
                <IdChip label={t("trade.id.run")} value={latestTradeRun.id} />
              ) : (
                t("common.none")
              )}
            </div>
            <div className="overview-sub">
              <span data-testid="paper-trade-status" data-status={latestTradeRun?.status || ""}>
                {latestTradeRun
                  ? `${formatStatus(latestTradeRun.status)} · ${formatDateTime(
                      latestTradeRun.created_at
                    )}`
                  : t("trade.runEmpty")}
              </span>
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.runMode")}</div>
            <div className="overview-value">
              {latestTradeRun ? formatRunMode(latestTradeRun.mode) : t("common.none")}
            </div>
            <div className="overview-sub">
              {t("trade.runProject")}
              {latestTradeRun ? ` #${latestTradeRun.project_id}` : ` ${t("common.none")}`}
            </div>
          </div>
          <div className="overview-card">
            <div className="overview-label">{t("trade.executionDataSource")}</div>
            <div className="overview-value">
              {tradeSettings?.execution_data_source
                ? tradeSettings.execution_data_source.toUpperCase()
                : t("common.none")}
            </div>
            <div className="overview-sub">
              {t("trade.signalDataSource")}: {t("trade.signalDataSourceValue")}
            </div>
          </div>
        </div>
        {tradeSettingsError && <div className="form-hint">{tradeSettingsError}</div>}
        {tradeError && <div className="form-hint">{tradeError}</div>}
        <div className="table-scroll" style={{ marginTop: "12px" }}>
          <table className="table" data-testid="trade-runs-table">
            <thead>
              <tr>
                <th>{t("trade.runTable.id")}</th>
                <th>{t("trade.runTable.status")}</th>
                <th>{t("trade.runTable.mode")}</th>
                <th>{t("trade.runTable.snapshot")}</th>
                <th>{t("trade.runTable.createdAt")}</th>
              </tr>
            </thead>
            <tbody>
              {filteredTradeRuns.length ? (
                filteredTradeRuns.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <IdChip label={t("trade.id.run")} value={run.id} />
                    </td>
                    <td>{formatStatus(run.status)}</td>
                    <td>{formatRunMode(run.mode)}</td>
                    <td>
                      {run.decision_snapshot_id ? (
                        <IdChip label={t("trade.id.snapshot")} value={run.decision_snapshot_id} />
                      ) : (
                        t("common.none")
                      )}
                    </td>
                    <td>{formatDateTime(run.created_at)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="empty-state">
                    {t("trade.runEmpty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "12px" }}>
          <button
            className="button-secondary"
            onClick={createTradeRun}
            disabled={createRunLoading || !selectedProjectId}
            data-testid="paper-trade-create"
          >
            {createRunLoading ? t("common.actions.loading") : t("trade.createRun")}
          </button>
        </div>
        {createRunError && <div className="form-hint">{createRunError}</div>}
        {createRunResult && <div className="form-hint">{createRunResult}</div>}
        <div className="form-grid" style={{ marginTop: "12px" }}>
          <div className="form-row">
            <label className="form-label">{t("trade.runSelect")}</label>
            <select
              className="form-select"
              value={selectedRunId ?? ""}
              onChange={(event) => {
                const next = Number(event.target.value);
                setSelectedRunId(Number.isNaN(next) || !next ? null : next);
              }}
            >
              <option value="">{t("common.noneText")}</option>
              {filteredTradeRuns.map((run) => (
                <option key={run.id} value={run.id}>
                  #{run.id} · {formatStatus(run.status)}
                </option>
              ))}
            </select>
            <div className="form-hint">{t("trade.runSelectHint")}</div>
          </div>
        </div>
        {activeTradeRun ? (
          <div className="meta-list" style={{ marginTop: "12px" }}>
            <div className="meta-row">
              <span>{t("trade.runProgressAt")}</span>
              <strong>
                {activeTradeRun.last_progress_at
                  ? formatDateTime(activeTradeRun.last_progress_at)
                  : t("common.none")}
              </strong>
            </div>
            <div className="meta-row">
              <span>{t("trade.runProgressStage")}</span>
              <strong>{activeTradeRun.progress_stage || t("common.none")}</strong>
            </div>
            <div className="meta-row">
              <span>{t("trade.runProgressReason")}</span>
              <strong>{activeTradeRun.progress_reason || t("common.none")}</strong>
            </div>
            {activeTradeRun.status === "stalled" ? (
              <>
                <div className="meta-row">
                  <span>{t("trade.runStalledAt")}</span>
                  <strong>
                    {activeTradeRun.stalled_at
                      ? formatDateTime(activeTradeRun.stalled_at)
                      : t("common.none")}
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("trade.runStalledReason")}</span>
                  <strong>{activeTradeRun.stalled_reason || t("common.none")}</strong>
                </div>
              </>
            ) : null}
          </div>
        ) : null}
        <TradeIntentMismatchCard
          mismatch={intentOrderMismatch}
          message={activeTradeRun?.message}
        />
        {activeTradeRun?.status === "stalled" ? (
          <div className="form-hint warn" style={{ marginTop: "8px" }}>
            {t("trade.runStalledHint")}
          </div>
        ) : null}
        <div className="form-grid" style={{ marginTop: "12px" }}>
          <div className="form-row">
            <label className="form-label">{t("trade.runActionReason")}</label>
            <input
              type="text"
              className="form-input"
              value={runActionReason}
              placeholder={t("trade.runActionReasonHint")}
              onChange={(event) => setRunActionReason(event.target.value)}
            />
            <div className="form-hint">{t("trade.runActionReasonHint")}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <button
            className="button-secondary"
            onClick={() => handleRunAction("sync")}
            disabled={runActionLoading || !activeTradeRun}
          >
            {runActionLoading ? t("common.actions.loading") : t("trade.runAction.sync")}
          </button>
          <button
            className="button-secondary"
            onClick={() => handleRunAction("resume")}
            disabled={runActionLoading || !canResumeRun}
          >
            {runActionLoading ? t("common.actions.loading") : t("trade.runAction.resume")}
          </button>
          <button
            className="danger-button"
            onClick={() => handleRunAction("terminate")}
            disabled={runActionLoading || !canTerminateRun}
          >
            {runActionLoading ? t("common.actions.loading") : t("trade.runAction.terminate")}
          </button>
        </div>
        {runActionError && (
          <div className="form-hint danger" style={{ marginTop: "8px" }}>
            {runActionError}
          </div>
        )}
        {runActionResult && (
          <div className="form-success" style={{ marginTop: "8px" }}>
            {runActionResult}
          </div>
        )}
        <div className="meta-list" style={{ marginTop: "12px" }}>
          <div className="meta-row" style={{ alignItems: "flex-start" }}>
            <span>{t("trade.executeContext")}</span>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <IdChip label={t("trade.id.project")} value={selectedProjectId || null} />
              <IdChip label={t("trade.id.snapshot")} value={snapshot?.id} />
              <IdChip label={t("trade.id.run")} value={latestTradeRun?.id} />
            </div>
          </div>
        </div>
        <div className="form-grid" style={{ marginTop: "12px" }}>
          <div className="form-row">
            <label className="form-label">{t("trade.executeRunId")}</label>
            <input
              type="number"
              className="form-input"
              value={executeForm.run_id}
              onChange={(event) => updateExecuteForm("run_id", event.target.value)}
              data-testid="paper-trade-run-id"
            />
            <div className="form-hint">{t("trade.executeRunIdHint")}</div>
          </div>
          <div className="form-row">
            <label className="form-label">{t("trade.executeToken")}</label>
            <input
              type="text"
              className="form-input"
              value={executeForm.live_confirm_token}
              placeholder={t("trade.executeTokenHint")}
              onChange={(event) => updateExecuteForm("live_confirm_token", event.target.value)}
            />
            <div className="form-hint">{t("trade.executeTokenHint")}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <button
            className="button-primary"
            onClick={executeTradeRun}
            disabled={executeLoading || !canExecute}
            data-testid="paper-trade-execute"
          >
            {executeLoading ? t("common.actions.loading") : t("trade.executeSubmit")}
          </button>
        </div>
        {!canExecute && selectedProjectId && !snapshotError && (
          <div className="form-hint" style={{ marginTop: "8px" }}>
            {t("trade.executeBlockedSnapshot")}
          </div>
        )}
        {executeError && (
          <div className="form-hint" data-testid="paper-trade-error">
            {executeError}
          </div>
        )}
        {executeResult && (
          <div className="form-hint" data-testid="paper-trade-result">
            {executeResult}
          </div>
        )}
      </div>
    ),
    symbolSummary: (
      <div className="card span-2">
        <div className="card-title">{t("trade.symbolSummaryTitle")}</div>
        <div className="card-meta">{t("trade.symbolSummaryMeta")}</div>
        {renderRefreshSchedule("execution", "symbol-summary")}
        {detailError && <div className="form-hint">{detailError}</div>}
        <div className="meta-list" style={{ marginTop: "12px" }}>
          <div className="meta-row">
            <span>{t("trade.symbolSummaryUpdatedAt")}</span>
            <strong>
              {symbolSummaryUpdatedAt ? formatDateTime(symbolSummaryUpdatedAt) : t("common.none")}
            </strong>
          </div>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
        </div>
        <div className="table-scroll" style={{ marginTop: "12px" }}>
          <table className="table table-compact" data-testid="trade-symbol-summary-table">
            <thead>
              <tr>
                <th>{t("trade.symbolTable.symbol")}</th>
                <th>{t("trade.symbolTable.targetWeight")}</th>
                <th>{t("trade.symbolTable.currentWeight")}</th>
                <th>{t("trade.symbolTable.deltaWeight")}</th>
                <th>{t("trade.symbolTable.targetValue")}</th>
                <th>{t("trade.symbolTable.currentValue")}</th>
                <th>{t("trade.symbolTable.deltaValue")}</th>
                <th>{t("trade.symbolTable.currentQty")}</th>
                <th>{t("trade.symbolTable.status")}</th>
              </tr>
            </thead>
            <tbody>
              {symbolSummary.length ? (
                symbolSummary.map((row) => (
                  <tr key={row.symbol}>
                    <td>{row.symbol}</td>
                    <td>{formatPercent(row.target_weight ?? null)}</td>
                    <td>{formatPercent(row.current_weight ?? null)}</td>
                    <td>{formatPercent(row.delta_weight ?? null)}</td>
                    <td>{formatNumber(row.target_value ?? null)}</td>
                    <td>{formatNumber(row.current_value ?? null)}</td>
                    <td>{formatNumber(row.delta_value ?? null)}</td>
                    <td>{formatNumber(row.current_qty ?? null, 2)}</td>
                    <td>{row.last_status ? formatStatus(row.last_status) : t("common.none")}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={9} className="empty-state">
                    {detailLoading ? t("common.actions.loading") : t("trade.symbolSummaryEmpty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    ),
  };
  return (
    <div className="main">
      <TopBar title={t("trade.title")} />
      <div className="content">
        <div className="project-tabs">
          <button
            className={mainTab === "overview" ? "tab-button active" : "tab-button"}
            onClick={() => setMainTab("overview")}
          >
            {t("trade.mainSectionTitle")}
          </button>
          <button
            className={mainTab === "pipeline" ? "tab-button active" : "tab-button"}
            onClick={() => setMainTab("pipeline")}
          >
            {t("trade.pipelineTab")}
          </button>
        </div>
        <div
          className="pipeline-view"
          style={{ display: mainTab === "pipeline" ? "grid" : "none" }}
        >
          <div className="pipeline-list">
            <div className="card-title">{t("trade.pipeline.listTitle")}</div>
            <div className="card-meta">{t("trade.pipelineMeta")}</div>
            <div className="form-grid" style={{ marginTop: "12px" }}>
              <div className="form-row">
                <label className="form-label">{t("trade.pipeline.filters.project")}</label>
                <select
                  className="form-select"
                  value={selectedProjectId}
                  onChange={(event) => setSelectedProjectId(event.target.value)}
                >
                  <option value="">{t("trade.projectSelectPlaceholder")}</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      #{project.id} · {project.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">{t("trade.pipeline.filters.type")}</label>
                <select
                  className="form-select"
                  value={pipelineTypeFilter}
                  onChange={(event) => setPipelineTypeFilter(event.target.value)}
                >
                  <option value="">{t("trade.pipeline.filters.all")}</option>
                  {pipelineTypeOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">{t("trade.pipeline.filters.status")}</label>
                <select
                  className="form-select"
                  value={pipelineStatusFilter}
                  onChange={(event) => setPipelineStatusFilter(event.target.value)}
                >
                  <option value="">{t("trade.pipeline.filters.all")}</option>
                  {pipelineStatusOptions.map((item) => (
                    <option key={item} value={item}>
                      {formatStatus(item)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">{t("trade.pipeline.filters.mode")}</label>
                <select
                  className="form-select"
                  value={pipelineModeFilter}
                  onChange={(event) => setPipelineModeFilter(event.target.value)}
                >
                  <option value="">{t("trade.pipeline.filters.all")}</option>
                  {pipelineModeOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">{t("trade.pipeline.filters.dateFrom")}</label>
                <input
                  type="date"
                  className="form-input"
                  value={pipelineDateFrom}
                  onChange={(event) => setPipelineDateFrom(event.target.value)}
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("trade.pipeline.filters.dateTo")}</label>
                <input
                  type="date"
                  className="form-input"
                  value={pipelineDateTo}
                  onChange={(event) => setPipelineDateTo(event.target.value)}
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("trade.pipeline.filters.keyword")}</label>
                <input
                  className="form-input pipeline-keyword-input"
                  value={pipelineKeyword}
                  onChange={(event) => setPipelineKeyword(event.target.value)}
                  placeholder={t("trade.pipeline.filters.keyword")}
                />
              </div>
            </div>
            {pipelineRunsError && <div className="form-hint">{pipelineRunsError}</div>}
            {pipelineRunsLoading && (
              <div className="form-hint">{t("common.actions.loading")}</div>
            )}
            <div className="pipeline-run-list">
              {!selectedProjectId ? (
                <div className="empty-state">{t("trade.pipeline.projectRequired")}</div>
              ) : filteredPipelineRuns.length ? (
                filteredPipelineRuns.map((item) => (
                  <button
                    key={item.trace_id}
                    type="button"
                    className={
                      item.trace_id === pipelineTraceId
                        ? "pipeline-run-item active"
                        : "pipeline-run-item"
                    }
                    onClick={() => setPipelineTraceId(item.trace_id)}
                  >
                    <div className="pipeline-run-title">
                      <span>{item.run_type}</span>
                      <span className="pipeline-run-status">{formatStatus(item.status)}</span>
                    </div>
                    <div className="pipeline-run-meta">
                      <span>{item.trace_id}</span>
                      <span>
                        {item.created_at ? formatDateTime(item.created_at) : t("common.none")}
                      </span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="empty-state">{t("trade.pipeline.empty")}</div>
              )}
            </div>
          </div>
          <div className="pipeline-detail">
            <div className="card-title">{t("trade.pipeline.detailTitle")}</div>
            <div className="card-meta">{t("trade.pipeline.detailMeta")}</div>
            {pipelineDetailError && <div className="form-hint">{pipelineDetailError}</div>}
            {pipelineActionError && <div className="form-hint">{pipelineActionError}</div>}
            {pipelineActionResult && <div className="form-success">{pipelineActionResult}</div>}
            {pipelineDetailLoading && (
              <div className="form-hint">{t("common.actions.loading")}</div>
            )}
            <div className="pipeline-stage-lanes">
              <div className="pipeline-stage-lane">
                <div className="pipeline-stage-title">{t("trade.pipeline.stages.data")}</div>
              </div>
              <div className="pipeline-stage-lane">
                <div className="pipeline-stage-title">{t("trade.pipeline.stages.snapshot")}</div>
              </div>
              <div className="pipeline-stage-lane">
                <div className="pipeline-stage-title">{t("trade.pipeline.stages.pretrade")}</div>
              </div>
              <div className="pipeline-stage-lane">
                <div className="pipeline-stage-title">{t("trade.pipeline.stages.trade")}</div>
              </div>
              <div className="pipeline-stage-lane">
                <div className="pipeline-stage-title">{t("trade.pipeline.stages.audit")}</div>
              </div>
            </div>
            <div className="pipeline-event-drawer">
              <div className="pipeline-drawer-title">{t("trade.pipeline.drawerTitle")}</div>
              {pipelineSelectedEvent ? (
                <div className="pipeline-drawer-body">
                  <div className="meta-list" style={{ marginTop: "8px" }}>
                    <div className="meta-row">
                      <span>{t("trade.pipeline.drawerLabelType")}</span>
                      <strong>{pipelineSelectedEvent.task_type}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("trade.pipeline.drawerLabelId")}</span>
                      <strong>{pipelineSelectedEvent.task_id ?? t("common.none")}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("trade.pipeline.drawerLabelStatus")}</span>
                      <strong>
                        {pipelineSelectedEvent.status
                          ? formatStatus(pipelineSelectedEvent.status)
                          : t("common.none")}
                      </strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("trade.pipeline.drawerLabelError")}</span>
                      <strong>{pipelineSelectedEvent.error_code || t("common.none")}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("trade.pipeline.drawerLabelLog")}</span>
                      <strong>{pipelineSelectedEvent.log_path || t("common.none")}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("trade.pipeline.drawerLabelTags")}</span>
                      <strong>
                        {pipelineSelectedEvent.tags?.length
                          ? pipelineSelectedEvent.tags.join(", ")
                          : t("common.none")}
                      </strong>
                    </div>
                  </div>
                  {pipelineSelectedEvent.params_snapshot ? (
                    <pre className="pipeline-drawer-json">
                      {JSON.stringify(pipelineSelectedEvent.params_snapshot, null, 2)}
                    </pre>
                  ) : null}
                  {pipelineSelectedEvent.artifact_paths ? (
                    <pre className="pipeline-drawer-json">
                      {JSON.stringify(pipelineSelectedEvent.artifact_paths, null, 2)}
                    </pre>
                  ) : null}
                </div>
              ) : (
                <div className="pipeline-drawer-empty">{t("trade.pipeline.drawerEmpty")}</div>
              )}
            </div>
            <span className="pipeline-event-highlight" style={{ display: "none" }} />
            <div className="pipeline-events">
              {pipelineDetail?.events?.length ? (
                pipelineDetail.events.map((event) => {
                  const eventTags = event.tags || [];
                  const isHighlighted =
                    pipelineKeywordValue.length > 0 &&
                    eventTags.some((tag) =>
                      String(tag).toLowerCase().includes(pipelineKeywordValue)
                    );
                  const canRetryStep =
                    event.task_type === "pretrade_step" &&
                    pipelinePretradeRunId &&
                    event.task_id;
                  const canResumeRun =
                    event.task_type === "pretrade_run" && pipelinePretradeRunId;
                  const canExecuteTrade =
                    event.task_type === "trade_run" && event.task_id;
                  return (
                    <div
                      key={event.event_id}
                      className={`pipeline-event${isHighlighted ? " pipeline-event-highlight" : ""}`}
                      onClick={() => setPipelineSelectedEvent(event)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="pipeline-event-title">
                        <span>{event.task_type}</span>
                        {event.status ? (
                          <span className="pipeline-event-status">
                            {formatStatus(event.status)}
                          </span>
                        ) : null}
                      </div>
                      <div className="pipeline-event-meta">
                        <span>{event.message || t("common.none")}</span>
                        <span>
                          {event.started_at ? formatDateTime(event.started_at) : t("common.none")}
                        </span>
                      </div>
                      {(canRetryStep || canResumeRun || canExecuteTrade) && (
                        <div className="pipeline-event-actions">
                          {canRetryStep && event.task_id ? (
                            <button
                              type="button"
                              className="button-secondary button-compact"
                              disabled={pipelineActionLoading[`pretrade-step-${event.task_id}`]}
                              onClick={() => retryPipelineStep(event.task_id as number)}
                            >
                              {pipelineActionLoading[`pretrade-step-${event.task_id}`]
                                ? t("common.actions.loading")
                                : t("trade.pipeline.actions.retryStep")}
                            </button>
                          ) : null}
                          {canResumeRun ? (
                            <button
                              type="button"
                              className="button-secondary button-compact"
                              disabled={
                                pipelinePretradeRunId
                                  ? pipelineActionLoading[`pretrade-run-${pipelinePretradeRunId}`]
                                  : false
                              }
                              onClick={resumePipelineRun}
                            >
                              {pipelinePretradeRunId &&
                              pipelineActionLoading[`pretrade-run-${pipelinePretradeRunId}`]
                                ? t("common.actions.loading")
                                : t("trade.pipeline.actions.resumeRun")}
                            </button>
                          ) : null}
                          {canExecuteTrade && event.task_id ? (
                            <button
                              type="button"
                              className="button-secondary button-compact"
                              disabled={pipelineActionLoading[`trade-run-${event.task_id}`]}
                              onClick={() => executePipelineTrade(event.task_id as number)}
                            >
                              {pipelineActionLoading[`trade-run-${event.task_id}`]
                                ? t("common.actions.loading")
                                : t("trade.pipeline.actions.executeTrade")}
                            </button>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                })
              ) : (
                <div className="empty-state">{t("trade.pipeline.detailEmpty")}</div>
              )}
            </div>
          </div>
        </div>
        <div style={{ display: mainTab === "overview" ? "block" : "none" }}>
          <div className="section-title">{t("trade.mainSectionTitle")}</div>
          <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
            <button
              className="button-primary"
              data-testid="live-trade-refresh-all"
              onClick={() => refreshAll(true)}
              disabled={loading}
            >
              {loading ? t("common.actions.loading") : t("trade.refreshAll")}
            </button>
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <span>{t("trade.autoUpdateLabel")}</span>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={autoRefreshEnabled}
                  onChange={(event) => setAutoRefreshEnabled(event.target.checked)}
                  data-testid="live-trade-auto-toggle"
                />
                <span className="slider" />
              </label>
              <strong data-testid="auto-refresh-status">
                {autoRefreshEnabled ? t("trade.autoUpdateOn") : t("trade.autoUpdateOff")}
              </strong>
            </div>
          </div>
          <div className="live-trade-main-row">
            {sections.mainRow.map((key) => (
              <Fragment key={key}>{sectionCards[key]}</Fragment>
            ))}
          </div>
          <div className="grid-2">
            {sections.main.map((key) => {
              if (key === "guard") {
                return (
                  <div key="execution-guard" className="span-2 live-trade-execution-row">
                    {sectionCards.execution}
                    {sectionCards.guard}
                  </div>
                );
              }
              if (key === "execution") {
                return null;
              }
              return <Fragment key={key}>{sectionCards[key]}</Fragment>;
            })}
          </div>
          <details className="algo-advanced" style={{ marginTop: "16px" }}>
            <summary>{t("trade.advancedSectionTitle")}</summary>
            <div className="grid-2" style={{ marginTop: "12px" }}>
              {sections.advanced.map((key) => (
                <Fragment key={key}>{sectionCards[key]}</Fragment>
              ))}
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
