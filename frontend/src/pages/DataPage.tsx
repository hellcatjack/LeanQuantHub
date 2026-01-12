import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { api } from "../api";
import DatasetChartPanel from "../components/DatasetChartPanel";
import PaginationBar from "../components/PaginationBar";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { DatasetSummary, Paginated } from "../types";

interface DatasetQuality {
  dataset_id: number;
  frequency?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  coverage_days?: number | null;
  expected_points_estimate?: number | null;
  data_points?: number | null;
  min_interval_days?: number | null;
  issues: string[];
  status: string;
}

interface DatasetQualityScan {
  dataset_id: number;
  file_path: string;
  rows: number;
  coverage_start?: string | null;
  coverage_end?: string | null;
  missing_days?: number | null;
  missing_ratio?: number | null;
  null_close_rows: number;
  duplicate_timestamps: number;
  outlier_returns: number;
  max_abs_return?: number | null;
  issues: string[];
}

interface DataSyncJob {
  id: number;
  dataset_id: number;
  dataset_name?: string | null;
  source_path: string;
  date_column: string;
  reset_history?: boolean;
  retry_count?: number | null;
  next_retry_at?: string | null;
  status: string;
  rows_scanned?: number | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  normalized_path?: string | null;
  output_path?: string | null;
  snapshot_path?: string | null;
  lean_path?: string | null;
  adjusted_path?: string | null;
  lean_adjusted_path?: string | null;
  message?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

interface DataSyncSpeed {
  window_seconds: number;
  completed: number;
  rate_per_min: number;
  running: number;
  pending: number;
  target_rpm?: number | null;
  effective_min_delay_seconds?: number | null;
}

interface AlphaRateConfig {
  max_rpm: number;
  rpm_floor?: number;
  rpm_ceil?: number;
  rpm_step_down?: number;
  rpm_step_up?: number;
  min_delay_seconds: number;
  effective_min_delay_seconds: number;
  rate_limit_sleep: number;
  rate_limit_retries: number;
  max_retries: number;
  auto_tune?: boolean;
  min_delay_floor_seconds?: number;
  min_delay_ceil_seconds?: number;
  tune_step_seconds?: number;
  tune_window_seconds?: number;
  tune_target_ratio_low?: number;
  tune_target_ratio_high?: number;
  tune_cooldown_seconds?: number;
  source: string;
  updated_at?: string | null;
  path: string;
}

interface AlphaFetchConfig {
  alpha_incremental_enabled: boolean;
  alpha_compact_days: number;
  updated_at?: string | null;
  source: string;
  path: string;
}

interface TradingCalendarConfig {
  source: string;
  config_source?: string | null;
  exchange: string;
  start_date: string;
  end_date: string;
  refresh_days: number;
  override_enabled: boolean;
  updated_at?: string | null;
  path: string;
  calendar_source?: string | null;
  calendar_exchange?: string | null;
  calendar_start?: string | null;
  calendar_end?: string | null;
  calendar_generated_at?: string | null;
  calendar_sessions?: number | null;
  calendar_path?: string | null;
  overrides_path?: string | null;
  overrides_applied?: number | null;
}

interface TradingCalendarRefreshResult {
  status: string;
  log_path: string;
  return_code: number;
  calendar?: TradingCalendarConfig | null;
}

interface BulkAutoConfig {
  status: string;
  batch_size: number;
  only_missing: boolean;
  min_delay_seconds: number;
  refresh_listing_mode: string;
  refresh_listing_ttl_days: number;
  updated_at?: string | null;
  source: string;
  path: string;
}

interface AlphaGapSummary {
  latest_complete: string;
  total: number;
  with_coverage: number;
  missing_coverage: number;
  up_to_date: number;
  gap_0_30: number;
  gap_31_120: number;
  gap_120_plus: number;
  listing_updated_at?: string | null;
  listing_age_days?: number | null;
}

interface DataSyncQueueClearOut {
  deleted: number;
  statuses: string[];
  only_alpha: boolean;
}

interface BulkSyncJob {
  id: number;
  status: string;
  phase: string;
  total_symbols?: number | null;
  processed_symbols?: number | null;
  created_datasets?: number | null;
  reused_datasets?: number | null;
  queued_jobs?: number | null;
  offset?: number | null;
  batch_size?: number | null;
  pending_sync_jobs?: number | null;
  running_sync_jobs?: number | null;
  completed_sync_jobs?: number | null;
  message?: string | null;
  error?: string | null;
  updated_at?: string;
  started_at?: string | null;
  ended_at?: string | null;
}

interface PitWeeklyJob {
  id: number;
  status: string;
  params?: Record<string, unknown> | null;
  output_dir?: string | null;
  log_path?: string | null;
  snapshot_count?: number | null;
  last_snapshot_path?: string | null;
  message?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

interface PitWeeklyQuality {
  available?: boolean;
  status?: string;
  snapshots?: number;
  symbols?: number;
  duplicates?: number;
  invalid_rows?: number;
  date_mismatches?: number;
  out_of_life?: number;
  no_data?: number;
  fixed_files?: number;
  updated_at?: string;
}

interface PitWeeklyProgress {
  stage?: string | null;
  status?: string | null;
  message?: string | null;
  snapshot_count?: number | null;
  updated_at?: string | null;
}

interface PitFundamentalJob {
  id: number;
  status: string;
  params?: Record<string, unknown> | null;
  output_dir?: string | null;
  log_path?: string | null;
  snapshot_count?: number | null;
  last_snapshot_path?: string | null;
  message?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

interface PitFundamentalProgress {
  stage?: string;
  status?: string;
  total?: number;
  done?: number;
  pending?: number;
  ok?: number;
  partial?: number;
  rate_limited?: number;
  current_symbol?: string;
  updated_at?: string;
  snapshot_count?: number | null;
  total_symbols?: number;
  missing_count?: number;
  missing_path?: string;
  message?: string | null;
  rate_per_min?: number | null;
  target_rpm?: number | null;
  min_delay_seconds?: number | null;
  effective_min_delay_seconds?: number | null;
  auto_tune?: boolean | null;
  tune_window_seconds?: number | null;
  tune_action?: Record<string, unknown> | null;
}


interface UniverseTheme {
  key: string;
  label: string;
  symbols: number;
  updated_at?: string | null;
}

interface UniverseThemeSymbols {
  key: string;
  label?: string | null;
  symbols: string[];
  updated_at?: string | null;
}

interface ThemeCoverage {
  theme_key: string;
  theme_label?: string | null;
  total_symbols: number;
  covered_symbols: number;
  missing_symbols: string[];
  updated_at?: string | null;
}


export default function DataPage() {
  const { t, formatDateTime } = useI18n();
  const pitFundDefaultStart = "1995-01-01";
  const pitFundDefaultEnd = new Date().toISOString().slice(0, 10);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetTotal, setDatasetTotal] = useState(0);
  const [datasetPage, setDatasetPage] = useState(1);
  const [datasetPageSize, setDatasetPageSize] = useState(10);
  const [frequencyFilter, setFrequencyFilter] = useState<"all" | "daily" | "minute">("all");
  const [themeFilter, setThemeFilter] = useState("all");
  const [themeOptions, setThemeOptions] = useState<UniverseTheme[]>([]);
  const [themeSymbols, setThemeSymbols] = useState<Set<string>>(new Set());
  const [themeLoading, setThemeLoading] = useState(false);
  const [themeError, setThemeError] = useState("");
  const [themeCoverage, setThemeCoverage] = useState<ThemeCoverage | null>(null);
  const [themeCoverageLoading, setThemeCoverageLoading] = useState(false);
  const [themeCoverageError, setThemeCoverageError] = useState("");
  const [form, setForm] = useState({
    name: "",
    vendor: "",
    asset_class: "",
    region: "",
    frequency: "",
    coverage_start: "",
    coverage_end: "",
    source_path: "",
  });
  const [resetHistory, setResetHistory] = useState(false);
  const [formError, setFormError] = useState("");
  const [qualityMap, setQualityMap] = useState<Record<number, DatasetQuality>>({});
  const [qualityLoading, setQualityLoading] = useState<Record<number, boolean>>({});
  const [qualityErrors, setQualityErrors] = useState<Record<number, string>>({});
  const qualityAbortRef = useRef<Record<number, AbortController>>({});
  const deletingDatasetIdsRef = useRef<Set<number>>(new Set());
  const [scanForm, setScanForm] = useState({
    dataset_id: "",
    file_path: "",
    date_column: "date",
    close_column: "close",
    frequency: "",
  });
  const [scanResult, setScanResult] = useState<DatasetQualityScan | null>(null);
  const [scanError, setScanError] = useState("");
  const [syncForm, setSyncForm] = useState({
    dataset_id: "",
    source_path: "",
    date_column: "date",
  });
  const [syncError, setSyncError] = useState("");
  const [syncing, setSyncing] = useState<Record<number, boolean>>({});
  const [syncAllLoading, setSyncAllLoading] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState<Record<string, boolean>>({});
  const [listError, setListError] = useState("");
  const [syncJobs, setSyncJobs] = useState<DataSyncJob[]>([]);
  const [syncTotal, setSyncTotal] = useState(0);
  const [syncPage, setSyncPage] = useState(1);
  const [syncPageSize, setSyncPageSize] = useState(10);
  const [syncSpeed, setSyncSpeed] = useState<DataSyncSpeed | null>(null);
  const [clearQueueLoading, setClearQueueLoading] = useState(false);
  const [clearQueueResult, setClearQueueResult] = useState("");
  const [clearQueueError, setClearQueueError] = useState("");
  const [alphaRate, setAlphaRate] = useState<AlphaRateConfig | null>(null);
  const [alphaRateForm, setAlphaRateForm] = useState({
    max_rpm: "75",
    rpm_floor: "80",
    rpm_ceil: "75",
    rpm_step_down: "5",
    rpm_step_up: "1",
    min_delay_seconds: "0.8",
    rate_limit_sleep: "10",
    rate_limit_retries: "3",
    max_retries: "3",
    auto_tune: false,
    min_delay_floor_seconds: "0.1",
    min_delay_ceil_seconds: "2.0",
    tune_step_seconds: "0.02",
    tune_window_seconds: "60",
    tune_target_ratio_low: "0.9",
    tune_target_ratio_high: "1.05",
    tune_cooldown_seconds: "10",
  });
  const [alphaRateSaving, setAlphaRateSaving] = useState(false);
  const [alphaRateResult, setAlphaRateResult] = useState("");
  const [alphaRateError, setAlphaRateError] = useState("");
  const [alphaFetchConfig, setAlphaFetchConfig] = useState<AlphaFetchConfig | null>(null);
  const [alphaFetchForm, setAlphaFetchForm] = useState({
    alpha_incremental_enabled: true,
    alpha_compact_days: "120",
  });
  const [alphaFetchSaving, setAlphaFetchSaving] = useState(false);
  const [alphaFetchError, setAlphaFetchError] = useState("");
  const [tradingCalendar, setTradingCalendar] = useState<TradingCalendarConfig | null>(null);
  const [tradingCalendarForm, setTradingCalendarForm] = useState({
    source: "auto",
    exchange: "XNYS",
    start_date: "1990-01-01",
    end_date: "",
    refresh_days: "7",
    override_enabled: true,
  });
  const [tradingCalendarSaving, setTradingCalendarSaving] = useState(false);
  const [tradingCalendarRefreshing, setTradingCalendarRefreshing] = useState(false);
  const [tradingCalendarResult, setTradingCalendarResult] = useState("");
  const [tradingCalendarError, setTradingCalendarError] = useState("");
  const [bulkAutoConfig, setBulkAutoConfig] = useState<BulkAutoConfig | null>(null);
  const [bulkAutoLoadError, setBulkAutoLoadError] = useState("");
  const [bulkDefaultsSaving, setBulkDefaultsSaving] = useState(false);
  const [bulkDefaultsResult, setBulkDefaultsResult] = useState("");
  const [bulkDefaultsError, setBulkDefaultsError] = useState("");
  const [alphaGapSummary, setAlphaGapSummary] = useState<AlphaGapSummary | null>(null);
  const [alphaGapLoading, setAlphaGapLoading] = useState(false);
  const [alphaGapError, setAlphaGapError] = useState("");
  const [bulkAutoForm, setBulkAutoForm] = useState({
    status: "all",
    batch_size: "200",
    only_missing: true,
    min_delay_seconds: "0.1",
    refresh_listing_mode: "stale_only",
    refresh_listing_ttl_days: "7",
  });
  const [bulkJob, setBulkJob] = useState<BulkSyncJob | null>(null);
  const [bulkJobLoading, setBulkJobLoading] = useState(false);
  const [bulkJobError, setBulkJobError] = useState("");
  const [bulkHistory, setBulkHistory] = useState<BulkSyncJob[]>([]);
  const [bulkHistoryTotal, setBulkHistoryTotal] = useState(0);
  const [bulkHistoryPage, setBulkHistoryPage] = useState(1);
  const [bulkHistoryPageSize, setBulkHistoryPageSize] = useState(5);
  const [bulkActionLoading, setBulkActionLoading] = useState<Record<number, boolean>>({});
  const [pitForm, setPitForm] = useState({
    start: "",
    end: "",
    require_data: false,
  });
  const [pitJobs, setPitJobs] = useState<PitWeeklyJob[]>([]);
  const [pitLoadError, setPitLoadError] = useState("");
  const [pitActionLoading, setPitActionLoading] = useState(false);
  const [pitActionError, setPitActionError] = useState("");
  const [pitActionResult, setPitActionResult] = useState("");
  const [pitQuality, setPitQuality] = useState<PitWeeklyQuality | null>(null);
  const [pitQualityError, setPitQualityError] = useState("");
  const [pitProgress, setPitProgress] = useState<PitWeeklyProgress | null>(null);
  const [pitProgressError, setPitProgressError] = useState("");
  const [pitFundForm, setPitFundForm] = useState({
    start: pitFundDefaultStart,
    end: pitFundDefaultEnd,
    report_delay_days: "1",
    missing_report_delay_days: "45",
    shares_delay_days: "45",
    shares_preference: "diluted",
    price_source: "raw",
    min_delay_seconds: "0.45",
    refresh_days: "0",
    refresh_fundamentals: false,
    asset_types: "STOCK",
  });
  const [pitFundJobs, setPitFundJobs] = useState<PitFundamentalJob[]>([]);
  const [pitFundLoadError, setPitFundLoadError] = useState("");
  const [pitFundActionLoading, setPitFundActionLoading] = useState(false);
  const [pitFundActionError, setPitFundActionError] = useState("");
  const [pitFundActionResult, setPitFundActionResult] = useState("");
  const [pitFundProgress, setPitFundProgress] = useState<PitFundamentalProgress | null>(null);
  const [pitFundProgressError, setPitFundProgressError] = useState("");
  const [pitFundProgressMap, setPitFundProgressMap] = useState<
    Record<number, PitFundamentalProgress | null>
  >({});
  const [pitFundResumeLoading, setPitFundResumeLoading] = useState<Record<number, boolean>>(
    {}
  );
  const [pitFundCancelLoading, setPitFundCancelLoading] = useState<Record<number, boolean>>(
    {}
  );
  const [expandedGroupKey, setExpandedGroupKey] = useState<string | null>(null);
  const [chartSelection, setChartSelection] = useState<Record<string, number>>({});

  const loadDatasets = async () => {
    const res = await api.get<Paginated<DatasetSummary>>("/api/datasets/page", {
      params: { page: datasetPage, page_size: datasetPageSize },
    });
    setDatasets(res.data.items);
    setDatasetTotal(res.data.total);
  };

