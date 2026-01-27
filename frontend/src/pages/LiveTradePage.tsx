import { useEffect, useMemo, useState } from "react";
import TopBar from "../components/TopBar";
import IdChip from "../components/IdChip";
import { api } from "../api";
import { useI18n } from "../i18n";
import { getOverviewStatus } from "../utils/ibOverview";
import { buildOrderTag } from "../utils/orderTag";

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

interface IBStatusOverview {
  connection?: {
    status?: string | null;
    message?: string | null;
    last_heartbeat?: string | null;
    updated_at?: string | null;
  };
  config?: {
    host?: string | null;
    port?: number | null;
    client_id?: number | null;
    account_id?: string | null;
    mode?: string | null;
    market_data_type?: string | null;
    api_mode?: string | null;
    use_regulatory_snapshot?: boolean | null;
  };
  stream?: {
    status?: string | null;
    subscribed_count?: number | null;
    last_heartbeat?: string | null;
    ib_error_count?: number | null;
    last_error?: string | null;
    market_data_type?: string | null;
  };
  snapshot_cache?: {
    status?: string | null;
    last_snapshot_at?: string | null;
    symbol_sample_count?: number | null;
  };
  orders?: {
    latest_order_id?: number | null;
    latest_order_status?: string | null;
    latest_order_at?: string | null;
    latest_fill_id?: number | null;
    latest_fill_at?: string | null;
  };
  alerts?: {
    latest_alert_id?: number | null;
    latest_alert_at?: string | null;
    latest_alert_title?: string | null;
  };
  partial?: boolean;
  errors?: string[];
  refreshed_at?: string | null;
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
  message?: string | null;
  created_at: string;
  ended_at?: string | null;
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
  status: string;
  created_at: string;
}

interface TradeFillDetail {
  id: number;
  order_id: number;
  exec_id?: string | null;
  fill_quantity: number;
  fill_price: number;
  commission?: number | null;
  fill_time?: string | null;
  currency?: string | null;
  exchange?: string | null;
}

interface TradeRunDetail {
  run: TradeRun;
  orders: TradeOrder[];
  fills: TradeFillDetail[];
  last_update_at?: string | null;
}

interface TradeSymbolSummary {
  symbol: string;
  target_weight?: number | null;
  target_value?: number | null;
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

export default function LiveTradePage() {
  const { t, formatDateTime } = useI18n();
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
  const [ibOverview, setIbOverview] = useState<IBStatusOverview | null>(null);
  const [ibOverviewLoading, setIbOverviewLoading] = useState(false);
  const [ibOverviewError, setIbOverviewError] = useState("");
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
  const [accountPositionsLoading, setAccountPositionsLoading] = useState(false);
  const [accountPositionsError, setAccountPositionsError] = useState("");
  const [positionSelections, setPositionSelections] = useState<Record<string, boolean>>({});
  const [positionQuantities, setPositionQuantities] = useState<Record<string, string>>({});
  const [positionActionLoading, setPositionActionLoading] = useState(false);
  const [positionActionError, setPositionActionError] = useState("");
  const [positionActionResult, setPositionActionResult] = useState("");
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
  const [marketSnapshot, setMarketSnapshot] = useState<IBMarketSnapshotItem | null>(null);
  const [marketSnapshotSymbol, setMarketSnapshotSymbol] = useState("");
  const [marketSnapshotLoading, setMarketSnapshotLoading] = useState(false);
  const [marketSnapshotError, setMarketSnapshotError] = useState("");
  const [tradeRuns, setTradeRuns] = useState<TradeRun[]>([]);
  const [tradeOrders, setTradeOrders] = useState<TradeOrder[]>([]);
  const [guardState, setGuardState] = useState<TradeGuardState | null>(null);
  const [tradeSettings, setTradeSettings] = useState<TradeSettings | null>(null);
  const [tradeSettingsError, setTradeSettingsError] = useState("");
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runDetail, setRunDetail] = useState<TradeRunDetail | null>(null);
  const [symbolSummary, setSymbolSummary] = useState<TradeSymbolSummary[]>([]);
  const [symbolSummaryUpdatedAt, setSymbolSummaryUpdatedAt] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<"orders" | "fills">("orders");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [executeForm, setExecuteForm] = useState({
    run_id: "",
    live_confirm_token: "",
  });
  const [executeLoading, setExecuteLoading] = useState(false);
  const [executeError, setExecuteError] = useState("");
  const [executeResult, setExecuteResult] = useState("");
  const [createRunLoading, setCreateRunLoading] = useState(false);
  const [createRunError, setCreateRunError] = useState("");
  const [createRunResult, setCreateRunResult] = useState("");
  const [guardLoading, setGuardLoading] = useState(false);
  const [guardError, setGuardError] = useState("");
  const [tradeError, setTradeError] = useState("");
  const [loading, setLoading] = useState(false);

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

