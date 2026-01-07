import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import PaginationBar from "../components/PaginationBar";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { Paginated } from "../types";

interface Project {
  id: number;
  name: string;
  description?: string | null;
  created_at: string;
}

interface ProjectVersion {
  id: number;
  project_id: number;
  version?: string | null;
  description?: string | null;
  content_hash?: string | null;
  created_at: string;
}

interface ProjectDiff {
  project_id: number;
  from_version_id: number;
  to_version_id: number;
  diff: string;
}

interface Algorithm {
  id: number;
  name: string;
  version?: string | null;
  language: string;
}

interface AlgorithmVersion {
  id: number;
  algorithm_id: number;
  version?: string | null;
  description?: string | null;
  language: string;
  file_path?: string | null;
  type_name?: string | null;
  created_at: string;
}

interface MLTrainJob {
  id: number;
  project_id: number;
  status: string;
  config?: Record<string, any> | null;
  metrics?: Record<string, any> | null;
  output_dir?: string | null;
  model_path?: string | null;
  payload_path?: string | null;
  scores_path?: string | null;
  log_path?: string | null;
  message?: string | null;
  is_active?: boolean;
  progress?: number | null;
  progress_detail?: Record<string, any> | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

interface ThemeSystemMeta {
  theme_id: number;
  version_id?: number | null;
  version?: string | null;
  source?: string | null;
  mode?: string | null;
}

interface ThemeSystemBase {
  label?: string | null;
  keywords?: string[];
  manual?: string[];
  exclude?: string[];
}

interface ThemeConfigItem {
  key: string;
  label: string;
  weight: number;
  priority?: number;
  keywords?: string[];
  manual?: string[];
  exclude?: string[];
  system?: ThemeSystemMeta | null;
  system_base?: ThemeSystemBase | null;
  source?: string | null;
  snapshot?: { theme_id?: number; version_id?: number; version?: string } | null;
}

interface ProjectStrategyConfig {
  source?: string | null;
  score_csv_path?: string | null;
  score_top_n?: number | null;
  score_weighting?: string | null;
  score_min?: number | null;
  score_max_weight?: number | null;
  score_fallback?: string | null;
}

interface ProjectConfig {
  template?: string;
  universe?: {
    mode?: string;
    include_history?: boolean;
    asset_types?: string[];
    pit_universe_only?: boolean;
  };
  data?: { primary_vendor?: string; fallback_vendor?: string; frequency?: string };
  weights?: Record<string, number>;
  benchmark?: string;
  rebalance?: string;
  risk_free_rate?: number;
  backtest_start?: string | null;
  backtest_end?: string | null;
  backtest_params?: Record<string, any>;
  backtest_plugins?: Record<string, any>;
  categories?: { key: string; label: string }[];
  themes?: ThemeConfigItem[];
  symbol_types?: Record<string, string>;
  strategy?: ProjectStrategyConfig;
}

interface ProjectConfigResponse {
  project_id: number;
  config: ProjectConfig;
  source: string;
  updated_at?: string | null;
  version_id?: number | null;
}

interface ProjectDataStatus {
  project_id: number;
  data_root: string;
  membership: {
    records: number;
    symbols: number;
    start?: string | null;
    end?: string | null;
    updated_at?: string | null;
  };
  universe: {
    records: number;
    sp500_count: number;
    theme_count: number;
    updated_at?: string | null;
  };
  themes: { records: number; categories: string[]; updated_at?: string | null };
  metrics: { records: number; updated_at?: string | null };
  prices: { stooq_files: number; yahoo_files: number; updated_at?: string | null };
  backtest: { updated_at?: string | null; summary?: Record<string, any> | null };
}

interface BacktestRun {
  id: number;
  project_id: number;
  status: string;
  params?: Record<string, unknown> | null;
  metrics?: Record<string, unknown> | null;
  created_at: string;
  ended_at?: string | null;
}

interface AutoWeeklyJob {
  id: number;
  project_id: number;
  status: string;
  params?: Record<string, unknown> | null;
  pit_weekly_job_id?: number | null;
  pit_weekly_log_path?: string | null;
  pit_fundamental_job_id?: number | null;
  pit_fundamental_log_path?: string | null;
  backtest_status?: string | null;
  backtest_log_path?: string | null;
  backtest_output_dir?: string | null;
  backtest_artifact_dir?: string | null;
  log_path?: string | null;
  message?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

interface FactorScoreJob {
  id: number;
  project_id: number;
  status: string;
  params?: Record<string, unknown> | null;
  output_dir?: string | null;
  log_path?: string | null;
  scores_path?: string | null;
  message?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

interface ThemeSummaryItem {
  key: string;
  label: string;
  symbols: number;
  sample: string[];
  sample_types?: Record<string, string>;
  manual_symbols?: string[];
  exclude_symbols?: string[];
}

interface ProjectThemeSummary {
  project_id: number;
  updated_at?: string | null;
  total_symbols: number;
  themes: ThemeSummaryItem[];
}

interface ProjectThemeSymbols {
  project_id: number;
  category: string;
  label?: string | null;
  symbols: string[];
  auto_symbols?: string[];
  manual_symbols?: string[];
  exclude_symbols?: string[];
  symbol_types?: Record<string, string>;
}

interface ThemeSearchItem {
  key: string;
  label: string;
  is_manual?: boolean;
  is_excluded?: boolean;
}

interface ProjectThemeSearch {
  project_id: number;
  symbol: string;
  themes: ThemeSearchItem[];
}

interface ProjectAlgorithmBinding {
  project_id: number;
  exists: boolean;
  algorithm_id?: number | null;
  algorithm_version_id?: number | null;
  algorithm_name?: string | null;
  algorithm_version?: string | null;
  is_locked: boolean;
  updated_at?: string | null;
}

export default function ProjectsPage() {
  const { t, formatDateTime } = useI18n();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectTotal, setProjectTotal] = useState(0);
  const [projectPage, setProjectPage] = useState(1);
  const [projectPageSize, setProjectPageSize] = useState(10);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [projectErrorKey, setProjectErrorKey] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [versions, setVersions] = useState<ProjectVersion[]>([]);
  const [versionOptions, setVersionOptions] = useState<ProjectVersion[]>([]);
  const [versionTotal, setVersionTotal] = useState(0);
  const [versionPage, setVersionPage] = useState(1);
  const [versionPageSize, setVersionPageSize] = useState(10);
  const [versionForm, setVersionForm] = useState({
    version: "",
    description: "",
    content: "",
  });
  const [versionErrorKey, setVersionErrorKey] = useState("");
  const [diffFromId, setDiffFromId] = useState("");
  const [diffToId, setDiffToId] = useState("");
  const [diffResult, setDiffResult] = useState("");
  const [diffErrorKey, setDiffErrorKey] = useState("");
  const [configDraft, setConfigDraft] = useState<ProjectConfig | null>(null);
  const [configMeta, setConfigMeta] = useState<ProjectConfigResponse | null>(null);
  const [configMessage, setConfigMessage] = useState("");
  const [themeDrafts, setThemeDrafts] = useState<ThemeConfigItem[]>([]);
  const [themeSummary, setThemeSummary] = useState<ProjectThemeSummary | null>(null);
  const [themeSummaryMessage, setThemeSummaryMessage] = useState("");
  const [themeFilterText, setThemeFilterText] = useState("");
  const [themeSearchSymbol, setThemeSearchSymbol] = useState("");
  const [themeSearchResult, setThemeSearchResult] = useState<ProjectThemeSearch | null>(null);
  const [themeSearchMessage, setThemeSearchMessage] = useState("");
  const [activeThemeKey, setActiveThemeKey] = useState("");
  const [activeThemeSymbols, setActiveThemeSymbols] = useState<ProjectThemeSymbols | null>(null);
  const [themeSymbolQuery, setThemeSymbolQuery] = useState("");
  const [themeSymbolsCache, setThemeSymbolsCache] = useState<
    Record<string, ProjectThemeSymbols>
  >({});
  const [highlightThemeKey, setHighlightThemeKey] = useState("");
  const [compareThemeA, setCompareThemeA] = useState("");
  const [compareThemeB, setCompareThemeB] = useState("");
  const [compareMessage, setCompareMessage] = useState("");
  const [newThemeSymbol, setNewThemeSymbol] = useState("");
  const [newThemeSymbolType, setNewThemeSymbolType] = useState("STOCK");
  const [themeSymbolMessage, setThemeSymbolMessage] = useState("");
  const themeSaveTimer = useRef<number | null>(null);
  const [configSection, setConfigSection] = useState<
    "universe" | "data" | "themes" | "portfolio"
  >("universe");
  const [dataStatus, setDataStatus] = useState<ProjectDataStatus | null>(null);
  const [dataMessage, setDataMessage] = useState("");
  const [latestBacktest, setLatestBacktest] = useState<BacktestRun | null>(null);
  const [backtestMessage, setBacktestMessage] = useState("");
  const [autoWeeklyJob, setAutoWeeklyJob] = useState<AutoWeeklyJob | null>(null);
  const [autoWeeklyMessage, setAutoWeeklyMessage] = useState("");
  const [autoWeeklyLoading, setAutoWeeklyLoading] = useState(false);
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [algorithmVersions, setAlgorithmVersions] = useState<AlgorithmVersion[]>([]);
  const [binding, setBinding] = useState<ProjectAlgorithmBinding | null>(null);
  const [bindingForm, setBindingForm] = useState({
    algorithmId: "",
    versionId: "",
    isLocked: true,
  });
  const [bindingMessage, setBindingMessage] = useState("");
  const [benchmarkMessage, setBenchmarkMessage] = useState("");
  const [mlJobs, setMlJobs] = useState<MLTrainJob[]>([]);
  const [mlMessage, setMlMessage] = useState("");
  const [mlLoading, setMlLoading] = useState(false);
  const [mlActionLoadingId, setMlActionLoadingId] = useState<number | null>(null);
  const [mlDetailId, setMlDetailId] = useState<number | null>(null);
  const [mlForm, setMlForm] = useState({
    device: "auto",
    trainYears: "8",
    trainStartYear: "",
    validMonths: "12",
    testMonths: "12",
    stepMonths: "6",
    labelHorizonDays: "20",
    walkForwardEnabled: true,
    modelType: "torch_mlp",
    modelParams: "",
  });
  const [factorJobs, setFactorJobs] = useState<FactorScoreJob[]>([]);
  const [factorLoadError, setFactorLoadError] = useState("");
  const [factorActionMessage, setFactorActionMessage] = useState("");
  const [factorActionLoading, setFactorActionLoading] = useState(false);
  const [factorForm, setFactorForm] = useState({
    start: "",
    end: "",
    config_path: "",
    output_path: "",
    overwrite_cache: false,
  });
  const [projectTab, setProjectTab] = useState<
    "overview" | "config" | "algorithm" | "data" | "backtest" | "versions" | "diff"
  >("overview");
  const [projectSearch, setProjectSearch] = useState("");
  const backtestRefreshTimers = useRef<number[]>([]);
  const autoWeeklyRefreshTimers = useRef<number[]>([]);

  const symbolTypeOptions = [
    { value: "STOCK", label: t("symbols.types.stock") },
    { value: "ETF", label: t("symbols.types.etf") },
    { value: "ADR", label: t("symbols.types.adr") },
    { value: "REIT", label: t("symbols.types.reit") },
    { value: "ETN", label: t("symbols.types.etn") },
    { value: "FUND", label: t("symbols.types.fund") },
    { value: "INDEX", label: t("symbols.types.index") },
    { value: "UNKNOWN", label: t("symbols.types.unknown") },
  ];

  const normalizeThemeDrafts = (config: ProjectConfig): ThemeConfigItem[] => {
    if (config.themes && config.themes.length) {
      return config.themes.map((item) => ({
        key: item.key || "",
        label: item.label || item.key || "",
        weight: Number(item.weight ?? config.weights?.[item.key] ?? 0),
        priority: Number(item.priority ?? 0),
        keywords: item.keywords || [],
        manual: item.manual || [],
        exclude: item.exclude || [],
        system: item.system || null,
        system_base: item.system_base || null,
        source: item.source || null,
        snapshot: item.snapshot || null,
      }));
    }
    const categoryList =
      config.categories?.length
        ? config.categories
        : Object.keys(config.weights || {}).map((key) => ({ key, label: key }));
    return categoryList.map((category) => ({
      key: category.key,
      label: category.label || category.key,
      weight: Number(config.weights?.[category.key] ?? 0),
      priority: 0,
      keywords: [],
      manual: [],
      exclude: [],
    }));
  };

  const parseListInput = (value: string) =>
    value
      .split(/[,，;；\n]/)
      .map((item) => item.trim())
      .filter((item) => item.length > 0);

  const loadProjects = async (pageOverride?: number, pageSizeOverride?: number) => {
    const nextPage = pageOverride ?? projectPage;
    const nextSize = pageSizeOverride ?? projectPageSize;
    const res = await api.get<Paginated<Project>>("/api/projects/page", {
      params: { page: nextPage, page_size: nextSize },
    });
    setProjects(res.data.items);
    setProjectTotal(res.data.total);
    if (
      res.data.items.length &&
      (!selectedProjectId || !res.data.items.some((item) => item.id === selectedProjectId))
    ) {
      setSelectedProjectId(res.data.items[0].id);
    }
    if (!res.data.items.length) {
      setSelectedProjectId(null);
    }
  };

  const loadVersions = async (projectId: number, pageOverride?: number, pageSizeOverride?: number) => {
    const nextPage = pageOverride ?? versionPage;
    const nextSize = pageSizeOverride ?? versionPageSize;
    const res = await api.get<Paginated<ProjectVersion>>(
      `/api/projects/${projectId}/versions/page`,
      { params: { page: nextPage, page_size: nextSize } }
    );
    setVersions(res.data.items);
    setVersionTotal(res.data.total);
  };

  const loadVersionOptions = async (projectId: number) => {
    const res = await api.get<ProjectVersion[]>(`/api/projects/${projectId}/versions`);
    setVersionOptions(res.data);
  };

  const loadProjectConfig = async (projectId: number) => {
    try {
      const res = await api.get<ProjectConfigResponse>(`/api/projects/${projectId}/config`);
      setConfigMeta(res.data);
      setConfigDraft(res.data.config || {});
      setThemeDrafts(normalizeThemeDrafts(res.data.config || {}));
    } catch (err) {
      setConfigMeta(null);
      setConfigDraft(null);
      setConfigMessage(t("projects.config.error"));
      setThemeDrafts([]);
    }
  };

  const loadProjectDataStatus = async (projectId: number) => {
    try {
      const res = await api.get<ProjectDataStatus>(`/api/projects/${projectId}/data-status`);
      setDataStatus(res.data);
    } catch (err) {
      setDataStatus(null);
      setDataMessage(t("projects.dataStatus.error"));
    }
  };

  const loadLatestBacktest = async (projectId: number) => {
    try {
      const res = await api.get<BacktestRun[]>(`/api/projects/${projectId}/backtests`);
      setLatestBacktest(res.data[0] || null);
    } catch (err) {
      setLatestBacktest(null);
      setBacktestMessage(t("projects.backtest.error"));
    }
  };

  const loadAutoWeeklyJob = async (projectId: number) => {
    try {
      const res = await api.get<AutoWeeklyJob>("/api/automation/weekly-jobs/latest", {
        params: { project_id: projectId },
      });
      setAutoWeeklyJob(res.data);
      setAutoWeeklyMessage("");
    } catch (err) {
      setAutoWeeklyJob(null);
    }
  };

  const scheduleBacktestRefresh = (projectId: number) => {
    backtestRefreshTimers.current.forEach((timer) => window.clearTimeout(timer));
    backtestRefreshTimers.current = [
      window.setTimeout(() => {
        void loadLatestBacktest(projectId);
      }, 4000),
      window.setTimeout(() => {
        void loadLatestBacktest(projectId);
      }, 12000),
    ];
  };

  const scheduleAutoWeeklyRefresh = (projectId: number) => {
    autoWeeklyRefreshTimers.current.forEach((timer) => window.clearTimeout(timer));
    autoWeeklyRefreshTimers.current = [
      window.setTimeout(() => {
        void loadAutoWeeklyJob(projectId);
      }, 4000),
      window.setTimeout(() => {
        void loadAutoWeeklyJob(projectId);
      }, 12000),
    ];
  };

  const loadThemeSummary = async (projectId: number) => {
    try {
      const res = await api.get<ProjectThemeSummary>(
        `/api/projects/${projectId}/themes/summary`
      );
      setThemeSummary(res.data);
      setThemeSummaryMessage("");
    } catch (err) {
      setThemeSummary(null);
      setThemeSummaryMessage(t("projects.config.themeSummaryError"));
    }
  };

  const loadAlgorithms = async () => {
    try {
      const res = await api.get<Algorithm[]>("/api/algorithms");
      setAlgorithms(res.data);
    } catch (err) {
      setAlgorithms([]);
    }
  };

  const loadAlgorithmVersions = async (algorithmId: number) => {
    try {
      const res = await api.get<AlgorithmVersion[]>(`/api/algorithms/${algorithmId}/versions`);
      setAlgorithmVersions(res.data);
    } catch (err) {
      setAlgorithmVersions([]);
    }
  };