  const loadSyncJobs = async () => {
    const res = await api.get<Paginated<DataSyncJob>>("/api/datasets/sync-jobs/page", {
      params: { page: syncPage, page_size: syncPageSize },
    });
    setSyncJobs(res.data.items);
    setSyncTotal(res.data.total);
  };

  const loadBulkHistory = async () => {
    const res = await api.get<Paginated<BulkSyncJob>>("/api/datasets/bulk-sync-jobs/page", {
      params: { page: bulkHistoryPage, page_size: bulkHistoryPageSize },
    });
    setBulkHistory(res.data.items);
    setBulkHistoryTotal(res.data.total);
  };

  const loadPitWeeklyJobs = async () => {
    try {
      const res = await api.get<PitWeeklyJob[]>("/api/pit/weekly-jobs", {
        params: { limit: 5, offset: 0 },
      });
      setPitJobs(res.data);
      setPitLoadError("");
      return res.data;
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setPitJobs([]);
        setPitLoadError("");
        return [];
      }
      const detail = err?.response?.data?.detail || t("data.pit.loadError");
      setPitLoadError(String(detail));
      return [];
    }
  };

  const loadPitQuality = async (jobId: number) => {
    try {
      const res = await api.get<PitWeeklyQuality>(`/api/pit/weekly-jobs/${jobId}/quality`);
      setPitQuality(res.data);
      setPitQualityError("");
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setPitQuality(null);
        setPitQualityError("");
        return;
      }
      const detail = err?.response?.data?.detail || t("data.pit.qualityError");
      setPitQualityError(String(detail));
    }
  };