  const createTradeRun = async () => {
    if (!selectedProjectId) {
      setCreateRunError(t("trade.executeBlockedProject"));
      return;
    }
    setCreateRunLoading(true);
    setCreateRunError("");
    setCreateRunResult("");
    try {
      const payload = {
        project_id: Number(selectedProjectId),
        decision_snapshot_id: snapshot?.id ?? undefined,
        mode: ibSettings?.mode || ibSettingsForm.mode || "paper",
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

  const loadIbOverview = async () => {
    setIbOverviewLoading(true);
    try {
      const res = await api.get<IBStatusOverview>("/api/brokerage/status/overview");
      setIbOverview(res.data);
      setIbOverviewError("");
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.overviewError");
      setIbOverviewError(String(detail));
    } finally {
      setIbOverviewLoading(false);
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

  const loadAccountPositions = async () => {
    setAccountPositionsLoading(true);
    setAccountPositionsError("");
    try {
      const res = await api.get<IBAccountPositionsOut>("/api/brokerage/account/positions", {
        params: { mode: ibSettings?.mode || ibSettingsForm.mode || "paper" },
      });
      setAccountPositions(res.data.items || []);
      setAccountPositionsUpdatedAt(res.data.refreshed_at || null);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("trade.accountPositionsError");
      setAccountPositionsError(String(detail));
      setAccountPositions([]);
      setAccountPositionsUpdatedAt(null);
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
    setPositionActionLoading(true);
    setPositionActionError("");
    setPositionActionResult("");
    try {
      await Promise.all(orders.map((payload) => api.post("/api/trade/orders", payload)));
      setPositionActionResult(t("trade.positionActionResult", { count: orders.length }));
      await loadTradeActivity();
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
    const confirmed = window.confirm(
      t("trade.positionOrderConfirm", {
        side,
        symbol: row.symbol,
        qty: formatNumber(quantity ?? null),
      })
    );
    if (!confirmed) {
      return;
    }
    const payload = {
      client_order_id: buildOrderTag(selectedRunId ?? latestTradeRun?.id ?? 0, index),
      symbol: row.symbol,
      side,
      quantity,
      order_type: "MKT",
      params: {
        account: row.account || undefined,
        currency: row.currency || undefined,
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
    const baseRunId = selectedRunId ?? latestTradeRun?.id ?? 0;
    const orders = positions.map((row, idx) => ({
      client_order_id: buildOrderTag(baseRunId, idx),
      symbol: row.symbol,
      side: row.position >= 0 ? "SELL" : "BUY",
      quantity: Math.abs(row.position ?? 0),
      order_type: "MKT",
      params: {
        account: row.account || undefined,
        currency: row.currency || undefined,
      },
    }));
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

  const loadTradeActivity = async () => {
    setTradeError("");
    setGuardError("");
    try {
      const [runsRes, ordersRes] = await Promise.all([
        api.get<TradeRun[]>("/api/trade/runs", { params: { limit: 5, offset: 0 } }),
        api.get<TradeOrder[]>("/api/trade/orders", { params: { limit: 5, offset: 0 } }),
      ]);
      const runs = runsRes.data || [];
      setTradeRuns(runs);
      setTradeOrders(ordersRes.data || []);
      const latestRun = runs[0];
      if (latestRun?.project_id) {
        await loadTradeGuard(latestRun.project_id, latestRun.mode || "paper");
      } else {
        setGuardState(null);
      }
    } catch (error) {
      setTradeError(t("trade.tradeError"));
      setTradeRuns([]);
      setTradeOrders([]);
      setGuardState(null);
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
      const res = await api.post<TradeRunExecuteOut>(`/api/trade/runs/${runId}/execute`, payload);
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

  const refreshAll = async () => {
    setLoading(true);
    await Promise.all([
      loadIbSettings(),
      loadIbOverview(),
      loadIbState(true),
      loadIbStreamStatus(true),
      loadIbHistoryJobs(),
      loadAccountSummary(false),
      loadAccountPositions(),
      loadTradeSettings(),
      loadTradeActivity(),
    ]);
    setLoading(false);
  };

  useEffect(() => {
    refreshAll();
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
    const refresh = async () => {
      await loadIbState(true);
      await loadIbStreamStatus(true);
    };
    const timer = window.setInterval(refresh, 10000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadIbOverview();
    }, 5000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const refresh = () => {
      loadAccountSummary(false);
      loadAccountPositions();
    };
    const timer = window.setInterval(refresh, 60000);
    return () => {
      window.clearInterval(timer);
    };
  }, [ibSettings?.mode, ibSettingsForm.mode]);

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
  }, [accountPositions]);

  const filteredTradeRuns = useMemo(() => {
    if (!selectedProjectId) {
      return tradeRuns;
    }
    return tradeRuns.filter((run) => String(run.project_id) === selectedProjectId);
  }, [selectedProjectId, tradeRuns]);

  const latestTradeRun = filteredTradeRuns[0];

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
    if (ibSettings?.market_data_type) {
      setIbStreamForm((prev) => ({
        ...prev,
        market_data_type: ibSettings.market_data_type,
      }));
    }
  }, [ibSettings?.market_data_type]);

  const streamSymbolKey = useMemo(() => {
    return (ibStreamStatus?.subscribed_symbols || []).join(",");
  }, [ibStreamStatus?.subscribed_symbols]);

  useEffect(() => {
    if (streamSymbolKey) {
      loadMarketSnapshot(ibStreamStatus?.subscribed_symbols?.[0]);
    } else {
      setMarketSnapshot(null);
      setMarketSnapshotSymbol("");
    }
  }, [streamSymbolKey]);

  const isConfigured = useMemo(() => {
    if (!ibSettings) {
      return false;
    }
    return Boolean(ibSettings.host && ibSettings.port);
  }, [ibSettings]);

  const overviewStatus = useMemo(() => getOverviewStatus(ibOverview), [ibOverview]);

  const overviewStatusLabel = useMemo(() => {
    if (overviewStatus === "ok") {
      return t("trade.overview.status.ok");
    }
    if (overviewStatus === "down") {
      return t("trade.overview.status.down");
    }
    if (overviewStatus === "partial") {
      return t("trade.overview.status.partial");
    }
    return t("trade.overview.status.unknown");
  }, [overviewStatus, t]);

  const bridgeIsStale = useMemo(() => {
    const snapshotStatus = ibOverview?.snapshot_cache?.status;
    const streamStatus = ibOverview?.stream?.status;
    return (
      accountSummary?.stale === true || snapshotStatus === "stale" || streamStatus === "degraded"
    );
  }, [accountSummary?.stale, ibOverview?.snapshot_cache?.status, ibOverview?.stream?.status]);

  const bridgeStatusLabel = useMemo(() => {
    const snapshotStatus = ibOverview?.snapshot_cache?.status;
    const streamStatus = ibOverview?.stream?.status;
    if (bridgeIsStale) {
      return t("trade.bridgeStatus.stale");
    }
    if (snapshotStatus || streamStatus) {
      return t("trade.bridgeStatus.ok");
    }
    return t("trade.bridgeStatus.unknown");
  }, [bridgeIsStale, ibOverview?.snapshot_cache?.status, ibOverview?.stream?.status, t]);

  const bridgeSource = useMemo(() => {
    return accountSummary?.source || "lean_bridge";
  }, [accountSummary?.source]);

  const bridgeUpdatedAt = useMemo(() => {
    return (
      ibOverview?.stream?.last_heartbeat ||
      ibOverview?.snapshot_cache?.last_snapshot_at ||
      accountSummary?.refreshed_at ||
      null
    );
  }, [
    accountSummary?.refreshed_at,
    ibOverview?.snapshot_cache?.last_snapshot_at,
    ibOverview?.stream?.last_heartbeat,
  ]);

  const positionsStale = useMemo(() => {
    return !accountPositionsLoading && accountPositions.length === 0 && bridgeIsStale;
  }, [accountPositions.length, accountPositionsLoading, bridgeIsStale]);

  const selectedProject = useMemo(() => {
    if (!selectedProjectId) {
      return null;
    }
    return projects.find((project) => String(project.id) === selectedProjectId) || null;
  }, [projects, selectedProjectId]);

  const snapshotReady = useMemo(() => Boolean(snapshot?.id), [snapshot?.id]);

  const canExecute = useMemo(
    () => Boolean(selectedProjectId) && snapshotReady,
    [selectedProjectId, snapshotReady]
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
    const key = `common.status.${String(value)}`;
    const translated = t(key);
    return translated === key ? String(value) : translated;
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

  return (
    <div className="main">
      <TopBar title={t("trade.title")} />
      <div className="content">
        <div className="grid-2">
          <div className="card">
            <div className="card-title">{t("trade.overviewTitle")}</div>
            <div className="card-meta">{t("trade.overviewMeta")}</div>
            {ibOverview?.partial && (
              <div className="form-hint" style={{ marginTop: "8px" }}>
                {t("trade.overviewPartial")}
              </div>
            )}
            <div className="overview-grid" style={{ marginTop: "12px" }}>
              <div className="overview-card">
                <div className="overview-label">{t("trade.overviewStatusLabel")}</div>
                <div className="overview-value">{overviewStatusLabel}</div>
                <div className="overview-sub">
                  {t("trade.overviewRefreshedAt")} {formatDateTime(ibOverview?.refreshed_at)}
                </div>
              </div>
              <div className="overview-card">
                <div className="overview-label">{t("trade.overviewStreamLabel")}</div>
                <div className="overview-value">
                  {formatStatus(ibOverview?.stream?.status || "unknown")}
                </div>
                <div className="overview-sub">
                  {t("trade.overviewStreamCount")}: {ibOverview?.stream?.subscribed_count ?? 0}
                </div>
              </div>
              <div className="overview-card">
                <div className="overview-label">{t("trade.overviewSnapshotLabel")}</div>
                <div className="overview-value">
                  {ibOverview?.snapshot_cache?.status || t("common.none")}
                </div>
                <div className="overview-sub">
                  {t("trade.overviewSnapshotAt")}{" "}
                  {formatDateTime(ibOverview?.snapshot_cache?.last_snapshot_at)}
                </div>
              </div>
              <div className="overview-card">
                <div className="overview-label">{t("trade.bridgeLabel")}</div>
                <div className="overview-value">{bridgeStatusLabel}</div>
                <div className="overview-sub">
                  {t("trade.bridgeSource")} {bridgeSource || t("common.none")}
                </div>
                <div className="overview-sub">
                  {t("trade.bridgeUpdatedAt")} {formatDateTime(bridgeUpdatedAt)}
                </div>
              </div>
              <div className="overview-card">
                <div className="overview-label">{t("trade.overviewOrderLabel")}</div>
                <div className="overview-value">
                  {ibOverview?.orders?.latest_order_status || t("common.none")}
                </div>
                <div className="overview-sub">
                  {t("trade.overviewOrderAt")}{" "}
                  {formatDateTime(ibOverview?.orders?.latest_order_at)}
                </div>
              </div>
            </div>
            <div className="meta-list" style={{ marginTop: "12px" }}>
              <div className="meta-row">
                <span>{t("trade.overviewAlertLabel")}</span>
                <strong>{ibOverview?.alerts?.latest_alert_title || t("common.none")}</strong>
              </div>
              <div className="meta-row">
                <span>{t("trade.overviewAlertAt")}</span>
                <strong>{formatDateTime(ibOverview?.alerts?.latest_alert_at)}</strong>
              </div>
            </div>
            {ibOverviewError && <div className="form-error">{ibOverviewError}</div>}
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button
                className="button-secondary"
                onClick={loadIbOverview}
                disabled={ibOverviewLoading}
              >
                {ibOverviewLoading ? t("common.actions.loading") : t("trade.overviewRefresh")}
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">{t("trade.statusTitle")}</div>
            <div className="card-meta">{t("trade.statusMeta")}</div>
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
                <div className="overview-label">{t("trade.modeLabel")}</div>
                <div className="overview-value">{modeLabel}</div>
                <div className="overview-sub">
                  {t("trade.marketDataType")}: {ibSettings?.market_data_type || t("common.none")}
                </div>
              </div>
            </div>
            {ibState && (
              <div className="meta-list" style={{ marginTop: "12px" }}>
                <div className="meta-row">
                  <span>{t("data.ib.status")}</span>
                  <strong>{formatStatus(ibState.status || "unknown")}</strong>
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
                    {ibState.last_heartbeat ? formatDateTime(ibState.last_heartbeat) : "-"}
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("data.ib.stateUpdated")}</span>
                  <strong>{ibState.updated_at ? formatDateTime(ibState.updated_at) : "-"}</strong>
                </div>
                {ibState.message && (
                  <div className="meta-row">
                    <span>{t("data.ib.message")}</span>
                    <strong>{ibState.message}</strong>
                  </div>
                )}
              </div>
            )}
            {ibStateResult && <div className="form-success">{ibStateResult}</div>}
            {ibStateError && <div className="form-error">{ibStateError}</div>}
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button
                className="button-secondary"
                onClick={() => loadIbState(false)}
                disabled={ibStateLoading}
              >
                {ibStateLoading ? t("common.actions.loading") : t("common.actions.refresh")}
              </button>
              <button
                className="button-secondary"
                onClick={probeIbState}
                disabled={ibStateLoading}
              >
                {ibStateLoading ? t("common.actions.loading") : t("data.ib.probe")}
              </button>
              <button className="button-secondary" onClick={refreshAll} disabled={loading}>
                {loading ? t("common.actions.loading") : t("trade.refresh")}
              </button>
              <a className="button-secondary" href="/data">
                {t("trade.openData")}
              </a>
            </div>
          </div>

          <div className="card">
            <div className="card-title">{t("trade.snapshotTitle")}</div>
            <div className="card-meta">{t("trade.snapshotMeta")}</div>
            <div className="snapshot-hero" style={{ marginTop: "12px" }}>
              <div className="snapshot-symbol">
                {marketSnapshotSymbol || t("trade.snapshotEmpty")}
              </div>
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
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button
                className="button-secondary"
                onClick={() => loadMarketSnapshot()}
                disabled={marketSnapshotLoading}
              >
                {marketSnapshotLoading ? t("common.actions.loading") : t("trade.snapshotRefresh")}
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">{t("trade.configTitle")}</div>
            <div className="card-meta">{t("trade.configMeta")}</div>
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
                <div className="overview-value">
                  {maskAccount(ibSettings?.account_id) || t("common.none")}
                </div>
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
                    onChange={(e) =>
                      updateIbSettingsForm("use_regulatory_snapshot", e.target.checked)
                    }
                  />
                  <span className="slider" />
                </label>
                <div className="form-hint">{t("data.ib.regulatorySnapshotHint")}</div>
              </div>
            </div>
            {ibSettingsResult && <div className="form-success">{ibSettingsResult}</div>}
            {ibSettingsError && <div className="form-error">{ibSettingsError}</div>}
            <button
              className="button-secondary"
              onClick={saveIbSettings}
              disabled={ibSettingsSaving}
            >
              {ibSettingsSaving ? t("common.actions.loading") : t("common.actions.save")}
            </button>
          </div>

          <div className="card" style={{ marginTop: "16px" }}>
            <div className="card-title">{t("trade.accountSummaryTitle")}</div>
            <div className="card-meta">{t("trade.accountSummaryMeta")}</div>
            {accountSummaryError && <div className="form-hint">{accountSummaryError}</div>}
            <div className="overview-grid" style={{ marginTop: "12px" }}>
              {accountSummaryItems.map((item) => (
                <div
                  className="overview-card"
                  key={item.key}
                  data-testid={`account-summary-${item.key}`}
                >
                  <div className="overview-label">{item.key}</div>
                  <div
                    className="overview-value"
                    data-testid={`account-summary-${item.key}-value`}
                  >
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
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button
                className="button-secondary"
                onClick={() => loadAccountSummary(true)}
                disabled={accountSummaryFullLoading}
              >
                {accountSummaryFullLoading
                  ? t("common.actions.loading")
                  : t("trade.accountSummaryRefresh")}
              </button>
            </div>
            {accountSummaryFullError && <div className="form-hint">{accountSummaryFullError}</div>}
            <details style={{ marginTop: "12px" }}>
              <summary>{t("trade.accountSummaryFullTitle")}</summary>
              <table className="table" style={{ marginTop: "8px" }}>
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
                        <td>{key}</td>
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
            </details>
          </div>

          <div
            className="card span-2"
            style={{ marginTop: "16px" }}
            data-testid="account-positions-card"
          >
            <div className="card-title">{t("trade.accountPositionsTitle")}</div>
            <div className="card-meta">{t("trade.accountPositionsMeta")}</div>
            {positionsStale && (
              <div className="form-hint warn" style={{ marginTop: "8px" }}>
                <div>{t("trade.accountPositionsStaleHint")}</div>
                <div className="meta-row" style={{ marginTop: "6px" }}>
                  <span>{t("trade.accountPositionsStaleUpdatedAt")}</span>
                  <strong>
                    {bridgeUpdatedAt ? formatDateTime(bridgeUpdatedAt) : t("common.none")}
                  </strong>
                  <button
                    className="button-compact"
                    onClick={loadAccountPositions}
                    disabled={accountPositionsLoading}
                  >
                    {accountPositionsLoading
                      ? t("common.actions.loading")
                      : t("trade.accountPositionsRefresh")}
                  </button>
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
              <table className="table" data-testid="account-positions-table">
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
                        positionQuantities[key] ??
                        String(Math.abs(row.position ?? 0) || 1);
                      return (
                        <tr key={key}>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={t("trade.positionActionSelectSymbol", {
                                symbol: row.symbol,
                              })}
                              checked={!!positionSelections[key]}
                              onChange={(event) =>
                                updatePositionSelection(key, event.target.checked)
                              }
                            />
                          </td>
                        <td>{row.symbol}</td>
                        <td>{formatNumber(row.position ?? null, 4)}</td>
                        <td>{formatNumber(row.avg_cost ?? null)}</td>
                        <td>{formatNumber(row.market_price ?? null)}</td>
                        <td>{formatNumber(row.market_value ?? null)}</td>
                        <td>{formatNumber(row.unrealized_pnl ?? null)}</td>
                        <td>{formatNumber(row.realized_pnl ?? null)}</td>
                        <td>{row.account || t("common.none")}</td>
                        <td>{row.currency || t("common.none")}</td>
                        <td>
                          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                            <input
                              className="form-input"
                              style={{ width: "90px" }}
                              type="number"
                              min="0"
                              step="1"
                              value={qtyValue}
                              onChange={(event) =>
                                updatePositionQuantity(key, event.target.value)
                              }
                            />
                            <button
                              className="button-compact"
                              onClick={() => handlePositionOrder(row, "BUY", index)}
                              disabled={positionActionLoading}
                            >
                              {t("trade.positionActionBuy")}
                            </button>
                            <button
                              className="button-compact"
                              onClick={() => handlePositionOrder(row, "SELL", index)}
                              disabled={positionActionLoading}
                            >
                              {t("trade.positionActionSell")}
                            </button>
                            <button
                              className="button-compact"
                              onClick={() => handleClosePositions([row])}
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
        </div>

        <div className="grid-2" style={{ marginTop: "16px" }}>
        <div className="card" style={{ marginTop: "16px" }}>
          <div className="card-title">{t("data.ib.streamTitle")}</div>
          <div className="card-meta">{t("data.ib.streamMeta")}</div>
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
            <button
              className="button-secondary"
              onClick={() => loadIbStreamStatus(false)}
              disabled={ibStreamLoading}
            >
              {ibStreamLoading ? t("common.actions.loading") : t("data.ib.streamRefresh")}
            </button>
          </div>
        </div>

        <div className="card">
          <div className="card-title">{t("data.ib.contractsTitle")}</div>
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
              {ibContractLoading ? t("common.actions.loading") : t("data.ib.contractsRefresh")}
            </button>
          </div>

          <div className="card">
            <div className="card-title">{t("data.ib.healthTitle")}</div>
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
                    onChange={(e) =>
                      updateIbMarketHealthForm("use_project_symbols", e.target.checked)
                    }
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
                    onChange={(e) =>
                      updateIbMarketHealthForm("fallback_history", e.target.checked)
                    }
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
                    onChange={(e) =>
                      updateIbMarketHealthForm("history_use_rth", e.target.checked)
                    }
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
        </div>

        <div className="card" style={{ marginTop: "16px" }}>
          <div className="card-title">{t("data.ib.historyTitle")}</div>
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
            <button
              className="button-secondary"
              onClick={loadIbHistoryJobs}
              disabled={ibHistoryLoading}
            >
              {ibHistoryLoading ? t("common.actions.loading") : t("common.actions.refresh")}
            </button>
          </div>
          {ibHistoryJobs.length > 0 ? (
            <table className="table" style={{ marginTop: "12px" }}>
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
          ) : (
            <div className="empty-state">{t("data.ib.historyEmpty")}</div>
          )}
        </div>

        <div className="card" style={{ marginTop: "16px" }}>
          <div className="card-title">{t("trade.projectBindingTitle")}</div>
          <div className="card-meta">{t("trade.projectBindingMeta")}</div>
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
          {!selectedProjectId && (
            <div className="form-hint">{t("trade.projectSelectHint")}</div>
          )}
          <div className="meta-list" style={{ marginTop: "12px" }}>
            <div className="meta-row">
              <span>{t("trade.snapshotStatus")}</span>
              <strong data-testid="live-trade-snapshot-status">
                {snapshotLoading
                  ? t("common.actions.loading")
                  : snapshotReady
                    ? t("trade.snapshotReady")
                    : t("trade.snapshotMissing")}
              </strong>
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

        <div className="grid-2" style={{ marginTop: "16px" }}>
          <div className="card">
            <div className="card-title">{t("trade.guardTitle")}</div>
            <div className="card-meta">{t("trade.guardMeta")}</div>
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
                  {t("trade.guardDrawdown")}:{" "}
                  {guardDrawdown !== null
                    ? `${(guardDrawdown * 100).toFixed(2)}%`
                    : t("common.none")}
                </div>
              </div>
              <div className="overview-card">
                <div className="overview-label">{t("trade.guardOrderFailures")}</div>
                <div className="overview-value">
                  {guardState ? guardState.order_failures : t("common.none")}
                </div>
                <div className="overview-sub">
                  {t("trade.guardMarketErrors")}:{" "}
                  {guardState ? guardState.market_data_errors : t("common.none")}
                </div>
              </div>
              <div className="overview-card">
                <div className="overview-label">{t("trade.guardRiskTriggers")}</div>
                <div className="overview-value">
                  {guardState ? guardState.risk_triggers : t("common.none")}
                </div>
                <div className="overview-sub">
                  {t("trade.guardCooldown")}:{" "}
                  {guardState?.cooldown_until
                    ? formatDateTime(guardState.cooldown_until)
                    : t("common.none")}
                </div>
              </div>
            </div>
            {guardState?.halt_reason ? (
              <div className="form-hint" style={{ marginTop: "8px" }}>
                {t("trade.guardReason")}: {guardReason}
              </div>
            ) : null}
          </div>
          <div className="card">
            <div className="card-title">{t("trade.executionTitle")}</div>
            <div className="card-meta">{t("trade.executionMeta")}</div>
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
                  <span
                    data-testid="paper-trade-status"
                    data-status={latestTradeRun?.status || ""}
                  >
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
            <table className="table" style={{ marginTop: "12px" }}>
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
                          <IdChip
                            label={t("trade.id.snapshot")}
                            value={run.decision_snapshot_id}
                          />
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
        </div>

        <div className="card" style={{ marginTop: "16px" }}>
          <div className="card-title">{t("trade.symbolSummaryTitle")}</div>
          <div className="card-meta">{t("trade.symbolSummaryMeta")}</div>
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
            <button
              className="button-secondary"
              disabled={detailLoading || !selectedRunId}
              onClick={() => selectedRunId && loadTradeRunData(selectedRunId)}
            >
              {detailLoading ? t("common.actions.loading") : t("trade.detailRefresh")}
            </button>
          </div>
          <table className="table" style={{ marginTop: "12px" }}>
            <thead>
              <tr>
                <th>{t("trade.symbolTable.symbol")}</th>
                <th>{t("trade.symbolTable.targetWeight")}</th>
                <th>{t("trade.symbolTable.targetValue")}</th>
                <th>{t("trade.symbolTable.filledQty")}</th>
                <th>{t("trade.symbolTable.avgPrice")}</th>
                <th>{t("trade.symbolTable.filledValue")}</th>
                <th>{t("trade.symbolTable.pendingQty")}</th>
                <th>{t("trade.symbolTable.deltaValue")}</th>
                <th>{t("trade.symbolTable.deltaWeight")}</th>
                <th>{t("trade.symbolTable.fillRatio")}</th>
                <th>{t("trade.symbolTable.status")}</th>
              </tr>
            </thead>
            <tbody>
              {symbolSummary.length ? (
                symbolSummary.map((row) => (
                  <tr key={row.symbol}>
                    <td>{row.symbol}</td>
                    <td>{formatPercent(row.target_weight ?? null)}</td>
                    <td>{formatNumber(row.target_value ?? null)}</td>
                    <td>{formatNumber(row.filled_qty ?? 0, 2)}</td>
                    <td>{formatNumber(row.avg_fill_price ?? null)}</td>
                    <td>{formatNumber(row.filled_value ?? 0)}</td>
                    <td>{formatNumber(row.pending_qty ?? 0, 2)}</td>
                    <td>{formatNumber(row.delta_value ?? null)}</td>
                    <td>{formatPercent(row.delta_weight ?? null)}</td>
                    <td>{formatPercent(row.fill_ratio ?? null)}</td>
                    <td>{row.last_status ? formatStatus(row.last_status) : t("common.none")}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={11} className="empty-state">
                    {detailLoading ? t("common.actions.loading") : t("trade.symbolSummaryEmpty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ marginTop: "16px" }}>
          <div className="card-title">{t("trade.monitorTitle")}</div>
          <div className="card-meta">{t("trade.monitorMeta")}</div>
          {tradeError && <div className="form-hint">{tradeError}</div>}
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <button
              className={detailTab === "orders" ? "button-primary" : "button-secondary"}
              onClick={() => setDetailTab("orders")}
            >
              {t("trade.ordersTitle")}
            </button>
            <button
              className={detailTab === "fills" ? "button-primary" : "button-secondary"}
              onClick={() => setDetailTab("fills")}
            >
              {t("trade.fillsTitle")}
            </button>
          </div>
          {detailTab === "orders" ? (
            <table className="table" style={{ marginTop: "12px" }}>
              <thead>
                <tr>
                  <th>{t("trade.orderTable.id")}</th>
                  <th>{t("trade.orderTable.clientOrderId")}</th>
                  <th>{t("trade.orderTable.symbol")}</th>
                  <th>{t("trade.orderTable.side")}</th>
                  <th>{t("trade.orderTable.qty")}</th>
                  <th>{t("trade.orderTable.status")}</th>
                  <th>{t("trade.orderTable.createdAt")}</th>
                </tr>
              </thead>
              <tbody>
                {(runDetail?.orders || tradeOrders).length ? (
                  (runDetail?.orders || tradeOrders).map((order) => (
                    <tr key={order.id}>
                      <td>#{order.id}</td>
                      <td>{order.client_order_id || t("common.none")}</td>
                      <td>{order.symbol || t("common.none")}</td>
                      <td>{formatSide(order.side)}</td>
                      <td>{order.quantity ?? t("common.none")}</td>
                      <td>{formatStatus(order.status)}</td>
                      <td>{formatDateTime(order.created_at)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="empty-state">
                      {t("trade.orderEmpty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          ) : (
            <table className="table" style={{ marginTop: "12px" }}>
              <thead>
                <tr>
                  <th>{t("trade.fillTable.orderId")}</th>
                  <th>{t("trade.fillTable.execId")}</th>
                  <th>{t("trade.fillTable.qty")}</th>
                  <th>{t("trade.fillTable.price")}</th>
                  <th>{t("trade.fillTable.commission")}</th>
                  <th>{t("trade.fillTable.exchange")}</th>
                  <th>{t("trade.fillTable.time")}</th>
                </tr>
              </thead>
              <tbody>
                {runDetail?.fills?.length ? (
                  runDetail.fills.map((fill) => (
                    <tr key={fill.id}>
                      <td>#{fill.order_id}</td>
                      <td>{fill.exec_id || t("common.none")}</td>
                      <td>{formatNumber(fill.fill_quantity, 2)}</td>
                      <td>{formatNumber(fill.fill_price, 4)}</td>
                      <td>{formatNumber(fill.commission ?? null, 4)}</td>
                      <td>{fill.exchange || t("common.none")}</td>
                      <td>{fill.fill_time ? formatDateTime(fill.fill_time) : t("common.none")}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="empty-state">
                      {t("trade.fillsEmpty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