  const loadProjectBinding = async (projectId: number) => {
    try {
      const res = await api.get<ProjectAlgorithmBinding>(
        `/api/projects/${projectId}/algorithm-binding`
      );
      setBinding(res.data);
      setBindingForm({
        algorithmId: res.data.algorithm_id ? String(res.data.algorithm_id) : "",
        versionId: res.data.algorithm_version_id ? String(res.data.algorithm_version_id) : "",
        isLocked: res.data.exists ? !!res.data.is_locked : true,
      });
      if (res.data.algorithm_id) {
        loadAlgorithmVersions(res.data.algorithm_id);
      }
    } catch (err) {
      setBinding(null);
      setBindingMessage(t("projects.algorithm.error"));
    }
  };

  const loadMlJobs = async (projectId: number) => {
    try {
      const res = await api.get<MLTrainJob[]>("/api/ml/train-jobs", {
        params: { project_id: projectId },
      });
      setMlJobs(res.data || []);
      setMlMessage("");
    } catch (err) {
      setMlJobs([]);
      setMlMessage(t("projects.ml.error"));
    }
  };

  const loadFactorJobs = async (projectId: number) => {
    try {
      const res = await api.get<FactorScoreJob[]>("/api/factor-scores/jobs", {
        params: { project_id: projectId },
      });
      setFactorJobs(res.data || []);
      setFactorLoadError("");
    } catch (err) {
      setFactorJobs([]);
      setFactorLoadError(t("projects.factorScores.error"));
    }
  };

  const createMlJob = async () => {
    if (!selectedProjectId) {
      return;
    }
    const toNumber = (value: string) => {
      if (!value.trim()) {
        return undefined;
      }
      const num = Number(value);
      return Number.isFinite(num) ? num : undefined;
    };
    let modelParams: Record<string, any> | undefined;
    const rawParams = mlForm.modelParams?.trim();
    if (rawParams) {
      try {
        const parsed = JSON.parse(rawParams);
        if (!parsed || typeof parsed !== "object") {
          throw new Error("invalid");
        }
        modelParams = parsed as Record<string, any>;
      } catch (err) {
        setMlMessage(t("projects.ml.modelParamsError"));
        return;
      }
    }
    const walkForwardEnabled = !!mlForm.walkForwardEnabled;
    setMlLoading(true);
    setMlMessage("");
    try {
      await api.post("/api/ml/train-jobs", {
        project_id: selectedProjectId,
        device: mlForm.device,
        train_years: toNumber(mlForm.trainYears),
        train_start_year: toNumber(mlForm.trainStartYear),
        valid_months: toNumber(mlForm.validMonths),
        test_months: walkForwardEnabled ? toNumber(mlForm.testMonths) : 0,
        step_months: walkForwardEnabled ? toNumber(mlForm.stepMonths) : 0,
        label_horizon_days: toNumber(mlForm.labelHorizonDays),
        model_type: mlForm.modelType,
        model_params: modelParams,
      });
      await loadMlJobs(selectedProjectId);
      setMlMessage(t("projects.ml.queued"));
    } catch (err) {
      setMlMessage(t("projects.ml.error"));
    } finally {
      setMlLoading(false);
    }
  };

  const createFactorJob = async () => {
    if (!selectedProjectId) {
      return;
    }
    setFactorActionLoading(true);
    setFactorActionMessage("");
    try {
      await api.post("/api/factor-scores/jobs", {
        project_id: selectedProjectId,
        start: factorForm.start || null,
        end: factorForm.end || null,
        config_path: factorForm.config_path || null,
        output_path: factorForm.output_path || null,
        overwrite_cache: factorForm.overwrite_cache,
      });
      await loadFactorJobs(selectedProjectId);
      setFactorActionMessage(t("projects.factorScores.queued"));
    } catch (err) {
      setFactorActionMessage(t("projects.factorScores.error"));
    } finally {
      setFactorActionLoading(false);
    }
  };

  const activateMlJob = async (jobId: number) => {
    if (!selectedProjectId) {
      return;
    }
    setMlMessage("");
    try {
      await api.post(`/api/ml/train-jobs/${jobId}/activate`);
      await loadMlJobs(selectedProjectId);
      setMlMessage(t("projects.ml.activated"));
    } catch (err) {
      setMlMessage(t("projects.ml.activateError"));
    }
  };

  const cancelMlJob = async (jobId: number) => {
    if (!selectedProjectId) {
      return;
    }
    setMlActionLoadingId(jobId);
    setMlMessage("");
    try {
      await api.post(`/api/ml/train-jobs/${jobId}/cancel`);
      await loadMlJobs(selectedProjectId);
      setMlMessage(t("projects.ml.cancelRequested"));
    } catch (err) {
      setMlMessage(t("projects.ml.cancelError"));
    } finally {
      setMlActionLoadingId(null);
    }
  };

  useEffect(() => {
    loadProjects();
  }, [projectPage, projectPageSize]);