  const loadPitProgress = async (jobId: number) => {
    try {
      const res = await api.get<PitWeeklyProgress>(`/api/pit/weekly-jobs/${jobId}/progress`);
      setPitProgress(res.data);
      setPitProgressError("");
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setPitProgress(null);
        setPitProgressError("");
        return;
      }
      const detail = err?.response?.data?.detail || t("data.pit.progressError");
      setPitProgressError(String(detail));
    }
  };

  const loadPitFundJobs = async () => {
    try {
      const res = await api.get<PitFundamentalJob[]>("/api/pit/fundamental-jobs", {
        params: { limit: 5, offset: 0 },
      });
      setPitFundJobs(res.data);
      setPitFundLoadError("");
      return res.data;
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setPitFundJobs([]);
        setPitFundLoadError("");
        return [];
      }
      const detail = err?.response?.data?.detail || t("data.pitFund.loadError");
      setPitFundLoadError(String(detail));
      return [];
    }
  };

  const loadPitFundProgress = async (jobId: number) => {
    try {
      const res = await api.get<PitFundamentalProgress>(
        `/api/pit/fundamental-jobs/${jobId}/progress`
      );
      setPitFundProgress(res.data);
      setPitFundProgressError("");
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setPitFundProgress(null);
        setPitFundProgressError("");
        return;
      }
      const detail = err?.response?.data?.detail || t("data.pitFund.progressError");
      setPitFundProgressError(String(detail));
    }
  };

  const loadPitFundProgressMap = async (jobs: PitFundamentalJob[]) => {
    if (!jobs.length) {
      setPitFundProgressMap({});
      return;
    }
    const entries = await Promise.all(
      jobs.map(async (job) => {
        try {
          const res = await api.get<PitFundamentalProgress>(
            `/api/pit/fundamental-jobs/${job.id}/progress`
          );
          return [job.id, res.data] as const;
        } catch (err: any) {
          return [job.id, null] as const;
        }
      })
    );
    setPitFundProgressMap(Object.fromEntries(entries));
  };

  const loadSyncSpeed = async () => {
    const res = await api.get<DataSyncSpeed>("/api/datasets/sync-jobs/speed", {
      params: { window_seconds: 60 },
    });
    return res.data;
  };

  const loadAlphaRate = async () => {
    try {
      const res = await api.get<AlphaRateConfig>("/api/datasets/alpha-rate");
      setAlphaRate(res.data);
      setAlphaRateForm({
        max_rpm: String(res.data.max_rpm ?? ""),
        rpm_floor: String(res.data.rpm_floor ?? ""),
        rpm_ceil: String(res.data.rpm_ceil ?? ""),
        rpm_step_down: String(res.data.rpm_step_down ?? ""),
        rpm_step_up: String(res.data.rpm_step_up ?? ""),
        min_delay_seconds: String(res.data.min_delay_seconds ?? ""),
        rate_limit_sleep: String(res.data.rate_limit_sleep ?? ""),
        rate_limit_retries: String(res.data.rate_limit_retries ?? ""),
        max_retries: String(res.data.max_retries ?? ""),
        auto_tune: !!res.data.auto_tune,
        min_delay_floor_seconds: String(res.data.min_delay_floor_seconds ?? ""),
        min_delay_ceil_seconds: String(res.data.min_delay_ceil_seconds ?? ""),
        tune_step_seconds: String(res.data.tune_step_seconds ?? ""),
        tune_window_seconds: String(res.data.tune_window_seconds ?? ""),
        tune_target_ratio_low: String(res.data.tune_target_ratio_low ?? ""),
        tune_target_ratio_high: String(res.data.tune_target_ratio_high ?? ""),
        tune_cooldown_seconds: String(res.data.tune_cooldown_seconds ?? ""),
      });
      setAlphaRateError("");
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.alphaRate.loadError");
      setAlphaRateError(String(detail));
    }
  };

  const loadAlphaFetchConfig = async () => {
    try {
      const res = await api.get<AlphaFetchConfig>("/api/datasets/alpha-fetch-config");
      setAlphaFetchConfig(res.data);
      setAlphaFetchForm({
        alpha_incremental_enabled: !!res.data.alpha_incremental_enabled,
        alpha_compact_days: String(res.data.alpha_compact_days ?? ""),
      });
      setAlphaFetchError("");
      return res.data;
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.bulk.incremental.loadError");
      setAlphaFetchError(String(detail));
      return null;
    }
  };

  const loadTradingCalendar = async () => {
    try {
      const res = await api.get<TradingCalendarConfig>("/api/datasets/trading-calendar");
      setTradingCalendar(res.data);
      setTradingCalendarForm({
        source: res.data.source || "auto",
        exchange: res.data.exchange || "XNYS",
        start_date: res.data.start_date || "1990-01-01",
        end_date: res.data.end_date || "",
        refresh_days: String(res.data.refresh_days ?? ""),
        override_enabled: !!res.data.override_enabled,
      });
      setTradingCalendarError("");
      return res.data;
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail || t("data.tradingCalendar.loadError");
      setTradingCalendarError(String(detail));
      return null;
    }
  };

  const loadBulkAutoConfig = async () => {
    try {
      const res = await api.get<BulkAutoConfig>("/api/datasets/bulk-auto-config");
      setBulkAutoConfig(res.data);
      setBulkAutoForm({
        status: res.data.status || "all",
        batch_size: String(res.data.batch_size ?? ""),
        only_missing: !!res.data.only_missing,
        min_delay_seconds: String(res.data.min_delay_seconds ?? ""),
        refresh_listing_mode: res.data.refresh_listing_mode || "stale_only",
        refresh_listing_ttl_days: String(res.data.refresh_listing_ttl_days ?? ""),
      });
      setBulkAutoLoadError("");
      return res.data;
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.bulk.defaults.loadError");
      setBulkAutoLoadError(String(detail));
      return null;
    }
  };

  const saveBulkAutoConfig = async () => {
    try {
      const payload = {
        status: bulkAutoForm.status,
        batch_size: Number.parseInt(bulkAutoForm.batch_size, 10) || 0,
        only_missing: !!bulkAutoForm.only_missing,
        min_delay_seconds: Number.parseFloat(bulkAutoForm.min_delay_seconds) || 0,
        refresh_listing_mode: bulkAutoForm.refresh_listing_mode,
        refresh_listing_ttl_days: Number.parseInt(bulkAutoForm.refresh_listing_ttl_days, 10) || 0,
      };
      const res = await api.post<BulkAutoConfig>("/api/datasets/bulk-auto-config", payload);
      setBulkAutoConfig(res.data);
      return true;
    } catch (err) {
      return false;
    }
  };

  const saveBulkDefaults = async (silent = false) => {
    setBulkDefaultsSaving(true);
    if (!silent) {
      setBulkDefaultsResult("");
      setBulkDefaultsError("");
    }
    const autoOk = await saveBulkAutoConfig();
    const fetchOk = await saveAlphaFetchConfig(true);
    const ok = autoOk && fetchOk;
    if (!silent) {
      if (ok) {
        setBulkDefaultsResult(t("data.bulk.defaults.saved"));
      } else {
        setBulkDefaultsError(t("data.bulk.defaults.saveError"));
      }
    }
    setBulkDefaultsSaving(false);
    return ok;
  };

  const saveAlphaFetchConfig = async (silent = false) => {
    setAlphaFetchSaving(true);
    if (!silent) {
      setAlphaFetchError("");
    }
    try {
      const payload = {
        alpha_incremental_enabled: !!alphaFetchForm.alpha_incremental_enabled,
        alpha_compact_days: Number.parseInt(alphaFetchForm.alpha_compact_days, 10) || 0,
      };
      const res = await api.post<AlphaFetchConfig>(
        "/api/datasets/alpha-fetch-config",
        payload
      );
      setAlphaFetchConfig(res.data);
      return true;
    } catch (err: any) {
      if (!silent) {
        const detail = err?.response?.data?.detail || t("data.bulk.incremental.saveError");
        setAlphaFetchError(String(detail));
      }
      return false;
    } finally {
      setAlphaFetchSaving(false);
    }
  };

  const loadAlphaGapSummary = async () => {
    setAlphaGapLoading(true);
    setAlphaGapError("");
    try {
      const res = await api.get<AlphaGapSummary>("/api/datasets/alpha-gap-summary");
      setAlphaGapSummary(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.bulk.gap.loadError");
      setAlphaGapError(String(detail));
      setAlphaGapSummary(null);
    } finally {
      setAlphaGapLoading(false);
    }
  };

  const updateAlphaRateForm = (
    key: keyof typeof alphaRateForm,
    value: string | boolean
  ) => {
    setAlphaRateForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateAlphaFetchForm = (
    key: keyof typeof alphaFetchForm,
    value: string | boolean
  ) => {
    setAlphaFetchForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateTradingCalendarForm = (
    key: keyof typeof tradingCalendarForm,
    value: string | boolean
  ) => {
    setTradingCalendarForm((prev) => ({ ...prev, [key]: value }));
  };

  const saveTradingCalendar = async () => {
    setTradingCalendarSaving(true);
    setTradingCalendarResult("");
    setTradingCalendarError("");
    try {
      const payload = {
        source: tradingCalendarForm.source,
        exchange: tradingCalendarForm.exchange,
        start_date: tradingCalendarForm.start_date,
        end_date: tradingCalendarForm.end_date,
        refresh_days: Number.parseInt(tradingCalendarForm.refresh_days, 10) || 0,
        override_enabled: !!tradingCalendarForm.override_enabled,
      };
      const res = await api.post<TradingCalendarConfig>(
        "/api/datasets/trading-calendar",
        payload
      );
      setTradingCalendar(res.data);
      setTradingCalendarResult(t("data.tradingCalendar.saved"));
      return true;
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail || t("data.tradingCalendar.saveError");
      setTradingCalendarError(String(detail));
      return false;
    } finally {
      setTradingCalendarSaving(false);
    }
  };

  const refreshTradingCalendar = async () => {
    setTradingCalendarRefreshing(true);
    setTradingCalendarResult("");
    setTradingCalendarError("");
    try {
      const res = await api.post<TradingCalendarRefreshResult>(
        "/api/datasets/trading-calendar/refresh"
      );
      if (res.data.calendar) {
        setTradingCalendar(res.data.calendar);
        setTradingCalendarForm({
          source: res.data.calendar.source || "auto",
          exchange: res.data.calendar.exchange || "XNYS",
          start_date: res.data.calendar.start_date || "1990-01-01",
          end_date: res.data.calendar.end_date || "",
          refresh_days: String(res.data.calendar.refresh_days ?? ""),
          override_enabled: !!res.data.calendar.override_enabled,
        });
      } else {
        await loadTradingCalendar();
      }
      setTradingCalendarResult(t("data.tradingCalendar.refreshed"));
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail || t("data.tradingCalendar.refreshError");
      setTradingCalendarError(String(detail));
    } finally {
      setTradingCalendarRefreshing(false);
    }
  };

  const saveAlphaRate = async () => {
    setAlphaRateSaving(true);
    setAlphaRateResult("");
    setAlphaRateError("");
    try {
      const payload = {
        max_rpm: Number.parseFloat(alphaRateForm.max_rpm) || 0,
        rpm_floor: Number.parseFloat(alphaRateForm.rpm_floor) || 0,
        rpm_ceil: Number.parseFloat(alphaRateForm.rpm_ceil) || 0,
        rpm_step_down: Number.parseFloat(alphaRateForm.rpm_step_down) || 0,
        rpm_step_up: Number.parseFloat(alphaRateForm.rpm_step_up) || 0,
        min_delay_seconds: Number.parseFloat(alphaRateForm.min_delay_seconds) || 0,
        rate_limit_sleep: Number.parseFloat(alphaRateForm.rate_limit_sleep) || 0,
        rate_limit_retries: Number.parseInt(alphaRateForm.rate_limit_retries, 10) || 0,
        max_retries: Number.parseInt(alphaRateForm.max_retries, 10) || 0,
        auto_tune: !!alphaRateForm.auto_tune,
        min_delay_floor_seconds:
          Number.parseFloat(alphaRateForm.min_delay_floor_seconds) || 0,
        min_delay_ceil_seconds:
          Number.parseFloat(alphaRateForm.min_delay_ceil_seconds) || 0,
        tune_step_seconds: Number.parseFloat(alphaRateForm.tune_step_seconds) || 0,
        tune_window_seconds: Number.parseFloat(alphaRateForm.tune_window_seconds) || 0,
        tune_target_ratio_low:
          Number.parseFloat(alphaRateForm.tune_target_ratio_low) || 0,
        tune_target_ratio_high:
          Number.parseFloat(alphaRateForm.tune_target_ratio_high) || 0,
        tune_cooldown_seconds:
          Number.parseFloat(alphaRateForm.tune_cooldown_seconds) || 0,
      };
      const res = await api.post<AlphaRateConfig>("/api/datasets/alpha-rate", payload);
      setAlphaRate(res.data);
      setAlphaRateResult(t("data.alphaRate.saved"));
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.alphaRate.saveError");
      setAlphaRateError(String(detail));
    } finally {
      setAlphaRateSaving(false);
    }
  };

  const clearSyncQueue = async () => {
    if (!window.confirm(t("data.jobs.clearConfirm"))) {
      return;
    }
    setClearQueueLoading(true);
    setClearQueueResult("");
    setClearQueueError("");
    try {
      const res = await api.post<DataSyncQueueClearOut>("/api/datasets/sync-jobs/clear");
      setClearQueueResult(t("data.jobs.clearDone", { count: res.data.deleted }));
      await loadSyncJobs();
      const data = await loadSyncSpeed();
      setSyncSpeed(data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.jobs.clearError");
      setClearQueueError(detail);
    } finally {
      setClearQueueLoading(false);
    }
  };

  const loadThemeOptions = async () => {
    setThemeError("");
    setThemeLoading(true);
    try {
      const res = await api.get<{ items: UniverseTheme[] }>("/api/universe/themes");
      setThemeOptions(res.data.items || []);
    } catch (err) {
      setThemeError(t("data.list.theme.error"));
    } finally {
      setThemeLoading(false);
    }
  };

  const loadThemeSymbols = async (themeKey: string) => {
    if (!themeKey || themeKey === "all") {
      setThemeSymbols(new Set());
      return;
    }
    setThemeError("");
    setThemeLoading(true);
    try {
      const res = await api.get<UniverseThemeSymbols>(
        `/api/universe/themes/${encodeURIComponent(themeKey)}/symbols`
      );
      setThemeSymbols(new Set(res.data.symbols || []));
    } catch (err) {
      setThemeError(t("data.list.theme.error"));
      setThemeSymbols(new Set());
    } finally {
      setThemeLoading(false);
    }
  };

  const loadThemeCoverage = async (themeKey: string) => {
    if (!themeKey || themeKey === "all") {
      setThemeCoverage(null);
      return;
    }
    setThemeCoverageError("");
    setThemeCoverageLoading(true);
    try {
      const res = await api.get<ThemeCoverage>("/api/datasets/theme-coverage", {
        params: { theme_key: themeKey },
      });
      setThemeCoverage(res.data);
    } catch (err) {
      setThemeCoverage(null);
      setThemeCoverageError(t("data.list.theme.coverageError"));
    } finally {
      setThemeCoverageLoading(false);
    }
  };

  useEffect(() => {
    loadDatasets();
  }, [datasetPage, datasetPageSize]);

  useEffect(() => {
    loadSyncJobs();
  }, [syncPage, syncPageSize]);

  useEffect(() => {
    loadBulkHistory();
  }, [bulkHistoryPage, bulkHistoryPageSize]);

  useEffect(() => {
    loadAlphaRate();
    loadAlphaFetchConfig();
    loadTradingCalendar();
    loadBulkAutoConfig();
    loadAlphaGapSummary();
  }, []);

  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      try {
        const data = await loadSyncSpeed();
        if (mounted) {
          setSyncSpeed(data);
        }
      } catch (err) {
        if (mounted) {
          setSyncSpeed(null);
        }
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      try {
        await loadBulkJob();
        await loadBulkHistory();
        const weeklyJobs = await loadPitWeeklyJobs();
        const latestWeeklyJob = weeklyJobs && weeklyJobs.length > 0 ? weeklyJobs[0] : null;
        if (latestWeeklyJob) {
          await loadPitQuality(latestWeeklyJob.id);
          await loadPitProgress(latestWeeklyJob.id);
        } else {
          setPitQuality(null);
          setPitQualityError("");
          setPitProgress(null);
          setPitProgressError("");
        }
        const fundJobs = await loadPitFundJobs();
        const latestFundJob = fundJobs && fundJobs.length > 0 ? fundJobs[0] : null;
        if (latestFundJob) {
          await loadPitFundProgress(latestFundJob.id);
          await loadPitFundProgressMap(fundJobs);
        } else {
          setPitFundProgress(null);
          setPitFundProgressError("");
          setPitFundProgressMap({});
        }
      } finally {
        if (!mounted) {
          return;
        }
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    loadThemeOptions();
  }, []);

  useEffect(() => {
    loadThemeSymbols(themeFilter);
  }, [themeFilter]);

  useEffect(() => {
    loadThemeCoverage(themeFilter);
  }, [themeFilter]);

  const updateForm = (key: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const createDataset = async () => {
    if (!form.name.trim()) {
      setFormError(t("data.register.errorName"));
      return;
    }
    setFormError("");
    await api.post("/api/datasets", {
      name: form.name.trim(),
      vendor: form.vendor || null,
      asset_class: form.asset_class || null,
      region: form.region || null,
      frequency: form.frequency || null,
      coverage_start: form.coverage_start || null,
      coverage_end: form.coverage_end || null,
      source_path: form.source_path || null,
    });
    setForm({
      name: "",
      vendor: "",
      asset_class: "",
      region: "",
      frequency: "",
      coverage_start: "",
      coverage_end: "",
      source_path: "",
    });
    loadDatasets();
  };

  const updateScanForm = (key: keyof typeof scanForm, value: string) => {
    setScanForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateSyncForm = (key: keyof typeof syncForm, value: string) => {
    setSyncForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateBulkAutoForm = (key: keyof typeof bulkAutoForm, value: string | boolean) => {
    setBulkAutoForm((prev) => ({ ...prev, [key]: value }));
  };

  const updatePitForm = (key: keyof typeof pitForm, value: string | boolean) => {
    setPitForm((prev) => ({ ...prev, [key]: value }));
  };

  const getParamString = (
    params: Record<string, unknown> | null | undefined,
    key: string
  ): string => {
    const value = params?.[key];
    return typeof value === "string" ? value : "";
  };

  const updatePitFundForm = (key: keyof typeof pitFundForm, value: string | boolean) => {
    setPitFundForm((prev) => ({ ...prev, [key]: value }));
  };

  const pitParams = pitJobs[0]?.params || null;
  const pitTimezone = getParamString(pitParams, "market_timezone");
  const pitSessionOpen = getParamString(pitParams, "market_session_open");
  const pitSessionClose = getParamString(pitParams, "market_session_close");

  const createPitWeeklyJob = async () => {
    setPitActionLoading(true);
    setPitActionError("");
    setPitActionResult("");
    try {
      const payload = {
        start: pitForm.start || null,
        end: pitForm.end || null,
        require_data: pitForm.require_data,
      };
      const res = await api.post<PitWeeklyJob>("/api/pit/weekly-jobs", payload);
      setPitActionResult(t("data.pit.created", { id: res.data.id }));
      await loadPitWeeklyJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.pit.error");
      setPitActionError(String(detail));
    } finally {
      setPitActionLoading(false);
    }
  };

  const createPitFundJob = async () => {
    setPitFundActionLoading(true);
    setPitFundActionError("");
    setPitFundActionResult("");
    try {
      const delayDays = Math.max(Number.parseInt(pitFundForm.report_delay_days, 10) || 1, 0);
      const missingDelayDays = Math.max(
        Number.parseInt(pitFundForm.missing_report_delay_days, 10) || 45,
        0
      );
      const sharesDelayDays = Math.max(
        Number.parseInt(pitFundForm.shares_delay_days, 10) || 45,
        0
      );
      const minDelay = Math.max(Number.parseFloat(pitFundForm.min_delay_seconds) || 0, 0);
      const refreshDaysInput = Number.parseInt(pitFundForm.refresh_days, 10);
      const refreshDays = Number.isFinite(refreshDaysInput)
        ? Math.max(refreshDaysInput, 0)
        : 30;
      const payload = {
        start: pitFundForm.start || null,
        end: pitFundForm.end || null,
        report_delay_days: delayDays,
        missing_report_delay_days: missingDelayDays,
        shares_delay_days: sharesDelayDays,
        shares_preference: pitFundForm.shares_preference || "diluted",
        price_source: pitFundForm.price_source || "raw",
        min_delay_seconds: minDelay,
        refresh_days: refreshDays,
        refresh_fundamentals: pitFundForm.refresh_fundamentals,
        asset_types: pitFundForm.asset_types || "STOCK",
      };
      const res = await api.post<PitFundamentalJob>("/api/pit/fundamental-jobs", payload);
      setPitFundActionResult(t("data.pitFund.created", { id: res.data.id }));
      await loadPitFundJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.pitFund.error");
      setPitFundActionError(String(detail));
    } finally {
      setPitFundActionLoading(false);
    }
  };

  const resumePitFundJob = async (jobId: number) => {
    setPitFundActionError("");
    setPitFundActionResult("");
    setPitFundResumeLoading((prev) => ({ ...prev, [jobId]: true }));
    try {
      const res = await api.post<PitFundamentalJob>(
        `/api/pit/fundamental-jobs/${jobId}/resume`
      );
      setPitFundActionResult(t("data.pitFund.resumed", { id: res.data.id }));
      await loadPitFundJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.pitFund.resumeError");
      setPitFundActionError(String(detail));
    } finally {
      setPitFundResumeLoading((prev) => ({ ...prev, [jobId]: false }));
    }
  };

  const cancelPitFundJob = async (jobId: number) => {
    setPitFundActionError("");
    setPitFundActionResult("");
    setPitFundCancelLoading((prev) => ({ ...prev, [jobId]: true }));
    try {
      const res = await api.post<PitFundamentalJob>(
        `/api/pit/fundamental-jobs/${jobId}/cancel`
      );
      setPitFundActionResult(t("data.pitFund.canceled", { id: res.data.id }));
      await loadPitFundJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.pitFund.cancelError");
      setPitFundActionError(String(detail));
    } finally {
      setPitFundCancelLoading((prev) => ({ ...prev, [jobId]: false }));
    }
  };

  const syncDataset = async (dataset: DatasetSummary) => {
    setSyncError("");
    setListError("");
    setSyncing((prev) => ({ ...prev, [dataset.id]: true }));
    try {
      await api.post(`/api/datasets/${dataset.id}/sync`, {
        source_path: dataset.source_path || null,
        date_column: "date",
        reset_history: resetHistory,
      });
      loadSyncJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.sync.errorCreate");
      setSyncError(String(detail));
      setListError(String(detail));
    } finally {
      setSyncing((prev) => {
        const next = { ...prev };
        delete next[dataset.id];
        return next;
      });
    }
  };

  const loadQuality = async (
    datasetId: number,
    options: { silent?: boolean; force?: boolean } = {}
  ) => {
    const { silent = false, force = false } = options;
    if (deletingDatasetIdsRef.current.has(datasetId)) {
      return;
    }
    if (!datasets.some((dataset) => dataset.id === datasetId)) {
      return;
    }
    if (!force && (qualityMap[datasetId] || qualityLoading[datasetId])) {
      return;
    }
    const existingController = qualityAbortRef.current[datasetId];
    if (existingController) {
      existingController.abort();
    }
    const controller = new AbortController();
    qualityAbortRef.current[datasetId] = controller;
    setQualityLoading((prev) => ({ ...prev, [datasetId]: true }));
    setQualityErrors((prev) => ({ ...prev, [datasetId]: "" }));
    try {
      const res = await api.get<DatasetQuality>(`/api/datasets/${datasetId}/quality`, {
        signal: controller.signal,
      });
      setQualityMap((prev) => ({ ...prev, [datasetId]: res.data }));
    } catch (err: any) {
      if (
        axios.isCancel(err) ||
        err?.code === "ERR_CANCELED" ||
        err?.name === "CanceledError"
      ) {
        return;
      }
      if (err?.response?.status === 404) {
        return;
      }
      if (!silent) {
        setQualityErrors((prev) => ({ ...prev, [datasetId]: t("data.list.quality.error") }));
      }
    } finally {
      if (qualityAbortRef.current[datasetId] === controller) {
        delete qualityAbortRef.current[datasetId];
      }
      setQualityLoading((prev) => {
        const next = { ...prev };
        delete next[datasetId];
        return next;
      });
    }
  };

  useEffect(() => {
    if (!datasets.length) {
      return;
    }
    const idsToLoad = datasets
      .map((dataset) => dataset.id)
      .filter(
        (id) =>
          !deletingDatasetIdsRef.current.has(id) &&
          !qualityMap[id] &&
          !qualityLoading[id]
      );
    if (!idsToLoad.length) {
      return;
    }
    idsToLoad.forEach((id) => {
      void loadQuality(id, { silent: true });
    });
  }, [datasets, qualityMap, qualityLoading]);

  const scanQuality = async () => {
    if (!scanForm.dataset_id) {
      setScanError(t("data.scan.errorSelect"));
      return;
    }
    if (!scanForm.file_path.trim()) {
      setScanError(t("data.scan.errorFilePath"));
      return;
    }
    setScanError("");
    setScanResult(null);
    try {
      const res = await api.post<DatasetQualityScan>(
        `/api/datasets/${Number(scanForm.dataset_id)}/quality/scan`,
        {
          file_path: scanForm.file_path.trim(),
          date_column: scanForm.date_column || "date",
          close_column: scanForm.close_column || "close",
          frequency: scanForm.frequency || null,
        }
      );
      setScanResult(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.scan.error");
      setScanError(String(detail));
    }
  };

  const createSyncJob = async () => {
    if (!syncForm.dataset_id) {
      setSyncError(t("data.scan.errorSelect"));
      return;
    }
    setSyncError("");
    try {
      await api.post(`/api/datasets/${Number(syncForm.dataset_id)}/sync`, {
        source_path: syncForm.source_path.trim() || null,
        date_column: syncForm.date_column || "date",
        reset_history: resetHistory,
      });
      setSyncForm({ dataset_id: "", source_path: "", date_column: "date" });
      loadSyncJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.sync.errorCreate");
      setSyncError(String(detail));
    }
  };

  const syncAll = async () => {
    setSyncError("");
    setListError("");
    setSyncAllLoading(true);
    try {
      if (resetHistory && !window.confirm(t("data.list.update.resetConfirm"))) {
        return;
      }
      await api.post("/api/datasets/sync-all", {
        reset_history: resetHistory,
      });
      loadSyncJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.sync.errorBatch");
      setSyncError(String(detail));
      setListError(String(detail));
    } finally {
      setSyncAllLoading(false);
    }
  };

  const deleteGroup = async (group: {
    key: string;
    symbol: string;
    region: string;
    items: DatasetSummary[];
  }) => {
    setListError("");
    const targetItems = datasets.filter((item) => {
      const symbol = deriveSymbol(item);
      const region = (item.region || "").trim();
      return symbol === group.symbol && region === group.region;
    });
    if (!targetItems.length) {
      setListError(t("data.list.delete.error"));
      return;
    }
    const confirm = window.confirm(
      t("data.list.delete.confirm", { symbol: group.symbol })
    );
    if (!confirm) {
      return;
    }
    const input = window.prompt(
      t("data.list.delete.prompt", { symbol: group.symbol }),
      ""
    );
    if (!input || input.trim().toUpperCase() !== group.symbol.toUpperCase()) {
      setListError(t("data.list.delete.mismatch"));
      return;
    }
      setDeleteLoading((prev) => ({ ...prev, [group.key]: true }));
      const deletingIds = targetItems.map((item) => item.id);
      deletingIds.forEach((id) => deletingDatasetIdsRef.current.add(id));
      try {
        targetItems.forEach((item) => {
          const controller = qualityAbortRef.current[item.id];
          if (controller) {
            controller.abort();
            delete qualityAbortRef.current[item.id];
          }
        });
        await api.post("/api/datasets/actions/batch-delete", {
          dataset_ids: targetItems.map((item) => item.id),
        });
      const ids = new Set(targetItems.map((item) => item.id));
      setQualityMap((prev) => {
        const next = { ...prev };
        ids.forEach((id) => delete next[id]);
        return next;
      });
      setQualityErrors((prev) => {
        const next = { ...prev };
        ids.forEach((id) => delete next[id]);
        return next;
      });
      setQualityLoading((prev) => {
        const next = { ...prev };
        ids.forEach((id) => delete next[id]);
        return next;
      });
      setSyncing((prev) => {
        const next = { ...prev };
        ids.forEach((id) => delete next[id]);
        return next;
      });
        await loadDatasets();
        await loadSyncJobs();
      } catch (err: any) {
        const detail = err?.response?.data?.detail || t("data.list.delete.error");
        setListError(String(detail));
      } finally {
        setDeleteLoading((prev) => {
          const next = { ...prev };
          delete next[group.key];
          return next;
        });
        deletingIds.forEach((id) => deletingDatasetIdsRef.current.delete(id));
      }
    };

  const renderStatus = (value: string) => {
    const key = `common.status.${value}`;
    const text = t(key);
    return text === key ? value : text;
  };

  const statusClass = (value: string) => {
    if (value === "success" || value === "ok") {
      return "success";
    }
    if (value === "rate_limited" || value === "not_found" || value === "warn") {
      return "warn";
    }
    if (value === "failed") {
      return "danger";
    }
    return "";
  };

  const loadBulkJob = async () => {
    try {
      const res = await api.get<BulkSyncJob>("/api/datasets/bulk-sync-jobs/latest");
      setBulkJob(res.data);
      setBulkJobError("");
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setBulkJob(null);
        setBulkJobError("");
        return;
      }
      const detail = err?.response?.data?.detail || t("data.bulk.autoError");
      setBulkJobError(String(detail));
    }
  };

  const startBulkSync = async () => {
    setBulkJobError("");
    setBulkJobLoading(true);
    try {
      const batchSize = Math.max(Number.parseInt(bulkAutoForm.batch_size, 10) || 1, 1);
      const minDelay = Math.max(
        Number.parseFloat(bulkAutoForm.min_delay_seconds) || 0,
        0
      );
      const saved = await saveBulkDefaults(true);
      if (!saved) {
        setBulkJobError(t("data.bulk.defaults.saveError"));
        return;
      }
      const refreshListingTtlDays = Math.max(
        Number.parseInt(bulkAutoForm.refresh_listing_ttl_days, 10) || 1,
        1
      );
      const res = await api.post<BulkSyncJob>("/api/datasets/actions/bulk-sync", {
        status: bulkAutoForm.status,
        batch_size: batchSize,
        only_missing: bulkAutoForm.only_missing,
        min_delay_seconds: minDelay,
        refresh_listing: true,
        refresh_listing_mode: bulkAutoForm.refresh_listing_mode,
        refresh_listing_ttl_days: refreshListingTtlDays,
        alpha_incremental_enabled: !!alphaFetchForm.alpha_incremental_enabled,
        alpha_compact_days:
          Number.parseInt(alphaFetchForm.alpha_compact_days, 10) || 0,
        auto_sync: true,
      });
      setBulkJob(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.bulk.autoError");
      setBulkJobError(String(detail));
    } finally {
      setBulkJobLoading(false);
    }
  };

  const runBulkAction = async (jobId: number, action: "pause" | "resume" | "cancel") => {
    setBulkActionLoading((prev) => ({ ...prev, [jobId]: true }));
    try {
      await api.post(`/api/datasets/bulk-sync-jobs/${jobId}/${action}`);
      await loadBulkJob();
      await loadBulkHistory();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.bulk.actionError");
      setBulkJobError(String(detail));
    } finally {
      setBulkActionLoading((prev) => {
        const next = { ...prev };
        delete next[jobId];
        return next;
      });
    }
  };

  const normalizeJobStatus = (job: DataSyncJob) => {
    if (job.status !== "failed" || !job.message) {
      return job.status;
    }
    const message = job.message.toLowerCase();
    if (message.includes("daily hits limit") || message.includes("访问限制")) {
      return "rate_limited";
    }
    if (message.includes("未覆盖") || message.includes("not found")) {
      return "not_found";
    }
    return job.status;
  };

  const resolveJobReason = (job: DataSyncJob) => {
    const normalized = normalizeJobStatus(job);
    const message = (job.message || "").toLowerCase();
    if (message.includes("stooq_only")) {
      return t("data.jobs.reason.stooqOnly");
    }
    if (message.includes("premium") || message.includes("付费")) {
      return t("data.jobs.reason.premium");
    }
    if (normalized === "rate_limited") {
      return t("data.jobs.reason.rateLimited");
    }
    if (normalized === "not_found") {
      return t("data.jobs.reason.notFound");
    }
    if (normalized === "failed") {
      return t("data.jobs.reason.failed");
    }
    return "";
  };

  const resolveJobStage = (job: DataSyncJob) => {
    if (!job.message || !job.message.startsWith("stage=")) {
      return "";
    }
    const [, stage] = job.message.split("stage=");
    return (stage || "").split(";")[0].trim();
  };

  const resolveJobProgress = (job: DataSyncJob) => {
    if (!job.message || !job.message.startsWith("stage=")) {
      return null;
    }
    const parts = job.message.split(";").map((part) => part.trim());
    const progressPart = parts.find((part) => part.startsWith("progress="));
    if (!progressPart) {
      return null;
    }
    const raw = progressPart.split("progress=")[1] || "";
    const value = Number.parseFloat(raw);
    if (!Number.isFinite(value)) {
      return null;
    }
    if (value > 1) {
      return Math.round(value);
    }
    return Math.round(value * 100);
  };

  const parseJobMeta = (message?: string | null) => {
    if (!message || message.startsWith("stage=")) {
      return {};
    }
    const parts = message.split(";").map((part) => part.trim());
    const meta: Record<string, string> = {};
    for (const part of parts) {
      const [key, rawValue] = part.split("=");
      if (!key || rawValue === undefined) {
        continue;
      }
      meta[key.trim()] = rawValue.trim();
    }
    return meta;
  };

  const resolveAlphaMeta = (job: DataSyncJob) => {
    const meta = parseJobMeta(job.message);
    const hasGapDays = Object.prototype.hasOwnProperty.call(meta, "gap_days");
    if (!meta.alpha_outputsize && !hasGapDays && !meta.alpha_compact_fallback) {
      return null;
    }
    return {
      outputsize: meta.alpha_outputsize || "",
      gapDays: hasGapDays ? Number.parseInt(meta.gap_days, 10) : null,
      compactFallback: meta.alpha_compact_fallback === "1",
    };
  };

  const renderJobStage = (stage: string) => {
    if (!stage) {
      return "";
    }
    const key = `data.jobs.stageLabel.${stage}`;
    const text = t(key);
    return text === key ? stage : text;
  };

  const reasonClass = (status: string) => {
    if (status === "failed") {
      return "danger";
    }
    if (status === "rate_limited" || status === "not_found") {
      return "warn";
    }
    return "";
  };

  const renderBulkStatus = (value: string) => {
    const key = `data.bulk.statusLabel.${value}`;
    const text = t(key);
    return text === key ? value : text;
  };

  const renderBulkPhase = (value: string) => {
    const key = `data.bulk.phaseLabel.${value}`;
    const text = t(key);
    return text === key ? value : text;
  };

  const formatDuration = (ms: number | null | undefined) => {
    if (!ms || ms < 0) {
      return "-";
    }
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const pad = (value: number) => String(value).padStart(2, "0");
    if (hours > 0) {
      return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
    }
    return `${pad(minutes)}:${pad(seconds)}`;
  };

  const resolveJobElapsed = (job: DataSyncJob) => {
    const createdAt = job.created_at ? new Date(job.created_at).getTime() : null;
    const startedAt = job.started_at ? new Date(job.started_at).getTime() : null;
    const endedAt = job.ended_at ? new Date(job.ended_at).getTime() : null;
    const base = startedAt ?? createdAt;
    if (!base) {
      return null;
    }
    const end = endedAt ?? Date.now();
    return Math.max(0, end - base);
  };

  const bulkErrorSummary = (errors?: Array<{ message?: string; phase?: string }>) => {
    if (!errors || errors.length === 0) {
      return t("common.none");
    }
    const last = errors[errors.length - 1];
    const prefix = last?.phase ? `${last.phase}: ` : "";
    return `${errors.length} · ${prefix}${last?.message || ""}`.trim();
  };

  const bulkErrorTooltip = (errors?: Array<{ message?: string; phase?: string }>) => {
    if (!errors || errors.length === 0) {
      return "";
    }
    return errors
      .slice(-5)
      .map((err) => `${err.phase ? `${err.phase}: ` : ""}${err.message || ""}`)
      .join("\n");
  };

  const normalizeFrequency = (value?: string | null) => {
    const freq = (value || "").trim().toLowerCase();
    if (["d", "day", "daily", "1d"].includes(freq)) {
      return "daily";
    }
    if (["m", "min", "minute", "1min"].includes(freq)) {
      return "minute";
    }
    return "";
  };

  const formatFrequency = (value?: string | null) => {
    const normalized = normalizeFrequency(value);
    if (normalized === "daily") {
      return { label: t("data.frequency.daily"), className: "daily" };
    }
    if (normalized === "minute") {
      return { label: t("data.frequency.minute"), className: "minute" };
    }
    if (!value) {
      return { label: t("common.none"), className: "unknown" };
    }
    return { label: value, className: "other" };
  };

  const normalizeSymbolInput = (value: string) =>
    value.trim().toUpperCase().replace(/[^A-Z0-9.]/g, "");

  const deriveSymbol = (dataset: DatasetSummary) => {
    const source = (dataset.source_path || "").trim();
    let symbol = "";
    if (source) {
      const lower = source.toLowerCase();
      if (lower.startsWith("stooq://")) {
        symbol = source.slice(8);
      } else if (lower.startsWith("stooq:")) {
        symbol = source.slice(6);
      } else if (lower.startsWith("stooq-only://")) {
        symbol = source.slice(13);
      } else if (lower.startsWith("stooq-only:")) {
        symbol = source.slice(11);
      } else if (lower.startsWith("yahoo://")) {
        symbol = source.slice(8);
      } else if (lower.startsWith("yahoo:")) {
        symbol = source.slice(6);
      } else if (lower.startsWith("alpha://")) {
        symbol = source.slice(8);
      } else if (lower.startsWith("alpha:")) {
        symbol = source.slice(6);
      } else {
        const normalized = source.replace(/\\/g, "/");
        const parts = normalized.split("/");
        const last = parts[parts.length - 1] || normalized;
        symbol = last.replace(/\.(csv|zip)$/i, "");
      }
    }
    if (!symbol) {
      symbol = dataset.name;
    }
    return symbol.toUpperCase();
  };

  const formatSource = (value?: string | null) => {
    if (!value) {
      return t("common.none");
    }
    const lower = value.toLowerCase();
    if (lower.startsWith("stooq://")) {
      return `stooq:${value.slice(8)}`;
    }
    if (lower.startsWith("stooq:")) {
      return value;
    }
    if (lower.startsWith("stooq-only://")) {
      return `stooq-only:${value.slice(13)}`;
    }
    if (lower.startsWith("stooq-only:")) {
      return value;
    }
    if (lower.startsWith("yahoo://")) {
      return `yahoo:${value.slice(8)}`;
    }
    if (lower.startsWith("yahoo:")) {
      return value;
    }
    if (lower.startsWith("alpha://")) {
      return `alpha:${value.slice(8)}`;
    }
    if (lower.startsWith("alpha:")) {
      return value;
    }
    const normalized = value.replace(/\\/g, "/");
    const parts = normalized.split("/");
    return parts[parts.length - 1] || value;
  };

  const formatCoverage = (start?: string | null, end?: string | null) => {
    if (!start && !end) {
      return t("common.none");
    }
    return `${start || t("common.none")} ~ ${end || t("common.none")}`;
  };

  const bulkJobProgress = useMemo(() => {
    if (!bulkJob) {
      return null;
    }
    const total = bulkJob.total_symbols || 0;
    const processed = bulkJob.processed_symbols ?? bulkJob.offset ?? 0;
    const percent = total ? (processed / total) * 100 : 0;
    return { processed, total, percent };
  }, [bulkJob]);

  const latestSyncByDataset = useMemo(() => {
    const map = new Map<number, DataSyncJob>();
    for (const job of syncJobs) {
      const existing = map.get(job.dataset_id);
      if (!existing || new Date(job.created_at).getTime() > new Date(existing.created_at).getTime()) {
        map.set(job.dataset_id, job);
      }
    }
    return map;
  }, [syncJobs]);
  const buildQualityTooltip = (quality: DatasetQuality) => {
    return [
      `${t("data.quality.status")}: ${renderStatus(quality.status)}`,
      `${t("data.quality.coverage")}: ${quality.coverage_start || t("common.none")} ~ ${quality.coverage_end || t("common.none")}`,
      `${t("data.quality.days")}: ${quality.coverage_days ?? t("common.none")}`,
      `${t("data.quality.expected")}: ${
        quality.expected_points_estimate ?? t("common.none")
      }`,
      `${t("data.quality.points")}: ${quality.data_points ?? t("common.none")}`,
      `${t("data.quality.minInterval")}: ${quality.min_interval_days ?? t("common.none")}`,
      `${t("data.quality.issues")}: ${
        quality.issues.length ? quality.issues.join(", ") : t("common.noneText")
      }`,
    ].join("\n");
  };

  const isDailyFrequency = (value?: string | null) => {
    const normalized = normalizeFrequency(value);
    return normalized === "daily";
  };

  const renderQualitySummary = (dataset: DatasetSummary) => {
    if (qualityLoading[dataset.id]) {
      return <span className="market-subtle">{t("data.list.quality.loading")}</span>;
    }
    const error = qualityErrors[dataset.id];
    if (error) {
      return <span className="market-subtle">{error}</span>;
    }
    const quality = qualityMap[dataset.id];
    if (!quality) {
      return <span className="market-subtle">{t("common.none")}</span>;
    }
    const minInterval = quality.min_interval_days;
    if (isDailyFrequency(dataset.frequency) && typeof minInterval === "number" && minInterval > 1) {
      return (
        <span className="pill danger" title={buildQualityTooltip(quality)}>
          {t("data.list.quality.incomplete")}
        </span>
      );
    }
    return (
      <span className={`pill ${statusClass(quality.status) || ""}`} title={buildQualityTooltip(quality)}>
        {renderStatus(quality.status)}
      </span>
    );
  };

  const groupedDatasets = useMemo(() => {
    const groups = new Map<
      string,
      {
        key: string;
        symbol: string;
        region: string;
        name: string;
        meta: string;
        items: DatasetSummary[];
      }
    >();

    const uniqueValues = (values: Array<string | null | undefined>) =>
      Array.from(
        new Set(values.map((value) => (value || "").trim()).filter((value) => value))
      );

    for (const dataset of datasets) {
      const frequency = normalizeFrequency(dataset.frequency);
      if (frequencyFilter !== "all" && frequency !== frequencyFilter) {
        continue;
      }
      const symbol = deriveSymbol(dataset);
      if (themeFilter !== "all" && !themeSymbols.has(symbol)) {
        continue;
      }
      const region = (dataset.region || "").trim();
      const key = `${symbol}|${region || "-"}`;
      const entry = groups.get(key) || {
        key,
        symbol,
        region,
        name: dataset.name,
        meta: "",
        items: [],
      };
      entry.items.push(dataset);
      groups.set(key, entry);
    }

    const frequencyOrder: Record<string, number> = {
      daily: 0,
      minute: 1,
      other: 2,
    };

    const grouped = Array.from(groups.values());
    for (const entry of grouped) {
      entry.items.sort((a, b) => {
        const aFreq = normalizeFrequency(a.frequency) || "other";
        const bFreq = normalizeFrequency(b.frequency) || "other";
        const order = (frequencyOrder[aFreq] ?? 9) - (frequencyOrder[bFreq] ?? 9);
        if (order !== 0) {
          return order;
        }
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      });
      entry.name = entry.items[0]?.name || entry.symbol;
      const vendors = uniqueValues(entry.items.map((item) => item.vendor));
      const regions = uniqueValues(entry.items.map((item) => item.region));
      const assets = uniqueValues(entry.items.map((item) => item.asset_class));
      const metaParts = [] as string[];
      if (vendors.length) {
        metaParts.push(vendors.join("/"));
      }
      if (regions.length) {
        metaParts.push(regions.join("/"));
      }
      if (assets.length) {
        metaParts.push(assets.join("/"));
      }
      entry.meta = metaParts.join(" · ");
    }

    grouped.sort((a, b) => a.symbol.localeCompare(b.symbol));
    return grouped;
  }, [datasets, frequencyFilter, themeFilter, themeSymbols]);
  const filteredDatasetTotal = groupedDatasets.reduce(
    (sum, group) => sum + group.items.length,
    0
  );
  const selectedTheme = useMemo(
    () => themeOptions.find((item) => item.key === themeFilter),
    [themeOptions, themeFilter]
  );
  const themeLabel =
    selectedTheme?.label || themeCoverage?.theme_label || themeFilter;
  const themeMissing = themeCoverage?.missing_symbols || [];
  const themeMissingSample = themeMissing.slice(0, 8).join(", ");

  const getChartDatasetId = (group: {
    key: string;
    items: DatasetSummary[];
  }) => chartSelection[group.key] ?? group.items[0]?.id;

  const getChartDataset = (group: {
    key: string;
    items: DatasetSummary[];
  }) => {
    const selectedId = getChartDatasetId(group);
    return group.items.find((item) => item.id === selectedId) || group.items[0];
  };

  const toggleChart = (group: { key: string; items: DatasetSummary[] }) => {
    setExpandedGroupKey((prev) => (prev === group.key ? null : group.key));
    if (!chartSelection[group.key] && group.items[0]) {
      setChartSelection((prev) => ({
        ...prev,
        [group.key]: group.items[0].id,
      }));
    }
  };

  const updateChartSelection = (groupKey: string, datasetId: number) => {
    setChartSelection((prev) => ({ ...prev, [groupKey]: datasetId }));
  };

  return (
    <div className="main">
      <TopBar title={t("data.title")} />
      <div className="content">
        <div className="card market-card">
          <div className="market-header">
            <div>
              <div className="card-title">{t("data.list.title")}</div>
              <div className="card-meta">
                {t("data.list.meta", {
                  totalSymbols: groupedDatasets.length,
                  totalDatasets: filteredDatasetTotal,
                })}
              </div>
            </div>
            <div className="market-toolbar">
              <button
                type="button"
                className="primary-button"
                onClick={syncAll}
                disabled={syncAllLoading}
              >
                {syncAllLoading ? t("data.list.update.syncingAll") : t("data.list.update.syncAll")}
              </button>
              <label className="market-toolbar-checkbox">
                <input
                  type="checkbox"
                  checked={resetHistory}
                  onChange={(e) => setResetHistory(e.target.checked)}
                />
                <span>{t("data.list.update.reset")}</span>
              </label>
              <div className="market-toolbar-group">
                <span className="market-toolbar-label">{t("data.list.theme.label")}</span>
                <select
                  className="market-toolbar-select"
                  value={themeFilter}
                  onChange={(e) => setThemeFilter(e.target.value)}
                >
                  <option value="all">{t("data.list.theme.all")}</option>
                  {themeOptions.map((theme) => (
                    <option key={theme.key} value={theme.key}>
                      {theme.label} ({theme.symbols})
                    </option>
                  ))}
                </select>
                {themeLoading && (
                  <span className="market-toolbar-hint">{t("data.list.theme.loading")}</span>
                )}
              </div>
              <div className="market-toolbar-group">
                <span className="market-toolbar-label">{t("data.list.filter.label")}</span>
                <div className="segmented">
                  <button
                    type="button"
                    className={frequencyFilter === "all" ? "active" : ""}
                    onClick={() => setFrequencyFilter("all")}
                  >
                    {t("data.list.filter.all")}
                  </button>
                  <button
                    type="button"
                    className={frequencyFilter === "daily" ? "active" : ""}
                    onClick={() => setFrequencyFilter("daily")}
                  >
                    {t("data.list.filter.daily")}
                  </button>
                  <button
                    type="button"
                    className={frequencyFilter === "minute" ? "active" : ""}
                    onClick={() => setFrequencyFilter("minute")}
                  >
                    {t("data.list.filter.minute")}
                  </button>
                </div>
              </div>
            </div>
          </div>
          {themeFilter !== "all" && (
            <div className="market-coverage">
              <div>
                <div className="market-coverage-title">
                  {t("data.list.theme.coverageTitle", { theme: themeLabel })}
                </div>
                {themeCoverageLoading ? (
                  <div className="market-coverage-meta">
                    {t("data.list.theme.loading")}
                  </div>
                ) : themeCoverage ? (
                  <>
                    <div className="market-coverage-meta">
                      {t("data.list.theme.coverageMeta", {
                        covered: themeCoverage.covered_symbols,
                        total: themeCoverage.total_symbols,
                        missing: themeMissing.length,
                      })}
                    </div>
                    {themeMissingSample && (
                      <div className="market-coverage-sample">
                        {t("data.list.theme.coverageSample", {
                          symbols: themeMissingSample,
                        })}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="market-coverage-meta">
                    {t("data.list.theme.coverageEmpty")}
                  </div>
                )}
                {themeCoverageError && (
                  <div className="market-coverage-error">{themeCoverageError}</div>
                )}
              </div>
            </div>
          )}
          {listError && <div className="market-inline-error">{listError}</div>}
          {themeError && <div className="market-inline-error">{themeError}</div>}
          <div className="market-table-wrapper">
            <table className="market-table">
              <thead>
                <tr>
                  <th>{t("data.list.table.symbol")}</th>
                  <th>{t("data.list.table.name")}</th>
                  <th>{t("data.list.table.periods")}</th>
                  <th>{t("data.list.table.updatedAt")}</th>
                  <th>{t("data.list.table.source")}</th>
                  <th>{t("data.list.table.quality")}</th>
                  <th>{t("data.list.table.update")}</th>
                  <th>{t("data.list.table.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {groupedDatasets.length === 0 && (
                  <tr>
                    <td colSpan={8}>{t("data.list.empty")}</td>
                  </tr>
                )}
                {groupedDatasets.map((group) => {
                  const expanded = expandedGroupKey === group.key;
                  const chartDataset = getChartDataset(group);
                  const chartDatasetId = chartDataset?.id ?? getChartDatasetId(group);
                  return (
                    <Fragment key={group.key}>
                      <tr>
                        <td>
                          <div className="market-symbol">{group.symbol}</div>
                          <div className="market-sub">{group.region || t("common.none")}</div>
                        </td>
                        <td>
                          <div className="market-name">{group.name}</div>
                          <div className="market-sub">{group.meta || t("common.none")}</div>
                        </td>
                        <td>
                          <div className="market-stack">
                            {group.items.map((item) => {
                              const freq = formatFrequency(item.frequency);
                              return (
                                <div key={item.id} className="market-line">
                                  <span className={`market-pill ${freq.className}`}>{freq.label}</span>
                                  <span className="market-coverage">
                                    {formatCoverage(item.coverage_start, item.coverage_end)}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </td>
                        <td>
                          <div className="market-stack">
                            {group.items.map((item) => (
                              <div key={item.id} className="market-line">
                                {formatDateTime(item.updated_at)}
                              </div>
                            ))}
                          </div>
                        </td>
                        <td>
                          <div className="market-stack">
                            {group.items.map((item) => (
                              <div
                                key={item.id}
                                className="market-line market-source"
                                title={item.source_path || ""}
                              >
                                {formatSource(item.source_path)}
                              </div>
                            ))}
                          </div>
                        </td>
                        <td className="market-actions">
                          <div className="market-stack">
                            {group.items.map((item) => (
                              <div key={item.id} className="market-line">
                            {renderQualitySummary(item)}
                              </div>
                            ))}
                          </div>
                        </td>
                        <td className="market-actions">
                          <div className="market-stack">
                            {group.items.map((item) => {
                              const job = latestSyncByDataset.get(item.id);
                              const jobStatus = job ? normalizeJobStatus(job) : null;
                              return (
                                <div key={item.id} className="market-line">
                                  <button
                                    type="button"
                                    className="link-button"
                                    onClick={() => syncDataset(item)}
                                    disabled={!!syncing[item.id]}
                                  >
                                    {syncing[item.id]
                                      ? t("data.list.update.syncing")
                                      : t("data.list.update.sync")}
                                  </button>
                                  {job ? (
                                    <span
                                      className={`pill ${statusClass(jobStatus || job.status) || ""}`}
                                      title={job.message || ""}
                                    >
                                      {renderStatus(jobStatus || job.status)}
                                    </span>
                                  ) : (
                                    <span className="market-subtle">{t("common.none")}</span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </td>
                        <td className="market-actions">
                          <div className="market-action-stack">
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => toggleChart(group)}
                            >
                              {expanded ? t("data.list.chart.hide") : t("data.list.chart.show")}
                            </button>
                            <button
                              type="button"
                              className="danger-button"
                              onClick={() => deleteGroup(group)}
                              disabled={!!deleteLoading[group.key]}
                            >
                              {deleteLoading[group.key]
                                ? t("data.list.delete.deleting")
                                : t("data.list.delete.action")}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {expanded && chartDataset && (
                        <tr className="market-chart-row">
                          <td colSpan={8}>
                            <DatasetChartPanel
                              dataset={chartDataset}
                              datasets={group.items}
                              selectedId={chartDatasetId}
                              onSelect={(id) => updateChartSelection(group.key, id)}
                              openUrl={chartDataset ? `/data/charts/${chartDataset.id}` : undefined}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <PaginationBar
            page={datasetPage}
            pageSize={datasetPageSize}
            total={datasetTotal}
            onPageChange={setDatasetPage}
            onPageSizeChange={(size) => {
              setDatasetPage(1);
              setDatasetPageSize(size);
            }}
          />
        </div>

        <div className="data-columns">
          <div className="data-stack">
            <div className="card">
              <div className="card-title">{t("data.coverage.title")}</div>
              <div className="card-meta">{t("data.coverage.meta")}</div>
              <div style={{ fontSize: "32px", fontWeight: 600, marginTop: "12px" }}>
                {datasetTotal}
              </div>
            </div>
            <div className="card">
              <div className="card-title">{t("data.lifecycle.title")}</div>
              <div className="card-meta">{t("data.lifecycle.meta")}</div>
              <div style={{ marginTop: "12px", display: "grid", gap: "6px" }}>
                <div className="form-hint">
                  {t("data.lifecycle.source")}{" "}
                  <code>data_root/universe/alpha_symbol_life.csv</code>
                </div>
                <div className="form-hint">
                  {t("data.lifecycle.override")}{" "}
                  <code>data_root/universe/symbol_life_override.csv</code>
                </div>
                <div className="form-hint">{t("data.lifecycle.priority")}</div>
                <div className="form-hint">
                  {t("data.lifecycle.config")} <code>symbol_life_override_path</code>
                </div>
              </div>
            </div>
            <div className="card">
            <div className="card-title">{t("data.register.title")}</div>
            <div className="card-meta">{t("data.register.meta")}</div>
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
              <input
                value={form.name}
                onChange={(e) => updateForm("name", e.target.value)}
                placeholder={t("data.register.name")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr" }}>
                <input
                  value={form.vendor}
                  onChange={(e) => updateForm("vendor", e.target.value)}
                  placeholder={t("data.register.vendor")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
                <input
                  value={form.frequency}
                  onChange={(e) => updateForm("frequency", e.target.value)}
                  placeholder={t("data.register.frequency")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
              </div>
              <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr" }}>
                <input
                  value={form.asset_class}
                  onChange={(e) => updateForm("asset_class", e.target.value)}
                  placeholder={t("data.register.asset")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
                <input
                  value={form.region}
                  onChange={(e) => updateForm("region", e.target.value)}
                  placeholder={t("data.register.region")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
              </div>
              <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr" }}>
                <input
                  value={form.coverage_start}
                  onChange={(e) => updateForm("coverage_start", e.target.value)}
                  placeholder={t("data.register.start")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
                <input
                  value={form.coverage_end}
                  onChange={(e) => updateForm("coverage_end", e.target.value)}
                  placeholder={t("data.register.end")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
              </div>
              <input
                value={form.source_path}
                onChange={(e) => updateForm("source_path", e.target.value)}
                placeholder={t("data.register.path")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              {formError && (
                <div style={{ color: "#d64545", fontSize: "13px" }}>{formError}</div>
              )}
              <button
                onClick={createDataset}
                style={{
                  padding: "10px",
                  borderRadius: "10px",
                  border: "none",
                  background: "#0f62fe",
                  color: "#fff",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {t("common.actions.save")}
              </button>
            </div>
          </div>

        <div className="card">
          <div className="card-title">{t("data.scan.title")}</div>
          <div className="card-meta">{t("data.scan.meta")}</div>
          <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
            <select
              value={scanForm.dataset_id}
              onChange={(e) => updateScanForm("dataset_id", e.target.value)}
              style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
            >
              <option value="">{t("data.scan.select")}</option>
              {datasets.map((ds) => (
                <option key={ds.id} value={ds.id}>
                  {ds.name}
                </option>
              ))}
            </select>
            <input
              value={scanForm.file_path}
              onChange={(e) => updateScanForm("file_path", e.target.value)}
              placeholder={t("data.scan.filePath")}
              style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
            />
            <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr 1fr" }}>
              <input
                value={scanForm.date_column}
                onChange={(e) => updateScanForm("date_column", e.target.value)}
                placeholder={t("data.scan.dateColumn")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={scanForm.close_column}
                onChange={(e) => updateScanForm("close_column", e.target.value)}
                placeholder={t("data.scan.closeColumn")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={scanForm.frequency}
                onChange={(e) => updateScanForm("frequency", e.target.value)}
                placeholder={t("data.scan.frequency")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
            </div>
            {scanError && (
              <div style={{ color: "#d64545", fontSize: "13px" }}>{scanError}</div>
            )}
            <button
              onClick={scanQuality}
              style={{
                padding: "10px",
                borderRadius: "10px",
                border: "none",
                background: "#0f62fe",
                color: "#fff",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {t("common.actions.scan")}
            </button>
          </div>
        </div>

        {scanResult && (
          <div className="card">
            <div className="card-title">{t("data.scan.result")}</div>
            <div className="card-meta">
              {t("data.table.path")}：{scanResult.file_path}
            </div>
            <div style={{ marginTop: "12px", display: "grid", gap: "6px" }}>
              <div>
                {t("data.scan.totalRows")}：{scanResult.rows}
              </div>
              <div>
                {t("data.quality.coverage")}：{scanResult.coverage_start || t("common.none")} ~{" "}
                {scanResult.coverage_end || t("common.none")}
              </div>
              <div>
                {t("data.scan.missingDays")}：{scanResult.missing_days ?? t("common.none")}
              </div>
              <div>
                {t("data.scan.missingRatio")}：
                {scanResult.missing_ratio !== null && scanResult.missing_ratio !== undefined
                  ? `${(scanResult.missing_ratio * 100).toFixed(2)}%`
                  : t("common.none")}
              </div>
              <div>
                {t("data.scan.nullClose")}：{scanResult.null_close_rows}
              </div>
              <div>
                {t("data.scan.duplicate")}：{scanResult.duplicate_timestamps}
              </div>
              <div>
                {t("data.scan.outliers")}：{scanResult.outlier_returns}
              </div>
              <div>
                {t("data.scan.maxAbs")}：
                {scanResult.max_abs_return !== null && scanResult.max_abs_return !== undefined
                  ? scanResult.max_abs_return.toFixed(4)
                  : t("common.none")}
              </div>
              <div>
                {t("data.quality.issues")}：
                {scanResult.issues.length ? scanResult.issues.join("；") : t("common.noneText")}
              </div>
            </div>
          </div>
        )}

        <div className="card">
            <div className="card-title">{t("data.sync.title")}</div>
            <div className="card-meta">{t("data.sync.meta")}</div>
            {alphaFetchConfig && (
              <div className="card-meta">
                {t("data.sync.incrementalHint", {
                  mode: alphaFetchConfig.alpha_incremental_enabled
                    ? t("data.sync.incremental.enabled")
                    : t("data.sync.incremental.disabled"),
                  days: alphaFetchConfig.alpha_compact_days,
                })}
              </div>
            )}
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
            <select
              value={syncForm.dataset_id}
              onChange={(e) => updateSyncForm("dataset_id", e.target.value)}
              style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
            >
              <option value="">{t("data.scan.select")}</option>
              {datasets.map((ds) => (
                <option key={ds.id} value={ds.id}>
                  {ds.name}
                </option>
              ))}
            </select>
            <input
              value={syncForm.source_path}
              onChange={(e) => updateSyncForm("source_path", e.target.value)}
              placeholder={t("data.sync.path")}
              style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
            />
            <input
              value={syncForm.date_column}
              onChange={(e) => updateSyncForm("date_column", e.target.value)}
              placeholder={t("data.sync.dateColumn")}
              style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
            />
            {syncError && <div style={{ color: "#d64545", fontSize: "13px" }}>{syncError}</div>}
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <button
                onClick={createSyncJob}
                style={{
                  padding: "10px",
                  borderRadius: "10px",
                  border: "none",
                  background: "#0f62fe",
                  color: "#fff",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {t("common.actions.start")}
              </button>
              <button
                onClick={syncAll}
                style={{
                  padding: "10px",
                  borderRadius: "10px",
                  border: "1px solid #e3e6ee",
                  background: "#fff",
                  color: "#0f62fe",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {t("common.actions.syncAll")}
              </button>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-title">{t("data.pit.title")}</div>
          <div className="card-meta">{t("data.pit.meta")}</div>
          <div className="form-grid">
            <div className="form-grid two-col">
              <input
                type="date"
                className="form-input"
                value={pitForm.start}
                onChange={(e) => updatePitForm("start", e.target.value)}
                placeholder={t("data.pit.start")}
              />
              <input
                type="date"
                className="form-input"
                value={pitForm.end}
                onChange={(e) => updatePitForm("end", e.target.value)}
                placeholder={t("data.pit.end")}
              />
            </div>
            <label className="checkbox-row" style={{ marginTop: 0 }}>
              <input
                type="checkbox"
                checked={pitForm.require_data}
                onChange={(e) => updatePitForm("require_data", e.target.checked)}
              />
              <span>{t("data.pit.requireData")}</span>
            </label>
            {pitActionError && <div className="form-error">{pitActionError}</div>}
            {pitActionResult && <div className="form-success">{pitActionResult}</div>}
            {pitJobs[0] && (
              <div className="form-success">
                <div>
                  {t("data.pit.latest", {
                    id: pitJobs[0].id,
                    status: renderStatus(pitJobs[0].status),
                  })}
                </div>
                {(pitTimezone || pitSessionOpen || pitSessionClose) && (
                  <div>
                    {t("data.pit.calendar", {
                      tz: pitTimezone || "-",
                      session: `${pitSessionOpen || "-"}-${pitSessionClose || "-"}`,
                    })}
                  </div>
                )}
                {pitQuality?.available && (
                  <div className="progress-block">
                    <div className="progress-meta">
                      <span>
                        {t("data.pit.quality.snapshots", {
                          count: pitQuality.snapshots ?? 0,
                        })}
                      </span>
                      <span>
                        {t("data.pit.quality.symbols", { count: pitQuality.symbols ?? 0 })}
                      </span>
                      <span>
                        {t("data.pit.quality.fixed", { count: pitQuality.fixed_files ?? 0 })}
                      </span>
                    </div>
                    <div className="progress-meta">
                      <span>{t("data.pit.quality.dup", { count: pitQuality.duplicates ?? 0 })}</span>
                      <span>
                        {t("data.pit.quality.invalid", { count: pitQuality.invalid_rows ?? 0 })}
                      </span>
                      <span>
                        {t("data.pit.quality.mismatch", {
                          count: pitQuality.date_mismatches ?? 0,
                        })}
                      </span>
                      <span>
                        {t("data.pit.quality.life", { count: pitQuality.out_of_life ?? 0 })}
                      </span>
                      <span>
                        {t("data.pit.quality.noData", { count: pitQuality.no_data ?? 0 })}
                      </span>
                    </div>
                    {pitQuality.updated_at && (
                      <div className="progress-meta">
                        {t("data.pit.quality.updated", {
                          at: formatDateTime(pitQuality.updated_at),
                        })}
                      </div>
                    )}
                  </div>
                )}
                {pitProgress && (
                  <div className="progress-block">
                    <div className="progress-meta">
                      <span>
                        {t("data.pit.progress.stage", {
                          stage: pitProgress.stage || "-",
                        })}
                      </span>
                      <span>
                        {t("data.pit.progress.status", {
                          status: pitProgress.status || "-",
                        })}
                      </span>
                      {pitProgress.snapshot_count !== null &&
                        pitProgress.snapshot_count !== undefined && (
                          <span>
                            {t("data.pit.progress.count", {
                              count: pitProgress.snapshot_count,
                            })}
                          </span>
                        )}
                    </div>
                    {pitProgress.updated_at && (
                      <div className="progress-meta">
                        {t("data.pit.progress.updated", {
                          at: formatDateTime(pitProgress.updated_at),
                        })}
                      </div>
                    )}
                    {pitProgress.message && (
                      <div className="progress-meta">{pitProgress.message}</div>
                    )}
                  </div>
                )}
                {pitQualityError && <div className="form-error">{pitQualityError}</div>}
                {pitProgressError && <div className="form-error">{pitProgressError}</div>}
                {pitJobs[0].snapshot_count !== null && pitJobs[0].snapshot_count !== undefined && (
                  <div>{t("data.pit.snapshotCount", { count: pitJobs[0].snapshot_count })}</div>
                )}
                {pitJobs[0].last_snapshot_path && (
                  <div>{t("data.pit.lastSnapshot", { path: pitJobs[0].last_snapshot_path })}</div>
                )}
                {pitJobs[0].output_dir && (
                  <div>{t("data.pit.output", { path: pitJobs[0].output_dir })}</div>
                )}
                {pitJobs[0].log_path && (
                  <div>{t("data.pit.log", { path: pitJobs[0].log_path })}</div>
                )}
              </div>
            )}
            <div className="form-actions">
              <button
                type="button"
                className="primary-button large"
                onClick={createPitWeeklyJob}
                disabled={pitActionLoading}
              >
                {pitActionLoading ? t("data.pit.loading") : t("data.pit.action")}
              </button>
              <span className="form-note">{t("data.pit.note")}</span>
            </div>
            <div className="section-divider" />
            <div className="form-hint">{t("data.pit.historyTitle")}</div>
            {pitLoadError && <div className="form-error">{pitLoadError}</div>}
            {pitJobs.length === 0 ? (
              <div className="form-hint">{t("data.pit.historyEmpty")}</div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("data.pit.history.id")}</th>
                    <th>{t("data.pit.history.status")}</th>
                    <th>{t("data.pit.history.count")}</th>
                    <th>{t("common.labels.createdAt")}</th>
                  </tr>
                </thead>
                <tbody>
                  {pitJobs.map((job) => (
                    <tr key={job.id}>
                      <td>{job.id}</td>
                      <td>{renderStatus(job.status)}</td>
                      <td>{job.snapshot_count ?? t("common.none")}</td>
                      <td>{formatDateTime(job.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-title">{t("data.pitFund.title")}</div>
          <div className="card-meta">{t("data.pitFund.meta")}</div>
          <div className="form-grid">
            <div className="form-grid two-col">
              <div>
                <input
                  type="date"
                  className="form-input"
                  value={pitFundForm.start}
                  onChange={(e) => updatePitFundForm("start", e.target.value)}
                  placeholder={t("data.pitFund.start")}
                />
                <div className="form-hint">{t("data.pitFund.startHint")}</div>
              </div>
              <div>
                <input
                  type="date"
                  className="form-input"
                  value={pitFundForm.end}
                  onChange={(e) => updatePitFundForm("end", e.target.value)}
                  placeholder={t("data.pitFund.end")}
                />
                <div className="form-hint">{t("data.pitFund.endHint")}</div>
              </div>
            </div>
            <div className="form-grid two-col">
              <div>
                <input
                  type="number"
                  min="0"
                  className="form-input"
                  value={pitFundForm.report_delay_days}
                  onChange={(e) => updatePitFundForm("report_delay_days", e.target.value)}
                  placeholder={t("data.pitFund.delay")}
                />
                <div className="form-hint">{t("data.pitFund.delayHint")}</div>
              </div>
              <div>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  className="form-input"
                  value={pitFundForm.min_delay_seconds}
                  onChange={(e) => updatePitFundForm("min_delay_seconds", e.target.value)}
                  placeholder={t("data.pitFund.minDelay")}
                />
                <div className="form-hint">{t("data.pitFund.minDelayHint")}</div>
              </div>
            </div>
            <div className="form-grid two-col">
              <div>
                <input
                  type="number"
                  min="0"
                  className="form-input"
                  value={pitFundForm.missing_report_delay_days}
                  onChange={(e) =>
                    updatePitFundForm("missing_report_delay_days", e.target.value)
                  }
                  placeholder={t("data.pitFund.missingDelay")}
                />
                <div className="form-hint">{t("data.pitFund.missingDelayHint")}</div>
              </div>
              <div>
                <input
                  type="text"
                  className="form-input"
                  value={pitFundForm.asset_types}
                  onChange={(e) => updatePitFundForm("asset_types", e.target.value)}
                  placeholder={t("data.pitFund.assetTypes")}
                />
                <div className="form-hint">{t("data.pitFund.assetTypesHint")}</div>
              </div>
            </div>
            <div className="form-grid two-col">
              <div>
                <input
                  type="number"
                  min="0"
                  className="form-input"
                  value={pitFundForm.shares_delay_days}
                  onChange={(e) => updatePitFundForm("shares_delay_days", e.target.value)}
                  placeholder={t("data.pitFund.sharesDelay")}
                />
                <div className="form-hint">{t("data.pitFund.sharesDelayHint")}</div>
              </div>
              <div>
                <select
                  className="form-select"
                  value={pitFundForm.shares_preference}
                  onChange={(e) => updatePitFundForm("shares_preference", e.target.value)}
                >
                  <option value="diluted">{t("data.pitFund.sharesPreferenceDiluted")}</option>
                  <option value="basic">{t("data.pitFund.sharesPreferenceBasic")}</option>
                </select>
                <div className="form-hint">{t("data.pitFund.sharesPreferenceHint")}</div>
              </div>
            </div>
            <div className="form-grid two-col">
              <div>
                <select
                  className="form-select"
                  value={pitFundForm.price_source}
                  onChange={(e) => updatePitFundForm("price_source", e.target.value)}
                >
                  <option value="raw">{t("data.pitFund.priceSourceRaw")}</option>
                  <option value="adjusted">{t("data.pitFund.priceSourceAdjusted")}</option>
                </select>
                <div className="form-hint">{t("data.pitFund.priceSourceHint")}</div>
              </div>
              <div>
                <input
                  type="number"
                  min="0"
                  className="form-input"
                  value={pitFundForm.refresh_days}
                  onChange={(e) => updatePitFundForm("refresh_days", e.target.value)}
                  placeholder={t("data.pitFund.refreshDays")}
                />
                <div className="form-hint">{t("data.pitFund.refreshDaysHint")}</div>
              </div>
            </div>
            <div className="form-grid two-col">
              <div>
                <label className="checkbox-row" style={{ marginTop: 0 }}>
                  <input
                    type="checkbox"
                    checked={pitFundForm.refresh_fundamentals}
                    onChange={(e) => updatePitFundForm("refresh_fundamentals", e.target.checked)}
                  />
                  <span>{t("data.pitFund.refresh")}</span>
                </label>
                <div className="form-hint">{t("data.pitFund.refreshHint")}</div>
              </div>
            </div>
            {pitFundActionError && <div className="form-error">{pitFundActionError}</div>}
            {pitFundActionResult && <div className="form-success">{pitFundActionResult}</div>}
            {pitFundJobs[0] && (
              <div className="form-success">
                <div>
                  {t("data.pitFund.latest", {
                    id: pitFundJobs[0].id,
                    status: renderStatus(pitFundJobs[0].status),
                  })}
                </div>
                {pitFundProgress && (
                  <div className="progress-block">
                    <div className="progress-meta">
                      <span>
                        {t("data.pitFund.progress.stage", {
                          stage: pitFundProgress.stage || "-",
                        })}
                      </span>
                      {pitFundProgress.total ? (
                        <span>
                          {t("data.pitFund.progress.count", {
                            done: pitFundProgress.done ?? 0,
                            total: pitFundProgress.total ?? 0,
                          })}
                        </span>
                      ) : null}
                    </div>
                    {pitFundProgress.total ? (
                      <div className="progress-bar">
                        <div
                          className="progress-bar-fill"
                          style={{
                            width: `${Math.min(
                              100,
                              Math.max(
                                0,
                                Math.round(
                                  ((pitFundProgress.done ?? 0) /
                                    Math.max(pitFundProgress.total ?? 1, 1)) *
                                    100
                                )
                              )
                            )}%`,
                          }}
                        />
                      </div>
                    ) : null}
                    <div className="progress-meta">
                      <span>
                        {t("data.pitFund.progress.ok", { count: pitFundProgress.ok ?? 0 })}
                      </span>
                      <span>
                        {t("data.pitFund.progress.partial", {
                          count: pitFundProgress.partial ?? 0,
                        })}
                      </span>
                      <span>
                        {t("data.pitFund.progress.rate", {
                          count: pitFundProgress.rate_limited ?? 0,
                        })}
                      </span>
                    </div>
                    {pitFundProgress.rate_per_min !== undefined ? (
                      <div className="progress-meta">
                        {t("data.pitFund.progress.speed", {
                          rate:
                            pitFundProgress.rate_per_min !== null
                              ? pitFundProgress.rate_per_min.toFixed(1)
                              : "-",
                          target:
                            pitFundProgress.target_rpm &&
                            pitFundProgress.target_rpm > 0
                              ? pitFundProgress.target_rpm.toFixed(1)
                              : "-",
                          interval:
                            pitFundProgress.effective_min_delay_seconds &&
                            pitFundProgress.effective_min_delay_seconds > 0
                              ? pitFundProgress.effective_min_delay_seconds.toFixed(2)
                              : "-",
                        })}
                      </div>
                    ) : null}
                    {(() => {
                      const tuneAction = pitFundProgress.tune_action || null;
                      const reason =
                        tuneAction && typeof tuneAction.reason === "string"
                          ? tuneAction.reason
                          : "";
                      const delay =
                        tuneAction && typeof tuneAction.min_delay_seconds === "number"
                          ? tuneAction.min_delay_seconds
                          : null;
                      if (!reason) {
                        return null;
                      }
                      return (
                        <div className="progress-meta">
                          {t("data.pitFund.progress.tune", {
                            reason,
                            delay: delay !== null ? delay.toFixed(2) : "-",
                          })}
                        </div>
                      );
                    })()}
                    {pitFundProgress.current_symbol ? (
                      <div className="progress-meta">
                        {t("data.pitFund.progress.current", {
                          symbol: pitFundProgress.current_symbol,
                        })}
                      </div>
                    ) : null}
                    {pitFundProgress.missing_count !== undefined ? (
                      <div className="progress-meta">
                        <span>
                          {t("data.pitFund.progress.missing", {
                            count: pitFundProgress.missing_count ?? 0,
                          })}
                        </span>
                        {pitFundProgress.missing_path ? (
                          <span>
                            {t("data.pitFund.progress.missingPath", {
                              path: pitFundProgress.missing_path,
                            })}
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )}
                {pitFundProgressError && (
                  <div className="form-error">{pitFundProgressError}</div>
                )}
                {pitFundJobs[0].snapshot_count !== null &&
                  pitFundJobs[0].snapshot_count !== undefined && (
                    <div>
                      {t("data.pitFund.snapshotCount", { count: pitFundJobs[0].snapshot_count })}
                    </div>
                  )}
                {pitFundJobs[0].last_snapshot_path && (
                  <div>
                    {t("data.pitFund.lastSnapshot", { path: pitFundJobs[0].last_snapshot_path })}
                  </div>
                )}
                {pitFundJobs[0].output_dir && (
                  <div>{t("data.pitFund.output", { path: pitFundJobs[0].output_dir })}</div>
                )}
                {pitFundJobs[0].log_path && (
                  <div>{t("data.pitFund.log", { path: pitFundJobs[0].log_path })}</div>
                )}
              </div>
            )}
            <div className="form-actions">
              <button
                type="button"
                className="primary-button large"
                onClick={createPitFundJob}
                disabled={pitFundActionLoading}
              >
                {pitFundActionLoading ? t("data.pitFund.loading") : t("data.pitFund.action")}
              </button>
              <span className="form-note">{t("data.pitFund.note")}</span>
            </div>
            <div className="section-divider" />
            <div className="form-hint">{t("data.pitFund.historyTitle")}</div>
            {pitFundLoadError && <div className="form-error">{pitFundLoadError}</div>}
            {pitFundJobs.length === 0 ? (
              <div className="form-hint">{t("data.pitFund.historyEmpty")}</div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("data.pitFund.history.id")}</th>
                    <th>{t("data.pitFund.history.status")}</th>
                    <th>{t("data.pitFund.history.count")}</th>
                    <th>{t("data.pitFund.history.progress")}</th>
                    <th>{t("common.labels.createdAt")}</th>
                    <th>{t("data.pitFund.history.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {pitFundJobs.map((job) => (
                    <tr key={job.id}>
                      <td>{job.id}</td>
                      <td>{renderStatus(job.status)}</td>
                      <td>{job.snapshot_count ?? t("common.none")}</td>
                      <td>
                        {(() => {
                          const progress = pitFundProgressMap[job.id];
                          if (!progress) {
                            return t("common.none");
                          }
                          if (progress.total) {
                            const done = progress.done ?? 0;
                            const total = progress.total ?? 0;
                            const percent =
                              total > 0 ? Math.round((done / total) * 100) : 0;
                            return `${done}/${total} (${percent}%)`;
                          }
                          return progress.stage || t("common.none");
                        })()}
                      </td>
                      <td>{formatDateTime(job.created_at)}</td>
                      <td>
                        <div className="table-actions">
                          <button
                            type="button"
                            className="button-secondary button-compact"
                            disabled={pitFundResumeLoading[job.id] || job.status === "running"}
                            onClick={() => resumePitFundJob(job.id)}
                          >
                            {pitFundResumeLoading[job.id]
                              ? t("common.actions.loading")
                              : t("data.pitFund.history.resume")}
                          </button>
                          <button
                            type="button"
                            className="button-secondary button-compact"
                            disabled={
                              pitFundCancelLoading[job.id] ||
                              job.status === "cancel_requested" ||
                              !["running", "queued"].includes(job.status)
                            }
                            onClick={() => cancelPitFundJob(job.id)}
                          >
                            {pitFundCancelLoading[job.id] ||
                            job.status === "cancel_requested"
                              ? t("data.pitFund.history.canceling")
                              : t("data.pitFund.history.stop")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

          </div>
          <div className="data-stack">
            <div className="card">
          <div className="card-title">{t("data.bulk.title")}</div>
          <div className="card-meta">{t("data.bulk.meta")}</div>
          <div className="form-grid">
            <div className="form-row">
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "12px",
                }}
              >
                <div className="form-hint">{t("data.bulk.gap.title")}</div>
                <button
                  type="button"
                  className="button-secondary button-compact"
                  onClick={loadAlphaGapSummary}
                  disabled={alphaGapLoading}
                >
                  {alphaGapLoading ? t("common.actions.loading") : t("common.actions.refresh")}
                </button>
              </div>
              {alphaGapError && <div className="form-error">{alphaGapError}</div>}
              {alphaGapSummary && (
                <div className="progress-block">
                  <div className="progress-meta">
                    <span>
                      {t("data.bulk.gap.latestComplete", {
                        date: alphaGapSummary.latest_complete,
                      })}
                    </span>
                    <span>
                      {t("data.bulk.gap.total", { count: alphaGapSummary.total })}
                    </span>
                    <span>
                      {t("data.bulk.gap.withCoverage", {
                        count: alphaGapSummary.with_coverage,
                      })}
                    </span>
                    <span>
                      {t("data.bulk.gap.missingCoverage", {
                        count: alphaGapSummary.missing_coverage,
                      })}
                    </span>
                    <span>
                      {t("data.bulk.gap.upToDate", {
                        count: alphaGapSummary.up_to_date,
                      })}
                    </span>
                  </div>
                  <div className="progress-meta">
                    <span>
                      {t("data.bulk.gap.bucket0_30", {
                        count: alphaGapSummary.gap_0_30,
                      })}
                    </span>
                    <span>
                      {t("data.bulk.gap.bucket31_120", {
                        count: alphaGapSummary.gap_31_120,
                      })}
                    </span>
                    <span>
                      {t("data.bulk.gap.bucket120Plus", {
                        count: alphaGapSummary.gap_120_plus,
                      })}
                    </span>
                    <span>
                      {t("data.bulk.gap.listingAge", {
                        days:
                          alphaGapSummary.listing_age_days !== null &&
                          alphaGapSummary.listing_age_days !== undefined
                            ? alphaGapSummary.listing_age_days
                            : "-",
                      })}
                    </span>
                  </div>
                </div>
              )}
            </div>
            <div className="form-hint">{t("data.bulk.autoTitle")}</div>
            <div className="form-grid two-col">
              <select
                className="form-select"
                value={bulkAutoForm.status}
                    onChange={(e) => updateBulkAutoForm("status", e.target.value)}
                  >
                    <option value="all">{t("data.bulk.status.all")}</option>
                    <option value="active">{t("data.bulk.status.active")}</option>
                    <option value="delisted">{t("data.bulk.status.delisted")}</option>
                  </select>
                  <input
                    className="form-input"
                    value={bulkAutoForm.batch_size}
                    onChange={(e) => updateBulkAutoForm("batch_size", e.target.value)}
                    placeholder={t("data.bulk.auto.batch")}
                  />
                </div>
                <div className="form-grid two-col">
                  <input
                    className="form-input"
                    value={bulkAutoForm.min_delay_seconds}
                    onChange={(e) => updateBulkAutoForm("min_delay_seconds", e.target.value)}
                    placeholder={t("data.bulk.auto.delay")}
                  />
                  <label className="checkbox-row" style={{ marginTop: 0 }}>
                    <input
                      type="checkbox"
                      checked={bulkAutoForm.only_missing}
                      onChange={(e) => updateBulkAutoForm("only_missing", e.target.checked)}
                    />
                    <span>{t("data.bulk.onlyMissing")}</span>
                  </label>
                </div>
                <div className="form-hint">{t("data.bulk.listing.title")}</div>
                <div className="form-grid two-col">
                  <select
                    className="form-select"
                    value={bulkAutoForm.refresh_listing_mode}
                    onChange={(e) => updateBulkAutoForm("refresh_listing_mode", e.target.value)}
                  >
                    <option value="always">{t("data.bulk.listing.modeAlways")}</option>
                    <option value="stale_only">{t("data.bulk.listing.modeStale")}</option>
                    <option value="never">{t("data.bulk.listing.modeNever")}</option>
                  </select>
                  <input
                    className="form-input"
                    value={bulkAutoForm.refresh_listing_ttl_days}
                    onChange={(e) =>
                      updateBulkAutoForm("refresh_listing_ttl_days", e.target.value)
                    }
                    placeholder={t("data.bulk.listing.ttlDays")}
                  />
                </div>
                <div className="form-hint">{t("data.bulk.listing.hint")}</div>
                <div className="form-hint">{t("data.bulk.incremental.title")}</div>
                <div className="form-grid two-col">
                  <label className="checkbox-row" style={{ marginTop: 0 }}>
                    <input
                      type="checkbox"
                      checked={alphaFetchForm.alpha_incremental_enabled}
                      onChange={(e) =>
                        updateAlphaFetchForm("alpha_incremental_enabled", e.target.checked)
                      }
                    />
                    <span>{t("data.bulk.incremental.enabled")}</span>
                  </label>
                  <input
                    className="form-input"
                    value={alphaFetchForm.alpha_compact_days}
                    onChange={(e) =>
                      updateAlphaFetchForm("alpha_compact_days", e.target.value)
                    }
                    placeholder={t("data.bulk.incremental.compactDays")}
                  />
                </div>
                <div className="form-hint">{t("data.bulk.incremental.hint")}</div>
                {bulkAutoLoadError && <div className="form-error">{bulkAutoLoadError}</div>}
                {alphaFetchError && <div className="form-error">{alphaFetchError}</div>}
                {bulkDefaultsResult && <div className="form-success">{bulkDefaultsResult}</div>}
                {bulkDefaultsError && <div className="form-error">{bulkDefaultsError}</div>}
                <div className="form-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => saveBulkDefaults(false)}
                    disabled={bulkDefaultsSaving || alphaFetchSaving}
                  >
                    {bulkDefaultsSaving || alphaFetchSaving
                      ? t("common.actions.loading")
                      : t("common.actions.save")}
                  </button>
                  <span className="form-note">{t("data.bulk.defaults.note")}</span>
                </div>
                <div className="form-hint">{t("data.bulk.autoHint")}</div>
                {bulkJobError && <div className="form-error">{bulkJobError}</div>}
                {bulkJob && (
                  <div className="form-success">
                    {t("data.bulk.autoStatus", {
                      id: bulkJob.id,
                      status: renderBulkStatus(bulkJob.status),
                      phase: renderBulkPhase(bulkJob.phase),
                    })}
                    {bulkJobProgress && (
                      <div>
                        {t("data.bulk.progress", {
                          processed: bulkJobProgress.processed,
                          total: bulkJobProgress.total,
                          percent: bulkJobProgress.percent.toFixed(1),
                        })}
                      </div>
                    )}
                    <div>
                      {t("data.bulk.autoCounts", {
                        created: bulkJob.created_datasets ?? 0,
                        reused: bulkJob.reused_datasets ?? 0,
                        queued: bulkJob.queued_jobs ?? 0,
                        running: bulkJob.running_sync_jobs ?? 0,
                        pending: bulkJob.pending_sync_jobs ?? 0,
                      })}
                    </div>
                    {bulkJob.errors && bulkJob.errors.length > 0 && (
                      <div title={bulkErrorTooltip(bulkJob.errors)}>
                        {t("data.bulk.errorDetail", {
                          detail: bulkErrorSummary(bulkJob.errors),
                        })}
                      </div>
                    )}
                  </div>
                )}
                <div className="form-actions">
                  <button
                    type="button"
                    className="primary-button large"
                    onClick={startBulkSync}
                    disabled={bulkJobLoading}
                  >
                    {bulkJobLoading ? t("data.bulk.autoLoading") : t("data.bulk.autoAction")}
                  </button>
                  <span className="form-note">{t("data.bulk.autoNote")}</span>
                </div>
                <div className="section-divider" />
                <div className="section-divider" />
                <div className="form-hint">{t("data.bulk.history.title")}</div>
                {bulkHistory.length === 0 ? (
                  <div className="form-hint">{t("data.bulk.history.empty")}</div>
                ) : (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("data.bulk.history.id")}</th>
                        <th>{t("data.bulk.history.status")}</th>
                        <th>{t("data.bulk.history.phase")}</th>
                        <th>{t("data.bulk.history.progress")}</th>
                        <th>{t("data.bulk.history.counts")}</th>
                        <th>{t("data.bulk.history.error")}</th>
                        <th>{t("data.bulk.history.updatedAt")}</th>
                        <th>{t("data.bulk.history.actions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bulkHistory.map((item) => (
                        <tr key={item.id}>
                          <td>{item.id}</td>
                          <td>{renderBulkStatus(item.status)}</td>
                          <td>{renderBulkPhase(item.phase)}</td>
                          <td>
                            {t("data.bulk.history.progressValue", {
                              processed: item.processed_symbols ?? item.offset ?? 0,
                              total: item.total_symbols ?? 0,
                            })}
                          </td>
                          <td>
                            {t("data.bulk.history.countsValue", {
                              created: item.created_datasets ?? 0,
                              reused: item.reused_datasets ?? 0,
                              queued: item.queued_jobs ?? 0,
                            })}
                          </td>
                          <td title={bulkErrorTooltip(item.errors)}>
                            {bulkErrorSummary(item.errors)}
                          </td>
                          <td>{item.updated_at ? formatDateTime(item.updated_at) : "-"}</td>
                          <td>
                            <div className="table-actions">
                              {item.status === "running" || item.status === "queued" ? (
                                <>
                                  <button
                                    type="button"
                                    className="link-button"
                                    onClick={() => runBulkAction(item.id, "pause")}
                                    disabled={!!bulkActionLoading[item.id]}
                                  >
                                    {t("data.bulk.actions.pause")}
                                  </button>
                                  <button
                                    type="button"
                                    className="link-button"
                                    onClick={() => runBulkAction(item.id, "cancel")}
                                    disabled={!!bulkActionLoading[item.id]}
                                  >
                                    {t("data.bulk.actions.cancel")}
                                  </button>
                                </>
                              ) : item.status === "paused" ? (
                                <>
                                  <button
                                    type="button"
                                    className="link-button"
                                    onClick={() => runBulkAction(item.id, "resume")}
                                    disabled={!!bulkActionLoading[item.id]}
                                  >
                                    {t("data.bulk.actions.resume")}
                                  </button>
                                  <button
                                    type="button"
                                    className="link-button"
                                    onClick={() => runBulkAction(item.id, "cancel")}
                                    disabled={!!bulkActionLoading[item.id]}
                                  >
                                    {t("data.bulk.actions.cancel")}
                                  </button>
                                </>
                              ) : (
                                <span className="market-subtle">{t("common.none")}</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <PaginationBar
                  page={bulkHistoryPage}
                  pageSize={bulkHistoryPageSize}
                  total={bulkHistoryTotal}
                  onPageChange={setBulkHistoryPage}
                  onPageSizeChange={(size) => {
                    setBulkHistoryPage(1);
                    setBulkHistoryPageSize(size);
                  }}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-title">{t("data.jobs.title")}</div>
          <div className="card-meta">
            {t("data.jobs.meta", { total: syncTotal })}
            {syncSpeed ? (
              <>
                {" · "}
                {t("data.jobs.speed", {
                  rate: syncSpeed.rate_per_min.toFixed(1),
                  target:
                    syncSpeed.target_rpm && syncSpeed.target_rpm > 0
                      ? syncSpeed.target_rpm.toFixed(1)
                      : "-",
                  interval:
                    syncSpeed.effective_min_delay_seconds &&
                    syncSpeed.effective_min_delay_seconds > 0
                      ? syncSpeed.effective_min_delay_seconds.toFixed(2)
                      : "-",
                  window: syncSpeed.window_seconds,
                  running: syncSpeed.running,
                  pending: syncSpeed.pending,
                })}
              </>
            ) : (
              <>
                {" · "}
                {t("data.jobs.speedEmpty")}
              </>
            )}
          </div>
          <div
            style={{
              marginTop: "8px",
              display: "flex",
              gap: "8px",
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <button
              onClick={clearSyncQueue}
              disabled={clearQueueLoading}
              style={{
                padding: "8px 12px",
                borderRadius: "10px",
                border: "1px solid #e3e6ee",
                background: "#fff",
                color: "#d64545",
                fontWeight: 600,
                cursor: clearQueueLoading ? "not-allowed" : "pointer",
              }}
            >
              {clearQueueLoading ? t("data.jobs.clearing") : t("data.jobs.clear")}
            </button>
            {clearQueueResult && (
              <span style={{ fontSize: "12px", color: "#2e7d32" }}>{clearQueueResult}</span>
            )}
            {clearQueueError && (
              <span style={{ fontSize: "12px", color: "#d64545" }}>{clearQueueError}</span>
            )}
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("data.jobs.id")}</th>
                <th>{t("data.jobs.dataset")}</th>
                <th>{t("data.jobs.status")}</th>
                <th>{t("data.jobs.rows")}</th>
                <th>{t("data.jobs.coverage")}</th>
                <th>{t("data.jobs.outputs")}</th>
                <th>{t("data.jobs.message")}</th>
                <th>{t("data.jobs.createdAt")}</th>
              </tr>
            </thead>
            <tbody>
              {syncJobs.length === 0 && (
                <tr>
                  <td colSpan={8}>{t("data.jobs.empty")}</td>
                </tr>
              )}
              {syncJobs.map((job) => {
                const normalized = normalizeJobStatus(job);
                const reason = resolveJobReason(job);
                const stage = resolveJobStage(job);
                const progress = resolveJobProgress(job);
                const elapsed = resolveJobElapsed(job);
                const alphaMeta = resolveAlphaMeta(job);
                return (
                  <tr key={job.id}>
                    <td>{job.id}</td>
                    <td>{job.dataset_name || `#${job.dataset_id}`}</td>
                    <td>
                      <span
                        className={`pill ${statusClass(normalized) || ""}`}
                        title={job.message || ""}
                      >
                        {renderStatus(normalized)}
                      </span>
                    </td>
                    <td>{job.rows_scanned ?? t("common.none")}</td>
                    <td>
                      {job.coverage_start || t("common.none")} ~{" "}
                      {job.coverage_end || t("common.none")}
                    </td>
                    <td>
                      <div style={{ fontSize: "12px", lineHeight: 1.4 }}>
                        <div>
                          {t("data.jobs.outputLabels.curated")}:{" "}
                          {job.output_path || t("common.none")}
                        </div>
                        <div>
                          {t("data.jobs.outputLabels.normalized")}:{" "}
                          {job.normalized_path || t("common.none")}
                        </div>
                        <div>
                          {t("data.jobs.outputLabels.adjusted")}:{" "}
                          {job.adjusted_path || t("common.none")}
                        </div>
                        <div>
                          {t("data.jobs.outputLabels.snapshot")}:{" "}
                          {job.snapshot_path || t("common.none")}
                        </div>
                        <div>
                          {t("data.jobs.outputLabels.lean")}: {job.lean_path || t("common.none")}
                        </div>
                        <div>
                          {t("data.jobs.outputLabels.leanAdjusted")}:{" "}
                          {job.lean_adjusted_path || t("common.none")}
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="job-message">
                        {reason && (
                          <span className={`pill ${reasonClass(normalized)}`}>{reason}</span>
                        )}
                        {stage ? (
                          <span className="pill">
                            {progress !== null
                              ? t("data.jobs.stageProgress", {
                                  stage: renderJobStage(stage),
                                  progress,
                                })
                              : t("data.jobs.stage", { stage: renderJobStage(stage) })}
                          </span>
                        ) : (
                          <span>{job.message || t("common.none")}</span>
                        )}
                        {alphaMeta?.outputsize ? (
                          <span className="pill">
                            {t("data.jobs.alpha.outputsize", {
                              value: alphaMeta.outputsize,
                            })}
                          </span>
                        ) : null}
                        {alphaMeta && alphaMeta.gapDays !== null ? (
                          <span className="pill">
                            {t("data.jobs.alpha.gapDays", {
                              value: alphaMeta.gapDays,
                            })}
                          </span>
                        ) : null}
                        {alphaMeta?.compactFallback ? (
                          <span className="pill warn">
                            {t("data.jobs.alpha.fallback")}
                          </span>
                        ) : null}
                        {(job.retry_count ?? 0) > 0 || job.next_retry_at ? (
                          <span className="market-subtle">
                            {t("data.jobs.retry", {
                              count: job.retry_count ?? 0,
                              next: job.next_retry_at
                                ? formatDateTime(job.next_retry_at)
                                : t("common.none"),
                            })}
                          </span>
                        ) : null}
                        {elapsed !== null ? (
                          <span className="market-subtle">
                            {t("data.jobs.elapsed", { value: formatDuration(elapsed) })}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td>{formatDateTime(job.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <PaginationBar
            page={syncPage}
            pageSize={syncPageSize}
            total={syncTotal}
            onPageChange={setSyncPage}
            onPageSizeChange={(size) => {
              setSyncPage(1);
              setSyncPageSize(size);
            }}
          />
        </div>

        <div className="card">
          <div className="card-title">{t("data.tradingCalendar.title")}</div>
          <div className="card-meta">
            {t("data.tradingCalendar.meta", { path: tradingCalendar?.path || "-" })}
          </div>
          {tradingCalendar && (
            <div className="meta-list">
              <div className="meta-row">
                <span>{t("data.tradingCalendar.source")}</span>
                <strong>{tradingCalendar.config_source || "-"}</strong>
              </div>
              <div className="meta-row">
                <span>{t("data.tradingCalendar.calendarSource")}</span>
                <strong>{tradingCalendar.calendar_source || "-"}</strong>
              </div>
              <div className="meta-row">
                <span>{t("data.tradingCalendar.coverage")}</span>
                <strong>
                  {tradingCalendar.calendar_start || "-"} ~{" "}
                  {tradingCalendar.calendar_end || "-"}
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("data.tradingCalendar.generatedAt")}</span>
                <strong>
                  {tradingCalendar.calendar_generated_at
                    ? formatDateTime(tradingCalendar.calendar_generated_at)
                    : "-"}
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("common.labels.updatedAt")}</span>
                <strong>
                  {tradingCalendar.updated_at
                    ? formatDateTime(tradingCalendar.updated_at)
                    : "-"}
                </strong>
              </div>
            </div>
          )}
          <div className="trading-calendar-section">
            <div className="section-title">{t("data.tradingCalendar.configTitle")}</div>
            <div className="form-grid trading-calendar-grid">
              <div className="form-row">
                <label className="form-label">{t("data.tradingCalendar.sourceMode")}</label>
                <select
                  className="form-select"
                  value={tradingCalendarForm.source}
                  onChange={(e) => updateTradingCalendarForm("source", e.target.value)}
                >
                  <option value="auto">auto</option>
                  <option value="local">local</option>
                  <option value="exchange_calendars">exchange_calendars</option>
                  <option value="lean">lean</option>
                  <option value="spy">spy</option>
                </select>
                <div className="form-hint">{t("data.tradingCalendar.sourceModeHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.tradingCalendar.exchange")}</label>
                <input
                  type="text"
                  className="form-input"
                  value={tradingCalendarForm.exchange}
                  onChange={(e) => updateTradingCalendarForm("exchange", e.target.value)}
                />
                <div className="form-hint">{t("data.tradingCalendar.exchangeHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.tradingCalendar.startDate")}</label>
                <input
                  type="date"
                  className="form-input"
                  value={tradingCalendarForm.start_date}
                  onChange={(e) => updateTradingCalendarForm("start_date", e.target.value)}
                />
                <div className="form-hint">{t("data.tradingCalendar.startDateHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.tradingCalendar.endDate")}</label>
                <input
                  type="date"
                  className="form-input"
                  value={tradingCalendarForm.end_date}
                  onChange={(e) => updateTradingCalendarForm("end_date", e.target.value)}
                />
                <div className="form-hint">{t("data.tradingCalendar.endDateHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.tradingCalendar.refreshDays")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={tradingCalendarForm.refresh_days}
                  onChange={(e) => updateTradingCalendarForm("refresh_days", e.target.value)}
                />
                <div className="form-hint">{t("data.tradingCalendar.refreshDaysHint")}</div>
              </div>
              <div className="form-row trading-calendar-toggle">
                <label className="form-label">{t("data.tradingCalendar.overrides")}</label>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={tradingCalendarForm.override_enabled}
                    onChange={(e) =>
                      updateTradingCalendarForm("override_enabled", e.target.checked)
                    }
                  />
                  <span className="slider" />
                </label>
                <div className="form-hint">{t("data.tradingCalendar.overridesHint")}</div>
              </div>
            </div>
          </div>
          {tradingCalendarResult && (
            <div className="form-success">{tradingCalendarResult}</div>
          )}
          {tradingCalendarError && <div className="form-error">{tradingCalendarError}</div>}
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <button
              className="button-secondary"
              onClick={saveTradingCalendar}
              disabled={tradingCalendarSaving}
            >
              {tradingCalendarSaving ? t("common.actions.loading") : t("common.actions.save")}
            </button>
            <button
              className="button-secondary"
              onClick={refreshTradingCalendar}
              disabled={tradingCalendarRefreshing}
            >
              {tradingCalendarRefreshing
                ? t("common.actions.loading")
                : t("data.tradingCalendar.refresh")}
            </button>
          </div>
          {tradingCalendar?.calendar_path && (
            <div className="form-note">
              {t("data.tradingCalendar.calendarPath", {
                path: tradingCalendar.calendar_path,
              })}
            </div>
          )}
          {tradingCalendar?.overrides_path && (
            <div className="form-note">
              {t("data.tradingCalendar.overridesPath", {
                path: tradingCalendar.overrides_path,
              })}
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">{t("data.alphaRate.title")}</div>
          <div className="card-meta">
            {t("data.alphaRate.meta", { path: alphaRate?.path || "-" })}
          </div>
          {alphaRate && (
            <div className="meta-list">
              <div className="meta-row">
                <span>{t("data.alphaRate.source")}</span>
                <strong>{alphaRate.source}</strong>
              </div>
              <div className="meta-row">
                <span>{t("data.alphaRate.effective")}</span>
                <strong>
                  {Number.isFinite(alphaRate.effective_min_delay_seconds)
                    ? alphaRate.effective_min_delay_seconds.toFixed(2)
                    : "-"}
                  s
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("common.labels.updatedAt")}</span>
                <strong>
                  {alphaRate.updated_at ? formatDateTime(alphaRate.updated_at) : "-"}
                </strong>
              </div>
            </div>
          )}
          <div className="alpha-rate-section">
            <div className="section-title">{t("data.alphaRate.baseTitle")}</div>
            <div className="form-grid alpha-rate-grid">
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.maxRpm")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={alphaRateForm.max_rpm}
                  onChange={(e) => updateAlphaRateForm("max_rpm", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.maxRpmHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.minDelay")}</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-input"
                  value={alphaRateForm.min_delay_seconds}
                  onChange={(e) => updateAlphaRateForm("min_delay_seconds", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.minDelayHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.rateLimitSleep")}</label>
                <input
                  type="number"
                  step="1"
                  className="form-input"
                  value={alphaRateForm.rate_limit_sleep}
                  onChange={(e) => updateAlphaRateForm("rate_limit_sleep", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.rateLimitSleepHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.rateLimitRetries")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={alphaRateForm.rate_limit_retries}
                  onChange={(e) => updateAlphaRateForm("rate_limit_retries", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.rateLimitRetriesHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.maxRetries")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={alphaRateForm.max_retries}
                  onChange={(e) => updateAlphaRateForm("max_retries", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.maxRetriesHint")}</div>
              </div>
            </div>
          </div>
          <div className="alpha-rate-section">
            <div className="section-title">{t("data.alphaRate.tuneTitle")}</div>
            <div className="form-grid alpha-rate-grid">
              <div className="form-row alpha-rate-toggle">
                <label className="form-label">{t("data.alphaRate.autoTune")}</label>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={alphaRateForm.auto_tune}
                    onChange={(e) => updateAlphaRateForm("auto_tune", e.target.checked)}
                  />
                  <span className="slider" />
                </label>
                <div className="form-hint">{t("data.alphaRate.autoTuneHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.rpmFloor")}</label>
                <input
                  type="number"
                  step="1"
                  className="form-input"
                  value={alphaRateForm.rpm_floor}
                  onChange={(e) => updateAlphaRateForm("rpm_floor", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.rpmFloorHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.rpmCeil")}</label>
                <input
                  type="number"
                  step="1"
                  className="form-input"
                  value={alphaRateForm.rpm_ceil}
                  onChange={(e) => updateAlphaRateForm("rpm_ceil", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.rpmCeilHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.rpmStepDown")}</label>
                <input
                  type="number"
                  step="1"
                  className="form-input"
                  value={alphaRateForm.rpm_step_down}
                  onChange={(e) => updateAlphaRateForm("rpm_step_down", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.rpmStepDownHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.rpmStepUp")}</label>
                <input
                  type="number"
                  step="1"
                  className="form-input"
                  value={alphaRateForm.rpm_step_up}
                  onChange={(e) => updateAlphaRateForm("rpm_step_up", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.rpmStepUpHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.minDelayFloor")}</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-input"
                  value={alphaRateForm.min_delay_floor_seconds}
                  onChange={(e) =>
                    updateAlphaRateForm("min_delay_floor_seconds", e.target.value)
                  }
                />
                <div className="form-hint">{t("data.alphaRate.minDelayFloorHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.minDelayCeil")}</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-input"
                  value={alphaRateForm.min_delay_ceil_seconds}
                  onChange={(e) =>
                    updateAlphaRateForm("min_delay_ceil_seconds", e.target.value)
                  }
                />
                <div className="form-hint">{t("data.alphaRate.minDelayCeilHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.tuneStep")}</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-input"
                  value={alphaRateForm.tune_step_seconds}
                  onChange={(e) => updateAlphaRateForm("tune_step_seconds", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.tuneStepHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.tuneWindow")}</label>
                <input
                  type="number"
                  step="1"
                  className="form-input"
                  value={alphaRateForm.tune_window_seconds}
                  onChange={(e) => updateAlphaRateForm("tune_window_seconds", e.target.value)}
                />
                <div className="form-hint">{t("data.alphaRate.tuneWindowHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.tuneLow")}</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-input"
                  value={alphaRateForm.tune_target_ratio_low}
                  onChange={(e) =>
                    updateAlphaRateForm("tune_target_ratio_low", e.target.value)
                  }
                />
                <div className="form-hint">{t("data.alphaRate.tuneLowHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.tuneHigh")}</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-input"
                  value={alphaRateForm.tune_target_ratio_high}
                  onChange={(e) =>
                    updateAlphaRateForm("tune_target_ratio_high", e.target.value)
                  }
                />
                <div className="form-hint">{t("data.alphaRate.tuneHighHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("data.alphaRate.tuneCooldown")}</label>
                <input
                  type="number"
                  step="1"
                  className="form-input"
                  value={alphaRateForm.tune_cooldown_seconds}
                  onChange={(e) =>
                    updateAlphaRateForm("tune_cooldown_seconds", e.target.value)
                  }
                />
                <div className="form-hint">{t("data.alphaRate.tuneCooldownHint")}</div>
              </div>
            </div>
          </div>
          {alphaRateResult && <div className="form-success">{alphaRateResult}</div>}
          {alphaRateError && <div className="form-error">{alphaRateError}</div>}
          <button
            className="button-secondary"
            onClick={saveAlphaRate}
            disabled={alphaRateSaving}
          >
            {alphaRateSaving ? t("common.actions.loading") : t("common.actions.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
