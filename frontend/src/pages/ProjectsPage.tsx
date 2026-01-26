import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import IdChip from "../components/IdChip";
import PaginationBar from "../components/PaginationBar";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { Paginated } from "../types";
import {
  buildMinorTickIndices,
  buildMinorTickValues,
  buildTickIndices,
  computePaddedRange,
  formatAxisValue,
} from "../utils/mlCurve";

interface Project {
  id: number;
  name: string;
  description?: string | null;
  is_archived?: boolean;
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

interface AlgorithmVersionDetail extends AlgorithmVersion {
  content_hash?: string | null;
  params?: Record<string, any> | null;
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

interface DecisionSnapshotItem {
  symbol: string;
  snapshot_date: string;
  rebalance_date: string;
  company_name?: string | null;
  weight?: number | null;
  score?: number | null;
  rank?: number | null;
  theme?: string | null;
  reason?: string | null;
  snapshot_price?: number | null;
}

interface DecisionSnapshotDetail {
  id?: number | null;
  project_id: number;
  pipeline_id?: number | null;
  train_job_id?: number | null;
  status?: string | null;
  snapshot_date?: string | null;
  summary?: Record<string, any> | null;
  params?: Record<string, any> | null;
  artifact_dir?: string | null;
  summary_path?: string | null;
  items_path?: string | null;
  filters_path?: string | null;
  message?: string | null;
  items?: DecisionSnapshotItem[];
  filters?: DecisionSnapshotItem[];
  created_at?: string | null;
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

interface SystemThemeItem {
  id: number;
  key: string;
  label: string;
  source?: string | null;
}

interface SystemThemePage {
  items: SystemThemeItem[];
  total: number;
  page: number;
  page_size: number;
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
  backtest_train_job_id?: number | null;
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

interface MLPipeline {
  id: number;
  project_id: number;
  name?: string | null;
  status: string;
  params?: Record<string, unknown> | null;
  notes?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
  train_job_count?: number;
  backtest_count?: number;
  best_train_score?: number | null;
  best_backtest_score?: number | null;
  combined_score?: number | null;
  best_train_job_id?: number | null;
  best_backtest_run_id?: number | null;
}

interface PipelineBacktest extends BacktestRun {
  score?: number | null;
  score_detail?: Record<string, unknown> | null;
}

interface MLPipelineDetail extends MLPipeline {
  train_jobs: MLTrainJob[];
  backtests: PipelineBacktest[];
  train_score_summary?: Record<string, unknown> | null;
  backtest_score_summary?: Record<string, unknown> | null;
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

const extractMetricValue = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "number" && !Number.isNaN(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isNaN(parsed) ? null : parsed;
  }
  if (typeof value === "object") {
    const record = value as Record<string, any>;
    for (const key of Object.keys(record)) {
      const nested = extractMetricValue(record[key]);
      if (nested !== null) {
        return nested;
      }
    }
  }
  return null;
};

const averageMetric = (values: number[]) => {
  if (!values.length) {
    return null;
  }
  const total = values.reduce((sum, item) => sum + item, 0);
  return total / values.length;
};

const extractWindowMetric = (
  metrics: Record<string, any> | null | undefined,
  key: string
) => {
  const windows = metrics?.walk_forward?.windows || metrics?.walkForward?.windows || [];
  if (!Array.isArray(windows)) {
    return null;
  }
  const values = windows
    .map((item) => extractMetricValue(item?.[key]))
    .filter((value): value is number => value !== null);
  return averageMetric(values);
};

const extractCurveMetricName = (metrics?: Record<string, any> | null) => {
  const curve = (metrics?.curve ||
    metrics?.walk_forward?.curve ||
    metrics?.walkForward?.curve) as Record<string, any> | undefined;
  if (curve?.metric) {
    return String(curve.metric);
  }
  return "-";
};

const extractMlCurve = (metrics?: Record<string, any> | null) => {
  if (!metrics) {
    return null;
  }
  const curve =
    (metrics.curve || metrics.walk_forward?.curve || metrics.walkForward?.curve) ?? null;
  if (curve && typeof curve === "object") {
    const iterations = Array.isArray(curve.iterations) ? curve.iterations : [];
    const train = Array.isArray(curve.train) ? curve.train : [];
    const valid = Array.isArray(curve.valid) ? curve.valid : [];
    if (train.length || valid.length) {
      return {
        metric: String(curve.metric || ""),
        iterations,
        train,
        valid,
      };
    }
  }
  const history = metrics.history as Array<Record<string, any>> | undefined;
  if (Array.isArray(history) && history.length) {
    const valid = history
      .map((item) => extractMetricValue(item?.valid_loss))
      .filter((value): value is number => value !== null);
    if (valid.length) {
      const iterations = history
        .map((item, index) => Number(item?.epoch) || index + 1)
        .filter((value) => Number.isFinite(value));
      return { metric: "valid_loss", iterations, train: [], valid };
    }
  }
  return null;
};

const PIPELINE_BACKTEST_PRESETS = {
  E35: { max_exposure: 0.35 },
  E45: { max_exposure: 0.45 },
} as const;

type PipelinePresetKey = keyof typeof PIPELINE_BACKTEST_PRESETS | "custom";

const ML_SWEEP_MAX_VALUES = 50;

const PIPELINE_BACKTEST_FIELDS = [
  "top_n",
  "weighting",
  "max_weight",
  "min_score",
  "max_exposure",
  "score_delay_days",
  "score_smoothing_alpha",
  "score_smoothing_carry",
  "retain_top_n",
  "market_filter",
  "market_ma_window",
  "risk_off_mode",
  "risk_off_pick",
  "risk_off_symbols",
  "risk_off_symbol",
  "max_drawdown",
  "max_drawdown_52w",
  "drawdown_recovery_ratio",
  "drawdown_exposure_floor",
  "drawdown_tiers",
  "drawdown_exposures",
  "max_turnover_week",
  "vol_target",
  "vol_window",
  "idle_allocation",
  "dynamic_exposure",
  "rebalance_frequency",
  "rebalance_day",
  "rebalance_time_minutes",
] as const;

const PIPELINE_BACKTEST_BOOLEAN_FIELDS = new Set([
  "score_smoothing_carry",
  "market_filter",
  "dynamic_exposure",
]);

const PIPELINE_BACKTEST_NUMBER_FIELDS = new Set([
  "top_n",
  "max_weight",
  "min_score",
  "max_exposure",
  "score_delay_days",
  "score_smoothing_alpha",
  "retain_top_n",
  "market_ma_window",
  "max_drawdown",
  "max_drawdown_52w",
  "drawdown_recovery_ratio",
  "drawdown_exposure_floor",
  "max_turnover_week",
  "vol_target",
  "vol_window",
  "rebalance_time_minutes",
]);

const PIPELINE_BACKTEST_DEFAULTS: Record<string, any> = {
  top_n: 36,
  weighting: "score",
  max_weight: 0.025,
  min_score: 0,
  max_exposure: 0.45,
  score_smoothing_alpha: 0.15,
  retain_top_n: 10,
  market_filter: true,
  market_ma_window: 200,
  risk_off_mode: "defensive",
  risk_off_pick: "lowest_vol",
  risk_off_symbols: "SHY,IEF,GLD,TLT",
  rebalance_frequency: "Weekly",
  rebalance_day: "Monday",
  rebalance_time_minutes: 30,
  max_drawdown: 0.15,
  max_drawdown_52w: 0.15,
  drawdown_exposure_floor: 0.0,
  drawdown_tiers: "0.08,0.12,0.15",
  drawdown_exposures: "0.80,0.60,0.40",
  idle_allocation: "defensive",
  dynamic_exposure: true,
  max_turnover_week: 0.08,
  vol_target: 0.055,
};

export default function ProjectsPage() {
  const { t, formatDateTime } = useI18n();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectTotal, setProjectTotal] = useState(0);
  const [projectPage, setProjectPage] = useState(1);
  const [projectPageSize, setProjectPageSize] = useState(10);
  const [showArchived, setShowArchived] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [projectErrorKey, setProjectErrorKey] = useState("");
  const [projectActionMessage, setProjectActionMessage] = useState("");
  const [projectActionError, setProjectActionError] = useState("");
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
  const [systemThemes, setSystemThemes] = useState<SystemThemeItem[]>([]);
  const [systemThemeMessage, setSystemThemeMessage] = useState("");
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
  const [algorithmVersionDetail, setAlgorithmVersionDetail] =
    useState<AlgorithmVersionDetail | null>(null);
  const [algorithmVersionDetailMessage, setAlgorithmVersionDetailMessage] =
    useState("");
  const [binding, setBinding] = useState<ProjectAlgorithmBinding | null>(null);
  const [bindingForm, setBindingForm] = useState({
    algorithmId: "",
    versionId: "",
    isLocked: true,
  });
  const [bindingMessage, setBindingMessage] = useState("");
  const [benchmarkMessage, setBenchmarkMessage] = useState("");
  const [mlJobs, setMlJobs] = useState<MLTrainJob[]>([]);
  const [mlJobPage, setMlJobPage] = useState(1);
  const [mlJobPageSize, setMlJobPageSize] = useState(10);
  const [mlMessage, setMlMessage] = useState("");
  const [mlLoading, setMlLoading] = useState(false);
  const [mlActionLoadingId, setMlActionLoadingId] = useState<number | null>(null);
  const [mlDetailId, setMlDetailId] = useState<number | null>(null);
  const [mlForm, setMlForm] = useState({
    device: "auto",
    trainYears: "8",
    trainStartYear: "2001",
    validMonths: "12",
    testMonths: "12",
    stepMonths: "12",
    labelHorizonDays: "5",
    walkForwardEnabled: true,
    modelType: "lgbm_ranker",
    lgbmLearningRate: "0.03",
    lgbmNumLeaves: "31",
    lgbmMinDataInLeaf: "50",
    lgbmEstimators: "150",
    lgbmSubsample: "0.8",
    lgbmColsampleBytree: "0.8",
    modelParams: "",
    sampleWeighting: "mcap_dv_mix",
    sampleWeightAlpha: "0.6",
    sampleWeightDvWindowDays: "20",
    pitMissingPolicy: "drop",
    pitSampleOnSnapshot: false,
    pitMinCoverage: "0.05",
    symbolSource: "project",
    systemThemeKey: "",
  });
  const [mlSweep, setMlSweep] = useState({
    paramKey: "learning_rate",
    start: "0.03",
    end: "0.07",
    step: "0.005",
    includeEnd: true,
  });
  const [mlSweepMessage, setMlSweepMessage] = useState("");
  const [mlSweepLoading, setMlSweepLoading] = useState(false);
  const [pipelines, setPipelines] = useState<MLPipeline[]>([]);
  const [pipelineDetailId, setPipelineDetailId] = useState<number | null>(null);
  const [pipelineDetail, setPipelineDetail] = useState<MLPipelineDetail | null>(null);
  const [pipelineMessage, setPipelineMessage] = useState("");
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [pipelineSort, setPipelineSort] = useState("id_desc");
  const [pipelineForm, setPipelineForm] = useState({
    name: "",
    notes: "",
    autoCreate: true,
  });
  const [pipelineBacktestPreset, setPipelineBacktestPreset] =
    useState<PipelinePresetKey>("E35");
  const [pipelineBacktestParams, setPipelineBacktestParams] = useState<
    Record<string, any>
  >({});
  const [pipelineBacktestMessage, setPipelineBacktestMessage] = useState("");
  const [pipelineBacktestSaving, setPipelineBacktestSaving] = useState(false);
  const [pipelineBacktestRunning, setPipelineBacktestRunning] = useState(false);
  const [pipelineBacktestRunMessage, setPipelineBacktestRunMessage] = useState("");
  const [activePipelineId, setActivePipelineId] = useState<number | null>(null);
  const [decisionLatest, setDecisionLatest] = useState<DecisionSnapshotDetail | null>(null);
  const [decisionPreview, setDecisionPreview] = useState<DecisionSnapshotDetail | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionMode, setDecisionMode] = useState<"selected" | "filtered">("selected");
  const [decisionTrainJobId, setDecisionTrainJobId] = useState<string>("");
  const [decisionSnapshotDate, setDecisionSnapshotDate] = useState("");
  const [decisionMessage, setDecisionMessage] = useState("");
  const decisionPollRef = useRef(0);
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
  const lockedSymbolTypeOptions = symbolTypeOptions.filter(
    (option) => option.value === "STOCK"
  );

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
      params: {
        page: nextPage,
        page_size: nextSize,
        include_archived: showArchived,
      },
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
      const items = [...res.data].sort((a, b) => b.id - a.id);
      setLatestBacktest(items[0] || null);
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

