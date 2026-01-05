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
  message?: string | null;
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
  const [bulkAutoForm, setBulkAutoForm] = useState({
    status: "all",
    batch_size: "200",
    only_missing: true,
    min_delay_seconds: "0.1",
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
  const [pitFundForm, setPitFundForm] = useState({
    start: "",
    end: "",
    report_delay_days: "1",
    min_delay_seconds: "0.8",
    refresh_fundamentals: false,
  });
  const [pitFundJobs, setPitFundJobs] = useState<PitFundamentalJob[]>([]);
  const [pitFundLoadError, setPitFundLoadError] = useState("");
  const [pitFundActionLoading, setPitFundActionLoading] = useState(false);
  const [pitFundActionError, setPitFundActionError] = useState("");
  const [pitFundActionResult, setPitFundActionResult] = useState("");
  const [pitFundProgress, setPitFundProgress] = useState<PitFundamentalProgress | null>(null);
  const [pitFundProgressError, setPitFundProgressError] = useState("");
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

  const loadSyncSpeed = async () => {
    const res = await api.get<DataSyncSpeed>("/api/datasets/sync-jobs/speed", {
      params: { window_seconds: 60 },
    });
    return res.data;
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
        } else {
          setPitQuality(null);
          setPitQualityError("");
        }
        const fundJobs = await loadPitFundJobs();
        const latestFundJob = fundJobs && fundJobs.length > 0 ? fundJobs[0] : null;
        if (latestFundJob) {
          await loadPitFundProgress(latestFundJob.id);
        } else {
          setPitFundProgress(null);
          setPitFundProgressError("");
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
      const minDelay = Math.max(Number.parseFloat(pitFundForm.min_delay_seconds) || 0, 0);
      const payload = {
        start: pitFundForm.start || null,
        end: pitFundForm.end || null,
        report_delay_days: delayDays,
        min_delay_seconds: minDelay,
        refresh_fundamentals: pitFundForm.refresh_fundamentals,
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
      const res = await api.post<BulkSyncJob>("/api/datasets/actions/bulk-sync", {
        status: bulkAutoForm.status,
        batch_size: batchSize,
        only_missing: bulkAutoForm.only_missing,
        min_delay_seconds: minDelay,
        refresh_listing: true,
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
                {pitQualityError && <div className="form-error">{pitQualityError}</div>}
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
                    {pitFundProgress.current_symbol ? (
                      <div className="progress-meta">
                        {t("data.pitFund.progress.current", {
                          symbol: pitFundProgress.current_symbol,
                        })}
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
                    <th>{t("common.labels.createdAt")}</th>
                  </tr>
                </thead>
                <tbody>
                  {pitFundJobs.map((job) => (
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

          </div>
          <div className="data-stack">
            <div className="card">
              <div className="card-title">{t("data.bulk.title")}</div>
              <div className="card-meta">{t("data.bulk.meta")}</div>
              <div className="form-grid">
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
                        <span>{job.message || t("common.none")}</span>
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
      </div>
    </div>
  );
}