  useEffect(() => {
    loadAlgorithms();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      setVersionPage(1);
      loadVersions(selectedProjectId, 1, versionPageSize);
      loadVersionOptions(selectedProjectId);
      loadProjectConfig(selectedProjectId);
      loadProjectDataStatus(selectedProjectId);
      loadLatestBacktest(selectedProjectId);
      loadThemeSummary(selectedProjectId);
      loadProjectBinding(selectedProjectId);
      loadMlJobs(selectedProjectId);
      loadFactorJobs(selectedProjectId);
      setConfigMessage("");
      setDataMessage("");
      setBacktestMessage("");
      setBenchmarkMessage("");
      setBindingMessage("");
      setNewThemeSymbol("");
      setNewThemeSymbolType("STOCK");
      setThemeSymbolMessage("");
      setProjectTab("overview");
    } else {
      setVersions([]);
      setVersionOptions([]);
      setVersionTotal(0);
      setConfigDraft(null);
      setConfigMeta(null);
      setDataStatus(null);
      setLatestBacktest(null);
      setThemeSummary(null);
      setThemeSummaryMessage("");
      setThemeFilterText("");
      setThemeSearchSymbol("");
      setThemeSearchResult(null);
      setThemeSearchMessage("");
      setActiveThemeKey("");
      setActiveThemeSymbols(null);
      setThemeSymbolQuery("");
      setThemeSymbolsCache({});
      setHighlightThemeKey("");
      setCompareThemeA("");
      setCompareThemeB("");
      setCompareMessage("");
      setBinding(null);
      setMlJobs([]);
      setMlMessage("");
      setMlActionLoadingId(null);
      setMlDetailId(null);
      setFactorJobs([]);
      setFactorLoadError("");
      setFactorActionMessage("");
      setNewThemeSymbol("");
      setNewThemeSymbolType("STOCK");
      setThemeSymbolMessage("");
      setBenchmarkMessage("");
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    const hasActiveJob = mlJobs.some(
      (job) => job.status === "running" || job.status === "queued"
    );
    if (!hasActiveJob) {
      return;
    }
    const timer = window.setInterval(() => {
      loadMlJobs(selectedProjectId);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [selectedProjectId, mlJobs]);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    const hasActiveJob = factorJobs.some(
      (job) => job.status === "running" || job.status === "queued"
    );
    if (!hasActiveJob) {
      return;
    }
    const timer = window.setInterval(() => {
      loadFactorJobs(selectedProjectId);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [selectedProjectId, factorJobs]);

  useEffect(() => {
    const selectedId = Number(bindingForm.algorithmId);
    if (selectedId) {
      loadAlgorithmVersions(selectedId);
    } else {
      setAlgorithmVersions([]);
    }
  }, [bindingForm.algorithmId]);

  useEffect(() => {
    if (selectedProjectId) {
      loadVersions(selectedProjectId);
    }
  }, [versionPage, versionPageSize]);

  useEffect(() => {
    if (selectedProjectId && projectTab === "backtest") {
      loadLatestBacktest(selectedProjectId);
      loadAutoWeeklyJob(selectedProjectId);
    }
  }, [projectTab, selectedProjectId]);

  useEffect(() => {
    return () => {
      backtestRefreshTimers.current.forEach((timer) => window.clearTimeout(timer));
      autoWeeklyRefreshTimers.current.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  const createProject = async () => {
    if (!name.trim()) {
      setProjectErrorKey("projects.new.errorName");
      return;
    }
    setProjectErrorKey("");
    await api.post("/api/projects", { name, description });
    setName("");
    setDescription("");
    setProjectPage(1);
    loadProjects(1, projectPageSize);
  };

  const updateVersionForm = (key: keyof typeof versionForm, value: string) => {
    setVersionForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateStrategyField = (key: keyof ProjectStrategyConfig, value: string | number | boolean) => {
    setConfigDraft((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        strategy: {
          ...(prev.strategy || {}),
          [key]: value,
        },
      };
    });
  };

  const handleStrategySourceChange = (value: string) => {
    const normalized = value || "theme_weights";
    setConfigDraft((prev) => {
      if (!prev) {
        return prev;
      }
      const next = { ...(prev.strategy || {}), source: normalized };
      if (normalized === "factor_scores") {
        next.score_csv_path = "ml/models/factor_scores.csv";
      } else if (normalized === "ml_scores") {
        next.score_csv_path = "ml/models/scores.csv";
      } else {
        next.score_csv_path = "";
      }
      return { ...prev, strategy: next };
    });
  };

  const createVersion = async () => {
    if (!selectedProjectId) {
      setVersionErrorKey("projects.versions.errorSelect");
      return;
    }
    if (!versionForm.version.trim() && !versionForm.content.trim()) {
      setVersionErrorKey("projects.versions.errorContent");
      return;
    }
    setVersionErrorKey("");
    await api.post(`/api/projects/${selectedProjectId}/versions`, {
      version: versionForm.version || null,
      description: versionForm.description || null,
      content: versionForm.content || null,
    });
    setVersionForm({ version: "", description: "", content: "" });
    setVersionPage(1);
    loadVersions(selectedProjectId, 1, versionPageSize);
    loadVersionOptions(selectedProjectId);
  };

  const updateConfigSection = (
    section: keyof ProjectConfig,
    key: string,
    value: string | number | boolean | string[]
  ) => {
    setConfigDraft((prev) => {
      const next = { ...(prev || {}) };
      const sectionValue = { ...(next[section] as Record<string, any> | undefined) };
      sectionValue[key] = value;
      (next as Record<string, any>)[section] = sectionValue;
      return next;
    });
  };

  const updateBacktestPlugin = (key: string, value: any) => {
    setConfigDraft((prev) => {
      const next = { ...(prev || {}) } as ProjectConfig;
      const plugins = { ...(next.backtest_plugins || {}) } as Record<string, any>;
      plugins[key] = value;
      next.backtest_plugins = plugins;
      return next;
    });
  };

  const updateBacktestPluginSection = (section: string, key: string, value: any) => {
    setConfigDraft((prev) => {
      const next = { ...(prev || {}) } as ProjectConfig;
      const plugins = { ...(next.backtest_plugins || {}) } as Record<string, any>;
      const sectionValue = { ...(plugins[section] || {}) };
      sectionValue[key] = value;
      plugins[section] = sectionValue;
      next.backtest_plugins = plugins;
      return next;
    });
  };

  const toggleUniverseAssetType = (value: string) => {
    setConfigDraft((prev) => {
      const next = { ...(prev || {}) } as ProjectConfig;
      const universe = { ...(next.universe || {}) };
      const current = new Set<string>(universe.asset_types || []);
      if (current.has(value)) {
        current.delete(value);
      } else {
        current.add(value);
      }
      universe.asset_types = Array.from(current);
      next.universe = universe;
      return next;
    });
  };

  const addTheme = () => {
    setThemeDrafts((prev) => [
      ...prev,
      { key: "", label: "", weight: 0, priority: 0, keywords: [], manual: [], exclude: [] },
    ]);
  };

  const updateTheme = (
    index: number,
    field:
      | "key"
      | "label"
      | "weight"
      | "priority"
      | "keywords"
      | "manual"
      | "exclude",
    value: string | number
  ) => {
    setThemeDrafts((prev) =>
      prev.map((item, idx) => {
        if (idx !== index) {
          return item;
        }
        if (field === "keywords" || field === "manual" || field === "exclude") {
          return { ...item, [field]: parseListInput(String(value)) };
        }
        if (field === "weight") {
          return { ...item, weight: Number(value) || 0 };
        }
        if (field === "priority") {
          return { ...item, priority: Number(value) || 0 };
        }
        return { ...item, [field]: String(value) };
      })
    );
  };

  const removeTheme = (index: number) => {
    setThemeDrafts((prev) => prev.filter((_, idx) => idx !== index));
  };

  const loadThemeSymbols = async (key: string) => {
    if (!selectedProjectId) {
      return;
    }
    try {
      const res = await api.get<ProjectThemeSymbols>(
        `/api/projects/${selectedProjectId}/themes/symbols`,
        { params: { category: key } }
      );
      setActiveThemeKey(key);
      setActiveThemeSymbols(res.data);
      setThemeSymbolQuery("");
      setNewThemeSymbol("");
      setNewThemeSymbolType("STOCK");
      setThemeSymbolMessage("");
      setBenchmarkMessage("");
      setThemeSymbolsCache((prev) => ({ ...prev, [key]: res.data }));
    } catch (err) {
      setActiveThemeKey("");
      setActiveThemeSymbols(null);
    }
  };

  const fetchThemeSymbolsCached = async (key: string) => {
    if (!selectedProjectId || !key) {
      return null;
    }
    const cached = themeSymbolsCache[key];
    if (cached) {
      return cached;
    }
    try {
      const res = await api.get<ProjectThemeSymbols>(
        `/api/projects/${selectedProjectId}/themes/symbols`,
        { params: { category: key } }
      );
      setThemeSymbolsCache((prev) => ({ ...prev, [key]: res.data }));
      return res.data;
    } catch (err) {
      return null;
    }
  };

  const exportThemeSymbols = () => {
    if (!activeThemeKey || !activeThemeSymbols) {
      return;
    }
    const rows = ["symbol", ...filteredCombinedSymbols];
    const blob = new Blob([rows.join("\n")], {
      type: "text/csv;charset=utf-8;",
    });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `theme-${activeThemeKey.toLowerCase()}-symbols.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const closeThemeSymbols = () => {
    setActiveThemeKey("");
    setActiveThemeSymbols(null);
    setThemeSymbolQuery("");
  };

  const searchThemeSymbol = async (symbolOverride?: string) => {
    if (!selectedProjectId) {
      return;
    }
    const symbol = (symbolOverride ?? themeSearchSymbol).trim().toUpperCase();
    if (!symbol) {
      setThemeSearchMessage(t("projects.config.themeSearchEmpty"));
      setThemeSearchResult(null);
      return;
    }
    try {
      const res = await api.get<ProjectThemeSearch>(
        `/api/projects/${selectedProjectId}/themes/search`,
        { params: { symbol } }
      );
      setThemeSearchSymbol(symbol);
      setThemeSearchResult(res.data);
      setThemeSearchMessage("");
    } catch (err) {
      setThemeSearchResult(null);
      setThemeSearchMessage(t("projects.config.themeSearchError"));
    }
  };

  const clearThemeSearch = () => {
    setThemeSearchSymbol("");
    setThemeSearchResult(null);
    setThemeSearchMessage("");
  };

  const applyThemeSymbolFilter = async (symbol: string) => {
    setThemeSearchSymbol(symbol);
    await searchThemeSymbol(symbol);
  };

  const normalizeSymbolInput = (value: string) => value.trim().toUpperCase();

  const normalizeSymbolType = (value?: string | null) => {
    const text = String(value || "").trim().toUpperCase();
    if (!text) {
      return "UNKNOWN";
    }
    if (text === "EQUITY") {
      return "STOCK";
    }
    return text;
  };

  const updateSymbolTypeOverride = (symbol: string, type: string) => {
    if (!configDraft) {
      return undefined;
    }
    const nextTypes = { ...(configDraft.symbol_types || {}) };
    nextTypes[symbol] = normalizeSymbolType(type);
    setConfigDraft((prev) => (prev ? { ...prev, symbol_types: nextTypes } : prev));
    return nextTypes;
  };

  const updateThemeSymbols = (
    themeKey: string,
    updater: (current: ThemeConfigItem) => ThemeConfigItem
  ) => {
    const nextDrafts = themeDrafts.map((item) =>
      item.key === themeKey ? updater(item) : item
    );
    setThemeDrafts(nextDrafts);
    return nextDrafts;
  };

  const addManualSymbol = (symbol: string, type: string) => {
    if (!activeThemeKey) {
      return;
    }
    const nextDrafts = updateThemeSymbols(activeThemeKey, (item) => {
      const manual = new Set(item.manual || []);
      manual.add(symbol);
      const exclude = new Set(item.exclude || []);
      exclude.delete(symbol);
      return {
        ...item,
        manual: Array.from(manual),
        exclude: Array.from(exclude),
      };
    });
    const nextTypes = updateSymbolTypeOverride(symbol, type);
    scheduleThemeSave(nextDrafts, nextTypes);
  };

  const addExcludeSymbol = (symbol: string, type: string) => {
    if (!activeThemeKey) {
      return;
    }
    const nextDrafts = updateThemeSymbols(activeThemeKey, (item) => {
      const exclude = new Set(item.exclude || []);
      exclude.add(symbol);
      const manual = new Set(item.manual || []);
      manual.delete(symbol);
      return {
        ...item,
        manual: Array.from(manual),
        exclude: Array.from(exclude),
      };
    });
    const nextTypes = updateSymbolTypeOverride(symbol, type);
    scheduleThemeSave(nextDrafts, nextTypes);
  };

  const removeManualSymbol = (symbol: string) => {
    if (!activeThemeKey) {
      return;
    }
    const nextDrafts = updateThemeSymbols(activeThemeKey, (item) => ({
      ...item,
      manual: (item.manual || []).filter((value) => value !== symbol),
    }));
    scheduleThemeSave(nextDrafts, undefined);
  };

  const restoreExcludedSymbol = (symbol: string) => {
    if (!activeThemeKey) {
      return;
    }
    const nextDrafts = updateThemeSymbols(activeThemeKey, (item) => ({
      ...item,
      exclude: (item.exclude || []).filter((value) => value !== symbol),
    }));
    scheduleThemeSave(nextDrafts, undefined);
  };

  const handleAddSymbol = (mode: "manual" | "exclude") => {
    const symbol = normalizeSymbolInput(newThemeSymbol);
    if (!symbol) {
      setThemeSymbolMessage(t("projects.config.themeSymbolEmpty"));
      return;
    }
    setThemeSymbolMessage("");
    if (mode === "manual") {
      addManualSymbol(symbol, newThemeSymbolType);
    } else {
      addExcludeSymbol(symbol, newThemeSymbolType);
    }
    setNewThemeSymbol("");
  };

  const yahooSymbolUrl = (symbol: string) =>
    `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}`;

  const toggleHighlightTheme = (key: string) => {
    setHighlightThemeKey((prev) => (prev === key ? "" : key));
  };

  const updateCompareTheme = async (key: string, slot: "A" | "B") => {
    if (slot === "A") {
      setCompareThemeA(key);
    } else {
      setCompareThemeB(key);
    }
    setCompareMessage("");
    if (key) {
      const data = await fetchThemeSymbolsCached(key);
      if (!data) {
        setCompareMessage(t("projects.config.themeCompareError"));
      }
    }
  };

  const buildThemePayload = (drafts: ThemeConfigItem[]) =>
    drafts
      .map((theme) => ({
        key: theme.key.trim(),
        label: theme.label.trim() || theme.key.trim(),
        weight: Number(theme.weight) || 0,
        priority: Number(theme.priority) || 0,
        keywords: theme.keywords || [],
        manual: theme.manual || [],
        exclude: theme.exclude || [],
        system: theme.system || undefined,
        system_base: theme.system_base || undefined,
        source: theme.source || undefined,
        snapshot: theme.snapshot || undefined,
      }))
      .filter((theme) => theme.key);

  const persistProjectConfig = async (
    draftsOverride?: ThemeConfigItem[],
    symbolTypesOverride?: Record<string, string>,
    silent?: boolean
  ) => {
    if (!selectedProjectId || !configDraft) {
      return false;
    }
    const themePayload = buildThemePayload(draftsOverride ?? themeDrafts);
    const keys = themePayload.map((theme) => theme.key);
    if (new Set(keys).size !== keys.length) {
      const message = t("projects.config.themeDuplicate");
      if (silent) {
        setThemeSymbolMessage(message);
      } else {
        setConfigMessage(message);
      }
      return false;
    }
    const weights = themePayload.reduce<Record<string, number>>((acc, theme) => {
      acc[theme.key] = theme.weight;
      return acc;
    }, {});
    const categories = themePayload.map((theme) => ({
      key: theme.key,
      label: theme.label,
    }));
    const payloadConfig: ProjectConfig = {
      ...configDraft,
      themes: themePayload,
      weights,
      categories,
    };
    if (symbolTypesOverride) {
      payloadConfig.symbol_types = symbolTypesOverride;
    }
    try {
      await api.post(`/api/projects/${selectedProjectId}/config`, {
        config: payloadConfig,
        version: new Date().toISOString(),
      });
      if (silent) {
        setThemeSymbolMessage(t("projects.config.saved"));
      } else {
        setConfigMessage(t("projects.config.saved"));
      }
      if (silent) {
        await loadThemeSummary(selectedProjectId);
      } else {
        await loadProjectConfig(selectedProjectId);
        await loadThemeSummary(selectedProjectId);
      }
      return true;
    } catch (err) {
      const message = t("projects.config.error");
      if (silent) {
        setThemeSymbolMessage(message);
      } else {
        setConfigMessage(message);
      }
      return false;
    }
  };

  const saveProjectConfig = async () => {
    await persistProjectConfig();
  };

  const scheduleThemeSave = (
    draftsOverride?: ThemeConfigItem[],
    symbolTypesOverride?: Record<string, string>
  ) => {
    if (themeSaveTimer.current !== null) {
      window.clearTimeout(themeSaveTimer.current);
    }
    themeSaveTimer.current = window.setTimeout(() => {
      void persistProjectConfig(draftsOverride, symbolTypesOverride, true);
    }, 0);
  };

  const refreshProjectData = async () => {
    if (!selectedProjectId) {
      return;
    }
    try {
      await api.post(`/api/projects/${selectedProjectId}/actions/refresh-data`, {});
      setDataMessage(t("projects.dataStatus.queued"));
      await loadProjectDataStatus(selectedProjectId);
      await loadThemeSummary(selectedProjectId);
    } catch (err) {
      setDataMessage(t("projects.dataStatus.error"));
    }
  };

  const runThematicBacktest = async () => {
    if (!selectedProjectId) {
      return;
    }
    try {
      setBacktestMessage(t("projects.backtest.queued"));
      const res = await api.post<BacktestRun>("/api/backtests", {
        project_id: selectedProjectId,
      });
      setLatestBacktest(res.data || null);
      scheduleBacktestRefresh(selectedProjectId);
    } catch (err) {
      setBacktestMessage(t("projects.backtest.error"));
    }
  };

  const runAutoWeeklyJob = async () => {
    if (!selectedProjectId) {
      return;
    }
    setAutoWeeklyLoading(true);
    setAutoWeeklyMessage("");
    try {
      const res = await api.post<AutoWeeklyJob>("/api/automation/weekly-jobs", {
        project_id: selectedProjectId,
      });
      setAutoWeeklyJob(res.data || null);
      setAutoWeeklyMessage(t("projects.automation.queued"));
      scheduleAutoWeeklyRefresh(selectedProjectId);
    } catch (err) {
      setAutoWeeklyMessage(t("projects.automation.error"));
    } finally {
      setAutoWeeklyLoading(false);
    }
  };

  const saveAlgorithmBinding = async () => {
    if (!selectedProjectId) {
      return;
    }
    const algorithmId = Number(bindingForm.algorithmId);
    const versionId = Number(bindingForm.versionId);
    if (!algorithmId || !versionId) {
      setBindingMessage(t("projects.algorithm.errorSelect"));
      return;
    }
    try {
      await api.post(`/api/projects/${selectedProjectId}/algorithm-binding`, {
        algorithm_id: algorithmId,
        algorithm_version_id: versionId,
        is_locked: bindingForm.isLocked,
      });
      setBindingMessage(t("projects.algorithm.saved"));
      await loadProjectBinding(selectedProjectId);
    } catch (err) {
      setBindingMessage(t("projects.algorithm.error"));
    }
  };

  const runDiff = async () => {
    if (!selectedProjectId) {
      setDiffErrorKey("projects.versions.errorSelect");
      return;
    }
    if (!diffFromId || !diffToId) {
      setDiffErrorKey("projects.diff.errorSelect");
      return;
    }
    setDiffErrorKey("");
    const res = await api.get<ProjectDiff>(`/api/projects/${selectedProjectId}/diff`, {
      params: { from_id: Number(diffFromId), to_id: Number(diffToId) },
    });
    setDiffResult(res.data.diff || "");
  };

  const selectedProject = useMemo(
    () => projects.find((item) => item.id === selectedProjectId),
    [projects, selectedProjectId]
  );
  const mlActiveJob = useMemo(
    () => mlJobs.find((job) => job.is_active) || mlJobs[0] || null,
    [mlJobs]
  );
  const mlDetailJob = useMemo(
    () => mlJobs.find((job) => job.id === mlDetailId) || mlActiveJob,
    [mlJobs, mlDetailId, mlActiveJob]
  );
  const strategyDraft = configDraft?.strategy || {};
  const strategySource = (strategyDraft.source || "theme_weights").toString();
  const filteredProjects = useMemo(() => {
    const keyword = projectSearch.trim().toLowerCase();
    if (!keyword) {
      return projects;
    }
    return projects.filter(
      (item) =>
        item.name.toLowerCase().includes(keyword) ||
        (item.description || "").toLowerCase().includes(keyword)
    );
  }, [projects, projectSearch]);

  const weightTotal = useMemo(() => {
    if (!themeDrafts.length) {
      return 0;
    }
    return themeDrafts.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
  }, [themeDrafts]);

  const formatPercent = (value?: number | null) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    return `${(value * 100).toFixed(2)}%`;
  };

  const mlStatusLabel = (status?: string) => {
    const key = `projects.ml.status.${status || "unknown"}`;
    const label = t(key);
    return label === key ? status || t("common.none") : label;
  };

  const factorStatusLabel = (status?: string) => {
    const key = `projects.factorScores.status.${status || "unknown"}`;
    const label = t(key);
    return label === key ? status || t("common.none") : label;
  };

  const automationStatusLabel = (status?: string) => {
    const key = `projects.automation.status.${status || "unknown"}`;
    const label = t(key);
    return label === key ? status || t("common.none") : label;
  };

  const mlProgressLabel = (job: MLTrainJob) => {
    const value = job.progress_detail?.progress ?? job.progress;
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    const pct = Math.max(0, Math.min(1, Number(value))) * 100;
    return `${pct.toFixed(0)}%`;
  };

  const parseYear = (value: unknown) => {
    if (typeof value === "number" && !Number.isNaN(value)) {
      return value;
    }
    if (typeof value !== "string") {
      return null;
    }
    const match = value.match(/(\d{4})/);
    if (!match) {
      return null;
    }
    const year = Number(match[1]);
    return Number.isNaN(year) ? null : year;
  };

  const formatYearRange = (start: unknown, end: unknown) => {
    const startYear = parseYear(start);
    const endYear = parseYear(end);
    if (startYear === null && endYear === null) {
      return "-";
    }
    if (startYear !== null && endYear !== null) {
      return `${startYear}-${endYear}`;
    }
    if (startYear !== null) {
      return `${startYear}-`;
    }
    return `-${endYear}`;
  };

  const mlTrainRangeDetail = (job: MLTrainJob) => {
    const metrics = (job.metrics || {}) as Record<string, any>;
    const dataRanges = (metrics.data_ranges || metrics.dataRanges) as
      | Record<string, any>
      | undefined;
    if (dataRanges && typeof dataRanges === "object") {
      const train = formatYearRange(dataRanges.train?.start, dataRanges.train?.end);
      const valid = formatYearRange(dataRanges.valid?.start, dataRanges.valid?.end);
      const test = formatYearRange(dataRanges.test?.start, dataRanges.test?.end);
      if (train !== "-" || valid !== "-" || test !== "-") {
        return { train, valid, test };
      }
    }

    const walk = (metrics.walk_forward || {}) as Record<string, any>;
    const windows = Array.isArray(walk.windows) ? walk.windows : [];
    const ranges = {
      train: { min: null as number | null, max: null as number | null },
      valid: { min: null as number | null, max: null as number | null },
      test: { min: null as number | null, max: null as number | null },
    };
    const update = (range: { min: number | null; max: number | null }, start: unknown, end: unknown) => {
      const startYear = parseYear(start);
      const endYear = parseYear(end);
      if (startYear !== null) {
        range.min = range.min === null ? startYear : Math.min(range.min, startYear);
      }
      if (endYear !== null) {
        range.max = range.max === null ? endYear : Math.max(range.max, endYear);
      }
    };
    for (const window of windows) {
      update(ranges.train, window.train_start || window.trainStart, window.train_end || window.trainEnd);
      update(
        ranges.valid,
        window.valid_start || window.validStart || window.train_end || window.trainEnd,
        window.valid_end || window.validEnd
      );
      update(
        ranges.test,
        window.test_start || window.testStart || window.valid_end || window.validEnd,
        window.test_end || window.testEnd || window.valid_end || window.validEnd
      );
    }
    const derived = {
      train: formatYearRange(ranges.train.min, ranges.train.max),
      valid: formatYearRange(ranges.valid.min, ranges.valid.max),
      test: formatYearRange(ranges.test.min, ranges.test.max),
    };
    if (derived.train !== "-" || derived.valid !== "-" || derived.test !== "-") {
      return derived;
    }

    const cfg = (job.config || {}) as Record<string, any>;
    const startYearRaw = cfg.train_start_year;
    const startYear =
      typeof startYearRaw === "number" ? startYearRaw : Number(startYearRaw);
    const trainYearsRaw = cfg.walk_forward?.train_years ?? cfg.train_years;
    const trainYears =
      typeof trainYearsRaw === "number" ? trainYearsRaw : Number(trainYearsRaw);
    const trainRange =
      !Number.isNaN(startYear) && startYear && !Number.isNaN(trainYears) && trainYears
        ? `${startYear}-${startYear + trainYears - 1}`
        : "-";
    return { train: trainRange, valid: "-", test: "-" };
  };

  const mlStatusClass = (status?: string) => {
    if (status === "success") {
      return "success";
    }
    if (status === "failed") {
      return "danger";
    }
    if (status === "running" || status === "queued" || status === "cancel_requested") {
      return "warn";
    }
    return "";
  };

  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    return value.toFixed(4);
  };

  const formatBacktestParamValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    if (typeof value === "boolean") {
      return value ? t("common.boolean.true") : t("common.boolean.false");
    }
    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (normalized === "true" || normalized === "yes") {
        return t("common.boolean.true");
      }
      if (normalized === "false" || normalized === "no") {
        return t("common.boolean.false");
      }
      return value;
    }
    if (typeof value === "number") {
      return String(value);
    }
    return String(value);
  };

  const backtestDefaultParams = useMemo(() => {
    const defaults = configDraft?.backtest_params;
    if (!defaults || typeof defaults !== "object") {
      return [];
    }
    const entries = [
      { key: "top_n", label: t("projects.backtest.defaults.topN") },
      { key: "weighting", label: t("projects.backtest.defaults.weighting") },
      { key: "max_weight", label: t("projects.backtest.defaults.maxWeight") },
      { key: "max_exposure", label: t("projects.backtest.defaults.maxExposure") },
      { key: "min_score", label: t("projects.backtest.defaults.minScore") },
      { key: "market_filter", label: t("projects.backtest.defaults.marketFilter") },
      { key: "market_ma_window", label: t("projects.backtest.defaults.marketMa") },
      { key: "risk_off_mode", label: t("projects.backtest.defaults.riskOff") },
      { key: "rebalance_frequency", label: t("projects.backtest.defaults.rebalanceFreq") },
      { key: "rebalance_day", label: t("projects.backtest.defaults.rebalanceDay") },
      { key: "rebalance_time_minutes", label: t("projects.backtest.defaults.rebalanceTime") },
      { key: "score_delay_days", label: t("projects.backtest.defaults.scoreDelay") },
      { key: "reload_scores", label: t("projects.backtest.defaults.reloadScores") },
    ];
    return entries
      .map((entry) => ({
        ...entry,
        value: (defaults as Record<string, any>)[entry.key],
      }))
      .filter((entry) => entry.value !== undefined && entry.value !== "");
  }, [configDraft, t]);

  const backtestPlugins = (configDraft?.backtest_plugins || {}) as Record<string, any>;
  const scoreSmoothing = (backtestPlugins.score_smoothing || {}) as Record<string, any>;
  const scoreHysteresis = (backtestPlugins.score_hysteresis || {}) as Record<string, any>;
  const weightSmoothing = (backtestPlugins.weight_smoothing || {}) as Record<string, any>;
  const riskControl = (backtestPlugins.risk_control || {}) as Record<string, any>;
  const pluginCosts = (backtestPlugins.costs || {}) as Record<string, any>;

  const renderWeightDonut = (value: number) => {
    const percent = Math.max(0, Math.min(1, value || 0));
    const radius = 10;
    const circumference = 2 * Math.PI * radius;
    const dash = circumference * percent;
    const remainder = circumference - dash;
    return (
      <div className="weight-donut">
        <svg viewBox="0 0 24 24">
          <circle className="donut-bg" cx="12" cy="12" r={radius} />
          <circle
            className="donut-fg"
            cx="12"
            cy="12"
            r={radius}
            strokeDasharray={`${dash} ${remainder}`}
          />
        </svg>
        <span>{formatPercent(value)}</span>
      </div>
    );
  };

  const renderWeightPie = () => {
    const radius = 12;
    const circumference = 2 * Math.PI * radius;
    let offset = 0;
    return (
      <div className="weight-pie">
        <svg viewBox="0 0 32 32">
          <circle className="donut-bg" cx="16" cy="16" r={radius} />
          {weightSegments.map((segment) => {
            const dash = circumference * segment.percent;
            const dashArray = `${dash} ${circumference - dash}`;
            const dashOffset = -offset;
            offset += dash;
            const dimmed = highlightThemeKey && highlightThemeKey !== segment.key;
            return (
              <circle
                key={segment.key}
                className="donut-segment"
                cx="16"
                cy="16"
                r={radius}
                stroke={segment.color}
                strokeDasharray={dashArray}
                strokeDashoffset={dashOffset}
                style={{ opacity: dimmed ? 0.3 : 1 }}
              />
            );
          })}
        </svg>
        <div className="weight-legend">
          {(weightSegments.length ? weightSegments : themeDrafts)
            .slice(0, 6)
            .map((segment, idx) => (
              <button
                type="button"
                className={`weight-legend-item ${
                  highlightThemeKey === (segment as any).key ? "active" : ""
                }`}
                onClick={() => toggleHighlightTheme((segment as any).key || "")}
                key={(segment as any).key || idx}
              >
                <span
                  className="weight-dot"
                  style={{
                    backgroundColor:
                      (segment as any).color || ["#0f62fe", "#35b9a3", "#f6ad55", "#ed5564"][idx],
                  }}
                />
                <span className="weight-label">{segment.label || segment.key}</span>
                {"value" in segment ? (
                  <span>{formatPercent((segment as any).value || 0)}</span>
                ) : (
                  <span>{formatPercent((segment as any).weight || 0)}</span>
                )}
              </button>
            ))}
        </div>
      </div>
    );
  };

  const weightTotalWarn = Math.abs(weightTotal - 1) > 0.02;
  const themeRows = themeSummary?.themes || [];
  const themeWeightMap = useMemo(
    () =>
      themeDrafts.reduce<Record<string, number>>((acc, item) => {
        acc[item.key] = Number(item.weight) || 0;
        return acc;
      }, {}),
    [themeDrafts]
  );
  const themeSearchKeys = useMemo(
    () => new Set((themeSearchResult?.themes || []).map((item) => item.key)),
    [themeSearchResult]
  );
  const themeRowsFiltered = useMemo(() => {
    const keyword = themeFilterText.trim().toLowerCase();
    const normalizedSymbol = themeSearchSymbol.trim().toUpperCase();
    const hasSymbolFilter =
      normalizedSymbol.length > 0 && themeSearchResult?.symbol === normalizedSymbol;
    return themeRows.filter((row) => {
      const textMatch =
        !keyword ||
        row.key.toLowerCase().includes(keyword) ||
        row.label.toLowerCase().includes(keyword);
      const symbolMatch = !hasSymbolFilter || themeSearchKeys.has(row.key);
      return textMatch && symbolMatch;
    });
  }, [themeRows, themeFilterText, themeSearchSymbol, themeSearchKeys]);
  const maxThemeSymbols = useMemo(
    () => Math.max(1, ...themeRows.map((item) => item.symbols)),
    [themeRows]
  );
  const themeSelectOptions = useMemo(
    () =>
      themeRows.map((item) => ({
        key: item.key,
        label: item.label || item.key,
      })),
    [themeRows]
  );
  const compareSymbolsA = themeSymbolsCache[compareThemeA]?.symbols || [];
  const compareSymbolsB = themeSymbolsCache[compareThemeB]?.symbols || [];
  const compareSets = useMemo(() => {
    const setA = new Set(compareSymbolsA);
    const setB = new Set(compareSymbolsB);
    const shared = [...setA].filter((symbol) => setB.has(symbol));
    const onlyA = [...setA].filter((symbol) => !setB.has(symbol));
    const onlyB = [...setB].filter((symbol) => !setA.has(symbol));
    return {
      shared: shared.sort(),
      onlyA: onlyA.sort(),
      onlyB: onlyB.sort(),
    };
  }, [compareSymbolsA, compareSymbolsB]);
  const symbolTypeLabels = useMemo(
    () => ({
      STOCK: t("symbols.types.stock"),
      ETF: t("symbols.types.etf"),
      ADR: t("symbols.types.adr"),
      REIT: t("symbols.types.reit"),
      ETN: t("symbols.types.etn"),
      FUND: t("symbols.types.fund"),
      INDEX: t("symbols.types.index"),
      UNKNOWN: t("symbols.types.unknown"),
    }),
    [t]
  );
  const configSymbolTypes = useMemo(() => {
    const normalized: Record<string, string> = {};
    Object.entries(configDraft?.symbol_types || {}).forEach(([symbol, type]) => {
      normalized[symbol.toUpperCase()] = normalizeSymbolType(type);
    });
    return normalized;
  }, [configDraft]);
  const activeSymbolTypes = useMemo(() => {
    const base = { ...(activeThemeSymbols?.symbol_types || {}) };
    Object.entries(configSymbolTypes).forEach(([symbol, type]) => {
      base[symbol.toUpperCase()] = normalizeSymbolType(type);
    });
    return base;
  }, [activeThemeSymbols, configSymbolTypes]);
  const compareSymbolTypes = useMemo(() => {
    const base = {
      ...(themeSymbolsCache[compareThemeA]?.symbol_types || {}),
      ...(themeSymbolsCache[compareThemeB]?.symbol_types || {}),
    };
    Object.entries(configSymbolTypes).forEach(([symbol, type]) => {
      base[symbol.toUpperCase()] = normalizeSymbolType(type);
    });
    return base;
  }, [themeSymbolsCache, compareThemeA, compareThemeB, configSymbolTypes]);
  const formatSymbolLabel = (symbol: string, types: Record<string, string>) => {
    const raw = types[symbol];
    if (!raw) {
      return symbol;
    }
    const label = symbolTypeLabels[normalizeSymbolType(raw)] || symbolTypeLabels.UNKNOWN;
    return `${symbol} · ${label}`;
  };
  const activeThemeDraft = useMemo(
    () => themeDrafts.find((item) => item.key === activeThemeKey),
    [themeDrafts, activeThemeKey]
  );
  const activeAutoSymbols = activeThemeSymbols?.auto_symbols || activeThemeSymbols?.symbols || [];
  const activeManualSymbols =
    activeThemeDraft?.manual || activeThemeSymbols?.manual_symbols || [];
  const activeExcludeSymbols =
    activeThemeDraft?.exclude || activeThemeSymbols?.exclude_symbols || [];
  const activeExcludeSet = useMemo(
    () => new Set(activeExcludeSymbols),
    [activeExcludeSymbols]
  );
  const activeCombinedSymbols = useMemo(() => {
    const combined = new Set(activeAutoSymbols);
    activeManualSymbols.forEach((symbol) => combined.add(symbol));
    activeExcludeSymbols.forEach((symbol) => combined.delete(symbol));
    return Array.from(combined).sort();
  }, [activeAutoSymbols, activeManualSymbols, activeExcludeSymbols]);
  const filterSymbolsByQuery = (symbols: string[]) => {
    const keyword = themeSymbolQuery.trim().toUpperCase();
    if (!keyword) {
      return symbols;
    }
    return symbols.filter((symbol) => symbol.includes(keyword));
  };
  const filteredAutoSymbols = useMemo(
    () => filterSymbolsByQuery(activeAutoSymbols.filter((symbol) => !activeExcludeSet.has(symbol))),
    [activeAutoSymbols, activeExcludeSet, themeSymbolQuery]
  );
  const filteredManualSymbols = useMemo(
    () => filterSymbolsByQuery(activeManualSymbols.filter((symbol) => !activeExcludeSet.has(symbol))),
    [activeManualSymbols, activeExcludeSet, themeSymbolQuery]
  );
  const filteredExcludedSymbols = useMemo(
    () => filterSymbolsByQuery(activeExcludeSymbols),
    [activeExcludeSymbols, themeSymbolQuery]
  );
  const filteredCombinedSymbols = useMemo(
    () => filterSymbolsByQuery(activeCombinedSymbols),
    [activeCombinedSymbols, themeSymbolQuery]
  );
  const weightSegments = useMemo(() => {
    const palette = ["#0f62fe", "#35b9a3", "#f6ad55", "#ed5564", "#6f56d9", "#6b7280"];
    const total = themeDrafts.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
    return themeDrafts
      .map((item, idx) => ({
        key: item.key,
        label: item.label || item.key,
        value: Number(item.weight) || 0,
        percent: total > 0 ? (Number(item.weight) || 0) / total : 0,
        color: palette[idx % palette.length],
      }))
      .filter((item) => item.value > 0);
  }, [themeDrafts]);
  const activeThemeCount = useMemo(
    () => themeDrafts.filter((item) => (Number(item.weight) || 0) > 0).length,
    [themeDrafts]
  );
  const metricRows = [
    { key: "Compounding Annual Return", label: t("metrics.cagr") },
    { key: "Drawdown", label: t("metrics.drawdown") },
    { key: "MaxDD_all", label: t("metrics.drawdownAll") },
    { key: "MaxDD_52w", label: t("metrics.drawdown52w") },
    { key: "Sharpe Ratio", label: t("metrics.sharpe") },
    { key: "Net Profit", label: t("metrics.netProfit") },
    { key: "Total Fees", label: t("metrics.totalFees") },
    { key: "Portfolio Turnover", label: t("metrics.turnover") },
    { key: "MaxTurnover_week", label: t("metrics.turnoverWeek") },
    { key: "Risk Status", label: t("metrics.riskStatus") },
  ];
  const backtestSummary = latestBacktest?.metrics as Record<string, any> | null;
  const benchmarkSummary =
    (backtestSummary?.benchmark as Record<string, any> | undefined) || {};
  const backtestErrorMessage =
    latestBacktest?.status === "failed" ? t("projects.backtest.error") : "";
  const missingScoresRaw =
    (backtestSummary?.["Missing Scores"] as unknown) ?? backtestSummary?.missing_scores;
  const missingScores = Array.isArray(missingScoresRaw)
    ? missingScoresRaw.map((item) => String(item).trim()).filter((item) => item.length)
    : typeof missingScoresRaw === "string"
      ? missingScoresRaw
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item.length)
      : [];
  const formatPriceMode = (mode?: string | null) => {
    if (!mode) {
      return t("common.none");
    }
    const value = String(mode).toLowerCase();
    if (value === "adjusted") {
      return t("projects.backtest.priceAdjusted");
    }
    if (value === "raw") {
      return t("projects.backtest.priceRaw");
    }
    if (value === "mixed") {
      return t("projects.backtest.priceMixed");
    }
    return String(mode);
  };
  const formatPricePolicy = (policy?: string | null) => {
    if (!policy) {
      return t("common.none");
    }
    const value = String(policy).toLowerCase();
    if (value.includes("adjusted")) {
      return t("projects.backtest.policyAdjusted");
    }
    if (value.includes("raw")) {
      return t("projects.backtest.policyRaw");
    }
    return String(policy);
  };
  const formatMetricValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") {
      return t("common.none");
    }
    return String(value);
  };
  const saveBenchmark = async () => {
    if (!configDraft) {
      return;
    }
    setBenchmarkMessage("");
    const ok = await persistProjectConfig();
    setBenchmarkMessage(ok ? t("projects.config.saved") : t("projects.config.error"));
  };


  const renderBenchmarkEditor = () => (
    <div className="card">
      <div className="card-title">{t("projects.backtest.benchmarkTitle")}</div>
      <div className="card-meta">{t("projects.backtest.benchmarkMeta")}</div>
      <div className="form-grid">
        <div className="form-row">
          <label className="form-label">{t("projects.config.benchmark")}</label>
          <input
            className="form-input"
            value={configDraft?.benchmark || ""}
            onChange={(e) =>
              setConfigDraft((prev) => ({ ...(prev || {}), benchmark: e.target.value }))
            }
            placeholder="SPY"
          />
        </div>
        {benchmarkMessage && <div className="form-hint">{benchmarkMessage}</div>}
        <button className="button-secondary" onClick={saveBenchmark}>
          {t("projects.config.save")}
        </button>
      </div>
    </div>
  );
  const placeholderDescription = selectedProject?.description || t("common.none");
  const configTabs = [
    { key: "universe", label: t("projects.config.sectionUniverse") },
    { key: "data", label: t("projects.config.sectionData") },
    { key: "portfolio", label: t("projects.config.sectionPortfolio") },
  ] as const;
  const projectTabs = [
    { key: "overview", label: t("projects.tabs.overview") },
    { key: "config", label: t("projects.tabs.config") },
    { key: "algorithm", label: t("projects.tabs.algorithm") },
    { key: "data", label: t("projects.tabs.data") },
    { key: "backtest", label: t("projects.tabs.backtest") },
    { key: "versions", label: t("projects.tabs.versions") },
    { key: "diff", label: t("projects.tabs.diff") },
  ] as const;

  return (
    <div className="main">
      <TopBar title={t("projects.title")} />
      <div className="content">
        <div className="projects-layout">
          <div className="projects-sidebar">
            <div className="grid-2">
          <div className="card">
            <div className="card-title">{t("projects.new.title")}</div>
            <div className="card-meta">{t("projects.new.meta")}</div>
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("projects.new.name")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t("projects.new.description")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              {projectErrorKey && (
                <div style={{ color: "#d64545", fontSize: "13px" }}>
                  {t(projectErrorKey)}
                </div>
              )}
              <button
                onClick={createProject}
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
                {t("common.actions.create")}
              </button>
            </div>
          </div>
          <div className="card">
            <div className="card-title">{t("projects.overview.title")}</div>
            <div className="card-meta">{t("projects.overview.meta")}</div>
            <div style={{ fontSize: "32px", fontWeight: 600, marginTop: "12px" }}>
              {projectTotal}
            </div>
          </div>
            </div>
            <div className="card">
              <div className="card-title">{t("projects.list.title")}</div>
              <div className="card-meta">{t("projects.list.meta")}</div>
              <input
                value={projectSearch}
                onChange={(e) => setProjectSearch(e.target.value)}
                placeholder={t("projects.list.search")}
                className="form-input"
                style={{ marginTop: "12px" }}
              />
              <div className="project-list">
                {filteredProjects.map((project) => (
                  <div
                    key={project.id}
                    className={
                      project.id === selectedProjectId
                        ? "project-item project-item-active"
                        : "project-item"
                    }
                    onClick={() => setSelectedProjectId(project.id)}
                  >
                    <div className="project-item-title">{project.name}</div>
                    <div className="project-item-meta">
                      #{project.id} | {formatDateTime(project.created_at)}
                    </div>
                  </div>
                ))}
                {filteredProjects.length === 0 && (
                  <div className="form-hint">{t("projects.list.empty")}</div>
                )}
              </div>
              <PaginationBar
                page={projectPage}
                pageSize={projectPageSize}
                total={projectTotal}
                onPageChange={setProjectPage}
                onPageSizeChange={(size) => {
                  setProjectPage(1);
                  setProjectPageSize(size);
                }}
              />
            </div>
          </div>

          <div className="projects-main">
        {selectedProject ? (
          <>
            <div className="card project-detail-card">
              <div className="project-detail-header">
                <div>
                  <div className="project-detail-title">{selectedProject.name}</div>
                  <div className="project-detail-meta">
                    {selectedProject.description || t("common.none")}
                  </div>
                </div>
              <div className="project-detail-actions">
                <a className="button-secondary" href="/themes">
                  {t("projects.detail.openThemes")}
                </a>
                <button className="button-secondary" onClick={refreshProjectData}>
                  {t("projects.dataStatus.action")}
                </button>
                <button className="button-primary" onClick={runThematicBacktest}>
                  {t("projects.backtest.action")}
                </button>
              </div>
            </div>
            {backtestMessage && (
              <div className="project-detail-status">{backtestMessage}</div>
            )}
            <div className="project-detail-meta-grid">
              <div className="meta-row">
                <span>{t("projects.detail.projectId")}</span>
                  <strong>{selectedProject.id}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("common.labels.createdAt")}</span>
                  <strong>{formatDateTime(selectedProject.created_at)}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.config.source")}</span>
                  <strong>{configMeta?.source || t("common.none")}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("common.labels.updatedAt")}</span>
                  <strong>{formatDateTime(configMeta?.updated_at)}</strong>
                </div>
              </div>
            </div>

            <div className="project-tabs">
              {projectTabs.map((tab) => (
                <button
                  key={tab.key}
                  className={projectTab === tab.key ? "tab-button active" : "tab-button"}
                  onClick={() => setProjectTab(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {projectTab === "overview" && (
              <>
                <div className="grid-2">
                  <div className="card">
                    <div className="card-title">{t("projects.detail.summaryTitle")}</div>
                    <div className="card-meta">{t("projects.detail.summaryMeta")}</div>
                    <div className="overview-grid">
                      <div className="overview-card">
                        <div className="overview-label">{t("projects.config.themeCount")}</div>
                        <div className="overview-value">{activeThemeCount}</div>
                        <div className="overview-sub">
                          {t("projects.config.themeTotalSymbols")}{" "}
                          {themeSummary?.total_symbols ?? 0}
                        </div>
                      </div>
                      <div className="overview-card">
                        <div className="overview-label">{t("projects.algorithm.title")}</div>
                        <div className="overview-value">
                          {binding?.algorithm_name || t("common.none")}
                        </div>
                        <div className="overview-sub">
                          {binding?.algorithm_version || t("common.none")}
                        </div>
                      </div>
                      <div className="overview-card">
                        <div className="overview-label">
                          {t("projects.dataStatus.membership")}
                        </div>
                        <div className="overview-value">
                          {dataStatus?.membership.symbols ?? 0}
                        </div>
                        <div className="overview-sub">
                          {dataStatus?.membership.start || t("common.none")} ~{" "}
                          {dataStatus?.membership.end || t("common.none")}
                        </div>
                      </div>
                      <div className="overview-card">
                        <div className="overview-label">{t("projects.backtest.title")}</div>
                        <div className="overview-value">
                          {latestBacktest?.status || t("common.none")}
                        </div>
                        <div className="overview-sub">
                          {t("common.labels.updatedAt")}{" "}
                          {formatDateTime(latestBacktest?.ended_at || latestBacktest?.created_at)}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-title">{t("projects.detail.themeTitle")}</div>
                    <div className="card-meta">{t("projects.detail.themeMeta")}</div>
                    {themeDrafts.length ? (
                      renderWeightPie()
                    ) : (
                      <div className="empty-state">{t("projects.config.themesEmpty")}</div>
                    )}
                    <div className={`meta-row ${weightTotalWarn ? "meta-warn" : ""}`}>
                      <span>{t("projects.config.weightTotal")}</span>
                      <strong>{formatPercent(weightTotal)}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("projects.config.themeCount")}</span>
                      <strong>{activeThemeCount}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("projects.config.themeTotalSymbols")}</span>
                      <strong>{themeSummary?.total_symbols ?? 0}</strong>
                    </div>
                  </div>
                </div>

                <div className="grid-2">
                  <div className="card">
                    <div className="card-title">{t("projects.dataStatus.title")}</div>
                    <div className="card-meta">{t("projects.dataStatus.meta")}</div>
                    {!dataStatus ? (
                      <div className="empty-state">{t("common.noneText")}</div>
                    ) : (
                      <div className="meta-list">
                        <div className="meta-row">
                          <span>{t("projects.dataStatus.universe")}</span>
                          <strong>{dataStatus.universe.records}</strong>
                        </div>
                        <div className="meta-row">
                          <span>{t("projects.dataStatus.prices")}</span>
                          <strong>
                            {dataStatus.prices.stooq_files + dataStatus.prices.yahoo_files}
                          </strong>
                        </div>
                        <div className="meta-row">
                          <span>{t("projects.dataStatus.metrics")}</span>
                          <strong>{dataStatus.metrics.records}</strong>
                        </div>
                        <div className="meta-row">
                          <span>{t("common.labels.updatedAt")}</span>
                          <strong>{formatDateTime(dataStatus.prices.updated_at)}</strong>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="card">
                    <div className="card-title">{t("projects.detail.performanceTitle")}</div>
                    <div className="card-meta">{t("projects.detail.performanceMeta")}</div>
                    {latestBacktest?.status === "success" && backtestSummary ? (
                      <>
                        <div className="metric-table">
                          <div className="metric-header">
                            <span>{t("projects.backtest.metric")}</span>
                            <span>{t("projects.backtest.portfolio")}</span>
                            <span>{t("projects.backtest.benchmark")}</span>
                          </div>
                          {metricRows.map((metric) => (
                            <div className="metric-row" key={metric.key}>
                              <span>{metric.label}</span>
                              <span>{formatMetricValue(backtestSummary?.[metric.key])}</span>
                              <span>{formatMetricValue(benchmarkSummary?.[metric.key])}</span>
                            </div>
                          ))}
                        </div>
                        <div className="meta-row" style={{ marginTop: "10px" }}>
                          <span>{t("projects.backtest.priceMode")}</span>
                          <strong>
                            {formatPriceMode(
                              (backtestSummary?.["Price Mode"] as string | undefined) ??
                                (backtestSummary?.price_mode as string | undefined)
                            )}
                          </strong>
                        </div>
                        <div className="meta-row">
                          <span>{t("projects.backtest.benchmarkMode")}</span>
                          <strong>
                            {formatPriceMode(
                              (backtestSummary?.["Benchmark Price Mode"] as string | undefined) ??
                                (backtestSummary?.benchmark_mode as string | undefined)
                            )}
                          </strong>
                        </div>
                        <div className="meta-row">
                          <span>{t("projects.backtest.pricePolicy")}</span>
                          <strong>
                            {formatPricePolicy(
                              (backtestSummary?.["Price Policy"] as string | undefined) ??
                                (backtestSummary?.price_policy as string | undefined) ??
                                (backtestSummary?.price_source_policy as string | undefined)
                            )}
                          </strong>
                        </div>
                  {missingScores.length > 0 && (
                    <div className="missing-score-block">
                      <div className="missing-score-title">
                        {t("projects.backtest.missingScoresTitle", {
                          count: missingScores.length,
                        })}
                      </div>
                      <div className="missing-score-list">{missingScores.join(", ")}</div>
                    </div>
                  )}
                </>
              ) : latestBacktest?.status === "failed" && backtestErrorMessage ? (
                      <div className="empty-state">
                        {t("projects.backtest.failed", { message: backtestErrorMessage })}
                      </div>
                    ) : (
                      <div className="empty-state">{t("projects.backtest.empty")}</div>
                    )}
                  </div>
                </div>
              </>
            )}
          </>
        ) : (
          <div className="card">
            <div className="empty-state">{t("projects.detail.empty")}</div>
          </div>
        )}

        {selectedProject && (projectTab === "config" || projectTab === "algorithm") && (
          <div className={projectTab === "algorithm" ? "project-tab-stack" : "grid-2"}>
            {projectTab === "config" && (
              <div className="card">
            <div className="card-title">{t("projects.config.title")}</div>
            <div className="card-meta">{t("projects.config.meta")}</div>
            {!configDraft ? (
              <div className="empty-state">{t("common.noneText")}</div>
            ) : (
              <div className="form-grid">
                <div className="config-tabs">
                  <div className="segmented">
                    {configTabs.map((tab) => (
                      <button
                        key={tab.key}
                        className={configSection === tab.key ? "active" : ""}
                        onClick={() => setConfigSection(tab.key)}
                        type="button"
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.config.themeCount")}</span>
                    <strong>{themeDrafts.length}</strong>
                  </div>
                </div>
                <div className="form-hint">{t("projects.config.themeMovedHint")}</div>

                {configSection === "universe" && (
                  <div className="config-section">
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.universeMode")}</label>
                      <select
                        className="form-select"
                        value={configDraft.universe?.mode || "sp500_history"}
                        onChange={(e) => updateConfigSection("universe", "mode", e.target.value)}
                      >
                        <option value="sp500_history">{t("projects.config.universeHistory")}</option>
                        <option value="sp500_current">{t("projects.config.universeCurrent")}</option>
                      </select>
                    </div>
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={configDraft.universe?.include_history ?? true}
                        onChange={(e) =>
                          updateConfigSection("universe", "include_history", e.target.checked)
                        }
                      />
                      {t("projects.config.includeHistory")}
                    </label>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.assetTypes")}</label>
                      <div className="checkbox-group">
                        {symbolTypeOptions.map((option) => (
                          <label className="checkbox-row" key={option.value}>
                            <input
                              type="checkbox"
                              checked={
                                configDraft.universe?.asset_types?.includes(option.value) || false
                              }
                              onChange={() => toggleUniverseAssetType(option.value)}
                            />
                            {option.label}
                          </label>
                        ))}
                      </div>
                      <div className="form-hint">{t("projects.config.assetTypesHint")}</div>
                    </div>
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={configDraft.universe?.pit_universe_only ?? false}
                        onChange={(e) =>
                          updateConfigSection("universe", "pit_universe_only", e.target.checked)
                        }
                      />
                      {t("projects.config.pitUniverseOnly")}
                    </label>
                    <div className="form-hint">{t("projects.config.pitUniverseOnlyHint")}</div>
                  </div>
                )}

                {configSection === "data" && (
                  <div className="config-section">
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.frequency")}</label>
                      <select
                        className="form-select"
                        value={configDraft.data?.frequency || "daily"}
                        onChange={(e) => updateConfigSection("data", "frequency", e.target.value)}
                      >
                        <option value="daily">{t("projects.config.frequencyDaily")}</option>
                        <option value="minute">{t("projects.config.frequencyMinute")}</option>
                      </select>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.vendorPrimary")}</label>
                      <select
                        className="form-select"
                        value={configDraft.data?.primary_vendor || "alpha"}
                        onChange={(e) =>
                          updateConfigSection("data", "primary_vendor", e.target.value)
                        }
                      >
                        <option value="alpha">Alpha</option>
                      </select>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.vendorFallback")}</label>
                      <select
                        className="form-select"
                        value={configDraft.data?.fallback_vendor || "alpha"}
                        onChange={(e) =>
                          updateConfigSection("data", "fallback_vendor", e.target.value)
                        }
                      >
                        <option value="alpha">Alpha</option>
                      </select>
                    </div>
                  </div>
                )}

                {configSection === "themes" && (
                  <div className="config-section">
                    <div className="theme-summary-grid">
                      <div className="theme-summary-card">
                        <div className="theme-summary-label">{t("projects.config.themeCount")}</div>
                        <div className="theme-summary-value">{themeRows.length}</div>
                      </div>
                      <div className="theme-summary-card">
                        <div className="theme-summary-label">
                          {t("projects.config.themeTotalSymbols")}
                        </div>
                        <div className="theme-summary-value">
                          {themeSummary?.total_symbols ?? 0}
                        </div>
                      </div>
                      <div className="theme-summary-card">
                        <div className="theme-summary-label">{t("common.labels.updatedAt")}</div>
                        <div className="theme-summary-value">
                          {formatDateTime(themeSummary?.updated_at)}
                        </div>
                      </div>
                      <div className="theme-summary-card theme-summary-chart-card">
                        <div className="theme-summary-label">
                          {t("projects.config.themeWeightDistribution")}
                        </div>
                        {renderWeightPie()}
                      </div>
                    </div>
                    {themeSummaryMessage && <div className="form-hint">{themeSummaryMessage}</div>}
                    <div className="form-row">
                      <div className="form-label">{t("projects.config.themesTitle")}</div>
                      <div className="theme-table-wrapper">
                        <table className="theme-table">
                          <thead>
                            <tr>
                              <th>{t("projects.config.themeKey")}</th>
                              <th>{t("projects.config.themeLabel")}</th>
                              <th>{t("projects.config.themeWeight")}</th>
                              <th>{t("projects.config.themePriority")}</th>
                              <th>{t("projects.config.themeKeywords")}</th>
                              <th>{t("projects.config.themeManual")}</th>
                              <th>{t("projects.config.themeExclude")}</th>
                              <th>{t("projects.config.themeActions")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {themeDrafts.length ? (
                              themeDrafts.map((theme, index) => {
                                const isSystemTheme = Boolean(theme.system || theme.system_base);
                                return (
                                  <tr key={`${theme.key}-${index}`}>
                                    <td>
                                      <input
                                        className="table-input"
                                        value={theme.key}
                                        onChange={(e) =>
                                          updateTheme(index, "key", e.target.value)
                                        }
                                        placeholder={t("projects.config.themeKey")}
                                        disabled={isSystemTheme}
                                      />
                                    </td>
                                    <td>
                                      <div className="theme-label-input">
                                        <input
                                          className="table-input"
                                          value={theme.label}
                                          onChange={(e) =>
                                            updateTheme(index, "label", e.target.value)
                                          }
                                          placeholder={t("projects.config.themeLabel")}
                                          disabled={isSystemTheme}
                                        />
                                        {isSystemTheme && (
                                          <span className="theme-badge">
                                            {t("projects.config.themeSystem")}
                                          </span>
                                        )}
                                      </div>
                                    </td>
                                  <td>
                                    <input
                                      className="table-input"
                                      type="number"
                                      step="0.01"
                                      value={theme.weight}
                                      onChange={(e) => updateTheme(index, "weight", e.target.value)}
                                      placeholder={t("projects.config.themeWeight")}
                                    />
                                  </td>
                                  <td>
                                    <input
                                      className="table-input"
                                      type="number"
                                      step="1"
                                      value={theme.priority ?? 0}
                                      onChange={(e) =>
                                        updateTheme(index, "priority", e.target.value)
                                      }
                                      placeholder={t("projects.config.themePriority")}
                                    />
                                  </td>
                                  <td>
                                    <input
                                      className="table-input"
                                      value={(theme.keywords || []).join(", ")}
                                      onChange={(e) =>
                                        updateTheme(index, "keywords", e.target.value)
                                      }
                                      placeholder={t("projects.config.themeKeywords")}
                                      disabled={isSystemTheme}
                                    />
                                  </td>
                                  <td>
                                    <input
                                      className="table-input"
                                      value={(theme.manual || []).join(", ")}
                                      onChange={(e) =>
                                        updateTheme(index, "manual", e.target.value)
                                      }
                                      placeholder={t("projects.config.themeManual")}
                                    />
                                  </td>
                                  <td>
                                    <input
                                      className="table-input"
                                      value={(theme.exclude || []).join(", ")}
                                      onChange={(e) =>
                                        updateTheme(index, "exclude", e.target.value)
                                      }
                                      placeholder={t("projects.config.themeExclude")}
                                    />
                                  </td>
                                  <td className="theme-actions">
                                    <button
                                      type="button"
                                      className="link-button theme-remove"
                                      onClick={() => removeTheme(index)}
                                    >
                                      {t("projects.config.themeRemove")}
                                    </button>
                                  </td>
                                  </tr>
                                );
                              })
                            ) : (
                              <tr>
                                <td colSpan={8}>{t("projects.config.themesEmpty")}</td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                      <div className="theme-footer">
                        <button type="button" className="button-secondary" onClick={addTheme}>
                          {t("projects.config.themeAdd")}
                        </button>
                        <span className="form-hint">{t("projects.config.themeHint")}</span>
                      </div>
                    </div>

                    <div className="theme-toolbar">
                      <div className="theme-toolbar-row">
                        <div className="theme-filter-field">
                          <label className="form-label">{t("projects.config.themeFilter")}</label>
                          <input
                            className="form-input"
                            value={themeFilterText}
                            onChange={(e) => setThemeFilterText(e.target.value)}
                            placeholder={t("projects.config.themeFilterPlaceholder")}
                          />
                        </div>
                        <div className="theme-filter-field">
                          <label className="form-label">
                            {t("projects.config.themeSearchSymbol")}
                          </label>
                          <div className="theme-filter-input">
                            <input
                              className="form-input"
                              value={themeSearchSymbol}
                              onChange={(e) => setThemeSearchSymbol(e.target.value.toUpperCase())}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  searchThemeSymbol();
                                }
                              }}
                              placeholder={t("projects.config.themeSearchPlaceholder")}
                            />
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => searchThemeSymbol()}
                            >
                              {t("common.actions.query")}
                            </button>
                            <button
                              type="button"
                              className="link-button"
                              onClick={clearThemeSearch}
                            >
                              {t("projects.config.themeSearchClear")}
                            </button>
                          </div>
                          <div className="form-hint">
                            {t("projects.config.themeSearchHint")}
                          </div>
                        </div>
                      </div>
                      <div className="theme-toolbar-row theme-toolbar-meta">
                        <span>
                          {t("projects.config.themeSearchMatches", {
                            count: themeSearchResult?.themes.length ?? 0,
                          })}
                        </span>
                        {themeSearchMessage && (
                          <span className="form-hint">{themeSearchMessage}</span>
                        )}
                      </div>
                    </div>

                    <div className="form-row">
                      <div className="form-label">{t("projects.config.themeComposition")}</div>
                      <div className="theme-table-wrapper">
                        <table className="theme-table theme-composition-table">
                          <colgroup>
                            <col className="col-theme" />
                            <col className="col-weight" />
                            <col className="col-count" />
                            <col className="col-distribution" />
                            <col className="col-sample" />
                            <col className="col-manual" />
                            <col className="col-exclude" />
                            <col className="col-actions" />
                          </colgroup>
                          <thead>
                            <tr>
                              <th>{t("projects.config.themeLabel")}</th>
                              <th>{t("projects.config.themeWeight")}</th>
                              <th>{t("projects.config.themeSymbolCount")}</th>
                              <th>{t("projects.config.themeDistribution")}</th>
                              <th>{t("projects.config.themeSample")}</th>
                              <th>{t("projects.config.themeManual")}</th>
                              <th>{t("projects.config.themeExcludeShort")}</th>
                              <th>{t("projects.config.themeActions")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {themeRowsFiltered.length ? (
                              themeRowsFiltered.map((item) => (
                                <Fragment key={item.key}>
                                  <tr
                                    className={
                                      highlightThemeKey && highlightThemeKey === item.key
                                        ? "theme-row-highlight"
                                        : ""
                                    }
                                  >
                                    <td>
                                      <div className="theme-name">
                                        <span className="theme-key">{item.key}</span>
                                        <span className="theme-label">{item.label}</span>
                                      </div>
                                    </td>
                                    <td>{renderWeightDonut(themeWeightMap[item.key] || 0)}</td>
                                    <td>{item.symbols}</td>
                                    <td>
                                      <div className="theme-distribution">
                                        <div className="theme-bar-track">
                                          <div
                                            className="theme-bar-fill"
                                            style={{
                                              width: `${Math.round(
                                                (item.symbols / maxThemeSymbols) * 100
                                              )}%`,
                                            }}
                                          />
                                        </div>
                                        <span>
                                          {formatPercent(
                                            item.symbols /
                                              Math.max(themeSummary?.total_symbols ?? 0, 1)
                                          )}
                                        </span>
                                      </div>
                                    </td>
                                    <td>
                                      <div className="theme-samples">
                                        {item.sample.length
                                          ? item.sample.map((symbol) => (
                                              <a
                                                key={symbol}
                                                className="theme-chip"
                                                href={yahooSymbolUrl(symbol)}
                                                target="_blank"
                                                rel="noreferrer"
                                                onClick={() => applyThemeSymbolFilter(symbol)}
                                              >
                                                {formatSymbolLabel(symbol, item.sample_types || {})}
                                              </a>
                                            ))
                                          : "-"}
                                      </div>
                                    </td>
                                    <td>
                                      <div className="theme-samples">
                                        {(item.manual_symbols || []).length
                                          ? (item.manual_symbols || []).map((symbol) => (
                                              <a
                                                key={symbol}
                                                className="theme-chip exclude"
                                                href={yahooSymbolUrl(symbol)}
                                                target="_blank"
                                                rel="noreferrer"
                                                onClick={() => applyThemeSymbolFilter(symbol)}
                                              >
                                                {formatSymbolLabel(symbol, configSymbolTypes)}
                                              </a>
                                            ))
                                          : "-"}
                                      </div>
                                    </td>
                                    <td>
                                      <div className="theme-samples">
                                        {(item.exclude_symbols || []).length
                                          ? (item.exclude_symbols || []).map((symbol) => (
                                              <a
                                                key={symbol}
                                                className="theme-chip manual"
                                                href={yahooSymbolUrl(symbol)}
                                                target="_blank"
                                                rel="noreferrer"
                                                onClick={() => applyThemeSymbolFilter(symbol)}
                                              >
                                                {formatSymbolLabel(symbol, configSymbolTypes)}
                                              </a>
                                            ))
                                          : "-"}
                                      </div>
                                    </td>
                                    <td className="theme-actions">
                                      <button
                                        type="button"
                                        className="link-button"
                                        onClick={() =>
                                          activeThemeKey === item.key
                                            ? closeThemeSymbols()
                                            : loadThemeSymbols(item.key)
                                        }
                                      >
                                        {activeThemeKey === item.key
                                          ? t("projects.config.themeClose")
                                          : t("projects.config.themeView")}
                                      </button>
                                    </td>
                                  </tr>
                                </Fragment>
                              ))
                            ) : (
                            <tr>
                              <td colSpan={8}>{t("projects.config.themesEmpty")}</td>
                            </tr>
                          )}
                          </tbody>
                        </table>
                      </div>
                      {activeThemeKey && activeThemeSymbols && (
                        <div className="theme-detail-panel">
                          <div className="theme-detail-header">
                            <div>
                              <div className="theme-detail-title">
                                {t("projects.config.themeDetailTitle", {
                                  name: activeThemeSymbols.label || activeThemeKey,
                                })}
                              </div>
                              <div className="theme-detail-meta">
                                {t("projects.config.themeDetailMeta", {
                                  total: activeCombinedSymbols.length,
                                  manual: activeManualSymbols.length,
                                  excluded: activeExcludeSymbols.length,
                                })}
                              </div>
                            </div>
                            <div className="theme-detail-actions">
                              <input
                                className="form-input"
                                value={themeSymbolQuery}
                                onChange={(e) => setThemeSymbolQuery(e.target.value.toUpperCase())}
                                placeholder={t("projects.config.themeDetailFilter")}
                              />
                              <button
                                type="button"
                                className="button-secondary"
                                onClick={() => setThemeSymbolQuery("")}
                              >
                                {t("projects.config.themeDetailClear")}
                              </button>
                              <button
                                type="button"
                                className="button-secondary"
                                onClick={exportThemeSymbols}
                              >
                                {t("projects.config.themeDetailExport")}
                              </button>
                            </div>
                            <div className="theme-symbol-form">
                              <input
                                className="form-input"
                                value={newThemeSymbol}
                                onChange={(e) => {
                                  setNewThemeSymbol(e.target.value.toUpperCase());
                                  setThemeSymbolMessage("");
      setBenchmarkMessage("");
                                }}
                                placeholder={t("projects.config.themeSymbolPlaceholder")}
                              />
                              <select
                                className="form-select"
                                value={newThemeSymbolType}
                                onChange={(e) => setNewThemeSymbolType(e.target.value)}
                              >
                                {symbolTypeOptions.map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                              <div className="theme-symbol-actions">
                                <button
                                  type="button"
                                  className="button-secondary"
                                  onClick={() => handleAddSymbol("manual")}
                                >
                                  {t("projects.config.themeSymbolAdd")}
                                </button>
                                <button
                                  type="button"
                                  className="button-secondary"
                                  onClick={() => handleAddSymbol("exclude")}
                                >
                                  {t("projects.config.themeSymbolExclude")}
                                </button>
                              </div>
                            </div>
                            {themeSymbolMessage && (
                              <div className="form-hint">{themeSymbolMessage}</div>
                            )}
                          </div>
                          <div className="theme-detail-section">
                            <div className="theme-detail-section-title">
                              {t("projects.config.themeDetailAuto")}
                            </div>
                            <div className="theme-detail-list">
                              {filteredAutoSymbols.length ? (
                                filteredAutoSymbols.map((symbol) => (
                                  <span key={symbol} className="theme-chip-group">
                                    <a
                                      className="theme-chip"
                                      href={yahooSymbolUrl(symbol)}
                                      target="_blank"
                                      rel="noreferrer"
                                      onClick={() => applyThemeSymbolFilter(symbol)}
                                    >
                                      {formatSymbolLabel(symbol, activeSymbolTypes)}
                                    </a>
                                    <button
                                      type="button"
                                      className="theme-chip-action"
                                      onClick={() =>
                                        addExcludeSymbol(
                                          symbol,
                                          activeSymbolTypes[symbol] || "UNKNOWN"
                                        )
                                      }
                                    >
                                      {t("projects.config.themeSymbolExcludeAction")}
                                    </button>
                                  </span>
                                ))
                              ) : (
                                <span className="theme-detail-empty">
                                  {t("projects.config.themeEmptySymbols")}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="theme-detail-section">
                            <div className="theme-detail-section-title">
                              {t("projects.config.themeDetailManual")}
                            </div>
                            <div className="theme-detail-list">
                              {filteredManualSymbols.length ? (
                                filteredManualSymbols.map((symbol) => (
                                  <span key={symbol} className="theme-chip-group">
                                    <a
                                      className="theme-chip exclude"
                                      href={yahooSymbolUrl(symbol)}
                                      target="_blank"
                                      rel="noreferrer"
                                      onClick={() => applyThemeSymbolFilter(symbol)}
                                    >
                                      {formatSymbolLabel(symbol, activeSymbolTypes)}
                                    </a>
                                    <button
                                      type="button"
                                      className="theme-chip-action"
                                      onClick={() => removeManualSymbol(symbol)}
                                    >
                                      {t("projects.config.themeSymbolRemove")}
                                    </button>
                                  </span>
                                ))
                              ) : (
                                <span className="theme-detail-empty">
                                  {t("projects.config.themeEmptySymbols")}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="theme-detail-section">
                            <div className="theme-detail-section-title">
                              {t("projects.config.themeDetailExcluded")}
                            </div>
                            <div className="theme-detail-list">
                              {filteredExcludedSymbols.length ? (
                                filteredExcludedSymbols.map((symbol) => (
                                  <span key={symbol} className="theme-chip-group">
                                    <a
                                      className="theme-chip manual"
                                      href={yahooSymbolUrl(symbol)}
                                      target="_blank"
                                      rel="noreferrer"
                                      onClick={() => applyThemeSymbolFilter(symbol)}
                                    >
                                      {formatSymbolLabel(symbol, activeSymbolTypes)}
                                    </a>
                                    <button
                                      type="button"
                                      className="theme-chip-action theme-chip-action-neutral"
                                      onClick={() => restoreExcludedSymbol(symbol)}
                                    >
                                      {t("projects.config.themeSymbolRestore")}
                                    </button>
                                  </span>
                                ))
                              ) : (
                                <span className="theme-detail-empty">
                                  {t("projects.config.themeEmptySymbols")}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="theme-compare-panel">
                      <div className="form-label">{t("projects.config.themeCompareTitle")}</div>
                      <div className="theme-compare-controls">
                        <div className="theme-compare-field">
                          <label className="form-label">{t("projects.config.themeCompareA")}</label>
                          <select
                            className="form-select"
                            value={compareThemeA}
                            onChange={(e) => updateCompareTheme(e.target.value, "A")}
                          >
                            <option value="">{t("projects.config.themeCompareEmpty")}</option>
                            {themeSelectOptions.map((option) => (
                              <option key={option.key} value={option.key}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="theme-compare-field">
                          <label className="form-label">{t("projects.config.themeCompareB")}</label>
                          <select
                            className="form-select"
                            value={compareThemeB}
                            onChange={(e) => updateCompareTheme(e.target.value, "B")}
                          >
                            <option value="">{t("projects.config.themeCompareEmpty")}</option>
                            {themeSelectOptions.map((option) => (
                              <option key={option.key} value={option.key}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="theme-compare-stats">
                          <div>
                            {t("projects.config.themeCompareShared")}{" "}
                            <strong>{compareSets.shared.length}</strong>
                          </div>
                          <div>
                            {t("projects.config.themeCompareOnlyA")}{" "}
                            <strong>{compareSets.onlyA.length}</strong>
                          </div>
                          <div>
                            {t("projects.config.themeCompareOnlyB")}{" "}
                            <strong>{compareSets.onlyB.length}</strong>
                          </div>
                        </div>
                      </div>
                      {compareMessage && <div className="form-hint">{compareMessage}</div>}
                      <div className="theme-compare-grid">
                        <div className="theme-compare-block">
                          <div className="theme-compare-title">
                            {t("projects.config.themeCompareOnlyA")}
                          </div>
                          <div className="theme-compare-list">
                            {compareSets.onlyA.length
                              ? compareSets.onlyA.map((symbol) => (
                                  <a
                                    key={symbol}
                                    className="theme-chip"
                                    href={yahooSymbolUrl(symbol)}
                                    target="_blank"
                                    rel="noreferrer"
                                    onClick={() => applyThemeSymbolFilter(symbol)}
                                  >
                                    {formatSymbolLabel(symbol, compareSymbolTypes)}
                                  </a>
                                ))
                              : t("projects.config.themeEmptySymbols")}
                          </div>
                        </div>
                        <div className="theme-compare-block">
                          <div className="theme-compare-title">
                            {t("projects.config.themeCompareShared")}
                          </div>
                          <div className="theme-compare-list">
                            {compareSets.shared.length
                              ? compareSets.shared.map((symbol) => (
                                  <a
                                    key={symbol}
                                    className="theme-chip"
                                    href={yahooSymbolUrl(symbol)}
                                    target="_blank"
                                    rel="noreferrer"
                                    onClick={() => applyThemeSymbolFilter(symbol)}
                                  >
                                    {formatSymbolLabel(symbol, compareSymbolTypes)}
                                  </a>
                                ))
                              : t("projects.config.themeEmptySymbols")}
                          </div>
                        </div>
                        <div className="theme-compare-block">
                          <div className="theme-compare-title">
                            {t("projects.config.themeCompareOnlyB")}
                          </div>
                          <div className="theme-compare-list">
                            {compareSets.onlyB.length
                              ? compareSets.onlyB.map((symbol) => (
                                  <a
                                    key={symbol}
                                    className="theme-chip"
                                    href={yahooSymbolUrl(symbol)}
                                    target="_blank"
                                    rel="noreferrer"
                                    onClick={() => applyThemeSymbolFilter(symbol)}
                                  >
                                    {formatSymbolLabel(symbol, compareSymbolTypes)}
                                  </a>
                                ))
                              : t("projects.config.themeEmptySymbols")}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {configSection === "portfolio" && (
                  <div className="config-section">
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.benchmark")}</label>
                      <input
                        className="form-input"
                        value={configDraft.benchmark || ""}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({ ...(prev || {}), benchmark: e.target.value }))
                        }
                        placeholder="SPY"
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.rebalance")}</label>
                      <select
                        className="form-select"
                        value={configDraft.rebalance || "M"}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({ ...(prev || {}), rebalance: e.target.value }))
                        }
                      >
                        <option value="D">{t("projects.config.rebalanceDaily")}</option>
                        <option value="W">{t("projects.config.rebalanceWeekly")}</option>
                        <option value="M">{t("projects.config.rebalanceMonthly")}</option>
                        <option value="Q">{t("projects.config.rebalanceQuarterly")}</option>
                      </select>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.backtestStart")}</label>
                      <input
                        className="form-input"
                        type="date"
                        value={configDraft.backtest_start || ""}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...(prev || {}),
                            backtest_start: e.target.value || "",
                          }))
                        }
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.backtestEnd")}</label>
                      <input
                        className="form-input"
                        type="date"
                        value={configDraft.backtest_end || ""}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...(prev || {}),
                            backtest_end: e.target.value || "",
                          }))
                        }
                      />
                    </div>
                    <div className="form-hint">{t("projects.config.backtestRangeHint")}</div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.riskFreeRate")}</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        value={configDraft.risk_free_rate ?? 0}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...(prev || {}),
                            risk_free_rate: Number(e.target.value) || 0,
                          }))
                        }
                      />
                    </div>
                    <div className={`meta-row ${weightTotalWarn ? "meta-warn" : ""}`}>
                      <span>{t("projects.config.weightTotal")}</span>
                      <strong>{formatPercent(weightTotal)}</strong>
                    </div>
                  </div>
                )}

                <div className="meta-row">
                  <span>{t("projects.config.source")}</span>
                  <strong>{configMeta?.source || t("common.none")}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("common.labels.updatedAt")}</span>
                  <strong>{formatDateTime(configMeta?.updated_at)}</strong>
                </div>
                {configMessage && <div className="form-hint">{configMessage}</div>}
                <button className="button-primary" onClick={saveProjectConfig}>
                  {t("projects.config.save")}
                </button>
              </div>
            )}
            </div>
            )}

            {projectTab === "algorithm" && (
              <>
              <div className="card">
            <div className="card-title">{t("projects.algorithm.title")}</div>
            <div className="card-meta">{t("projects.algorithm.meta")}</div>
            <div className="form-grid">
              <div className="form-row">
                <label className="form-label">{t("projects.algorithm.algorithm")}</label>
                <select
                  className="form-select"
                  value={bindingForm.algorithmId}
                  onChange={(e) =>
                    setBindingForm((prev) => ({
                      ...prev,
                      algorithmId: e.target.value,
                      versionId: "",
                    }))
                  }
                >
                  <option value="">{t("projects.algorithm.selectAlgorithm")}</option>
                  {algorithms.map((algo) => (
                    <option key={algo.id} value={algo.id}>
                      {algo.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.algorithm.version")}</label>
                <select
                  className="form-select"
                  value={bindingForm.versionId}
                  onChange={(e) =>
                    setBindingForm((prev) => ({ ...prev, versionId: e.target.value }))
                  }
                >
                  <option value="">{t("projects.algorithm.selectVersion")}</option>
                  {algorithmVersions.map((ver) => (
                    <option key={ver.id} value={ver.id}>
                      #{ver.id} {ver.version || t("common.none")}
                    </option>
                  ))}
                </select>
              </div>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={bindingForm.isLocked}
                  onChange={(e) =>
                    setBindingForm((prev) => ({ ...prev, isLocked: e.target.checked }))
                  }
                />
                {t("projects.algorithm.lock")}
              </label>
              <div className="meta-row">
                <span>{t("projects.algorithm.current")}</span>
                <strong>
                  {binding?.exists
                    ? `${binding.algorithm_name || ""} ${binding.algorithm_version || ""}`
                    : t("common.noneText")}
                </strong>
              </div>
              <div className="meta-row">
                <span>{t("common.labels.updatedAt")}</span>
                <strong>{formatDateTime(binding?.updated_at)}</strong>
              </div>
              {bindingMessage && <div className="form-hint">{bindingMessage}</div>}
              <button className="button-primary" onClick={saveAlgorithmBinding}>
                {t("projects.algorithm.save")}
              </button>
            </div>
            </div>
              {renderBenchmarkEditor()}
              <div className="card">
                <div className="card-title">{t("projects.strategy.title")}</div>
                <div className="card-meta">{t("projects.strategy.meta")}</div>
                <div className="form-grid two-col">
                  <div className="form-row">
                    <label className="form-label">{t("projects.strategy.source")}</label>
                    <select
                      className="form-select"
                      value={strategySource}
                      onChange={(e) => handleStrategySourceChange(e.target.value)}
                    >
                      <option value="theme_weights">
                        {t("projects.strategy.sourceTheme")}
                      </option>
                      <option value="factor_scores">
                        {t("projects.strategy.sourceFactor")}
                      </option>
                      <option value="ml_scores">{t("projects.strategy.sourceMl")}</option>
                    </select>
                  </div>
                  {strategySource !== "theme_weights" && (
                    <>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.strategy.scorePath")}
                        </label>
                        <input
                          value={strategyDraft.score_csv_path || ""}
                          onChange={(e) =>
                            updateStrategyField("score_csv_path", e.target.value)
                          }
                          placeholder={t("projects.strategy.scorePathHint")}
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.strategy.scoreTopN")}
                        </label>
                        <input
                          type="number"
                          value={strategyDraft.score_top_n ?? ""}
                          onChange={(e) => {
                            const value = e.target.value;
                            updateStrategyField(
                              "score_top_n",
                              value === "" ? "" : Number(value)
                            );
                          }}
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.strategy.scoreWeighting")}
                        </label>
                        <select
                          className="form-select"
                          value={strategyDraft.score_weighting || "score"}
                          onChange={(e) =>
                            updateStrategyField("score_weighting", e.target.value)
                          }
                        >
                          <option value="score">{t("projects.strategy.weightScore")}</option>
                          <option value="equal">{t("projects.strategy.weightEqual")}</option>
                        </select>
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.strategy.scoreMin")}
                        </label>
                        <input
                          type="number"
                          value={strategyDraft.score_min ?? ""}
                          onChange={(e) => {
                            const value = e.target.value;
                            updateStrategyField(
                              "score_min",
                              value === "" ? "" : Number(value)
                            );
                          }}
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.strategy.scoreMaxWeight")}
                        </label>
                        <input
                          type="number"
                          value={strategyDraft.score_max_weight ?? ""}
                          onChange={(e) => {
                            const value = e.target.value;
                            updateStrategyField(
                              "score_max_weight",
                              value === "" ? "" : Number(value)
                            );
                          }}
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.strategy.scoreFallback")}
                        </label>
                        <select
                          className="form-select"
                          value={strategyDraft.score_fallback || "theme_weights"}
                          onChange={(e) =>
                            updateStrategyField("score_fallback", e.target.value)
                          }
                        >
                          <option value="theme_weights">
                            {t("projects.strategy.fallbackTheme")}
                          </option>
                          <option value="universe">
                            {t("projects.strategy.fallbackUniverse")}
                          </option>
                          <option value="skip">{t("projects.strategy.fallbackSkip")}</option>
                        </select>
                      </div>
                    </>
                  )}
                  {strategySource === "theme_weights" && (
                    <div className="form-hint">{t("projects.strategy.themeHint")}</div>
                  )}
                </div>
                {configMessage && <div className="form-hint">{configMessage}</div>}
                <button className="button-primary" onClick={saveProjectConfig}>
                  {t("projects.strategy.save")}
                </button>
              </div>
              <div className="card">
                <div className="card-title">{t("projects.factorScores.title")}</div>
                <div className="card-meta">{t("projects.factorScores.meta")}</div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">
                      {t("projects.factorScores.start")}
                    </label>
                    <input
                      value={factorForm.start}
                      onChange={(e) =>
                        setFactorForm((prev) => ({ ...prev, start: e.target.value }))
                      }
                      placeholder={t("projects.factorScores.startHint")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">
                      {t("projects.factorScores.end")}
                    </label>
                    <input
                      value={factorForm.end}
                      onChange={(e) =>
                        setFactorForm((prev) => ({ ...prev, end: e.target.value }))
                      }
                      placeholder={t("projects.factorScores.endHint")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">
                      {t("projects.factorScores.config")}
                    </label>
                    <input
                      value={factorForm.config_path}
                      onChange={(e) =>
                        setFactorForm((prev) => ({ ...prev, config_path: e.target.value }))
                      }
                      placeholder={t("projects.factorScores.configHint")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">
                      {t("projects.factorScores.output")}
                    </label>
                    <input
                      value={factorForm.output_path}
                      onChange={(e) =>
                        setFactorForm((prev) => ({ ...prev, output_path: e.target.value }))
                      }
                      placeholder={t("projects.factorScores.outputHint")}
                    />
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={factorForm.overwrite_cache}
                      onChange={(e) =>
                        setFactorForm((prev) => ({
                          ...prev,
                          overwrite_cache: e.target.checked,
                        }))
                      }
                    />
                    {t("projects.factorScores.overwrite")}
                  </label>
                </div>
                {factorActionMessage && <div className="form-hint">{factorActionMessage}</div>}
                {factorLoadError && <div className="form-error">{factorLoadError}</div>}
                {factorJobs.length ? (
                  <>
                    <div className="meta-row">
                      <span>{t("projects.factorScores.latest")}</span>
                      <strong>
                        {factorJobs[0].id} · {factorStatusLabel(factorJobs[0].status)}
                      </strong>
                    </div>
                    {factorJobs[0].scores_path && (
                      <div className="meta-row">
                        <span>{t("projects.factorScores.scoresPath")}</span>
                        <strong>{factorJobs[0].scores_path}</strong>
                      </div>
                    )}
                    {factorJobs[0].log_path && (
                      <div className="meta-row">
                        <span>{t("projects.factorScores.logPath")}</span>
                        <strong>{factorJobs[0].log_path}</strong>
                      </div>
                    )}
                    <div className="table-scroll">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>{t("projects.factorScores.table.id")}</th>
                            <th>{t("projects.factorScores.table.status")}</th>
                            <th>{t("projects.factorScores.table.createdAt")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {factorJobs.map((job) => (
                            <tr key={job.id}>
                              <td>#{job.id}</td>
                              <td>
                                <span className={`pill ${mlStatusClass(job.status)}`.trim()}>
                                  {factorStatusLabel(job.status)}
                                </span>
                              </td>
                              <td>{formatDateTime(job.created_at)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <div className="empty-state">{t("projects.factorScores.empty")}</div>
                )}
                <button
                  className="button-primary"
                  onClick={createFactorJob}
                  disabled={factorActionLoading}
                >
                  {factorActionLoading
                    ? t("common.actions.loading")
                    : t("projects.factorScores.action")}
                </button>
              </div>
              <div className="card">
                <div className="card-title">{t("projects.ml.title")}</div>
                <div className="card-meta">{t("projects.ml.meta")}</div>
                <div className="meta-list" style={{ marginBottom: "12px" }}>
                  <div className="meta-row">
                    <span>{t("projects.ml.symbolCount")}</span>
                    <strong>{themeSummary?.total_symbols ?? 0}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.ml.benchmark")}</span>
                    <strong>{configDraft?.benchmark || "SPY"}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.ml.current")}</span>
                    <strong>
                      {mlActiveJob?.id
                        ? t("projects.ml.currentJob", { id: mlActiveJob.id })
                        : t("common.noneText")}
                    </strong>
                  </div>
                </div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.device")}</label>
                    <select
                      className="form-select"
                      value={mlForm.device}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, device: e.target.value }))
                      }
                    >
                      <option value="auto">{t("projects.ml.deviceAuto")}</option>
                      <option value="cpu">{t("projects.ml.deviceCpu")}</option>
                      <option value="cuda">{t("projects.ml.deviceCuda")}</option>
                    </select>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.modelType")}</label>
                    <select
                      className="form-select"
                      value={mlForm.modelType}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, modelType: e.target.value }))
                      }
                    >
                      <option value="torch_mlp">{t("projects.ml.modelTypeTorch")}</option>
                      <option value="lgbm_ranker">{t("projects.ml.modelTypeLgbm")}</option>
                    </select>
                    <div className="form-hint">{t("projects.ml.modelTypeHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.trainYears")}</label>
                    <input
                      type="number"
                      className="form-input"
                      value={mlForm.trainYears}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, trainYears: e.target.value }))
                      }
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.trainStartYear")}</label>
                    <input
                      type="number"
                      min={2000}
                      max={2100}
                      className="form-input"
                      value={mlForm.trainStartYear}
                      onChange={(e) =>
                        setMlForm((prev) => ({
                          ...prev,
                          trainStartYear: e.target.value,
                        }))
                      }
                      placeholder={t("projects.ml.trainStartYearPlaceholder")}
                    />
                    <div className="form-hint">{t("projects.ml.trainStartYearHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.validMonths")}</label>
                    <input
                      type="number"
                      className="form-input"
                      value={mlForm.validMonths}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, validMonths: e.target.value }))
                      }
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.walkForward")}</label>
                    <label className="switch">
                      <input
                        type="checkbox"
                        checked={mlForm.walkForwardEnabled}
                        onChange={(e) =>
                          setMlForm((prev) => ({
                            ...prev,
                            walkForwardEnabled: e.target.checked,
                          }))
                        }
                      />
                      <span className="slider" />
                    </label>
                    <div className="form-hint">{t("projects.ml.walkForwardHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.testMonths")}</label>
                    <input
                      type="number"
                      className="form-input"
                      value={mlForm.testMonths}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, testMonths: e.target.value }))
                      }
                      disabled={!mlForm.walkForwardEnabled}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.stepMonths")}</label>
                    <input
                      type="number"
                      className="form-input"
                      value={mlForm.stepMonths}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, stepMonths: e.target.value }))
                      }
                      disabled={!mlForm.walkForwardEnabled}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.horizonDays")}</label>
                    <input
                      type="number"
                      className="form-input"
                      value={mlForm.labelHorizonDays}
                      onChange={(e) =>
                        setMlForm((prev) => ({
                          ...prev,
                          labelHorizonDays: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <div className="form-row" style={{ gridColumn: "1 / -1" }}>
                    <label className="form-label">{t("projects.ml.modelParams")}</label>
                    <textarea
                      className="form-input"
                      rows={3}
                      value={mlForm.modelParams}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, modelParams: e.target.value }))
                      }
                      placeholder={t("projects.ml.modelParamsPlaceholder")}
                    />
                    <div className="form-hint">{t("projects.ml.modelParamsHint")}</div>
                  </div>
                  {mlMessage && <div className="form-hint">{mlMessage}</div>}
                  <button className="button-primary" onClick={createMlJob} disabled={mlLoading}>
                    {mlLoading ? t("common.actions.loading") : t("projects.ml.train")}
                  </button>
                </div>
                <div className="section-divider" />
                {mlJobs.length ? (
                  <div className="table-scroll">
                    <table className="table ml-train-table">
                      <thead>
                        <tr>
                          <th>{t("projects.ml.table.status")}</th>
                          <th>{t("projects.ml.table.progress")}</th>
                          <th>{t("projects.ml.table.window")}</th>
                          <th>{t("projects.ml.table.range")}</th>
                          <th>{t("projects.ml.table.model")}</th>
                          <th>{t("projects.ml.table.horizon")}</th>
                          <th>{t("projects.ml.table.symbols")}</th>
                          <th>{t("projects.ml.table.device")}</th>
                          <th>{t("projects.ml.table.createdAt")}</th>
                          <th>{t("projects.ml.table.actions")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mlJobs.map((job) => {
                          const cfg = job.config || {};
                          const walk = (cfg.walk_forward || {}) as Record<string, any>;
                          const modelType = cfg.model_type || cfg.model?.type || "torch_mlp";
                          const symbolCount =
                            cfg.meta?.symbol_count ?? (cfg.symbols?.length ?? 0);
                          const ranges = mlTrainRangeDetail(job);
                          const trainLabel = t("projects.ml.table.trainRangeShort");
                          const validLabel = t("projects.ml.table.validRangeShort");
                          const testLabel = t("projects.ml.table.testRangeShort");
                          return (
                            <tr key={job.id}>
                              <td>
                                <div className="ml-status-cell">
                                  <span className={`pill ${mlStatusClass(job.status)}`.trim()}>
                                    {mlStatusLabel(job.status)}
                                  </span>
                                  {job.is_active && (
                                    <span className="badge">{t("projects.ml.active")}</span>
                                  )}
                                </div>
                              </td>
                              <td>{mlProgressLabel(job)}</td>
                              <td>
                                {walk.train_years ? `${walk.train_years}Y` : "-"} /{" "}
                                {walk.valid_months ? `${walk.valid_months}M` : "-"} /{" "}
                                {walk.test_months ? `${walk.test_months}M` : "-"}
                              </td>
                              <td className="ml-range-cell">
                                <div className="ml-range-inline">
                                  <span title={`${t("projects.ml.table.trainRange")}: ${ranges.train}`}>
                                    {trainLabel} {ranges.train}
                                  </span>
                                  <span title={`${t("projects.ml.table.validRange")}: ${ranges.valid}`}>
                                    {validLabel} {ranges.valid}
                                  </span>
                                  <span title={`${t("projects.ml.table.testRange")}: ${ranges.test}`}>
                                    {testLabel} {ranges.test}
                                  </span>
                                </div>
                              </td>
                              <td>{String(modelType)}</td>
                              <td>{cfg.label_horizon_days ?? "-"}</td>
                              <td>{symbolCount || "-"}</td>
                              <td>{cfg.device || "auto"}</td>
                              <td>{formatDateTime(job.created_at)}</td>
                              <td className="ml-actions-cell">
                                <div className="table-actions">
                                  <button
                                    className="link-button"
                                    type="button"
                                    onClick={() => setMlDetailId(job.id)}
                                  >
                                    {t("projects.ml.detail")}
                                  </button>
                                  {(job.status === "running" || job.status === "queued") && (
                                    <button
                                      className="link-button"
                                      type="button"
                                      onClick={() => cancelMlJob(job.id)}
                                      disabled={mlActionLoadingId === job.id}
                                    >
                                      {mlActionLoadingId === job.id
                                        ? t("projects.ml.canceling")
                                        : t("projects.ml.cancel")}
                                    </button>
                                  )}
                                  {job.status === "success" && !job.is_active && (
                                    <button
                                      className="link-button"
                                      type="button"
                                      onClick={() => activateMlJob(job.id)}
                                    >
                                      {t("projects.ml.activate")}
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="empty-state">{t("projects.ml.empty")}</div>
                )}
                {mlDetailJob && (
                  <div style={{ marginTop: "12px" }} className="meta-list">
                    <div className="meta-row">
                      <span>{t("projects.ml.detailTitle")}</span>
                      <strong>
                        {t("projects.ml.currentJob", { id: mlDetailJob.id })}
                      </strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("projects.ml.detailStatus")}</span>
                      <strong>{mlStatusLabel(mlDetailJob.status)}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("projects.ml.detailModel")}</span>
                      <strong>
                        {String(
                          mlDetailJob.config?.model_type ||
                            mlDetailJob.config?.model?.type ||
                            "torch_mlp"
                        )}
                      </strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("projects.ml.detailProgress")}</span>
                      <strong>{mlProgressLabel(mlDetailJob)}</strong>
                    </div>
                    {mlDetailJob.progress_detail?.phase && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailPhase")}</span>
                        <strong>{String(mlDetailJob.progress_detail.phase)}</strong>
                      </div>
                    )}
                    {mlDetailJob.progress_detail?.window_total && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailWindow")}</span>
                        <strong>
                          {String(mlDetailJob.progress_detail.window || 0)}/
                          {String(mlDetailJob.progress_detail.window_total)}
                        </strong>
                      </div>
                    )}
                    {mlDetailJob.progress_detail?.epoch_total && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailEpoch")}</span>
                        <strong>
                          {String(mlDetailJob.progress_detail.epoch || 0)}/
                          {String(mlDetailJob.progress_detail.epoch_total)}
                        </strong>
                      </div>
                    )}
                    <div className="meta-row">
                      <span>{t("projects.ml.detailOutput")}</span>
                      <strong>{mlDetailJob.output_dir || "-"}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("projects.ml.detailScores")}</span>
                      <strong>{mlDetailJob.scores_path || "-"}</strong>
                    </div>
                    <div className="meta-row">
                      <span>{t("projects.ml.detailLog")}</span>
                      <strong>{mlDetailJob.log_path || "-"}</strong>
                    </div>
                    {mlDetailJob.message && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailMessage")}</span>
                        <strong>{mlDetailJob.message}</strong>
                      </div>
                    )}
                  </div>
                )}
              </div>
              </>
            )}
          </div>
        )}

        {selectedProject && (projectTab === "data" || projectTab === "backtest") && (
          <div className="grid-2">
            {projectTab === "data" && (
              <div className="card">
            <div className="card-title">{t("projects.dataStatus.title")}</div>
            <div className="card-meta">{t("projects.dataStatus.meta")}</div>
            {!dataStatus ? (
              <div className="empty-state">{t("common.noneText")}</div>
            ) : (
              <div className="meta-list">
                {(() => {
                  const backtestSummary = dataStatus.backtest?.summary as
                    | Record<string, any>
                    | null
                    | undefined;
                  if (!backtestSummary) {
                    return null;
                  }
                  return (
                    <>
                      <div className="meta-row">
                        <span>{t("projects.dataStatus.backtestLog")}</span>
                        <strong>{backtestSummary.log_path || t("common.none")}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.dataStatus.backtestOutput")}</span>
                        <strong>{backtestSummary.output_dir || t("common.none")}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.dataStatus.backtestArtifact")}</span>
                        <strong>{backtestSummary.artifact_dir || t("common.none")}</strong>
                      </div>
                    </>
                  );
                })()}
                <div className="meta-row">
                  <span>{t("projects.dataStatus.membership")}</span>
                  <strong>{dataStatus.membership.symbols}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.dataStatus.range")}</span>
                  <strong>
                    {dataStatus.membership.start || t("common.none")} ~{" "}
                    {dataStatus.membership.end || t("common.none")}
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.dataStatus.universe")}</span>
                  <strong>{dataStatus.universe.records}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.dataStatus.themes")}</span>
                  <strong>{dataStatus.themes.categories.length}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.dataStatus.metrics")}</span>
                  <strong>{dataStatus.metrics.records}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.dataStatus.prices")}</span>
                  <strong>
                    {dataStatus.prices.stooq_files + dataStatus.prices.yahoo_files}
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("common.labels.updatedAt")}</span>
                  <strong>{formatDateTime(dataStatus.prices.updated_at)}</strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.dataStatus.root")}</span>
                  <strong>{dataStatus.data_root}</strong>
                </div>
              </div>
            )}
            {dataMessage && <div className="form-hint">{dataMessage}</div>}
            <button className="button-secondary" onClick={refreshProjectData}>
              {t("projects.dataStatus.action")}
            </button>
            </div>
            )}

            {projectTab === "backtest" && (
              <>
              <div className="card">
            <div className="card-title">{t("projects.automation.title")}</div>
            <div className="card-meta">{t("projects.automation.meta")}</div>
            {autoWeeklyJob ? (
              <div className="meta-list">
                <div className="meta-row">
                  <span>{t("projects.automation.statusLabel")}</span>
                  <strong>
                    <span className={`pill ${mlStatusClass(autoWeeklyJob.status)}`.trim()}>
                      {automationStatusLabel(autoWeeklyJob.status)}
                    </span>
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.automation.pitWeekly")}</span>
                  <strong>{autoWeeklyJob.pit_weekly_job_id ?? t("common.none")}</strong>
                </div>
                {autoWeeklyJob.pit_weekly_log_path && (
                  <div className="meta-row">
                    <span>{t("projects.automation.pitWeeklyLog")}</span>
                    <strong>{autoWeeklyJob.pit_weekly_log_path}</strong>
                  </div>
                )}
                <div className="meta-row">
                  <span>{t("projects.automation.pitFund")}</span>
                  <strong>{autoWeeklyJob.pit_fundamental_job_id ?? t("common.none")}</strong>
                </div>
                {autoWeeklyJob.pit_fundamental_log_path && (
                  <div className="meta-row">
                    <span>{t("projects.automation.pitFundLog")}</span>
                    <strong>{autoWeeklyJob.pit_fundamental_log_path}</strong>
                  </div>
                )}
                <div className="meta-row">
                  <span>{t("projects.automation.backtest")}</span>
                  <strong>{automationStatusLabel(autoWeeklyJob.backtest_status || "")}</strong>
                </div>
                {autoWeeklyJob.backtest_log_path && (
                  <div className="meta-row">
                    <span>{t("projects.automation.backtestLog")}</span>
                    <strong>{autoWeeklyJob.backtest_log_path}</strong>
                  </div>
                )}
                {autoWeeklyJob.backtest_output_dir && (
                  <div className="meta-row">
                    <span>{t("projects.automation.backtestOutput")}</span>
                    <strong>{autoWeeklyJob.backtest_output_dir}</strong>
                  </div>
                )}
                {autoWeeklyJob.backtest_artifact_dir && (
                  <div className="meta-row">
                    <span>{t("projects.automation.backtestArtifact")}</span>
                    <strong>{autoWeeklyJob.backtest_artifact_dir}</strong>
                  </div>
                )}
                {autoWeeklyJob.log_path && (
                  <div className="meta-row">
                    <span>{t("projects.automation.log")}</span>
                    <strong>{autoWeeklyJob.log_path}</strong>
                  </div>
                )}
                <div className="meta-row">
                  <span>{t("common.labels.updatedAt")}</span>
                  <strong>
                    {formatDateTime(
                      autoWeeklyJob.ended_at ||
                        autoWeeklyJob.started_at ||
                        autoWeeklyJob.created_at
                    )}
                  </strong>
                </div>
                {autoWeeklyJob.message && (
                  <div className="form-hint">{autoWeeklyJob.message}</div>
                )}
              </div>
            ) : (
              <div className="empty-state">{t("projects.automation.empty")}</div>
            )}
            {autoWeeklyMessage && <div className="form-hint">{autoWeeklyMessage}</div>}
            <button
              className="button-secondary"
              onClick={runAutoWeeklyJob}
              disabled={autoWeeklyLoading}
            >
              {autoWeeklyLoading
                ? t("projects.automation.running")
                : t("projects.automation.action")}
            </button>
            </div>
              <div className="card">
            <div className="card-title">{t("projects.config.backtestRangeTitle")}</div>
            <div className="card-meta">{t("projects.config.backtestRangeMeta")}</div>
            <div className="form-row">
              <label className="form-label">{t("projects.config.backtestStart")}</label>
              <input
                className="form-input"
                type="date"
                value={configDraft?.backtest_start || ""}
                onChange={(e) =>
                  setConfigDraft((prev) => ({
                    ...(prev || {}),
                    backtest_start: e.target.value || "",
                  }))
                }
              />
            </div>
            <div className="form-row">
              <label className="form-label">{t("projects.config.backtestEnd")}</label>
              <input
                className="form-input"
                type="date"
                value={configDraft?.backtest_end || ""}
                onChange={(e) =>
                  setConfigDraft((prev) => ({
                    ...(prev || {}),
                    backtest_end: e.target.value || "",
                  }))
                }
              />
            </div>
            <div className="form-hint">{t("projects.config.backtestRangeHint")}</div>
            <button className="button-secondary" onClick={saveProjectConfig}>
              {t("projects.config.save")}
            </button>
            </div>
            <div className="card">
            <div className="card-title">{t("projects.backtest.defaults.title")}</div>
            <div className="card-meta">{t("projects.backtest.defaults.meta")}</div>
            {backtestDefaultParams.length ? (
              <div className="meta-list">
                {backtestDefaultParams.map((item) => (
                  <div className="meta-row" key={item.key}>
                    <span>{item.label}</span>
                    <strong>{formatBacktestParamValue(item.value)}</strong>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">{t("projects.backtest.defaults.empty")}</div>
            )}
            </div>
              <div className="card">
            <div className="card-title">{t("projects.backtest.plugins.title")}</div>
            <div className="card-meta">{t("projects.backtest.plugins.meta")}</div>
            <div className="form-grid">
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.scoreDelay")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={backtestPlugins.score_delay_days ?? ""}
                  onChange={(e) =>
                    updateBacktestPlugin(
                      "score_delay_days",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
                <div className="form-hint">{t("projects.backtest.plugins.scoreDelayHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.scoreSmoothing")}</label>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={!!scoreSmoothing.enabled}
                    onChange={(e) =>
                      updateBacktestPluginSection("score_smoothing", "enabled", e.target.checked)
                    }
                  />
                  <span className="slider" />
                </label>
                <div className="form-hint">{t("projects.backtest.plugins.scoreSmoothingHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.scoreSmoothMethod")}</label>
                <select
                  className="form-select"
                  value={scoreSmoothing.method || "ema"}
                  onChange={(e) =>
                    updateBacktestPluginSection("score_smoothing", "method", e.target.value)
                  }
                >
                  <option value="ema">{t("projects.backtest.plugins.scoreSmoothEma")}</option>
                  <option value="none">{t("projects.backtest.plugins.scoreSmoothNone")}</option>
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.scoreSmoothAlpha")}</label>
                <input
                  type="number"
                  step="0.05"
                  className="form-input"
                  value={scoreSmoothing.alpha ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "score_smoothing",
                      "alpha",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.scoreCarry")}</label>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={scoreSmoothing.carry_missing ?? true}
                    onChange={(e) =>
                      updateBacktestPluginSection(
                        "score_smoothing",
                        "carry_missing",
                        e.target.checked
                      )
                    }
                  />
                  <span className="slider" />
                </label>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.scoreHysteresis")}</label>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={!!scoreHysteresis.enabled}
                    onChange={(e) =>
                      updateBacktestPluginSection("score_hysteresis", "enabled", e.target.checked)
                    }
                  />
                  <span className="slider" />
                </label>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.scoreRetain")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={scoreHysteresis.retain_top_n ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "score_hysteresis",
                      "retain_top_n",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
                <div className="form-hint">{t("projects.backtest.plugins.scoreRetainHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.weightSmoothing")}</label>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={!!weightSmoothing.enabled}
                    onChange={(e) =>
                      updateBacktestPluginSection("weight_smoothing", "enabled", e.target.checked)
                    }
                  />
                  <span className="slider" />
                </label>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.weightAlpha")}</label>
                <input
                  type="number"
                  step="0.05"
                  className="form-input"
                  value={weightSmoothing.alpha ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "weight_smoothing",
                      "alpha",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.riskControl")}</label>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={!!riskControl.enabled}
                    onChange={(e) => {
                      updateBacktestPluginSection("risk_control", "enabled", e.target.checked);
                      updateBacktestPluginSection(
                        "risk_control",
                        "market_filter",
                        e.target.checked
                      );
                    }}
                  />
                  <span className="slider" />
                </label>
                <div className="form-hint">{t("projects.backtest.plugins.riskControlHint")}</div>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.marketMa")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={riskControl.market_ma_window ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "risk_control",
                      "market_ma_window",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.riskOffMode")}</label>
                <select
                  className="form-select"
                  value={riskControl.risk_off_mode || "cash"}
                  onChange={(e) =>
                    updateBacktestPluginSection("risk_control", "risk_off_mode", e.target.value)
                  }
                >
                  <option value="cash">{t("projects.backtest.plugins.riskOffCash")}</option>
                  <option value="benchmark">{t("projects.backtest.plugins.riskOffBenchmark")}</option>
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.maxExposure")}</label>
                <input
                  type="number"
                  step="0.05"
                  className="form-input"
                  value={riskControl.max_exposure ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "risk_control",
                      "max_exposure",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.feeBps")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={pluginCosts.fee_bps ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "costs",
                      "fee_bps",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.slippageBps")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={pluginCosts.slippage_bps ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "costs",
                      "slippage_bps",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
              </div>
              <div className="form-row">
                <label className="form-label">{t("projects.backtest.plugins.impactBps")}</label>
                <input
                  type="number"
                  className="form-input"
                  value={pluginCosts.impact_bps ?? ""}
                  onChange={(e) =>
                    updateBacktestPluginSection(
                      "costs",
                      "impact_bps",
                      e.target.value ? Number(e.target.value) : ""
                    )
                  }
                />
              </div>
            </div>
            <button className="button-secondary" onClick={saveProjectConfig}>
              {t("projects.config.save")}
            </button>
            </div>
              <div className="card">
            <div className="card-title">{t("projects.backtest.title")}</div>
            <div className="card-meta">{t("projects.backtest.meta")}</div>
            {latestBacktest?.status === "success" && backtestSummary ? (
              <>
                <div className="metric-table">
                  <div className="metric-header">
                    <span>{t("projects.backtest.metric")}</span>
                    <span>{t("projects.backtest.portfolio")}</span>
                    <span>{t("projects.backtest.benchmark")}</span>
                  </div>
                  {metricRows.map((metric) => (
                    <div className="metric-row" key={metric.key}>
                      <span>{metric.label}</span>
                      <span>{formatMetricValue(backtestSummary?.[metric.key])}</span>
                      <span>{formatMetricValue(benchmarkSummary?.[metric.key])}</span>
                    </div>
                  ))}
                </div>
                <div className="meta-row" style={{ marginTop: "10px" }}>
                  <span>{t("projects.backtest.priceMode")}</span>
                  <strong>
                    {formatPriceMode(
                      (backtestSummary?.["Price Mode"] as string | undefined) ??
                        (backtestSummary?.price_mode as string | undefined)
                    )}
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.backtest.benchmarkMode")}</span>
                  <strong>
                    {formatPriceMode(
                      (backtestSummary?.["Benchmark Price Mode"] as string | undefined) ??
                        (backtestSummary?.benchmark_mode as string | undefined)
                    )}
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.backtest.pricePolicy")}</span>
                  <strong>
                    {formatPricePolicy(
                      (backtestSummary?.["Price Policy"] as string | undefined) ??
                        (backtestSummary?.price_policy as string | undefined) ??
                        (backtestSummary?.price_source_policy as string | undefined)
                    )}
                  </strong>
                </div>
                {missingScores.length > 0 && (
                  <div className="missing-score-block">
                    <div className="missing-score-title">
                      {t("projects.backtest.missingScoresTitle", {
                        count: missingScores.length,
                      })}
                    </div>
                    <div className="missing-score-list">{missingScores.join(", ")}</div>
                  </div>
                )}
              </>
            ) : latestBacktest?.status === "failed" && backtestErrorMessage ? (
              <div className="empty-state">
                {t("projects.backtest.failed", { message: backtestErrorMessage })}
              </div>
            ) : (
              <div className="empty-state">{t("projects.backtest.empty")}</div>
            )}
            <div className="meta-row">
              <span>{t("common.labels.updatedAt")}</span>
              <strong>
                {formatDateTime(latestBacktest?.ended_at || latestBacktest?.created_at)}
              </strong>
            </div>
            {backtestMessage && <div className="form-hint">{backtestMessage}</div>}
            <button className="button-primary" onClick={runThematicBacktest}>
              {t("projects.backtest.action")}
            </button>
            </div>
              {renderBenchmarkEditor()}
              </>
            )}
          </div>
        )}

        {selectedProject && (projectTab === "versions" || projectTab === "diff") && (
          <div className="grid-2">
            {projectTab === "versions" && (
              <div className="card">
            <div className="card-title">{t("projects.versions.title")}</div>
            <div className="card-meta">{t("projects.versions.meta")}</div>
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
              <select
                value={selectedProjectId ?? ""}
                onChange={(e) => setSelectedProjectId(Number(e.target.value) || null)}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              >
                {projects.length === 0 && (
                  <option value="">{t("projects.versions.emptyProject")}</option>
                )}
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
              <input
                value={versionForm.version}
                onChange={(e) => updateVersionForm("version", e.target.value)}
                placeholder={t("projects.versions.version")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={versionForm.description}
                onChange={(e) => updateVersionForm("description", e.target.value)}
                placeholder={t("projects.versions.description")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <textarea
                value={versionForm.content}
                onChange={(e) => updateVersionForm("content", e.target.value)}
                rows={4}
                placeholder={t("projects.versions.content", { description: placeholderDescription })}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              {versionErrorKey && (
                <div style={{ color: "#d64545", fontSize: "13px" }}>
                  {t(versionErrorKey)}
                </div>
              )}
              <button
                onClick={createVersion}
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
                {t("common.actions.saveVersion")}
              </button>
            </div>
            </div>
            )}

            {projectTab === "diff" && (
              <div className="card">
            <div className="card-title">{t("projects.diff.title")}</div>
            <div className="card-meta">{t("projects.diff.meta")}</div>
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
              <select
                value={diffFromId}
                onChange={(e) => setDiffFromId(e.target.value)}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              >
                <option value="">{t("projects.diff.selectFrom")}</option>
                {versionOptions.map((ver) => (
                  <option key={ver.id} value={ver.id}>
                    #{ver.id} {ver.version || t("projects.versionsTable.unnamed")}
                  </option>
                ))}
              </select>
              <select
                value={diffToId}
                onChange={(e) => setDiffToId(e.target.value)}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              >
                <option value="">{t("projects.diff.selectTo")}</option>
                {versionOptions.map((ver) => (
                  <option key={ver.id} value={ver.id}>
                    #{ver.id} {ver.version || t("projects.versionsTable.unnamed")}
                  </option>
                ))}
              </select>
              {diffErrorKey && (
                <div style={{ color: "#d64545", fontSize: "13px" }}>
                  {t(diffErrorKey)}
                </div>
              )}
              <button
                onClick={runDiff}
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
                {t("common.actions.generateDiff")}
              </button>
              <pre
                style={{
                  background: "#0b1022",
                  color: "#e2e8f0",
                  padding: "12px",
                  borderRadius: "12px",
                  minHeight: "140px",
                  whiteSpace: "pre-wrap",
                }}
              >
                {diffResult || t("projects.diff.none")}
              </pre>
            </div>
            </div>
            )}
          </div>
        )}

        {selectedProject && projectTab === "versions" && (
          <>
            <table className="table">
              <thead>
                <tr>
                  <th>{t("projects.versionsTable.id")}</th>
                  <th>{t("projects.versionsTable.version")}</th>
                  <th>{t("projects.versionsTable.summary")}</th>
                  <th>{t("projects.versionsTable.hash")}</th>
                  <th>{t("projects.versionsTable.createdAt")}</th>
                </tr>
              </thead>
              <tbody>
                {versions.length === 0 && (
                  <tr>
                    <td colSpan={5}>{t("projects.versionsTable.empty")}</td>
                  </tr>
                )}
                {versions.map((ver) => (
                  <tr key={ver.id}>
                    <td>{ver.id}</td>
                    <td>{ver.version || t("common.none")}</td>
                    <td>{ver.description || t("common.none")}</td>
                    <td>{ver.content_hash ? ver.content_hash.slice(0, 10) : t("common.none")}</td>
                    <td>{formatDateTime(ver.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <PaginationBar
              page={versionPage}
              pageSize={versionPageSize}
              total={versionTotal}
              onPageChange={setVersionPage}
              onPageSizeChange={(size) => {
                setVersionPage(1);
                setVersionPageSize(size);
              }}
            />
          </>
        )}
          </div>
        </div>
      </div>
    </div>
  );
}