  const loadSystemThemes = async () => {
    try {
      const res = await api.get<SystemThemePage>("/api/system-themes", {
        params: { page: 1, page_size: 200 },
      });
      const items = res.data.items || [];
      setSystemThemes(items);
      setSystemThemeMessage("");
      if (items.length) {
        const preferred = items.find((item) => item.key === "DATA_COMPLETE") || items[0];
        setMlForm((prev) => {
          if (prev.systemThemeKey) {
            return prev;
          }
          return { ...prev, systemThemeKey: preferred.key };
        });
      }
    } catch (err) {
      setSystemThemes([]);
      setSystemThemeMessage(t("projects.ml.systemThemeError"));
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

  const loadAlgorithmVersionDetail = async (algorithmId: number, versionId: number) => {
    try {
      setAlgorithmVersionDetailMessage("");
      const res = await api.get<AlgorithmVersionDetail>(
        `/api/algorithms/${algorithmId}/versions/${versionId}`
      );
      setAlgorithmVersionDetail(res.data);
    } catch (err) {
      setAlgorithmVersionDetail(null);
      setAlgorithmVersionDetailMessage(t("projects.algorithm.summaryError"));
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
      setMlJobPage(1);
      setMlMessage("");
    } catch (err) {
      setMlJobs([]);
      setMlJobPage(1);
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

  const loadPipelines = async (projectId: number) => {
    try {
      const res = await api.get<MLPipeline[]>("/api/ml/pipelines", {
        params: { project_id: projectId },
      });
      setPipelines(res.data || []);
      setPipelineMessage("");
    } catch (err) {
      setPipelines([]);
      setPipelineMessage(t("projects.pipeline.error"));
    }
  };

  const loadDecisionLatest = async (projectId: number) => {
    try {
      const res = await api.get<DecisionSnapshotDetail>("/api/decisions/latest", {
        params: { project_id: projectId },
      });
      setDecisionLatest(res.data);
      setDecisionMessage("");
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setDecisionLatest(null);
        return;
      }
      setDecisionLatest(null);
      setDecisionMessage(t("projects.decision.loadError"));
    }
  };

  const fetchDecisionSnapshot = async (snapshotId: number) => {
    if (!Number.isFinite(snapshotId)) {
      return null;
    }
    try {
      const res = await api.get<DecisionSnapshotDetail>(`/api/decisions/${snapshotId}`);
      return res.data;
    } catch {
      return null;
    }
  };

  const isDecisionSnapshotReady = (snapshot: DecisionSnapshotDetail | null) => {
    if (!snapshot) {
      return false;
    }
    if (snapshot.status === "failed") {
      return true;
    }
    const summary = (snapshot.summary as Record<string, any> | null) || null;
    return Boolean(summary?.snapshot_date || snapshot.snapshot_date);
  };

  const pollDecisionSnapshot = async (snapshotId: number, pollToken: number) => {
    const maxAttempts = 30;
    const intervalMs = 2000;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      if (decisionPollRef.current !== pollToken) {
        return null;
      }
      const detail = await fetchDecisionSnapshot(snapshotId);
      if (detail) {
        setDecisionLatest(detail);
        if (isDecisionSnapshotReady(detail)) {
          return detail;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    return null;
  };

  const buildDecisionPayload = () => {
    const trainJobId = decisionTrainJobId
      ? Number(decisionTrainJobId)
      : mlActiveJob?.id;
    const payload: Record<string, any> = {
      project_id: selectedProjectId,
      pipeline_id: activePipelineId ?? undefined,
      algorithm_parameters: buildPipelineBacktestAlgorithmParams(),
    };
    if (trainJobId) {
      payload.train_job_id = trainJobId;
    }
    if (decisionSnapshotDate) {
      payload.snapshot_date = decisionSnapshotDate;
    }
    return payload;
  };

  const previewDecisionSnapshot = async () => {
    if (!selectedProjectId) {
      return;
    }
    setDecisionLoading(true);
    setDecisionMessage("");
    try {
      const payload = buildDecisionPayload();
      const res = await api.post<DecisionSnapshotDetail>(
        "/api/decisions/preview",
        payload,
        { timeout: 120000 }
      );
      setDecisionPreview(res.data);
      setDecisionMessage(t("projects.decision.previewReady"));
    } catch (err) {
      setDecisionMessage(t("projects.decision.previewError"));
    } finally {
      setDecisionLoading(false);
    }
  };

  const runDecisionSnapshot = async () => {
    if (!selectedProjectId) {
      return;
    }
    setDecisionLoading(true);
    setDecisionMessage("");
    try {
      const payload = buildDecisionPayload();
      const res = await api.post<DecisionSnapshotDetail>("/api/decisions/run", payload);
      const snapshotId = res.data?.id ? Number(res.data.id) : null;
      setDecisionMessage(t("projects.decision.runQueued"));
      setDecisionPreview(null);
      if (snapshotId) {
        const pollToken = decisionPollRef.current + 1;
        decisionPollRef.current = pollToken;
        const detail = await pollDecisionSnapshot(snapshotId, pollToken);
        if (detail?.status === "failed") {
          setDecisionMessage(t("projects.decision.runError"));
        }
      } else {
        await loadDecisionLatest(selectedProjectId);
      }
    } catch (err) {
      setDecisionMessage(t("projects.decision.runError"));
    } finally {
      setDecisionLoading(false);
    }
  };

  const fetchPipelineDetail = async (pipelineId: unknown) => {
    const id = typeof pipelineId === "number" ? pipelineId : Number(pipelineId);
    if (!Number.isFinite(id)) {
      return null;
    }
    try {
      const res = await api.get<MLPipelineDetail>(`/api/ml/pipelines/${id}`);
      return res.data || null;
    } catch (err) {
      return null;
    }
  };

  const loadPipelineDetail = async (pipelineId: unknown) => {
    const detail = await fetchPipelineDetail(pipelineId);
    setPipelineDetail(detail);
    return detail;
  };

  const createPipeline = async (
    payload?: Record<string, unknown>,
    nameOverride?: string
  ) => {
    if (!selectedProjectId) {
      return null;
    }
    setPipelineLoading(true);
    setPipelineMessage("");
    try {
      const res = await api.post<MLPipeline>("/api/ml/pipelines", {
        project_id: selectedProjectId,
        name: nameOverride || pipelineForm.name || undefined,
        notes: pipelineForm.notes || undefined,
        params: payload,
      });
      await loadPipelines(selectedProjectId);
      setPipelineMessage(t("projects.pipeline.created"));
      return res.data;
    } catch (err) {
      setPipelineMessage(t("projects.pipeline.error"));
      return null;
    } finally {
      setPipelineLoading(false);
    }
  };

  const updatePipeline = async (
    pipelineId: number,
    payload: Record<string, unknown>
  ) => {
    try {
      const res = await api.patch<MLPipeline>(`/api/ml/pipelines/${pipelineId}`, payload);
      if (selectedProjectId) {
        await loadPipelines(selectedProjectId);
      }
      await loadPipelineDetail(pipelineId);
      return res.data;
    } catch (err) {
      return null;
    }
  };

  const savePipelineBacktestParams = async (pipelineIdOverride?: number | unknown) => {
    if (!configDraft) {
      setPipelineBacktestMessage(t("projects.pipeline.backtest.saveError"));
      return false;
    }
    const pipelineId =
      typeof pipelineIdOverride === "number" && Number.isFinite(pipelineIdOverride)
        ? pipelineIdOverride
        : undefined;
    setPipelineBacktestSaving(true);
    setPipelineBacktestMessage("");
    const algorithmParams = buildPipelineBacktestAlgorithmParams();
    const nextConfig: ProjectConfig = {
      ...configDraft,
      backtest_params: algorithmParams,
    };
    const configOk = await persistProjectConfig(undefined, undefined, false, nextConfig);
    let pipelineOk = true;
    let pipelineTarget: MLPipeline | MLPipelineDetail | null = null;
    if (pipelineId) {
      if (pipelineEditor?.id === pipelineId) {
        pipelineTarget = pipelineEditor;
      } else {
        pipelineTarget =
          pipelines.find((item) => item.id === pipelineId) || null;
      }
      if (!pipelineTarget) {
        pipelineTarget = await fetchPipelineDetail(pipelineId);
      }
    } else {
      pipelineTarget = pipelineEditor;
    }
    if (pipelineId && !pipelineTarget) {
      pipelineOk = false;
    }
    if (pipelineTarget?.id) {
      const baseParams =
        (pipelineTarget.params as Record<string, any> | null | undefined) ?? {};
      const nextBacktest = {
        ...(typeof baseParams.backtest === "object" ? baseParams.backtest : {}),
        preset: pipelineBacktestPreset,
        algorithm_parameters: algorithmParams,
      };
      const nextParams = { ...baseParams, backtest: nextBacktest };
      const updated = await updatePipeline(pipelineTarget.id, { params: nextParams });
      pipelineOk = !!updated;
    }
    if (!configOk || !pipelineOk) {
      setPipelineBacktestMessage(t("projects.pipeline.backtest.saveError"));
    } else {
      setPipelineBacktestMessage(t("projects.pipeline.backtest.saved"));
    }
    setPipelineBacktestSaving(false);
    return configOk && pipelineOk;
  };

  const enqueuePipelineBacktest = async (
    pipelineId: number,
    trainJob?: MLTrainJob
  ) => {
    const algorithmParams = buildPipelineBacktestAlgorithmParams();
    if (trainJob) {
      const outputScorePath = trainJob.output_dir
        ? `${trainJob.output_dir}/scores.csv`
        : "";
      const scorePath = outputScorePath || trainJob.scores_path || "";
      if (scorePath && !algorithmParams.score_csv_path) {
        algorithmParams.score_csv_path = scorePath;
      }
    }
    const params: Record<string, any> = {
      preset: pipelineBacktestPreset,
      algorithm_parameters: algorithmParams,
    };
    if (trainJob) {
      params.pipeline_train_job_id = trainJob.id;
    }
    const res = await api.post<BacktestRun>("/api/backtests", {
      project_id: selectedProjectId,
      pipeline_id: pipelineId,
      params,
    });
    setLatestBacktest(res.data || null);
    return res.data || null;
  };

  const runPipelineBacktest = async (options?: {
    saveTemplate?: boolean;
    trainJob?: MLTrainJob;
  }) => {
    if (!selectedProjectId) {
      return;
    }
    const pipelineId = pipelineEditor?.id ?? activePipelineId ?? null;
    if (!pipelineId) {
      setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runMissingPipeline"));
      return;
    }
    setPipelineBacktestRunning(true);
    setPipelineBacktestRunMessage("");
    try {
      if (options?.saveTemplate) {
        const ok = await savePipelineBacktestParams();
        if (!ok) {
          setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runError"));
          setPipelineBacktestRunning(false);
          return;
        }
      }
      await enqueuePipelineBacktest(pipelineId, options?.trainJob);
      setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runQueued"));
      await loadPipelineDetail(pipelineId);
      scheduleBacktestRefresh(selectedProjectId);
    } catch (err) {
      setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runError"));
    } finally {
      setPipelineBacktestRunning(false);
    }
  };

  const runPipelineBacktestsForActive = async (options?: { saveTemplate?: boolean }) => {
    if (!selectedProjectId) {
      return;
    }
    const pipelineId = activePipelineId ?? null;
    if (!pipelineId) {
      setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runMissingPipeline"));
      return;
    }
    setPipelineBacktestRunning(true);
    setPipelineBacktestRunMessage("");
    try {
      if (options?.saveTemplate) {
        const ok = await savePipelineBacktestParams(pipelineId);
        if (!ok) {
          setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runError"));
          setPipelineBacktestRunning(false);
          return;
        }
      }
      const detail =
        pipelineDetail?.id === pipelineId
          ? pipelineDetail
          : await fetchPipelineDetail(pipelineId);
      const trainJobs =
        detail?.train_jobs?.filter((job) => job.status === "success") ?? [];
      if (!trainJobs.length) {
        setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runNoTrainJobs"));
        return;
      }
      for (const job of trainJobs) {
        await enqueuePipelineBacktest(pipelineId, job);
      }
      setPipelineBacktestRunMessage(
        t("projects.pipeline.backtest.runQueuedBatch", { count: trainJobs.length })
      );
      if (pipelineDetailId === pipelineId) {
        await loadPipelineDetail(pipelineId);
      }
      scheduleBacktestRefresh(selectedProjectId);
    } catch (err) {
      setPipelineBacktestRunMessage(t("projects.pipeline.backtest.runError"));
    } finally {
      setPipelineBacktestRunning(false);
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
    const modelParams = buildModelParams(setMlMessage);
    if (modelParams === null) {
      return;
    }
    if (mlForm.symbolSource === "system_theme" && !mlForm.systemThemeKey) {
      setMlMessage(t("projects.ml.systemThemeRequired"));
      return;
    }
    const walkForwardEnabled = !!mlForm.walkForwardEnabled;
    setMlLoading(true);
    setMlMessage("");
    try {
      let pipelineId = activePipelineId;
      if (!pipelineId && pipelineForm.autoCreate) {
        const timestamp = new Date().toISOString().slice(0, 19).replace("T", " ");
        const autoName = `${mlForm.modelType}-${mlForm.trainYears || "?"}Y-${timestamp}`;
        const pipelineParams = {
          source: "ml_train",
          train: {
            device: mlForm.device,
            train_years: toNumber(mlForm.trainYears),
            train_start_year: toNumber(mlForm.trainStartYear),
            valid_months: toNumber(mlForm.validMonths),
            test_months: walkForwardEnabled ? toNumber(mlForm.testMonths) : 0,
            step_months: walkForwardEnabled ? toNumber(mlForm.stepMonths) : 0,
            label_horizon_days: toNumber(mlForm.labelHorizonDays),
            sample_weighting: mlForm.sampleWeighting,
            sample_weight_alpha: toNumber(mlForm.sampleWeightAlpha),
            sample_weight_dv_window_days: toNumber(mlForm.sampleWeightDvWindowDays),
            pit_missing_policy: mlForm.pitMissingPolicy,
            pit_sample_on_snapshot: mlForm.pitSampleOnSnapshot,
            pit_min_coverage: toNumber(mlForm.pitMinCoverage),
            symbol_source: mlForm.symbolSource,
            system_theme_key:
              mlForm.symbolSource === "system_theme" ? mlForm.systemThemeKey : undefined,
          },
          model: {
            model_type: mlForm.modelType,
            model_params: modelParams || null,
          },
          ...buildPipelineBacktestPayload(),
        };
        const created = await createPipeline(pipelineParams, autoName);
        pipelineId = created?.id ?? null;
        if (pipelineId) {
          setActivePipelineId(pipelineId);
          setPipelineDetailId(pipelineId);
        }
      }
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
        sample_weighting: mlForm.sampleWeighting,
        sample_weight_alpha: toNumber(mlForm.sampleWeightAlpha),
        sample_weight_dv_window_days: toNumber(mlForm.sampleWeightDvWindowDays),
        pit_missing_policy: mlForm.pitMissingPolicy,
        pit_sample_on_snapshot: mlForm.pitSampleOnSnapshot,
        pit_min_coverage: toNumber(mlForm.pitMinCoverage),
        symbol_source: mlForm.symbolSource,
        system_theme_key:
          mlForm.symbolSource === "system_theme" ? mlForm.systemThemeKey : undefined,
        pipeline_id: pipelineId || undefined,
      });
      await loadMlJobs(selectedProjectId);
      await loadPipelines(selectedProjectId);
      setMlMessage(t("projects.ml.queued"));
    } catch (err) {
      setMlMessage(t("projects.ml.error"));
    } finally {
      setMlLoading(false);
    }
  };

  const createMlSweepJobs = async () => {
    if (!selectedProjectId) {
      return;
    }
    const paramKey = mlSweep.paramKey.trim();
    if (!paramKey) {
      setMlSweepMessage(t("projects.ml.sweep.paramRequired"));
      return;
    }
    if (pipelineBacktestPreset !== "E35") {
      setMlSweepMessage(
        t("projects.ml.sweep.backtestMismatch", { preset: pipelineBacktestPreset })
      );
      return;
    }
    if (mlSweepPreview.error || mlSweepPreview.values.length === 0) {
      setMlSweepMessage(
        mlSweepPreview.error || t("projects.ml.sweep.rangeError")
      );
      return;
    }
    const modelParams = buildModelParams(setMlSweepMessage);
    if (modelParams === null) {
      return;
    }
    if (mlForm.symbolSource === "system_theme" && !mlForm.systemThemeKey) {
      setMlSweepMessage(t("projects.ml.systemThemeRequired"));
      return;
    }
    const toNumber = (value: string) => {
      if (!value.trim()) {
        return undefined;
      }
      const num = Number(value);
      return Number.isFinite(num) ? num : undefined;
    };
    const walkForwardEnabled = !!mlForm.walkForwardEnabled;
    const ensurePipelineBacktest = (params: Record<string, any>) => {
      const hasBacktest = params && typeof params.backtest === "object";
      if (hasBacktest) {
        return params;
      }
      return { ...params, ...buildPipelineBacktestPayload() };
    };
    const sweepPayload = {
      param_key: paramKey,
      start: Number(mlSweep.start),
      end: Number(mlSweep.end),
      step: Number(mlSweep.step),
      include_end: mlSweep.includeEnd,
      values: mlSweepPreview.values,
    };
    setMlSweepLoading(true);
    setMlSweepMessage("");
    try {
      let pipelineId = activePipelineId;
      let pipelineParamsForUpdate: Record<string, any> | null = null;
      if (!pipelineId && pipelineForm.autoCreate) {
        const timestamp = new Date().toISOString().slice(0, 19).replace("T", " ");
        const autoName = `${mlForm.modelType}-${paramKey}-sweep-${timestamp}`;
        const pipelineParams = {
          source: "ml_train",
          train: {
            device: mlForm.device,
            train_years: toNumber(mlForm.trainYears),
            train_start_year: toNumber(mlForm.trainStartYear),
            valid_months: toNumber(mlForm.validMonths),
            test_months: walkForwardEnabled ? toNumber(mlForm.testMonths) : 0,
            step_months: walkForwardEnabled ? toNumber(mlForm.stepMonths) : 0,
            label_horizon_days: toNumber(mlForm.labelHorizonDays),
            sample_weighting: mlForm.sampleWeighting,
            sample_weight_alpha: toNumber(mlForm.sampleWeightAlpha),
            sample_weight_dv_window_days: toNumber(mlForm.sampleWeightDvWindowDays),
            pit_missing_policy: mlForm.pitMissingPolicy,
            pit_sample_on_snapshot: mlForm.pitSampleOnSnapshot,
            pit_min_coverage: toNumber(mlForm.pitMinCoverage),
            symbol_source: mlForm.symbolSource,
            system_theme_key:
              mlForm.symbolSource === "system_theme" ? mlForm.systemThemeKey : undefined,
          },
          model: {
            model_type: mlForm.modelType,
            model_params: modelParams || null,
          },
          train_sweep: sweepPayload,
          auto_backtest: true,
          ...buildPipelineBacktestPayload(),
        };
        const created = await createPipeline(pipelineParams, autoName);
        pipelineId = created?.id ?? null;
        pipelineParamsForUpdate = pipelineParams;
        if (pipelineId) {
          setActivePipelineId(pipelineId);
          setPipelineDetailId(pipelineId);
        }
      }
      if (!pipelineId) {
        setMlSweepMessage(t("projects.ml.sweep.pipelineRequired"));
        return;
      }
      const baseParams =
        pipelineParamsForUpdate ??
        (pipelineDetail?.params as Record<string, any> | null | undefined) ??
        (activePipeline?.params as Record<string, any> | null | undefined) ??
        {};
      const nextParams = ensurePipelineBacktest({
        ...baseParams,
        train_sweep: sweepPayload,
        auto_backtest: true,
      });
      await updatePipeline(pipelineId, { params: nextParams });
      let createdCount = 0;
      for (const value of mlSweepPreview.values) {
        const mergedParams = { ...(modelParams || {}), [paramKey]: value };
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
          model_params: mergedParams,
          sample_weighting: mlForm.sampleWeighting,
          sample_weight_alpha: toNumber(mlForm.sampleWeightAlpha),
          sample_weight_dv_window_days: toNumber(mlForm.sampleWeightDvWindowDays),
          pit_missing_policy: mlForm.pitMissingPolicy,
          pit_sample_on_snapshot: mlForm.pitSampleOnSnapshot,
          pit_min_coverage: toNumber(mlForm.pitMinCoverage),
          symbol_source: mlForm.symbolSource,
          system_theme_key:
            mlForm.symbolSource === "system_theme" ? mlForm.systemThemeKey : undefined,
          pipeline_id: pipelineId || undefined,
        });
        createdCount += 1;
        setMlSweepMessage(
          t("projects.ml.sweep.progress", {
            current: createdCount,
            total: mlSweepPreview.values.length,
          })
        );
      }
      await loadMlJobs(selectedProjectId);
      await loadPipelines(selectedProjectId);
      setMlSweepMessage(
        t("projects.ml.sweep.queued", { count: mlSweepPreview.values.length })
      );
    } catch (err) {
      setMlSweepMessage(t("projects.ml.sweep.error"));
    } finally {
      setMlSweepLoading(false);
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
  }, [projectPage, projectPageSize, showArchived]);

  useEffect(() => {
    loadAlgorithms();
    loadSystemThemes();
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
      loadPipelines(selectedProjectId);
      loadDecisionLatest(selectedProjectId);
      setConfigMessage("");
      setDataMessage("");
      setBacktestMessage("");
      setBenchmarkMessage("");
      setBindingMessage("");
      setProjectActionMessage("");
      setProjectActionError("");
      setNewThemeSymbol("");
      setNewThemeSymbolType("STOCK");
      setThemeSymbolMessage("");
      setDecisionPreview(null);
      setDecisionMessage("");
      setDecisionSnapshotDate("");
      setDecisionMode("selected");
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
      setPipelines([]);
      setPipelineDetail(null);
      setPipelineDetailId(null);
      setActivePipelineId(null);
      setNewThemeSymbol("");
      setNewThemeSymbolType("STOCK");
      setThemeSymbolMessage("");
      setBenchmarkMessage("");
      setDecisionLatest(null);
      setDecisionPreview(null);
      setDecisionMessage("");
      setDecisionSnapshotDate("");
      setDecisionTrainJobId("");
      setDecisionMode("selected");
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
    if (!pipelineDetailId) {
      setPipelineDetail(null);
      return;
    }
    loadPipelineDetail(pipelineDetailId);
  }, [pipelineDetailId]);

  useEffect(() => {
    const selectedId = Number(bindingForm.algorithmId);
    if (selectedId) {
      loadAlgorithmVersions(selectedId);
    } else {
      setAlgorithmVersions([]);
    }
  }, [bindingForm.algorithmId]);

  useEffect(() => {
    const algoId = Number(bindingForm.algorithmId || binding?.algorithm_id || 0);
    const versionId = Number(bindingForm.versionId || binding?.algorithm_version_id || 0);
    if (algoId && versionId) {
      loadAlgorithmVersionDetail(algoId, versionId);
    } else {
      setAlgorithmVersionDetail(null);
      setAlgorithmVersionDetailMessage("");
    }
  }, [
    bindingForm.algorithmId,
    bindingForm.versionId,
    binding?.algorithm_id,
    binding?.algorithm_version_id,
  ]);

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
    setProjectActionMessage("");
    setProjectActionError("");
    await api.post("/api/projects", { name, description });
    setName("");
    setDescription("");
    setProjectPage(1);
    loadProjects(1, projectPageSize);
  };

  const archiveProject = async (project: Project) => {
    const confirmText = t("projects.detail.archiveConfirm", { name: project.name });
    if (!window.confirm(confirmText)) {
      return;
    }
    setProjectActionMessage("");
    setProjectActionError("");
    try {
      await api.post(`/api/projects/${project.id}/archive`);
      setProjectActionMessage(t("projects.detail.archiveSuccess"));
      setProjectPage(1);
      await loadProjects(1, projectPageSize);
    } catch (err) {
      setProjectActionError(t("projects.detail.archiveError"));
    }
  };

  const restoreProject = async (project: Project) => {
    const confirmText = t("projects.detail.restoreConfirm", { name: project.name });
    if (!window.confirm(confirmText)) {
      return;
    }
    setProjectActionMessage("");
    setProjectActionError("");
    try {
      await api.post(`/api/projects/${project.id}/restore`);
      setProjectActionMessage(t("projects.detail.restoreSuccess"));
      await loadProjects(projectPage, projectPageSize);
    } catch (err) {
      setProjectActionError(t("projects.detail.restoreError"));
    }
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

  const updateBacktestTrainJobId = (value: string) => {
    const cleaned = value.trim();
    const numeric = cleaned ? Number(cleaned) : NaN;
    setConfigDraft((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        backtest_train_job_id: Number.isFinite(numeric) ? numeric : null,
      };
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
    silent?: boolean,
    configOverride?: ProjectConfig
  ) => {
    const baseConfig = configOverride ?? configDraft;
    if (!selectedProjectId || !baseConfig) {
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
      ...baseConfig,
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
        await loadPipelines(selectedProjectId);
        if (pipelineDetailId) {
          await loadPipelineDetail(pipelineDetailId);
        }
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
      const params: Record<string, any> = {};
      if (backtestTrainJobId) {
        params.pipeline_train_job_id = backtestTrainJobId;
      }
      const payload: Record<string, any> = {
        project_id: selectedProjectId,
        pipeline_id: activePipelineId || undefined,
      };
      if (Object.keys(params).length) {
        payload.params = params;
      }
      const res = await api.post<BacktestRun>("/api/backtests", payload);
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
  const mlJobTotal = mlJobs.length;
  const mlJobsPaged = useMemo(() => {
    const start = (mlJobPage - 1) * mlJobPageSize;
    return mlJobs.slice(start, start + mlJobPageSize);
  }, [mlJobs, mlJobPage, mlJobPageSize]);
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(mlJobTotal / mlJobPageSize));
    if (mlJobPage > maxPage) {
      setMlJobPage(maxPage);
    }
  }, [mlJobPage, mlJobPageSize, mlJobTotal]);
  useEffect(() => {
    if (!decisionTrainJobId && mlActiveJob?.id) {
      setDecisionTrainJobId(String(mlActiveJob.id));
    }
  }, [decisionTrainJobId, mlActiveJob]);
  const mlDetailMetrics = useMemo(
    () => (mlDetailJob?.metrics as Record<string, any> | null) || null,
    [mlDetailJob]
  );
  const mlDetailSymbolSource = useMemo(() => {
    const meta = (mlDetailJob?.config as Record<string, any> | null)?.meta || {};
    return {
      source: String(meta.symbol_source || "project"),
      key: meta.symbol_source_key ? String(meta.symbol_source_key) : "",
    };
  }, [mlDetailJob]);
  const mlCurve = useMemo(() => extractMlCurve(mlDetailMetrics), [mlDetailMetrics]);
  const mlCurveMetric = useMemo(
    () => extractCurveMetricName(mlDetailMetrics),
    [mlDetailMetrics]
  );
  const mlBestScore = useMemo(() => {
    const direct = extractMetricValue(
      mlDetailMetrics?.best_score ?? mlDetailMetrics?.bestScore
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "best_score");
  }, [mlDetailMetrics]);
  const mlBestLoss = useMemo(() => {
    const direct = extractMetricValue(
      mlDetailMetrics?.best_loss ?? mlDetailMetrics?.bestLoss
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "best_loss");
  }, [mlDetailMetrics]);
  const mlBestIteration = useMemo(() => {
    const direct = extractMetricValue(
      mlDetailMetrics?.best_iteration ?? mlDetailMetrics?.bestIteration
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "best_iteration");
  }, [mlDetailMetrics]);
  const mlQualityScore = useMemo(() => {
    const direct = extractMetricValue(
      (mlDetailMetrics as Record<string, any> | null)?.quality_score ??
        (mlDetailMetrics as Record<string, any> | null)?.qualityScore
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "quality_score");
  }, [mlDetailMetrics]);
  const mlCurveGap = useMemo(() => {
    const direct = extractMetricValue(
      (mlDetailMetrics as Record<string, any> | null)?.curve_gap ??
        (mlDetailMetrics as Record<string, any> | null)?.curveGap
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "curve_gap");
  }, [mlDetailMetrics]);
  const mlNdcg10 = useMemo(() => {
    const direct = extractMetricValue(
      (mlDetailMetrics as Record<string, any> | null)?.ndcg_at_10 ??
        (mlDetailMetrics as Record<string, any> | null)?.ndcgAt10
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "ndcg_at_10");
  }, [mlDetailMetrics]);
  const mlNdcg50 = useMemo(() => {
    const direct = extractMetricValue(
      (mlDetailMetrics as Record<string, any> | null)?.ndcg_at_50 ??
        (mlDetailMetrics as Record<string, any> | null)?.ndcgAt50
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "ndcg_at_50");
  }, [mlDetailMetrics]);
  const mlNdcg100 = useMemo(() => {
    const direct = extractMetricValue(
      (mlDetailMetrics as Record<string, any> | null)?.ndcg_at_100 ??
        (mlDetailMetrics as Record<string, any> | null)?.ndcgAt100
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "ndcg_at_100");
  }, [mlDetailMetrics]);
  const mlIC = useMemo(() => {
    const direct = extractMetricValue(
      (mlDetailMetrics as Record<string, any> | null)?.ic
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "ic");
  }, [mlDetailMetrics]);
  const mlRankIC = useMemo(() => {
    const direct = extractMetricValue(
      (mlDetailMetrics as Record<string, any> | null)?.rank_ic ??
        (mlDetailMetrics as Record<string, any> | null)?.rankIc
    );
    return direct ?? extractWindowMetric(mlDetailMetrics, "rank_ic");
  }, [mlDetailMetrics]);
  const activePipeline = useMemo(
    () => pipelines.find((item) => item.id === activePipelineId) || null,
    [pipelines, activePipelineId]
  );
  const pipelineEditor = useMemo(
    () => pipelineDetail || activePipeline || null,
    [pipelineDetail, activePipeline]
  );
  const sortedPipelines = useMemo(() => {
    const items = [...pipelines];
    const scoreValue = (value?: number | null) =>
      typeof value === "number" && Number.isFinite(value) ? value : -Infinity;
    if (pipelineSort === "id_desc") {
      return items.sort((a, b) => (b.id || 0) - (a.id || 0));
    }
    if (pipelineSort === "train_desc") {
      return items.sort((a, b) => scoreValue(b.best_train_score) - scoreValue(a.best_train_score));
    }
    if (pipelineSort === "backtest_desc") {
      return items.sort(
        (a, b) => scoreValue(b.best_backtest_score) - scoreValue(a.best_backtest_score)
      );
    }
    if (pipelineSort === "created_asc") {
      return items.sort(
        (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
    }
    return items.sort(
      (a, b) => scoreValue(b.combined_score) - scoreValue(a.combined_score)
    );
  }, [pipelines, pipelineSort]);

  const pipelineBacktestSummary = useMemo(() => {
    const params = pipelineDetail?.params as Record<string, any> | null | undefined;
    if (!params || typeof params !== "object") {
      return [];
    }
    const backtest = params.backtest as Record<string, any> | undefined;
    const algoParams =
      backtest?.algorithm_parameters ||
      (params.algorithm_parameters as Record<string, any> | undefined);
    if (!algoParams || typeof algoParams !== "object") {
      return [];
    }
    const entries = [
      { key: "preset", label: t("projects.pipeline.backtest.preset"), value: backtest?.preset },
      { key: "top_n", label: t("projects.pipeline.backtest.fields.topN"), value: algoParams.top_n },
      { key: "weighting", label: t("projects.pipeline.backtest.fields.weighting"), value: algoParams.weighting },
      { key: "max_weight", label: t("projects.pipeline.backtest.fields.maxWeight"), value: algoParams.max_weight },
      { key: "min_score", label: t("projects.pipeline.backtest.fields.minScore"), value: algoParams.min_score },
      { key: "max_exposure", label: t("projects.pipeline.backtest.fields.maxExposure"), value: algoParams.max_exposure },
      { key: "score_delay_days", label: t("projects.pipeline.backtest.fields.scoreDelay"), value: algoParams.score_delay_days },
      { key: "score_smoothing_alpha", label: t("projects.pipeline.backtest.fields.scoreSmoothingAlpha"), value: algoParams.score_smoothing_alpha },
      { key: "score_smoothing_carry", label: t("projects.pipeline.backtest.fields.scoreSmoothingCarry"), value: algoParams.score_smoothing_carry },
      { key: "retain_top_n", label: t("projects.pipeline.backtest.fields.retainTopN"), value: algoParams.retain_top_n },
      { key: "market_filter", label: t("projects.pipeline.backtest.fields.marketFilter"), value: algoParams.market_filter },
      { key: "market_ma_window", label: t("projects.pipeline.backtest.fields.marketMa"), value: algoParams.market_ma_window },
      { key: "risk_off_mode", label: t("projects.pipeline.backtest.fields.riskOffMode"), value: algoParams.risk_off_mode },
      { key: "risk_off_pick", label: t("projects.pipeline.backtest.fields.riskOffPick"), value: algoParams.risk_off_pick },
      { key: "risk_off_symbols", label: t("projects.pipeline.backtest.fields.riskOffSymbols"), value: algoParams.risk_off_symbols },
      { key: "risk_off_symbol", label: t("projects.pipeline.backtest.fields.riskOffSymbol"), value: algoParams.risk_off_symbol },
      { key: "max_drawdown", label: t("projects.pipeline.backtest.fields.maxDrawdown"), value: algoParams.max_drawdown },
      { key: "max_drawdown_52w", label: t("projects.pipeline.backtest.fields.maxDrawdown52w"), value: algoParams.max_drawdown_52w },
      { key: "drawdown_recovery_ratio", label: t("projects.pipeline.backtest.fields.drawdownRecovery"), value: algoParams.drawdown_recovery_ratio },
      { key: "drawdown_exposure_floor", label: t("projects.pipeline.backtest.fields.drawdownExposureFloor"), value: algoParams.drawdown_exposure_floor },
      { key: "drawdown_tiers", label: t("projects.pipeline.backtest.fields.drawdownTiers"), value: algoParams.drawdown_tiers },
      { key: "drawdown_exposures", label: t("projects.pipeline.backtest.fields.drawdownExposures"), value: algoParams.drawdown_exposures },
      { key: "max_turnover_week", label: t("projects.pipeline.backtest.fields.maxTurnoverWeek"), value: algoParams.max_turnover_week },
      { key: "vol_target", label: t("projects.pipeline.backtest.fields.volTarget"), value: algoParams.vol_target },
      { key: "vol_window", label: t("projects.pipeline.backtest.fields.volWindow"), value: algoParams.vol_window },
      { key: "idle_allocation", label: t("projects.pipeline.backtest.fields.idleAllocation"), value: algoParams.idle_allocation },
      { key: "dynamic_exposure", label: t("projects.pipeline.backtest.fields.dynamicExposure"), value: algoParams.dynamic_exposure },
      { key: "rebalance_frequency", label: t("projects.pipeline.backtest.fields.rebalanceFreq"), value: algoParams.rebalance_frequency },
      { key: "rebalance_day", label: t("projects.pipeline.backtest.fields.rebalanceDay"), value: algoParams.rebalance_day },
      { key: "rebalance_time_minutes", label: t("projects.pipeline.backtest.fields.rebalanceTime"), value: algoParams.rebalance_time_minutes },
    ];
    return entries.filter((item) => item.value !== undefined && item.value !== null && item.value !== "");
  }, [pipelineDetail, t]);

  const decisionData = decisionPreview || decisionLatest;
  const decisionSummary = useMemo(
    () => (decisionData?.summary as Record<string, any> | null) || null,
    [decisionData]
  );
  const decisionItems = useMemo(() => {
    if (!decisionData) {
      return [];
    }
    return decisionMode === "filtered"
      ? decisionData.filters || []
      : decisionData.items || [];
  }, [decisionData, decisionMode]);
  const toYahooSymbol = (symbol: string) => {
    const trimmed = symbol.trim().toUpperCase();
    const parts = trimmed.split(".");
    if (parts.length === 2 && parts[1].length === 1) {
      return `${parts[0]}-${parts[1]}`;
    }
    return trimmed;
  };
  const buildYahooUrl = (symbol: string) =>
    `https://finance.yahoo.com/quote/${encodeURIComponent(toYahooSymbol(symbol))}`;
  const decisionFilterCounts = useMemo(() => {
    const raw = (decisionSummary?.filter_counts as Record<string, number> | null) || {};
    return Object.entries(raw)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);
  }, [decisionSummary]);

  const backtestTrainJobIdRaw = configDraft?.backtest_train_job_id;
  const backtestTrainJobId =
    typeof backtestTrainJobIdRaw === "number" && Number.isFinite(backtestTrainJobIdRaw)
      ? backtestTrainJobIdRaw
      : Number.isFinite(Number(backtestTrainJobIdRaw))
        ? Number(backtestTrainJobIdRaw)
        : null;
  const backtestTrainJobOptions = useMemo(() => {
    const items = mlJobs.filter((job) => job.status === "success");
    return items.sort((a, b) => (b.id || 0) - (a.id || 0));
  }, [mlJobs]);
  const backtestTrainJob = useMemo(() => {
    if (!backtestTrainJobId) {
      return null;
    }
    return backtestTrainJobOptions.find((job) => job.id === backtestTrainJobId) || null;
  }, [backtestTrainJobId, backtestTrainJobOptions]);
  const backtestTrainJobScorePath =
    backtestTrainJob?.scores_path ||
    (backtestTrainJob?.output_dir ? `${backtestTrainJob.output_dir}/scores.csv` : "");
  const formatBacktestTrainJobLabel = (job: MLTrainJob) => {
    const model = job.config?.model_type
      ? String(job.config.model_type).toUpperCase()
      : "";
    const parts = [`#${job.id}`];
    if (model) {
      parts.push(model);
    }
    return parts.join(" · ");
  };

  const renderSharedBacktestTemplate = (options?: { showTarget?: boolean }) => (
    <>
      <div className="card-title">{t("projects.pipeline.backtest.title")}</div>
      <div className="card-meta">{t("projects.pipeline.backtest.meta")}</div>
      {options?.showTarget && (
        <div className="meta-row">
          <span>{t("projects.pipeline.backtest.target")}</span>
          <strong>
            {pipelineEditor
              ? `#${pipelineEditor.id} ${
                  pipelineEditor.name || t("projects.pipeline.untitled")
                }`
              : t("projects.pipeline.none")}
          </strong>
        </div>
      )}
      <div className="meta-row">
        <span>{t("projects.pipeline.backtest.draftStatus")}</span>
        <strong>
          {pipelineBacktestDirty
            ? t("projects.pipeline.backtest.draftDirty")
            : t("projects.pipeline.backtest.draftSaved")}
        </strong>
      </div>
      <div className="form-grid">
        <div className="form-row" style={{ gridColumn: "1 / -1" }}>
          <label className="form-label">
            {t("projects.pipeline.backtest.trainJob")}
          </label>
          <select
            className="form-select"
            value={backtestTrainJobId ?? ""}
            onChange={(e) => updateBacktestTrainJobId(e.target.value)}
          >
            <option value="">{t("projects.pipeline.backtest.trainJobAuto")}</option>
            {backtestTrainJobOptions.map((job) => (
              <option key={job.id} value={job.id}>
                {formatBacktestTrainJobLabel(job)}
              </option>
            ))}
          </select>
          <div className="form-hint">{t("projects.pipeline.backtest.trainJobHint")}</div>
          {backtestTrainJobScorePath && (
            <div className="form-hint">
              {t("projects.pipeline.backtest.trainJobScorePath", {
                path: backtestTrainJobScorePath,
              })}
            </div>
          )}
        </div>
        <div className="form-row" style={{ gridColumn: "1 / -1" }}>
          <label className="form-label">
            {t("projects.pipeline.backtest.preset")}
          </label>
          <select
            className="form-select"
            value={pipelineBacktestPreset}
            onChange={(e) => {
              const preset = e.target.value as PipelinePresetKey;
              if (preset === "E35" || preset === "E45") {
                applyPipelinePreset(preset);
              } else {
                setPipelineBacktestPreset("custom");
              }
            }}
          >
            <option value="E35">{t("projects.pipeline.backtest.presetE35")}</option>
            <option value="E45">{t("projects.pipeline.backtest.presetE45")}</option>
            <option value="custom">
              {t("projects.pipeline.backtest.presetCustom")}
            </option>
          </select>
          <div className="form-hint">
            {t("projects.pipeline.backtest.presetHint")}
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              type="button"
              className="button-secondary"
              onClick={() => applyPipelinePreset("E35")}
            >
              {t("projects.pipeline.backtest.applyE35")}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() => applyPipelinePreset("E45")}
            >
              {t("projects.pipeline.backtest.applyE45")}
            </button>
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.topN")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.top_n ?? ""}
            onChange={(e) => updatePipelineBacktestParam("top_n", e.target.value)}
          />
          <div className="form-hint">{t("projects.pipeline.backtest.hints.topN")}</div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.weighting")}
          </label>
          <select
            className="form-select"
            value={pipelineBacktestParams.weighting ?? "score"}
            onChange={(e) => updatePipelineBacktestParam("weighting", e.target.value)}
          >
            <option value="score">
              {t("projects.pipeline.backtest.options.weightingScore")}
            </option>
            <option value="equal">
              {t("projects.pipeline.backtest.options.weightingEqual")}
            </option>
          </select>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.weighting")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.maxWeight")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.max_weight ?? ""}
            onChange={(e) => updatePipelineBacktestParam("max_weight", e.target.value)}
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.maxWeight")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.minScore")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.min_score ?? ""}
            onChange={(e) => updatePipelineBacktestParam("min_score", e.target.value)}
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.minScore")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.maxExposure")}
          </label>
          <input
            type="number"
            step="0.01"
            className="form-input"
            value={pipelineBacktestParams.max_exposure ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("max_exposure", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.maxExposure")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.scoreDelay")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.score_delay_days ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("score_delay_days", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.scoreDelay")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.scoreSmoothingAlpha")}
          </label>
          <input
            type="number"
            step="0.05"
            className="form-input"
            value={pipelineBacktestParams.score_smoothing_alpha ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("score_smoothing_alpha", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.scoreSmoothingAlpha")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.scoreSmoothingCarry")}
          </label>
          <label className="switch">
            <input
              type="checkbox"
              checked={coerceBoolean(
                pipelineBacktestParams.score_smoothing_carry ?? true,
                true
              )}
              onChange={(e) =>
                updatePipelineBacktestParam("score_smoothing_carry", e.target.checked)
              }
            />
            <span className="slider" />
          </label>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.scoreSmoothingCarry")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.retainTopN")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.retain_top_n ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("retain_top_n", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.retainTopN")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.marketFilter")}
          </label>
          <label className="switch">
            <input
              type="checkbox"
              checked={coerceBoolean(pipelineBacktestParams.market_filter ?? true, true)}
              onChange={(e) =>
                updatePipelineBacktestParam("market_filter", e.target.checked)
              }
            />
            <span className="slider" />
          </label>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.marketFilter")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.marketMa")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.market_ma_window ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("market_ma_window", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.marketMa")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.riskOffMode")}
          </label>
          <select
            className="form-select"
            value={pipelineBacktestParams.risk_off_mode ?? "cash"}
            onChange={(e) =>
              updatePipelineBacktestParam("risk_off_mode", e.target.value)
            }
          >
            <option value="cash">
              {t("projects.pipeline.backtest.options.riskOffCash")}
            </option>
            <option value="benchmark">
              {t("projects.pipeline.backtest.options.riskOffBenchmark")}
            </option>
            <option value="defensive">
              {t("projects.pipeline.backtest.options.riskOffDefensive")}
            </option>
          </select>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.riskOffMode")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.riskOffPick")}
          </label>
          <select
            className="form-select"
            value={pipelineBacktestParams.risk_off_pick ?? "best_momentum"}
            onChange={(e) =>
              updatePipelineBacktestParam("risk_off_pick", e.target.value)
            }
          >
            <option value="lowest_vol">
              {t("projects.pipeline.backtest.options.riskOffPickLowestVol")}
            </option>
            <option value="best_momentum">
              {t("projects.pipeline.backtest.options.riskOffPickBestMomentum")}
            </option>
          </select>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.riskOffPick")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.riskOffSymbols")}
          </label>
          <input
            className="form-input"
            value={pipelineBacktestParams.risk_off_symbols ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("risk_off_symbols", e.target.value)
            }
            placeholder="SHY,IEF,GLD,TLT"
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.riskOffSymbols")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.riskOffSymbol")}
          </label>
          <input
            className="form-input"
            value={pipelineBacktestParams.risk_off_symbol ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("risk_off_symbol", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.riskOffSymbol")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.maxDrawdown")}
          </label>
          <input
            type="number"
            step="0.01"
            className="form-input"
            value={pipelineBacktestParams.max_drawdown ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("max_drawdown", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.maxDrawdown")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.maxDrawdown52w")}
          </label>
          <input
            type="number"
            step="0.01"
            className="form-input"
            value={pipelineBacktestParams.max_drawdown_52w ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("max_drawdown_52w", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.maxDrawdown52w")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.drawdownRecovery")}
          </label>
          <input
            type="number"
            step="0.05"
            className="form-input"
            value={pipelineBacktestParams.drawdown_recovery_ratio ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("drawdown_recovery_ratio", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.drawdownRecovery")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.drawdownExposureFloor")}
          </label>
          <input
            type="number"
            step="0.01"
            className="form-input"
            value={pipelineBacktestParams.drawdown_exposure_floor ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("drawdown_exposure_floor", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.drawdownExposureFloor")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.drawdownTiers")}
          </label>
          <input
            className="form-input"
            value={pipelineBacktestParams.drawdown_tiers ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("drawdown_tiers", e.target.value)
            }
            placeholder="0.08,0.12"
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.drawdownTiers")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.drawdownExposures")}
          </label>
          <input
            className="form-input"
            value={pipelineBacktestParams.drawdown_exposures ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("drawdown_exposures", e.target.value)
            }
            placeholder="0.3,0.2"
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.drawdownExposures")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.maxTurnoverWeek")}
          </label>
          <input
            type="number"
            step="0.01"
            className="form-input"
            value={pipelineBacktestParams.max_turnover_week ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("max_turnover_week", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.maxTurnoverWeek")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.volTarget")}
          </label>
          <input
            type="number"
            step="0.005"
            className="form-input"
            value={pipelineBacktestParams.vol_target ?? ""}
            onChange={(e) => updatePipelineBacktestParam("vol_target", e.target.value)}
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.volTarget")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.volWindow")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.vol_window ?? ""}
            onChange={(e) => updatePipelineBacktestParam("vol_window", e.target.value)}
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.volWindow")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.idleAllocation")}
          </label>
          <select
            className="form-select"
            value={pipelineBacktestParams.idle_allocation ?? "none"}
            onChange={(e) =>
              updatePipelineBacktestParam("idle_allocation", e.target.value)
            }
          >
            <option value="none">
              {t("projects.pipeline.backtest.options.idleNone")}
            </option>
            <option value="defensive">
              {t("projects.pipeline.backtest.options.idleDefensive")}
            </option>
            <option value="benchmark">
              {t("projects.pipeline.backtest.options.idleBenchmark")}
            </option>
          </select>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.idleAllocation")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.dynamicExposure")}
          </label>
          <label className="switch">
            <input
              type="checkbox"
              checked={coerceBoolean(pipelineBacktestParams.dynamic_exposure ?? false, false)}
              onChange={(e) =>
                updatePipelineBacktestParam("dynamic_exposure", e.target.checked)
              }
            />
            <span className="slider" />
          </label>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.dynamicExposure")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.rebalanceFreq")}
          </label>
          <select
            className="form-select"
            value={pipelineBacktestParams.rebalance_frequency ?? "Weekly"}
            onChange={(e) =>
              updatePipelineBacktestParam("rebalance_frequency", e.target.value)
            }
          >
            <option value="Daily">
              {t("projects.pipeline.backtest.options.rebalanceDaily")}
            </option>
            <option value="Weekly">
              {t("projects.pipeline.backtest.options.rebalanceWeekly")}
            </option>
            <option value="Monthly">
              {t("projects.pipeline.backtest.options.rebalanceMonthly")}
            </option>
            <option value="Quarterly">
              {t("projects.pipeline.backtest.options.rebalanceQuarterly")}
            </option>
          </select>
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.rebalanceFreq")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.rebalanceDay")}
          </label>
          <input
            className="form-input"
            value={pipelineBacktestParams.rebalance_day ?? "Monday"}
            onChange={(e) => updatePipelineBacktestParam("rebalance_day", e.target.value)}
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.rebalanceDay")}
          </div>
        </div>
        <div className="form-row">
          <label className="form-label">
            {t("projects.pipeline.backtest.fields.rebalanceTime")}
          </label>
          <input
            type="number"
            className="form-input"
            value={pipelineBacktestParams.rebalance_time_minutes ?? ""}
            onChange={(e) =>
              updatePipelineBacktestParam("rebalance_time_minutes", e.target.value)
            }
          />
          <div className="form-hint">
            {t("projects.pipeline.backtest.hints.rebalanceTime")}
          </div>
        </div>
      </div>
      <div className="form-actions">
        <button
          className="button-primary"
          onClick={() => runPipelineBacktestsForActive({ saveTemplate: true })}
          disabled={!activePipelineId || pipelineBacktestSaving || pipelineBacktestRunning}
        >
          {pipelineBacktestSaving || pipelineBacktestRunning
            ? t("common.actions.loading")
            : t("projects.pipeline.backtest.runWithSave")}
        </button>
        <button
          className="button-secondary"
          onClick={() => runPipelineBacktestsForActive({ saveTemplate: false })}
          disabled={!activePipelineId || pipelineBacktestRunning}
        >
          {pipelineBacktestRunning
            ? t("common.actions.loading")
            : t("projects.pipeline.backtest.runOnce")}
        </button>
        <button
          className="button-secondary"
          onClick={() => savePipelineBacktestParams()}
          disabled={pipelineBacktestSaving}
        >
          {pipelineBacktestSaving
            ? t("common.actions.loading")
          : t("projects.pipeline.backtest.save")}
        </button>
      </div>
      {!activePipelineId && (
        <div className="form-hint">{t("projects.pipeline.backtest.runMissingPipeline")}</div>
      )}
      {pipelineBacktestMessage && (
        <div className="form-hint">{pipelineBacktestMessage}</div>
      )}
      {pipelineBacktestRunMessage && (
        <div className="form-hint">{pipelineBacktestRunMessage}</div>
      )}
    </>
  );

  const strategyDraft = configDraft?.strategy || {};
  const strategySource = (strategyDraft.source || "theme_weights").toString();
  const filteredProjects = useMemo(() => {
    const keyword = projectSearch.trim().toLowerCase();
    const base = showArchived
      ? projects
      : projects.filter((item) => !item.is_archived);
    if (!keyword) {
      return base;
    }
    return base.filter(
      (item) =>
        item.name.toLowerCase().includes(keyword) ||
        (item.description || "").toLowerCase().includes(keyword)
    );
  }, [projects, projectSearch, showArchived]);

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

  const formatYearRangeCompact = (range: string) => {
    if (!range || range === "-") {
      return "-";
    }
    const parts = range.split("-");
    if (parts.length !== 2) {
      return range;
    }
    const startYear = parseYear(parts[0]);
    const endYear = parseYear(parts[1]);
    if (startYear === null || endYear === null) {
      return range;
    }
    const short = (value: number) => String(value).slice(-2).padStart(2, "0");
    return `${short(startYear)}-${short(endYear)}`;
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

  const formatConfigJson = (value: unknown) => {
    if (value === null || value === undefined) {
      return "-";
    }
    const MAX_SYMBOLS = 12;
    const seen = new WeakSet<object>();
    const summarizeValue = (input: unknown): unknown => {
      if (input === null || input === undefined) {
        return input;
      }
      if (typeof input !== "object") {
        return input;
      }
      if (Array.isArray(input)) {
        return input.map((item) => summarizeValue(item));
      }
      const obj = input as Record<string, unknown>;
      if (seen.has(obj)) {
        return "[Circular]";
      }
      seen.add(obj);
      const result: Record<string, unknown> = {};
      for (const [key, val] of Object.entries(obj)) {
        if (key === "symbols" && Array.isArray(val)) {
          const total = val.length;
          const sample = val.slice(0, MAX_SYMBOLS);
          if (total > MAX_SYMBOLS) {
            sample.push(`... (+${total - MAX_SYMBOLS} more)`);
          }
          result[key] = sample;
          result[`${key}_count`] = total;
          continue;
        }
        result[key] = summarizeValue(val);
      }
      return result;
    };
    try {
      return JSON.stringify(summarizeValue(value), null, 2);
    } catch {
      return String(value);
    }
  };

  const resolveJobMetric = (job: MLTrainJob, key: string) => {
    const metrics = (job.metrics || {}) as Record<string, any>;
    const direct = extractMetricValue(metrics[key]);
    if (direct !== null) {
      return direct;
    }
    const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    const camelVal = extractMetricValue(metrics[camelKey]);
    if (camelVal !== null) {
      return camelVal;
    }
    return extractWindowMetric(metrics, key);
  };

  const resolveJobModelParam = (job: MLTrainJob, key?: string | null) => {
    if (!key) {
      return null;
    }
    const cfg = (job.config || {}) as Record<string, any>;
    const model = (cfg.model || {}) as Record<string, any>;
    const params =
      (model.model_params as Record<string, any> | undefined) ??
      (cfg.model_params as Record<string, any> | undefined) ??
      (cfg.modelParams as Record<string, any> | undefined);
    if (!params || typeof params !== "object") {
      return null;
    }
    return params[key];
  };

  const pipelineSweepInfo = useMemo(() => {
    const params = pipelineDetail?.params as Record<string, any> | null | undefined;
    if (!params || typeof params !== "object") {
      return null;
    }
    const sweep =
      (params.train_sweep as Record<string, any> | undefined) ??
      (params.trainSweep as Record<string, any> | undefined) ??
      (params.sweep as Record<string, any> | undefined);
    if (!sweep || typeof sweep !== "object") {
      return null;
    }
    const rawKey =
      sweep.param_key ?? sweep.paramKey ?? sweep.param ?? sweep.key ?? null;
    const paramKey = typeof rawKey === "string" ? rawKey.trim() : "";
    if (!paramKey) {
      return null;
    }
    return {
      paramKey,
      start: sweep.start ?? null,
      end: sweep.end ?? null,
      step: sweep.step ?? null,
      includeEnd: sweep.include_end ?? sweep.includeEnd ?? null,
      values: Array.isArray(sweep.values) ? sweep.values : null,
    };
  }, [pipelineDetail]);

  const pipelineSweepBest = useMemo(() => {
    const paramKey = pipelineSweepInfo?.paramKey;
    if (!paramKey || !pipelineDetail?.train_jobs?.length) {
      return null;
    }
    let bestJob: MLTrainJob | null = null;
    let bestScore: number | null = null;
    for (const job of pipelineDetail.train_jobs) {
      const score = resolveJobMetric(job, "quality_score");
      if (score === null) {
        continue;
      }
      if (bestScore === null || score > bestScore) {
        bestScore = score;
        bestJob = job;
      }
    }
    if (!bestJob || bestScore === null) {
      return null;
    }
    const paramValue = resolveJobModelParam(bestJob, paramKey);
    return {
      jobId: bestJob.id,
      paramKey,
      paramValue,
      score: bestScore,
    };
  }, [pipelineDetail, pipelineSweepInfo]);

  const formatSweepParamValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    if (typeof value === "number") {
      return formatNumber(value);
    }
    return String(value);
  };

  const parseModelParams = (
    raw: string | undefined,
    onError: (message: string) => void
  ) => {
    const trimmed = raw?.trim();
    if (!trimmed) {
      return undefined;
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (!parsed || typeof parsed !== "object") {
        throw new Error("invalid");
      }
      return parsed as Record<string, any>;
    } catch (err) {
      onError(t("projects.ml.modelParamsError"));
      return null;
    }
  };

  const buildModelParams = (onError: (message: string) => void) => {
    const params: Record<string, any> = {};
    const addNumber = (key: string, raw: string) => {
      const trimmed = raw?.trim() ?? "";
      if (!trimmed) {
        return;
      }
      const num = Number(trimmed);
      if (Number.isFinite(num)) {
        params[key] = num;
      }
    };
    if (mlForm.modelType === "lgbm_ranker") {
      addNumber("learning_rate", mlForm.lgbmLearningRate);
      addNumber("num_leaves", mlForm.lgbmNumLeaves);
      addNumber("min_data_in_leaf", mlForm.lgbmMinDataInLeaf);
      addNumber("n_estimators", mlForm.lgbmEstimators);
      addNumber("subsample", mlForm.lgbmSubsample);
      addNumber("colsample_bytree", mlForm.lgbmColsampleBytree);
    }
    const extraParams = parseModelParams(mlForm.modelParams, onError);
    if (extraParams === null) {
      return null;
    }
    if (extraParams) {
      Object.assign(params, extraParams);
    }
    return Object.keys(params).length ? params : undefined;
  };

  const buildSweepValues = (
    startRaw: string,
    endRaw: string,
    stepRaw: string,
    includeEnd: boolean
  ) => {
    const start = Number(startRaw);
    const end = Number(endRaw);
    const step = Number(stepRaw);
    if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(step)) {
      return { values: [] as number[], decimals: 0, error: t("projects.ml.sweep.rangeError") };
    }
    if (step <= 0) {
      return { values: [] as number[], decimals: 0, error: t("projects.ml.sweep.stepError") };
    }
    if (start > end) {
      return { values: [] as number[], decimals: 0, error: t("projects.ml.sweep.rangeOrderError") };
    }
    const stepText = stepRaw.trim();
    const match = stepText.match(/\.(\d+)/);
    const decimals = match ? match[1].length : 0;
    const scale = Math.pow(10, decimals);
    const startInt = Math.round(start * scale);
    const endInt = Math.round(end * scale);
    const stepInt = Math.round(step * scale);
    if (stepInt <= 0) {
      return { values: [] as number[], decimals, error: t("projects.ml.sweep.stepError") };
    }
    const values: number[] = [];
    for (let value = startInt; includeEnd ? value <= endInt : value < endInt; value += stepInt) {
      const normalized = Number((value / scale).toFixed(decimals));
      if (!values.includes(normalized)) {
        values.push(normalized);
      }
      if (values.length > ML_SWEEP_MAX_VALUES) {
        return {
          values: [],
          decimals,
          error: t("projects.ml.sweep.tooMany", { limit: ML_SWEEP_MAX_VALUES }),
        };
      }
    }
    if (!values.length) {
      return { values: [], decimals, error: t("projects.ml.sweep.rangeError") };
    }
    return { values, decimals, error: "" };
  };

  const buildLinePath = (
    values: number[],
    width: number,
    height: number,
    padding: number,
    minValue: number,
    maxValue: number
  ) => {
    if (values.length === 0) {
      return "";
    }
    const span = maxValue - minValue || 1;
    const usableWidth = width - padding * 2;
    const usableHeight = height - padding * 2;
    return values
      .map((value, index) => {
        const x =
          padding +
          (values.length === 1 ? 0 : (index / (values.length - 1)) * usableWidth);
        const y = height - padding - ((value - minValue) / span) * usableHeight;
        return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  };

  const renderMlCurve = (curve: {
    metric?: string;
    iterations?: number[];
    train: number[];
    valid: number[];
  }) => {
    const width = 520;
    const height = 180;
    const padding = 22;
    const allValues = [...curve.train, ...curve.valid].filter((value) =>
      Number.isFinite(value)
    );
    if (!allValues.length) {
      return <div className="empty-state">{t("projects.ml.metricCurveEmpty")}</div>;
    }
    const minValue = Math.min(...allValues);
    const maxValue = Math.max(...allValues);
    const span = maxValue - minValue || 1;
    const validRange = computePaddedRange(curve.valid);
    const validMin = validRange ? validRange.min : minValue;
    const validMax = validRange ? validRange.max : maxValue;
    const validSpan = validRange ? validRange.span : span;
    const hasValidAxis = Boolean(validRange);
    const toY = (value: number) =>
      padding + (maxValue - value) / span * (height - padding * 2);
    const toYValid = (value: number) =>
      padding + (validMax - value) / validSpan * (height - padding * 2);
    const toX = (index: number, total: number) =>
      padding + (total <= 1 ? 0 : (index / (total - 1)) * (width - padding * 2));
    const seriesLength = curve.valid.length || curve.train.length;
    const iterations =
      Array.isArray(curve.iterations) && curve.iterations.length === seriesLength
        ? curve.iterations
        : Array.from({ length: seriesLength }, (_, idx) => idx + 1);
    const yTickCount = 4;
    const yTicks = Array.from({ length: yTickCount }, (_, idx) => ({
      value: minValue + (span * idx) / Math.max(yTickCount - 1, 1),
      y: toY(minValue + (span * idx) / Math.max(yTickCount - 1, 1)),
    }));
    const yMinorValues = buildMinorTickValues(yTicks.map((tick) => tick.value));
    const yMinorTicks = yMinorValues.map((value) => ({
      value,
      y: toY(value),
    }));
    const yValidTicks = Array.from({ length: yTickCount }, (_, idx) => ({
      value: validMin + (validSpan * idx) / Math.max(yTickCount - 1, 1),
      y: toYValid(validMin + (validSpan * idx) / Math.max(yTickCount - 1, 1)),
    }));
    const majorTickCount = Math.min(5, Math.max(seriesLength, 1));
    const xTickIndices = buildTickIndices(seriesLength, majorTickCount);
    const xMinorTickIndices = buildMinorTickIndices(seriesLength, xTickIndices);
    const xTicks = xTickIndices.map((idx) => ({
      x: toX(idx, seriesLength),
      label: String(iterations[idx] ?? idx + 1),
    }));
    const xMinorTicks = xMinorTickIndices.map((idx) => ({
      x: toX(idx, seriesLength),
    }));
    const metricName = String(curve.metric || "").toLowerCase();
    const lowerIsBetter = /loss|error|rmse|mse|mae|logloss/.test(metricName);
    let bestIndex = -1;
    let bestValue: number | null = null;
    curve.valid.forEach((value, idx) => {
      if (!Number.isFinite(value)) {
        return;
      }
      if (bestValue === null) {
        bestValue = value;
        bestIndex = idx;
        return;
      }
      const better = lowerIsBetter ? value < bestValue : value > bestValue;
      if (better) {
        bestValue = value;
        bestIndex = idx;
      }
    });
    const bestIteration =
      bestIndex >= 0 ? iterations[bestIndex] ?? bestIndex + 1 : null;
    const bestPoint =
      bestIndex >= 0 && bestValue !== null
        ? {
            x: toX(bestIndex, curve.valid.length || 1),
            y: toYValid(bestValue),
            value: bestValue,
            iteration: bestIteration,
          }
        : null;
    const trainPath = buildLinePath(
      curve.train,
      width,
      height,
      padding,
      minValue,
      maxValue
    );
    const validPath = buildLinePath(
      curve.valid,
      width,
      height,
      padding,
      validMin,
      validMax
    );
    return (
      <div className="ml-curve-chart">
        <div className="ml-curve-header">
          <div className="card-title">{t("projects.ml.metricCurveTitle")}</div>
          <div className="card-meta">
            {t("projects.ml.metricCurveMetric", {
              metric: curve.metric || "-",
            })}
          </div>
        </div>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="ml-curve-canvas"
          preserveAspectRatio="none"
        >
          <rect
            x="0"
            y="0"
            width={width}
            height={height}
            className="ml-curve-bg"
          />
          {yMinorTicks.map((tick, idx) => (
            <line
              key={`y-minor-${idx}`}
              x1={padding}
              y1={tick.y}
              x2={width - padding}
              y2={tick.y}
              className="ml-curve-grid-line minor"
            />
          ))}
          {yTicks.map((tick, idx) => (
            <g key={`y-${idx}`}>
              <line
                x1={padding}
                y1={tick.y}
                x2={width - padding}
                y2={tick.y}
                className="ml-curve-grid-line"
              />
              <text
                x={6}
                y={tick.y + 3}
                className="ml-curve-axis-label"
              >
                {formatAxisValue(tick.value, span)}
              </text>
            </g>
          ))}
          {hasValidAxis &&
            yValidTicks.map((tick, idx) => (
              <g key={`y-valid-${idx}`}>
                <text
                  x={width - 6}
                  y={tick.y + 3}
                  textAnchor="end"
                  className="ml-curve-axis-label valid"
                >
                  {formatAxisValue(tick.value, validSpan)}
                </text>
              </g>
            ))}
          {xMinorTicks.map((tick, idx) => (
            <line
              key={`x-minor-${idx}`}
              x1={tick.x}
              y1={padding}
              x2={tick.x}
              y2={height - padding}
              className="ml-curve-grid-line vertical minor"
            />
          ))}
          {xTicks.map((tick, idx) => (
            <g key={`x-${idx}`}>
              <line
                x1={tick.x}
                y1={padding}
                x2={tick.x}
                y2={height - padding}
                className="ml-curve-grid-line vertical"
              />
              <text
                x={tick.x}
                y={height - 6}
                textAnchor="middle"
                className="ml-curve-axis-label"
              >
                {tick.label}
              </text>
            </g>
          ))}
          {trainPath && <path d={trainPath} className="ml-curve-line train" />}
          {validPath && <path d={validPath} className="ml-curve-line valid" />}
          {bestPoint && (
            <g className="ml-curve-best">
              <line
                x1={bestPoint.x}
                y1={bestPoint.y}
                x2={bestPoint.x}
                y2={Math.max(bestPoint.y - 14, padding)}
                className="ml-curve-best-stem"
              />
              <circle
                cx={bestPoint.x}
                cy={bestPoint.y}
                r={4}
                className="ml-curve-best-dot"
              />
              <text
                x={bestPoint.x}
                y={Math.max(bestPoint.y - 16, padding + 8)}
                textAnchor="middle"
                className="ml-curve-best-label"
              >
                {t("projects.ml.metricCurveBest", {
                  value: Number(bestPoint.value).toFixed(4),
                  iteration: bestPoint.iteration ?? "-",
                })}
              </text>
            </g>
          )}
        </svg>
        <div className="ml-curve-legend">
          {curve.train.length > 0 && (
            <span className="ml-curve-legend-item train">
              {t("projects.ml.metricCurveTrain")}
            </span>
          )}
          {curve.valid.length > 0 && (
            <span className="ml-curve-legend-item valid">
              {t("projects.ml.metricCurveValidScaled")}
            </span>
          )}
        </div>
      </div>
    );
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

  const coerceBoolean = (value: unknown, fallback: boolean) => {
    if (typeof value === "boolean") {
      return value;
    }
    if (typeof value === "number") {
      return value !== 0;
    }
    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (normalized === "true" || normalized === "yes" || normalized === "1") {
        return true;
      }
      if (normalized === "false" || normalized === "no" || normalized === "0") {
        return false;
      }
    }
    return fallback;
  };

  const resolvePipelinePreset = (
    preset: unknown,
    exposureValue: unknown
  ): PipelinePresetKey => {
    if (preset === "E35" || preset === "E45" || preset === "custom") {
      return preset;
    }
    const numeric =
      typeof exposureValue === "number"
        ? exposureValue
        : Number(String(exposureValue ?? ""));
    if (Number.isFinite(numeric)) {
      if (Math.abs(numeric - PIPELINE_BACKTEST_PRESETS.E35.max_exposure) < 1e-4) {
        return "E35";
      }
      if (Math.abs(numeric - PIPELINE_BACKTEST_PRESETS.E45.max_exposure) < 1e-4) {
        return "E45";
      }
    }
    return "custom";
  };

  const normalizePipelineBacktestParams = (params: Record<string, any> | null | undefined) => {
    if (!params || typeof params !== "object") {
      return {};
    }
    const normalized: Record<string, any> = {};
    PIPELINE_BACKTEST_FIELDS.forEach((key) => {
      if (params[key] !== undefined && params[key] !== null) {
        normalized[key] = params[key];
      }
    });
    return normalized;
  };

  const pipelineBacktestBaseParams = useMemo(() => {
    const base = configDraft?.backtest_params;
    if (!base || typeof base !== "object") {
      return {};
    }
    return normalizePipelineBacktestParams(base as Record<string, any>);
  }, [configDraft]);

  const mlSweepPreview = useMemo(
    () =>
      buildSweepValues(
        mlSweep.start,
        mlSweep.end,
        mlSweep.step,
        mlSweep.includeEnd
      ),
    [mlSweep, t]
  );

  const buildPipelineBacktestAlgorithmParams = () => {
    const params: Record<string, any> = {};
    PIPELINE_BACKTEST_FIELDS.forEach((key) => {
      const raw = pipelineBacktestParams[key];
      if (raw === null || raw === undefined || raw === "") {
        return;
      }
      if (PIPELINE_BACKTEST_BOOLEAN_FIELDS.has(key)) {
        params[key] = coerceBoolean(raw, false);
        return;
      }
      if (PIPELINE_BACKTEST_NUMBER_FIELDS.has(key)) {
        const num = typeof raw === "number" ? raw : Number(String(raw));
        if (Number.isFinite(num)) {
          params[key] = num;
        }
        return;
      }
      params[key] = raw;
    });
    return params;
  };

  const normalizeBacktestParamValue = (key: string, value: unknown) => {
    if (PIPELINE_BACKTEST_BOOLEAN_FIELDS.has(key)) {
      return coerceBoolean(value, false);
    }
    if (PIPELINE_BACKTEST_NUMBER_FIELDS.has(key)) {
      if (value === "" || value === null || value === undefined) {
        return "";
      }
      const num = typeof value === "number" ? value : Number(String(value));
      return Number.isFinite(num) ? num : "";
    }
    return value;
  };

  const buildPipelineBacktestPayload = () => ({
    backtest: {
      preset: pipelineBacktestPreset,
      algorithm_parameters: buildPipelineBacktestAlgorithmParams(),
    },
  });

  const applyPipelinePreset = (preset: Exclude<PipelinePresetKey, "custom">) => {
    setPipelineBacktestPreset(preset);
    updatePipelineBacktestParam(
      "max_exposure",
      PIPELINE_BACKTEST_PRESETS[preset].max_exposure
    );
  };

  const updatePipelineBacktestParam = (key: string, value: unknown) => {
    const normalized = normalizeBacktestParamValue(key, value);
    setPipelineBacktestParams((prev) => ({ ...prev, [key]: normalized }));
    setConfigDraft((prev) => {
      if (!prev) {
        return prev;
      }
      const backtestParams = { ...(prev.backtest_params || {}) };
      backtestParams[key] = normalized;
      return { ...prev, backtest_params: backtestParams };
    });
    if (key === "max_exposure") {
      const numeric =
        typeof normalized === "number" ? normalized : Number(String(normalized ?? ""));
      if (Number.isFinite(numeric)) {
        if (Math.abs(numeric - PIPELINE_BACKTEST_PRESETS.E35.max_exposure) < 1e-4) {
          setPipelineBacktestPreset("E35");
          return;
        }
        if (Math.abs(numeric - PIPELINE_BACKTEST_PRESETS.E45.max_exposure) < 1e-4) {
          setPipelineBacktestPreset("E45");
          return;
        }
      }
      setPipelineBacktestPreset("custom");
    }
  };

  useEffect(() => {
    const mergedParams = { ...pipelineBacktestBaseParams };
    Object.entries(PIPELINE_BACKTEST_DEFAULTS).forEach(([key, value]) => {
      if (
        mergedParams[key] === undefined ||
        mergedParams[key] === null ||
        mergedParams[key] === ""
      ) {
        mergedParams[key] = value;
      }
    });
    const exposureCandidate =
      mergedParams.max_exposure ??
      PIPELINE_BACKTEST_PRESETS.E35.max_exposure;
    const preset = resolvePipelinePreset(undefined, exposureCandidate);
    if (preset === "E35" || preset === "E45") {
      mergedParams.max_exposure = PIPELINE_BACKTEST_PRESETS[preset].max_exposure;
    }
    setPipelineBacktestParams(mergedParams);
    setPipelineBacktestPreset(preset);
    setPipelineBacktestMessage("");
  }, [pipelineBacktestBaseParams]);

  const buildComparableBacktestParams = (
    params: Record<string, any> | null | undefined
  ) => {
    const normalized = normalizePipelineBacktestParams(params);
    const comparable: Record<string, any> = {};
    PIPELINE_BACKTEST_FIELDS.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(normalized, key)) {
        comparable[key] = normalizeBacktestParamValue(key, normalized[key]);
      }
    });
    return comparable;
  };

  const areBacktestParamsEqual = (
    left: Record<string, any>,
    right: Record<string, any>
  ) => {
    const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
    for (const key of keys) {
      if ((left[key] ?? null) !== (right[key] ?? null)) {
        return false;
      }
    }
    return true;
  };

  const pipelineBacktestDraftParams = useMemo(
    () => buildComparableBacktestParams(configDraft?.backtest_params as Record<string, any>),
    [configDraft]
  );
  const pipelineBacktestSavedParams = useMemo(
    () =>
      buildComparableBacktestParams(
        configMeta?.config?.backtest_params as Record<string, any>
      ),
    [configMeta]
  );
  const pipelinePresetSaved = useMemo(() => {
    const params = pipelineEditor?.params as Record<string, any> | null | undefined;
    const backtest = params?.backtest as Record<string, any> | undefined;
    const preset = backtest?.preset;
    return preset === "E35" || preset === "E45" || preset === "custom" ? preset : null;
  }, [pipelineEditor]);
  const backtestTrainJobSavedRaw =
    (configMeta?.config as Record<string, any> | null | undefined)?.backtest_train_job_id;
  const backtestTrainJobSaved =
    typeof backtestTrainJobSavedRaw === "number" &&
    Number.isFinite(backtestTrainJobSavedRaw)
      ? backtestTrainJobSavedRaw
      : Number.isFinite(Number(backtestTrainJobSavedRaw))
        ? Number(backtestTrainJobSavedRaw)
        : null;
  const pipelineBacktestDirty =
    !areBacktestParamsEqual(pipelineBacktestDraftParams, pipelineBacktestSavedParams) ||
    (!!pipelinePresetSaved && pipelinePresetSaved !== pipelineBacktestPreset) ||
    backtestTrainJobId !== backtestTrainJobSaved;

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
  const algorithmSummaryName = useMemo(() => {
    const targetId = Number(bindingForm.algorithmId || binding?.algorithm_id || 0);
    if (targetId) {
      const match = algorithms.find((algo) => algo.id === targetId);
      if (match?.name) {
        return match.name;
      }
    }
    return binding?.algorithm_name || "";
  }, [algorithms, bindingForm.algorithmId, binding?.algorithm_id, binding?.algorithm_name]);
  const algorithmSummaryParamCount = useMemo(() => {
    const params = algorithmVersionDetail?.params;
    if (!params || typeof params !== "object") {
      return 0;
    }
    return Object.keys(params).length;
  }, [algorithmVersionDetail]);
  const algorithmSummaryVersionLabel = useMemo(() => {
    if (!algorithmVersionDetail) {
      return "";
    }
    return algorithmVersionDetail.version || `#${algorithmVersionDetail.id}`;
  }, [algorithmVersionDetail]);
  const algorithmSummaryDisplay = useMemo(() => {
    if (!algorithmSummaryVersionLabel) {
      return "";
    }
    if (algorithmSummaryName) {
      return `${algorithmSummaryName} ${algorithmSummaryVersionLabel}`.trim();
    }
    return algorithmSummaryVersionLabel;
  }, [algorithmSummaryName, algorithmSummaryVersionLabel]);
  const metricRows = [
    { key: "Compounding Annual Return", label: t("metrics.cagr") },
    { key: "Drawdown", label: t("metrics.drawdown") },
    { key: "MaxDD_all", label: t("metrics.drawdownAll") },
    { key: "MaxDD_52w", label: t("metrics.drawdown52w") },
    { key: "Sharpe Ratio", label: t("metrics.sharpe") },
    { key: "Net Profit", label: t("metrics.netProfit") },
    { key: "Total Fees", label: t("metrics.totalFees") },
    { key: "Portfolio Turnover", label: t("metrics.turnover") },
    { key: "Turnover_week", label: t("metrics.turnoverWeekAvg") },
    { key: "Turnover_sanity_ratio", label: t("metrics.turnoverSanityRatio") },
    { key: "MaxTurnover_week", label: t("metrics.turnoverWeek") },
    { key: "Risk Status", label: t("metrics.riskStatus") },
  ];
  const backtestSummary = latestBacktest?.metrics as Record<string, any> | null;
  const latestBacktestParams =
    (latestBacktest?.params as Record<string, any> | null | undefined) || {};
  const latestBacktestAlgoParams =
    (latestBacktestParams.algorithm_parameters as Record<string, any> | null | undefined) ||
    {};
  const latestBacktestTrainJobId =
    latestBacktestParams.pipeline_train_job_id ??
    latestBacktestParams.ml_train_job_id ??
    latestBacktestParams.train_job_id ??
    null;
  const latestBacktestScorePath =
    (latestBacktestAlgoParams.score_csv_path as string | undefined) ??
    (latestBacktestParams.score_csv_path as string | undefined) ??
    "";
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
              <label className="checkbox-row" style={{ marginTop: "8px" }}>
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => {
                    setShowArchived(e.target.checked);
                    setProjectPage(1);
                  }}
                />
                <span>{t("projects.list.showArchived")}</span>
              </label>
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
                    data-testid={`project-item-${project.id}`}
                  >
                    <div
                      className="project-item-title"
                      style={{ display: "flex", alignItems: "center", gap: "6px" }}
                    >
                      <span>{project.name}</span>
                      {project.is_archived && (
                        <span className="pill warn">{t("projects.list.archivedTag")}</span>
                      )}
                    </div>
                    <div
                      className="project-item-meta"
                      style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}
                    >
                      <IdChip label={t("projects.table.project")} value={project.id} />
                      <span>{formatDateTime(project.created_at)}</span>
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
                <a className="button-secondary" href="/algorithms">
                  {t("projects.algorithm.openLibrarySummary")}
                </a>
                <button className="button-secondary" onClick={refreshProjectData}>
                  {t("projects.dataStatus.action")}
                </button>
                {selectedProject.is_archived ? (
                  <button
                    className="button-secondary"
                    onClick={() => restoreProject(selectedProject)}
                  >
                    {t("projects.detail.restore")}
                  </button>
                ) : (
                  <button
                    className="danger-button"
                    onClick={() => archiveProject(selectedProject)}
                  >
                    {t("projects.detail.archive")}
                  </button>
                )}
                <button className="button-primary" onClick={runThematicBacktest}>
                  {t("projects.backtest.action")}
                </button>
              </div>
            </div>
            {backtestMessage && (
              <div className="project-detail-status">{backtestMessage}</div>
            )}
            {projectActionMessage && (
              <div className="project-detail-status">{projectActionMessage}</div>
            )}
            {projectActionError && (
              <div className="project-detail-status">{projectActionError}</div>
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
                  <span>{t("projects.detail.archivedLabel")}</span>
                  <strong>
                    {selectedProject.is_archived
                      ? t("common.boolean.true")
                      : t("common.boolean.false")}
                  </strong>
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
                  data-testid={`project-tab-${tab.key}`}
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
                          {t("projects.detail.symbolsTotalLabel")}
                        </div>
                        <div className="overview-value">
                          {themeSummary?.total_symbols ?? 0}
                        </div>
                        <div className="overview-sub">
                          {t("common.labels.updatedAt")}{" "}
                          {formatDateTime(themeSummary?.updated_at)}
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
                        <div className="meta-row">
                          <span>{t("projects.backtest.trainJob")}</span>
                          <strong>
                            {latestBacktestTrainJobId
                              ? `#${latestBacktestTrainJobId}`
                              : t("common.none")}
                          </strong>
                        </div>
                        <div className="meta-row">
                          <span>{t("projects.backtest.scorePath")}</span>
                          <strong>{latestBacktestScorePath || t("common.none")}</strong>
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
                        {lockedSymbolTypeOptions.map((option) => (
                          <label className="checkbox-row" key={option.value}>
                            <input
                              type="checkbox"
                              disabled
                              checked
                            />
                            {option.label}
                          </label>
                        ))}
                      </div>
                      <div className="form-hint">
                        {t("projects.config.assetTypesLockedHint")}
                      </div>
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
                        value="alpha"
                        disabled
                      >
                        <option value="alpha">Alpha</option>
                      </select>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.vendorFallback")}</label>
                      <select
                        className="form-select"
                        value="alpha"
                        disabled
                      >
                        <option value="alpha">Alpha</option>
                      </select>
                      <div className="form-hint">
                        {t("projects.config.vendorLockedHint")}
                      </div>
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
            <div className="card">
              <div className="card-title">{t("projects.algorithm.summaryTitle")}</div>
              <div className="card-meta">{t("projects.algorithm.summaryMeta")}</div>
              {algorithmVersionDetail ? (
                <div className="meta-list">
                  <div className="meta-row">
                    <span>{t("projects.algorithm.summaryCurrent")}</span>
                    <strong>{algorithmSummaryDisplay || "-"}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.algorithm.summaryVersionId")}</span>
                    <strong>#{algorithmVersionDetail.id}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.algorithm.summaryType")}</span>
                    <strong>{algorithmVersionDetail.type_name || "-"}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.algorithm.summaryLanguage")}</span>
                    <strong>{algorithmVersionDetail.language || "-"}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.algorithm.summaryPath")}</span>
                    <strong>{algorithmVersionDetail.file_path || "-"}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.algorithm.summaryParams")}</span>
                    <strong>{algorithmSummaryParamCount}</strong>
                  </div>
                  <div className="meta-row">
                    <span>{t("common.labels.updatedAt")}</span>
                    <strong>{formatDateTime(algorithmVersionDetail.created_at)}</strong>
                  </div>
                </div>
              ) : (
                <div className="empty-state">{t("projects.algorithm.summaryEmpty")}</div>
              )}
              {algorithmVersionDetailMessage && (
                <div className="form-hint">{algorithmVersionDetailMessage}</div>
              )}
              <div className="form-actions">
                <a className="button-secondary" href="/algorithms">
                  {t("projects.algorithm.openLibrary")}
                </a>
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
              <div className="card algorithm-top-ml">
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
                    <label className="form-label">{t("projects.ml.symbolSource")}</label>
                    <select
                      className="form-select"
                      value={mlForm.symbolSource}
                      onChange={(e) =>
                        setMlForm((prev) => ({ ...prev, symbolSource: e.target.value }))
                      }
                    >
                      <option value="project">{t("projects.ml.symbolSourceProject")}</option>
                      <option value="system_theme">
                        {t("projects.ml.symbolSourceSystem")}
                      </option>
                    </select>
                    <div className="form-hint">{t("projects.ml.symbolSourceHint")}</div>
                  </div>
                  {mlForm.symbolSource === "system_theme" && (
                    <div className="form-row">
                      <label className="form-label">{t("projects.ml.systemTheme")}</label>
                      <select
                        className="form-select"
                        value={mlForm.systemThemeKey}
                        onChange={(e) =>
                          setMlForm((prev) => ({
                            ...prev,
                            systemThemeKey: e.target.value,
                          }))
                        }
                        disabled={!systemThemes.length}
                      >
                        {systemThemes.map((theme) => (
                          <option key={theme.key} value={theme.key}>
                            {theme.key} {theme.label}
                          </option>
                        ))}
                      </select>
                      <div className="form-hint">
                        {systemThemeMessage || t("projects.ml.systemThemeHint")}
                      </div>
                    </div>
                  )}
                  <div className="form-row">
                    <label className="form-label">{t("projects.pipeline.link")}</label>
                    <select
                      className="form-select"
                      value={activePipelineId ?? ""}
                      onChange={(e) =>
                        setActivePipelineId(
                          e.target.value ? Number(e.target.value) : null
                        )
                      }
                    >
                      <option value="">{t("projects.pipeline.linkNone")}</option>
                      {pipelines.map((pipeline) => (
                        <option key={pipeline.id} value={pipeline.id}>
                          #{pipeline.id} {pipeline.name || t("projects.pipeline.untitled")}
                        </option>
                      ))}
                    </select>
                    <div className="form-hint">{t("projects.pipeline.linkHint")}</div>
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={pipelineForm.autoCreate}
                      onChange={(e) =>
                        setPipelineForm((prev) => ({
                          ...prev,
                          autoCreate: e.target.checked,
                        }))
                      }
                    />
                    {t("projects.pipeline.autoCreate")}
                  </label>
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
                  {mlForm.modelType === "lgbm_ranker" && (
                    <>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.ml.lgbm.learningRate")}
                        </label>
                        <input
                          type="number"
                          step="0.001"
                          min={0}
                          className="form-input"
                          value={mlForm.lgbmLearningRate}
                          onChange={(e) =>
                            setMlForm((prev) => ({
                              ...prev,
                              lgbmLearningRate: e.target.value,
                            }))
                          }
                        />
                        <div className="form-hint">
                          {t("projects.ml.lgbm.learningRateHint")}
                        </div>
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.ml.lgbm.numLeaves")}
                        </label>
                        <input
                          type="number"
                          min={2}
                          className="form-input"
                          value={mlForm.lgbmNumLeaves}
                          onChange={(e) =>
                            setMlForm((prev) => ({
                              ...prev,
                              lgbmNumLeaves: e.target.value,
                            }))
                          }
                        />
                        <div className="form-hint">
                          {t("projects.ml.lgbm.numLeavesHint")}
                        </div>
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.ml.lgbm.minDataInLeaf")}
                        </label>
                        <input
                          type="number"
                          min={1}
                          className="form-input"
                          value={mlForm.lgbmMinDataInLeaf}
                          onChange={(e) =>
                            setMlForm((prev) => ({
                              ...prev,
                              lgbmMinDataInLeaf: e.target.value,
                            }))
                          }
                        />
                        <div className="form-hint">
                          {t("projects.ml.lgbm.minDataInLeafHint")}
                        </div>
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.ml.lgbm.estimators")}
                        </label>
                        <input
                          type="number"
                          min={1}
                          className="form-input"
                          value={mlForm.lgbmEstimators}
                          onChange={(e) =>
                            setMlForm((prev) => ({
                              ...prev,
                              lgbmEstimators: e.target.value,
                            }))
                          }
                        />
                        <div className="form-hint">
                          {t("projects.ml.lgbm.estimatorsHint")}
                        </div>
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.ml.lgbm.subsample")}
                        </label>
                        <input
                          type="number"
                          step="0.05"
                          min={0}
                          max={1}
                          className="form-input"
                          value={mlForm.lgbmSubsample}
                          onChange={(e) =>
                            setMlForm((prev) => ({
                              ...prev,
                              lgbmSubsample: e.target.value,
                            }))
                          }
                        />
                        <div className="form-hint">{t("projects.ml.lgbm.subsampleHint")}</div>
                      </div>
                      <div className="form-row">
                        <label className="form-label">
                          {t("projects.ml.lgbm.colsampleBytree")}
                        </label>
                        <input
                          type="number"
                          step="0.05"
                          min={0}
                          max={1}
                          className="form-input"
                          value={mlForm.lgbmColsampleBytree}
                          onChange={(e) =>
                            setMlForm((prev) => ({
                              ...prev,
                              lgbmColsampleBytree: e.target.value,
                            }))
                          }
                        />
                        <div className="form-hint">
                          {t("projects.ml.lgbm.colsampleBytreeHint")}
                        </div>
                      </div>
                    </>
                  )}
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.sampleWeighting")}</label>
                    <select
                      className="form-select"
                      value={mlForm.sampleWeighting}
                      onChange={(e) =>
                        setMlForm((prev) => ({
                          ...prev,
                          sampleWeighting: e.target.value,
                        }))
                      }
                    >
                      <option value="none">{t("projects.ml.sampleWeightingNone")}</option>
                      <option value="dollar_volume">
                        {t("projects.ml.sampleWeightingDollarVolume")}
                      </option>
                      <option value="market_cap">
                        {t("projects.ml.sampleWeightingMarketCap")}
                      </option>
                      <option value="mcap_dv_mix">{t("projects.ml.sampleWeightingMix")}</option>
                    </select>
                    <div className="form-hint">{t("projects.ml.sampleWeightingHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.sampleWeightAlpha")}</label>
                    <input
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      className="form-input"
                      value={mlForm.sampleWeightAlpha}
                      onChange={(e) =>
                        setMlForm((prev) => ({
                          ...prev,
                          sampleWeightAlpha: e.target.value,
                        }))
                      }
                    />
                    <div className="form-hint">{t("projects.ml.sampleWeightAlphaHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">
                      {t("projects.ml.sampleWeightDvWindow")}
                    </label>
                    <input
                      type="number"
                      min={1}
                      className="form-input"
                      value={mlForm.sampleWeightDvWindowDays}
                      onChange={(e) =>
                        setMlForm((prev) => ({
                          ...prev,
                          sampleWeightDvWindowDays: e.target.value,
                        }))
                      }
                    />
                    <div className="form-hint">{t("projects.ml.sampleWeightDvWindowHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.pitMissingPolicy")}</label>
                    <select
                      className="form-select"
                      value={mlForm.pitMissingPolicy}
                      onChange={(e) =>
                        setMlForm((prev) => ({
                          ...prev,
                          pitMissingPolicy: e.target.value,
                        }))
                      }
                    >
                      <option value="fill_zero">
                        {t("projects.ml.pitMissingPolicyFillZero")}
                      </option>
                      <option value="drop">
                        {t("projects.ml.pitMissingPolicyDrop")}
                      </option>
                    </select>
                    <div className="form-hint">{t("projects.ml.pitMissingPolicyHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.pitSampleOnSnapshot")}</label>
                    <label className="switch">
                      <input
                        type="checkbox"
                        checked={!!mlForm.pitSampleOnSnapshot}
                        onChange={(e) =>
                          setMlForm((prev) => ({
                            ...prev,
                            pitSampleOnSnapshot: e.target.checked,
                          }))
                        }
                      />
                      <span className="slider" />
                    </label>
                    <div className="form-hint">{t("projects.ml.pitSampleOnSnapshotHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.pitMinCoverage")}</label>
                    <input
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      className="form-input"
                      value={mlForm.pitMinCoverage}
                      onChange={(e) =>
                        setMlForm((prev) => ({
                          ...prev,
                          pitMinCoverage: e.target.value,
                        }))
                      }
                    />
                    <div className="form-hint">{t("projects.ml.pitMinCoverageHint")}</div>
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
                <div className="card-title">{t("projects.ml.sweep.title")}</div>
                <div className="card-meta">{t("projects.ml.sweep.meta")}</div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.sweep.paramKey")}</label>
                    <input
                      className="form-input"
                      value={mlSweep.paramKey}
                      onChange={(e) =>
                        setMlSweep((prev) => ({ ...prev, paramKey: e.target.value }))
                      }
                      placeholder={t("projects.ml.sweep.paramKeyPlaceholder")}
                    />
                    <div className="form-hint">{t("projects.ml.sweep.paramHint")}</div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.sweep.start")}</label>
                    <input
                      type="number"
                      step="0.0001"
                      className="form-input"
                      value={mlSweep.start}
                      onChange={(e) =>
                        setMlSweep((prev) => ({ ...prev, start: e.target.value }))
                      }
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.sweep.end")}</label>
                    <input
                      type="number"
                      step="0.0001"
                      className="form-input"
                      value={mlSweep.end}
                      onChange={(e) =>
                        setMlSweep((prev) => ({ ...prev, end: e.target.value }))
                      }
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.ml.sweep.step")}</label>
                    <input
                      type="number"
                      step="0.0001"
                      className="form-input"
                      value={mlSweep.step}
                      onChange={(e) =>
                        setMlSweep((prev) => ({ ...prev, step: e.target.value }))
                      }
                    />
                    <div className="form-hint">{t("projects.ml.sweep.stepHint")}</div>
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={mlSweep.includeEnd}
                      onChange={(e) =>
                        setMlSweep((prev) => ({ ...prev, includeEnd: e.target.checked }))
                      }
                    />
                    {t("projects.ml.sweep.includeEnd")}
                  </label>
                  <div className="form-row" style={{ gridColumn: "1 / -1" }}>
                    <div className="form-hint">
                      {t("projects.ml.sweep.preview", {
                        count: mlSweepPreview.values.length,
                        values: mlSweepPreview.values.join(", "),
                      })}
                    </div>
                    <div className="form-hint">
                      {t("projects.ml.sweep.backtestPreset", {
                        preset: pipelineBacktestPreset,
                      })}
                    </div>
                  </div>
                  {mlSweepPreview.error && (
                    <div className="form-error">{mlSweepPreview.error}</div>
                  )}
                  {mlSweepMessage && <div className="form-hint">{mlSweepMessage}</div>}
                  <button
                    className="button-secondary"
                    onClick={createMlSweepJobs}
                    disabled={
                      mlSweepLoading ||
                      !!mlSweepPreview.error ||
                      mlSweepPreview.values.length === 0
                    }
                  >
                    {mlSweepLoading
                      ? t("common.actions.loading")
                      : t("projects.ml.sweep.action")}
                  </button>
                </div>
                <div className="section-divider" />
                {mlJobs.length ? (
                  <>
                    <div className="table-scroll">
                      <table className="table ml-train-table">
                        <thead>
                          <tr>
                            <th>{t("projects.ml.table.id")}</th>
                            <th>{t("projects.ml.table.status")}</th>
                            <th>{t("projects.ml.table.progress")}</th>
                            <th>{t("projects.ml.table.window")}</th>
                            <th>{t("projects.ml.table.range")}</th>
                            <th>{t("projects.ml.table.model")}</th>
                            <th>{t("projects.ml.table.horizon")}</th>
                            <th>{t("projects.ml.table.symbols")}</th>
                            <th>{t("projects.ml.table.createdAt")}</th>
                            <th>{t("projects.ml.table.actions")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mlJobsPaged.map((job) => {
                            const cfg = job.config || {};
                            const walk = (cfg.walk_forward || {}) as Record<string, any>;
                            const modelType = cfg.model_type || cfg.model?.type || "torch_mlp";
                            const symbolCount =
                              cfg.meta?.symbol_count ?? (cfg.symbols?.length ?? 0);
                            const symbolSource = cfg.meta?.symbol_source || "project";
                            const symbolSourceKey = cfg.meta?.symbol_source_key;
                            const symbolSourceLabel =
                              symbolSource === "system_theme"
                                ? `${t("projects.ml.symbolSourceSystemShort")}:${
                                    symbolSourceKey || "-"
                                  }`
                                : t("projects.ml.symbolSourceProjectShort");
                            const symbolSourceTitle =
                              symbolSource === "system_theme"
                                ? `${t("projects.ml.symbolSourceSystem")}: ${
                                    symbolSourceKey || "-"
                                  }`
                                : t("projects.ml.symbolSourceProject");
                            const ranges = mlTrainRangeDetail(job);
                            const trainLabel = t("projects.ml.table.trainRangeShort");
                            const validLabel = t("projects.ml.table.validRangeShort");
                            const testLabel = t("projects.ml.table.testRangeShort");
                            const trainDisplay = formatYearRangeCompact(ranges.train);
                            const validDisplay = formatYearRangeCompact(ranges.valid);
                            const testDisplay = formatYearRangeCompact(ranges.test);
                            return (
                              <tr key={job.id}>
                                <td>{`#${job.id}`}</td>
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
                                  {walk.train_years ? `${walk.train_years}Y` : "-"}
                                  {"/"}
                                  {walk.valid_months ? `${walk.valid_months}M` : "-"}
                                  {"/"}
                                  {walk.test_months ? `${walk.test_months}M` : "-"}
                                </td>
                                <td className="ml-range-cell">
                                  <div className="ml-range-inline">
                                    <span title={`${t("projects.ml.table.trainRange")}: ${ranges.train}`}>
                                      {trainLabel}
                                      {trainDisplay}
                                    </span>
                                    <span title={`${t("projects.ml.table.validRange")}: ${ranges.valid}`}>
                                      {validLabel}
                                      {validDisplay}
                                    </span>
                                    <span title={`${t("projects.ml.table.testRange")}: ${ranges.test}`}>
                                      {testLabel}
                                      {testDisplay}
                                    </span>
                                  </div>
                                </td>
                                <td>{String(modelType)}</td>
                                <td>{cfg.label_horizon_days ?? "-"}</td>
                                <td className="ml-symbol-cell">
                                  <div className="ml-symbol-wrap">
                                    <div>{symbolCount || "-"}</div>
                                    <div className="ml-symbol-source" title={symbolSourceTitle}>
                                      {symbolSourceLabel}
                                    </div>
                                  </div>
                                </td>
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
                    <PaginationBar
                      page={mlJobPage}
                      pageSize={mlJobPageSize}
                      total={mlJobTotal}
                      onPageChange={setMlJobPage}
                      onPageSizeChange={(size) => {
                        setMlJobPage(1);
                        setMlJobPageSize(size);
                      }}
                    />
                  </>
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
                      <span>{t("projects.ml.symbolSource")}</span>
                      <strong>
                        {mlDetailSymbolSource.source === "system_theme"
                          ? `${t("projects.ml.symbolSourceSystem")}: ${
                              mlDetailSymbolSource.key || "-"
                            }`
                          : t("projects.ml.symbolSourceProject")}
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
                    <div className="meta-row meta-row-block">
                      <span>{t("projects.ml.detailConfig")}</span>
                      <pre className="ml-config-block">
                        {formatConfigJson(mlDetailJob.config ?? {})}
                      </pre>
                    </div>
                    {mlCurveMetric !== "-" && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailMetric")}</span>
                        <strong>{mlCurveMetric}</strong>
                      </div>
                    )}
                    {mlBestScore !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailBestScore")}</span>
                        <strong>{formatNumber(mlBestScore)}</strong>
                      </div>
                    )}
                    {mlQualityScore !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailQualityScore")}</span>
                        <strong>{formatNumber(mlQualityScore)}</strong>
                      </div>
                    )}
                    {mlCurveGap !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailCurveGap")}</span>
                        <strong>{formatNumber(mlCurveGap)}</strong>
                      </div>
                    )}
                    {mlNdcg10 !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailNdcg10")}</span>
                        <strong>{formatNumber(mlNdcg10)}</strong>
                      </div>
                    )}
                    {mlNdcg50 !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailNdcg50")}</span>
                        <strong>{formatNumber(mlNdcg50)}</strong>
                      </div>
                    )}
                    {mlNdcg100 !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailNdcg100")}</span>
                        <strong>{formatNumber(mlNdcg100)}</strong>
                      </div>
                    )}
                    {mlIC !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailIc")}</span>
                        <strong>{formatNumber(mlIC)}</strong>
                      </div>
                    )}
                    {mlRankIC !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailRankIc")}</span>
                        <strong>{formatNumber(mlRankIC)}</strong>
                      </div>
                    )}
                    {mlBestLoss !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailBestLoss")}</span>
                        <strong>{formatNumber(mlBestLoss)}</strong>
                      </div>
                    )}
                    {mlBestIteration !== null && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailBestIteration")}</span>
                        <strong>{Math.round(mlBestIteration)}</strong>
                      </div>
                    )}
                    {mlDetailJob.message && (
                      <div className="meta-row">
                        <span>{t("projects.ml.detailMessage")}</span>
                        <strong>{mlDetailJob.message}</strong>
                      </div>
                    )}
                  </div>
                )}
                {mlCurve && (
                  <div style={{ marginTop: "12px" }}>
                    {renderMlCurve(mlCurve)}
                  </div>
                )}
              </div>
              <div className="card algorithm-top-decision">
                <div className="card-title">{t("projects.decision.title")}</div>
                <div className="card-meta">{t("projects.decision.meta")}</div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">{t("projects.decision.trainJob")}</label>
                    <select
                      className="form-select"
                      value={decisionTrainJobId}
                      onChange={(e) => setDecisionTrainJobId(e.target.value)}
                    >
                      <option value="">{t("projects.decision.trainJobAuto")}</option>
                      {mlJobs.map((job) => (
                        <option key={job.id} value={job.id}>
                          #{job.id} · {mlStatusLabel(job.status)}
                        </option>
                      ))}
                    </select>
                    <div className="form-hint">
                      {t("projects.decision.trainJobHint", {
                        id: decisionTrainJobId || mlActiveJob?.id || "-",
                      })}
                    </div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.decision.snapshotDate")}</label>
                    <input
                      type="date"
                      className="form-input"
                      value={decisionSnapshotDate}
                      onChange={(e) => setDecisionSnapshotDate(e.target.value)}
                    />
                    <div className="form-hint">{t("projects.decision.snapshotHint")}</div>
                  </div>
                </div>
                <div className="form-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={previewDecisionSnapshot}
                    disabled={!selectedProjectId || decisionLoading}
                  >
                    {decisionLoading
                      ? t("common.actions.loading")
                      : t("projects.decision.preview")}
                  </button>
                  <button
                    type="button"
                    className="button-primary"
                    onClick={runDecisionSnapshot}
                    disabled={!selectedProjectId || decisionLoading}
                    data-testid="decision-snapshot-run"
                  >
                    {decisionLoading
                      ? t("common.actions.loading")
                      : t("projects.decision.run")}
                  </button>
                </div>
                {decisionMessage && (
                  <div className="form-hint" data-testid="decision-snapshot-message">
                    {decisionMessage}
                  </div>
                )}
                {decisionData ? (
                  <>
                    <div className="section-divider" />
                    <div className="meta-list">
                      <div className="meta-row">
                        <span>{t("projects.decision.source")}</span>
                        <strong>
                          {decisionPreview
                            ? t("projects.decision.sourcePreview")
                            : t("projects.decision.sourceLatest")}
                        </strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.status")}</span>
                        <strong>{decisionData.status || "-"}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.snapshotDate")}</span>
                        <strong data-testid="decision-snapshot-today">
                          {decisionSummary?.snapshot_date || "-"}
                        </strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.asOf")}</span>
                        <strong>{decisionSummary?.as_of_time || "-"}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.scoreDate")}</span>
                        <strong>{decisionSummary?.score_date || "-"}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.activeCount")}</span>
                        <strong>{decisionSummary?.active_count ?? 0}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.selectedCount")}</span>
                        <strong>{decisionSummary?.selected_count ?? 0}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.filteredCount")}</span>
                        <strong>{decisionSummary?.filtered_count ?? 0}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.riskOff")}</span>
                        <strong>
                          {decisionSummary?.risk_off
                            ? t("common.boolean.true")
                            : t("common.boolean.false")}
                        </strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.riskOffReason")}</span>
                        <strong>{decisionSummary?.risk_off_reason || "-"}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.cashWeight")}</span>
                        <strong>{decisionSummary?.cash_weight ?? "-"}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.maxExposure")}</span>
                        <strong>{decisionSummary?.max_exposure ?? "-"}</strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.decision.scorePath")}</span>
                        <strong>{decisionSummary?.score_csv_path || "-"}</strong>
                      </div>
                    </div>
                    {decisionFilterCounts.length ? (
                      <>
                        <div className="section-divider" />
                        <div className="card-title">{t("projects.decision.filterStats")}</div>
                        <div className="meta-list decision-filter-list">
                          {decisionFilterCounts.map(([key, value]) => (
                            <div className="meta-row" key={key}>
                              <span>{key}</span>
                              <strong>{value}</strong>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : null}
                    <div className="section-divider" />
                    <div className="decision-toolbar">
                      <div className="segmented">
                        <button
                          type="button"
                          className={decisionMode === "selected" ? "active" : ""}
                          onClick={() => setDecisionMode("selected")}
                        >
                          {t("projects.decision.tabSelected")}
                        </button>
                        <button
                          type="button"
                          className={decisionMode === "filtered" ? "active" : ""}
                          onClick={() => setDecisionMode("filtered")}
                        >
                          {t("projects.decision.tabFiltered")}
                        </button>
                      </div>
                    </div>
                    <div className="table-scroll decision-table-scroll">
                      <table className="table decision-table">
                        <thead>
                          <tr>
                            <th>{t("projects.decision.table.rank")}</th>
                            <th>{t("projects.decision.table.symbol")}</th>
                            <th>{t("projects.decision.table.score")}</th>
                            <th>{t("projects.decision.table.weight")}</th>
                            <th>{t("projects.decision.table.theme")}</th>
                            <th>{t("projects.decision.table.reason")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {decisionItems.length ? (
                            decisionItems.map((item, index) => (
                              <tr key={`${item.symbol}-${index}`}>
                                <td>{item.rank ?? "-"}</td>
                                <td>
                                  <a
                                    className="decision-symbol"
                                    href={buildYahooUrl(item.symbol)}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    {item.symbol}
                                  </a>
                                  {item.company_name ? (
                                    <span
                                      className="decision-company"
                                      title={item.company_name}
                                    >
                                      {item.company_name}
                                    </span>
                                  ) : null}
                                </td>
                                <td>{formatNumber(item.score ?? null)}</td>
                                <td>{formatNumber(item.weight ?? null)}</td>
                                <td>{item.theme || "-"}</td>
                                <td>{item.reason || "-"}</td>
                              </tr>
                            ))
                          ) : (
                            <tr>
                              <td colSpan={6}>{t("projects.decision.table.empty")}</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <div className="empty-state">{t("projects.decision.empty")}</div>
                )}
              </div>
              <div className="card algorithm-top-pipeline">
                <div className="card-title">{t("projects.pipeline.title")}</div>
                <div className="card-meta">{t("projects.pipeline.meta")}</div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">{t("projects.pipeline.name")}</label>
                    <input
                      className="form-input"
                      value={pipelineForm.name}
                      onChange={(e) =>
                        setPipelineForm((prev) => ({ ...prev, name: e.target.value }))
                      }
                      placeholder={t("projects.pipeline.nameHint")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.pipeline.notes")}</label>
                    <input
                      className="form-input"
                      value={pipelineForm.notes}
                      onChange={(e) =>
                        setPipelineForm((prev) => ({ ...prev, notes: e.target.value }))
                      }
                      placeholder={t("projects.pipeline.notesHint")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("projects.pipeline.sort")}</label>
                    <select
                      className="form-select"
                      value={pipelineSort}
                      onChange={(e) => setPipelineSort(e.target.value)}
                    >
                      <option value="id_desc">
                        {t("projects.pipeline.sortIdDesc")}
                      </option>
                      <option value="combined_desc">
                        {t("projects.pipeline.sortCombined")}
                      </option>
                      <option value="train_desc">{t("projects.pipeline.sortTrain")}</option>
                      <option value="backtest_desc">
                        {t("projects.pipeline.sortBacktest")}
                      </option>
                      <option value="created_asc">{t("projects.pipeline.sortCreated")}</option>
                    </select>
                  </div>
                  <div className="meta-row">
                    <span>{t("projects.pipeline.current")}</span>
                    <strong>
                      {activePipeline
                        ? `#${activePipeline.id} ${activePipeline.name || t("projects.pipeline.untitled")}`
                        : t("projects.pipeline.none")}
                    </strong>
                  </div>
                  {pipelineMessage && <div className="form-hint">{pipelineMessage}</div>}
                  <button
                    className="button-primary"
                    onClick={() => createPipeline(buildPipelineBacktestPayload())}
                    disabled={pipelineLoading}
                  >
                    {pipelineLoading
                      ? t("common.actions.loading")
                      : t("projects.pipeline.create")}
                  </button>
                </div>
                <div className="section-divider" />
                {renderSharedBacktestTemplate({ showTarget: true })}
                {sortedPipelines.length ? (
                  <div className="table-scroll" style={{ marginTop: "12px" }}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>{t("projects.pipeline.table.id")}</th>
                          <th>{t("projects.pipeline.table.name")}</th>
                          <th>{t("projects.pipeline.table.trainScore")}</th>
                          <th>{t("projects.pipeline.table.backtestScore")}</th>
                          <th>{t("projects.pipeline.table.combinedScore")}</th>
                          <th>{t("projects.pipeline.table.trainCount")}</th>
                          <th>{t("projects.pipeline.table.backtestCount")}</th>
                          <th>{t("projects.pipeline.table.createdAt")}</th>
                          <th>{t("projects.pipeline.table.actions")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedPipelines.map((pipeline) => (
                          <tr key={pipeline.id}>
                            <td>
                              <div className="ml-status-cell">
                                <span>#{pipeline.id}</span>
                                {pipeline.id === activePipelineId && (
                                  <span className="badge">{t("projects.pipeline.active")}</span>
                                )}
                              </div>
                            </td>
                            <td>{pipeline.name || t("projects.pipeline.untitled")}</td>
                            <td>{formatNumber(pipeline.best_train_score ?? null)}</td>
                            <td>{formatNumber(pipeline.best_backtest_score ?? null)}</td>
                            <td>{formatNumber(pipeline.combined_score ?? null)}</td>
                            <td>{pipeline.train_job_count ?? 0}</td>
                            <td>{pipeline.backtest_count ?? 0}</td>
                            <td>{formatDateTime(pipeline.created_at)}</td>
                            <td className="ml-actions-cell">
                              <div className="table-actions">
                                <button
                                  className="link-button"
                                  type="button"
                                  onClick={() => setPipelineDetailId(pipeline.id)}
                                >
                                  {t("projects.pipeline.detail")}
                                </button>
                                <button
                                  className="link-button"
                                  type="button"
                                  onClick={() => setActivePipelineId(pipeline.id)}
                                >
                                  {t("projects.pipeline.use")}
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="empty-state">{t("projects.pipeline.empty")}</div>
                )}
                {pipelineDetail && (
                  <div style={{ marginTop: "12px" }}>
                    <div className="meta-list">
                      <div className="meta-row">
                        <span>{t("projects.pipeline.detailTitle")}</span>
                        <strong>
                          #{pipelineDetail.id}{" "}
                          {pipelineDetail.name || t("projects.pipeline.untitled")}
                        </strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.pipeline.detailTrainScore")}</span>
                        <strong>
                          {formatNumber(pipelineDetail.train_score_summary?.best_score ?? null)}
                        </strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.pipeline.detailBacktestScore")}</span>
                        <strong>
                          {formatNumber(
                            pipelineDetail.backtest_score_summary?.best_score ?? null
                          )}
                        </strong>
                      </div>
                      <div className="meta-row">
                        <span>{t("projects.pipeline.detailCombinedScore")}</span>
                        <strong>
                          {formatNumber(
                            pipelineDetail.backtest_score_summary?.combined_score ?? null
                          )}
                        </strong>
                      </div>
                    </div>
                    <div className="section-divider" />
                    <div className="card-title">
                      {t("projects.pipeline.backtest.summary")}
                    </div>
                    {pipelineBacktestSummary.length ? (
                      <div className="meta-list">
                        {pipelineBacktestSummary.map((item) => (
                          <div className="meta-row" key={item.key}>
                            <span>{item.label}</span>
                            <strong>{formatBacktestParamValue(item.value)}</strong>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="empty-state">
                        {t("projects.pipeline.backtest.empty")}
                      </div>
                    )}
                    {pipelineSweepInfo && (
                      <>
                        <div className="section-divider" />
                        <div className="card-title">{t("projects.ml.sweep.summaryTitle")}</div>
                        <div className="meta-list">
                          <div className="meta-row">
                            <span>{t("projects.ml.sweep.summaryParam")}</span>
                            <strong>{pipelineSweepInfo.paramKey}</strong>
                          </div>
                          <div className="meta-row">
                            <span>{t("projects.ml.sweep.summaryRange")}</span>
                            <strong>
                              {pipelineSweepInfo.start ?? "-"} ~ {pipelineSweepInfo.end ?? "-"} /{" "}
                              {pipelineSweepInfo.step ?? "-"}
                            </strong>
                          </div>
                          {pipelineSweepBest && (
                            <div className="meta-row">
                              <span>{t("projects.ml.sweep.best")}</span>
                              <strong>
                                {pipelineSweepBest.paramKey}={formatSweepParamValue(
                                  pipelineSweepBest.paramValue
                                )}{" "}
                                · {t("projects.ml.sweep.bestScore", { score: formatNumber(pipelineSweepBest.score) })}
                              </strong>
                            </div>
                          )}
                        </div>
                      </>
                    )}
                    <div className="section-divider" />
                    <div className="card-title">{t("projects.pipeline.trainListTitle")}</div>
                    {pipelineDetail.train_jobs?.length ? (
                      <div className="table-scroll" style={{ marginTop: "8px" }}>
                        <table className="table pipeline-train-table">
                          <thead>
                            <tr>
                              <th className="pipeline-train-id">
                                {t("projects.pipeline.trainTable.id")}
                              </th>
                              {pipelineSweepInfo?.paramKey && (
                                <th className="pipeline-train-param">
                                  {t("projects.pipeline.trainTable.param", {
                                    param: pipelineSweepInfo.paramKey,
                                  })}
                                </th>
                              )}
                              <th className="pipeline-train-status">
                                {t("projects.pipeline.trainTable.status")}
                              </th>
                              <th className="pipeline-train-num">
                                {t("projects.pipeline.trainTable.quality")}
                              </th>
                              <th className="pipeline-train-num">
                                {t("projects.pipeline.trainTable.ndcg10")}
                              </th>
                              <th className="pipeline-train-num">
                                {t("projects.pipeline.trainTable.ndcg50")}
                              </th>
                              <th className="pipeline-train-num">
                                {t("projects.pipeline.trainTable.ndcg100")}
                              </th>
                              <th className="pipeline-train-num">
                                {t("projects.pipeline.trainTable.ic")}
                              </th>
                              <th className="pipeline-train-num">
                                {t("projects.pipeline.trainTable.rankIc")}
                              </th>
                              <th className="pipeline-train-num">
                                {t("projects.pipeline.trainTable.curveGap")}
                              </th>
                              <th className="pipeline-train-created">
                                {t("projects.pipeline.trainTable.createdAt")}
                              </th>
                              <th className="pipeline-train-actions">
                                {t("projects.pipeline.trainTable.actions")}
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {pipelineDetail.train_jobs.map((job) => (
                              <tr key={job.id}>
                                <td className="pipeline-train-id">#{job.id}</td>
                                {pipelineSweepInfo?.paramKey && (
                                  <td className="pipeline-train-param">
                                    <div className="ml-status-cell">
                                      <span>
                                        {formatSweepParamValue(
                                          resolveJobModelParam(job, pipelineSweepInfo.paramKey)
                                        )}
                                      </span>
                                      {pipelineSweepBest?.jobId === job.id && (
                                        <span className="badge">
                                          {t("projects.ml.sweep.bestBadge")}
                                        </span>
                                      )}
                                    </div>
                                  </td>
                                  )}
                                <td className="pipeline-train-status">
                                  {mlStatusLabel(job.status)}
                                </td>
                                <td className="pipeline-train-num">
                                  {formatNumber(resolveJobMetric(job, "quality_score"))}
                                </td>
                                <td className="pipeline-train-num">
                                  {formatNumber(resolveJobMetric(job, "ndcg_at_10"))}
                                </td>
                                <td className="pipeline-train-num">
                                  {formatNumber(resolveJobMetric(job, "ndcg_at_50"))}
                                </td>
                                <td className="pipeline-train-num">
                                  {formatNumber(resolveJobMetric(job, "ndcg_at_100"))}
                                </td>
                                <td className="pipeline-train-num">
                                  {formatNumber(resolveJobMetric(job, "ic"))}
                                </td>
                                <td className="pipeline-train-num">
                                  {formatNumber(resolveJobMetric(job, "rank_ic"))}
                                </td>
                                <td className="pipeline-train-num">
                                  {formatNumber(resolveJobMetric(job, "curve_gap"))}
                                </td>
                                <td className="pipeline-train-created">
                                  {formatDateTime(job.created_at)}
                                </td>
                                <td className="pipeline-train-actions">
                                  {job.status === "success" ? (
                                    <div className="table-actions">
                                      <button
                                        className="link-button"
                                        type="button"
                                        onClick={() =>
                                          runPipelineBacktest({
                                            saveTemplate: false,
                                            trainJob: job,
                                          })
                                        }
                                        disabled={pipelineBacktestRunning}
                                      >
                                        {t("projects.pipeline.trainTable.backtest")}
                                      </button>
                                    </div>
                                  ) : (
                                    "-"
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="empty-state">{t("projects.pipeline.trainEmpty")}</div>
                    )}
                    <div className="section-divider" />
                    <div className="card-title">{t("projects.pipeline.backtestListTitle")}</div>
                    {pipelineDetail.backtests?.length ? (
                      <div className="table-scroll" style={{ marginTop: "8px" }}>
                        <table className="table pipeline-backtest-table">
                          <thead>
                            <tr>
                              <th className="pipeline-backtest-id">
                                {t("projects.pipeline.backtestTable.id")}
                              </th>
                              <th className="pipeline-backtest-train">
                                {t("projects.pipeline.backtestTable.trainId")}
                              </th>
                              <th className="pipeline-backtest-status">
                                {t("projects.pipeline.backtestTable.status")}
                              </th>
                              <th className="pipeline-backtest-num">
                                {t("projects.pipeline.backtestTable.cagr")}
                              </th>
                              <th className="pipeline-backtest-num">
                                {t("projects.pipeline.backtestTable.sharpe")}
                              </th>
                              <th className="pipeline-backtest-num">
                                {t("projects.pipeline.backtestTable.drawdown")}
                              </th>
                              <th className="pipeline-backtest-num">
                                {t("projects.pipeline.backtestTable.turnover")}
                              </th>
                              <th className="pipeline-backtest-num">
                                {t("projects.pipeline.backtestTable.score")}
                              </th>
                              <th className="pipeline-backtest-created">
                                {t("projects.pipeline.backtestTable.createdAt")}
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {pipelineDetail.backtests.map((run) => {
                              const params = run.params as Record<string, any> | null | undefined;
                              const trainId =
                                params?.pipeline_train_job_id ??
                                params?.ml_train_job_id ??
                                params?.train_job_id;
                              return (
                                <tr key={run.id}>
                                  <td className="pipeline-backtest-id">#{run.id}</td>
                                  <td className="pipeline-backtest-train">
                                    {trainId ? `#${trainId}` : "-"}
                                  </td>
                                  <td className="pipeline-backtest-status">{run.status}</td>
                                  <td className="pipeline-backtest-num">
                                    {String(run.metrics?.["Compounding Annual Return"] ?? "-")}
                                  </td>
                                  <td className="pipeline-backtest-num">
                                    {String(run.metrics?.["Sharpe Ratio"] ?? "-")}
                                  </td>
                                  <td className="pipeline-backtest-num">
                                    {String(run.metrics?.["Drawdown"] ?? "-")}
                                  </td>
                                  <td className="pipeline-backtest-num">
                                    {String(run.metrics?.["Turnover_week"] ?? "-")}
                                  </td>
                                  <td className="pipeline-backtest-num">
                                    {formatNumber(run.score ?? null)}
                                  </td>
                                  <td className="pipeline-backtest-created">
                                    {formatDateTime(run.created_at)}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="empty-state">
                        {t("projects.pipeline.backtestEmpty")}
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
            {renderSharedBacktestTemplate()}
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
                <div className="meta-row">
                  <span>{t("projects.backtest.trainJob")}</span>
                  <strong>
                    {latestBacktestTrainJobId
                      ? `#${latestBacktestTrainJobId}`
                      : t("common.none")}
                  </strong>
                </div>
                <div className="meta-row">
                  <span>{t("projects.backtest.scorePath")}</span>
                  <strong>{latestBacktestScorePath || t("common.none")}</strong>
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
