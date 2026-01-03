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

interface ProjectConfig {
  template?: string;
  universe?: { mode?: string; include_history?: boolean };
  data?: { primary_vendor?: string; fallback_vendor?: string; frequency?: string };
  weights?: Record<string, number>;
  benchmark?: string;
  rebalance?: string;
  risk_free_rate?: number;
  categories?: { key: string; label: string }[];
  themes?: ThemeConfigItem[];
  symbol_types?: Record<string, string>;
}

interface SystemThemeItem {
  id: number;
  key: string;
  label: string;
  source: string;
  description?: string | null;
  latest_version_id?: number | null;
  latest_version?: string | null;
  updated_at?: string | null;
}

interface SystemThemePage {
  items: SystemThemeItem[];
  total: number;
  page: number;
  page_size: number;
}

interface ThemeChangeReport {
  id: number;
  project_id: number;
  theme_id: number;
  from_version_id?: number | null;
  to_version_id: number;
  diff?: Record<string, { added?: string[]; removed?: string[] }>;
  created_at: string;
}

interface ThemeChangeReportPage {
  items: ThemeChangeReport[];
  total: number;
  page: number;
  page_size: number;
}

interface ProjectConfigResponse {
  project_id: number;
  config: ProjectConfig;
  source: string;
  updated_at?: string | null;
  version_id?: number | null;
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

export default function ThemesPage() {
  const { t, formatDateTime } = useI18n();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectPage] = useState(1);
  const [projectPageSize] = useState(200);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
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
  const [activeThemeSymbols, setActiveThemeSymbols] = useState<ProjectThemeSymbols | null>(
    null
  );
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
  const [systemThemes, setSystemThemes] = useState<SystemThemeItem[]>([]);
  const [systemThemeMessage, setSystemThemeMessage] = useState("");
  const [systemImportOptions, setSystemImportOptions] = useState<
    Record<number, { mode: string; weight: string }>
  >({});
  const [systemReports, setSystemReports] = useState<ThemeChangeReport[]>([]);
  const [systemReportTotal, setSystemReportTotal] = useState(0);
  const [systemReportPage, setSystemReportPage] = useState(1);
  const [systemReportPageSize, setSystemReportPageSize] = useState(5);
  const [expandedReportIds, setExpandedReportIds] = useState<Record<number, boolean>>(
    {}
  );

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

  const loadProjects = async () => {
    const res = await api.get<Paginated<Project>>("/api/projects/page", {
      params: { page: projectPage, page_size: projectPageSize },
    });
    setProjects(res.data.items);
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

  const loadProjectConfig = async (projectId: number) => {
    try {
      const res = await api.get<ProjectConfigResponse>(`/api/projects/${projectId}/config`);
      setConfigMeta(res.data);
      setConfigDraft(res.data.config || {});
      setThemeDrafts(normalizeThemeDrafts(res.data.config || {}));
      setConfigMessage("");
    } catch (err) {
      setConfigMeta(null);
      setConfigDraft(null);
      setConfigMessage(t("projects.config.error"));
      setThemeDrafts([]);
    }
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
      setSystemThemes(res.data.items || []);
      setSystemThemeMessage("");
    } catch (err) {
      setSystemThemes([]);
      setSystemThemeMessage(t("projects.config.systemThemeError"));
    }
  };

  const loadSystemReports = async (projectId: number) => {
    try {
      const res = await api.get<ThemeChangeReportPage>(
        `/api/system-themes/projects/${projectId}/reports/page`,
        { params: { page: systemReportPage, page_size: systemReportPageSize } }
      );
      setSystemReports(res.data.items || []);
      setSystemReportTotal(res.data.total || 0);
    } catch (err) {
      setSystemReports([]);
      setSystemReportTotal(0);
    }
  };

  const updateSystemImportOption = (
    themeId: number,
    field: "mode" | "weight",
    value: string
  ) => {
    setSystemImportOptions((prev) => ({
      ...prev,
      [themeId]: {
        mode: prev[themeId]?.mode || "follow_latest",
        weight: prev[themeId]?.weight || "",
        [field]: value,
      },
    }));
  };

  const getSystemImportOption = (themeId: number) =>
    systemImportOptions[themeId] || { mode: "follow_latest", weight: "" };

  const importSystemTheme = async (themeId: number) => {
    if (!selectedProjectId) {
      return;
    }
    const option = getSystemImportOption(themeId);
    const payload: {
      theme_id: number;
      mode: string;
      weight?: number;
    } = {
      theme_id: themeId,
      mode: option.mode,
    };
    if (option.weight.trim()) {
      payload.weight = Number(option.weight);
    }
    try {
      await api.post(`/api/system-themes/projects/${selectedProjectId}/import`, payload);
      setSystemThemeMessage(t("projects.config.systemThemeImported"));
      await loadProjectConfig(selectedProjectId);
      await loadThemeSummary(selectedProjectId);
      await loadSystemReports(selectedProjectId);
    } catch (err) {
      setSystemThemeMessage(t("projects.config.systemThemeImportError"));
    }
  };

  const refreshSystemTheme = async (themeId: number) => {
    try {
      await api.post(`/api/system-themes/${themeId}/refresh`, {});
      setSystemThemeMessage(t("projects.config.systemThemeRefreshSuccess"));
      await loadSystemThemes();
      if (selectedProjectId) {
        await loadSystemReports(selectedProjectId);
        await loadThemeSummary(selectedProjectId);
      }
    } catch (err) {
      setSystemThemeMessage(t("projects.config.systemThemeRefreshError"));
    }
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

  const addTheme = () => {
    setThemeDrafts((prev) => [
      ...prev,
      { key: "", label: "", weight: 0, priority: 0, keywords: [], manual: [], exclude: [] },
    ]);
  };

  const removeTheme = (index: number) => {
    setThemeDrafts((prev) => prev.filter((_, idx) => idx !== index));
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

  const closeThemeSymbols = () => {
    setActiveThemeKey("");
    setActiveThemeSymbols(null);
    setThemeSymbolQuery("");
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

  useEffect(() => {
    loadProjects();
    loadSystemThemes();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      loadProjectConfig(selectedProjectId);
      loadThemeSummary(selectedProjectId);
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
      setNewThemeSymbol("");
      setNewThemeSymbolType("STOCK");
      setThemeSymbolMessage("");
      setSystemReportPage(1);
      setSystemThemeMessage("");
    } else {
      setConfigDraft(null);
      setConfigMeta(null);
      setConfigMessage("");
      setThemeDrafts([]);
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
      setNewThemeSymbol("");
      setNewThemeSymbolType("STOCK");
      setThemeSymbolMessage("");
      setSystemThemeMessage("");
      setSystemReports([]);
      setSystemReportTotal(0);
      setSystemReportPage(1);
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId) {
      loadSystemReports(selectedProjectId);
    }
  }, [selectedProjectId, systemReportPage, systemReportPageSize]);

  const selectedProject = useMemo(
    () => projects.find((item) => item.id === selectedProjectId),
    [projects, selectedProjectId]
  );
  const themeRows = themeSummary?.themes || [];
  const weightTotal = useMemo(() => {
    if (!themeDrafts.length) {
      return 0;
    }
    return themeDrafts.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
  }, [themeDrafts]);
  const weightTotalWarn = Math.abs(weightTotal - 1) > 0.02;
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
  }, [themeRows, themeFilterText, themeSearchSymbol, themeSearchKeys, themeSearchResult]);
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
  const systemThemeMap = useMemo(
    () => new Map(systemThemes.map((theme) => [theme.id, theme])),
    [systemThemes]
  );
  const boundSystemThemeIds = useMemo(() => {
    const ids = new Set<number>();
    themeDrafts.forEach((theme) => {
      const id = theme.system?.theme_id;
      if (typeof id === "number") {
        ids.add(id);
      }
    });
    return ids;
  }, [themeDrafts]);
  const formatSymbolLabel = (symbol: string, types: Record<string, string>) => {
    const raw = types[symbol];
    if (!raw) {
      return symbol;
    }
    const label = symbolTypeLabels[normalizeSymbolType(raw)] || symbolTypeLabels.UNKNOWN;
    return `${symbol} · ${label}`;
  };

  const formatPercent = (value?: number | null) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    return `${(value * 100).toFixed(2)}%`;
  };

  const renderDiffSummary = (diff?: ThemeChangeReport["diff"]) => {
    if (!diff) {
      return t("projects.config.systemThemeReportNone");
    }
    const fields = [
      { key: "symbols", label: t("projects.config.systemThemeDiffSymbols") },
      { key: "keywords", label: t("projects.config.systemThemeDiffKeywords") },
      { key: "manual", label: t("projects.config.systemThemeDiffManual") },
      { key: "exclude", label: t("projects.config.systemThemeDiffExclude") },
    ];
    const parts = fields
      .map(({ key, label }) => {
        const added = diff[key]?.added?.length || 0;
        const removed = diff[key]?.removed?.length || 0;
        if (!added && !removed) {
          return null;
        }
        return `${label} +${added}/-${removed}`;
      })
      .filter(Boolean);
    if (!parts.length) {
      return t("projects.config.systemThemeReportNone");
    }
    return parts.join(" · ");
  };

  const toggleReportExpanded = (reportId: number) => {
    setExpandedReportIds((prev) => ({
      ...prev,
      [reportId]: !prev[reportId],
    }));
  };

  const renderDiffList = (items: string[], variant: "added" | "removed") => {
    if (!items.length) {
      return null;
    }
    return (
      <div className="report-diff-list">
        {items.map((item) => (
          <span key={`${variant}-${item}`} className={`theme-chip ${variant}`}>
            {item}
          </span>
        ))}
      </div>
    );
  };

  const renderDiffDetails = (diff?: ThemeChangeReport["diff"]) => {
    if (!diff) {
      return <div className="form-hint">{t("projects.config.systemThemeReportNone")}</div>;
    }
    const fields = [
      { key: "symbols", label: t("projects.config.systemThemeDiffSymbols") },
      { key: "keywords", label: t("projects.config.systemThemeDiffKeywords") },
      { key: "manual", label: t("projects.config.systemThemeDiffManual") },
      { key: "exclude", label: t("projects.config.systemThemeDiffExclude") },
    ];
    const blocks = fields
      .map(({ key, label }) => {
        const added = diff[key]?.added || [];
        const removed = diff[key]?.removed || [];
        if (!added.length && !removed.length) {
          return null;
        }
        return (
          <div key={key} className="report-diff-block">
            <div className="report-diff-header">{label}</div>
            {renderDiffList(added, "added")}
            {renderDiffList(removed, "removed")}
          </div>
        );
      })
      .filter(Boolean);
    if (!blocks.length) {
      return <div className="form-hint">{t("projects.config.systemThemeReportNone")}</div>;
    }
    return <div className="report-diff-grid">{blocks}</div>;
  };

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

  return (
    <div className="main">
      <TopBar title={t("themes.title")} />
      <div className="content">
        <div className="card">
          <div className="card-title">{t("themes.project.title")}</div>
          <div className="card-meta">{t("themes.project.meta")}</div>
          <div className="themes-project-row">
            <div className="themes-project-select">
              <label className="form-label">{t("themes.project.select")}</label>
              <select
                className="form-select"
                value={selectedProjectId ?? ""}
                onChange={(e) => setSelectedProjectId(Number(e.target.value))}
              >
                <option value="">{t("common.noneText")}</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    #{project.id} {project.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="themes-project-info">
              <div className="meta-row">
                <span>{t("themes.project.name")}</span>
                <strong>{selectedProject?.name || t("common.noneText")}</strong>
              </div>
              <div className="meta-row">
                <span>{t("themes.project.description")}</span>
                <strong>{selectedProject?.description || t("common.none")}</strong>
              </div>
              <div className="meta-row">
                <span>{t("themes.project.configSource")}</span>
                <strong>{configMeta?.source || t("common.none")}</strong>
              </div>
              <div className="meta-row">
                <span>{t("common.labels.updatedAt")}</span>
                <strong>{formatDateTime(configMeta?.updated_at)}</strong>
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-title">{t("themes.config.title")}</div>
          <div className="card-meta">{t("themes.config.meta")}</div>
          {!configDraft ? (
            <div className="empty-state">{t("themes.project.empty")}</div>
          ) : (
            <div className="form-grid">
              <div className="theme-summary-grid">
                <div className="theme-summary-card">
                  <div className="theme-summary-label">{t("projects.config.themeCount")}</div>
                  <div className="theme-summary-value">{themeRows.length}</div>
                </div>
                <div className="theme-summary-card">
                  <div className="theme-summary-label">
                    {t("projects.config.themeTotalSymbols")}
                  </div>
                  <div className="theme-summary-value">{themeSummary?.total_symbols ?? 0}</div>
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
                                  onChange={(e) => updateTheme(index, "key", e.target.value)}
                                  placeholder={t("projects.config.themeKey")}
                                  disabled={isSystemTheme}
                                />
                              </td>
                              <td>
                                <div className="theme-label-input">
                                  <input
                                    className="table-input"
                                    value={theme.label}
                                    onChange={(e) => updateTheme(index, "label", e.target.value)}
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
                                onChange={(e) => updateTheme(index, "priority", e.target.value)}
                                placeholder={t("projects.config.themePriority")}
                              />
                            </td>
                            <td>
                              <input
                                className="table-input"
                                value={(theme.keywords || []).join(", ")}
                                onChange={(e) => updateTheme(index, "keywords", e.target.value)}
                                placeholder={t("projects.config.themeKeywords")}
                                disabled={isSystemTheme}
                              />
                            </td>
                            <td>
                              <input
                                className="table-input"
                                value={(theme.manual || []).join(", ")}
                                onChange={(e) => updateTheme(index, "manual", e.target.value)}
                                placeholder={t("projects.config.themeManual")}
                              />
                            </td>
                            <td>
                              <input
                                className="table-input"
                                value={(theme.exclude || []).join(", ")}
                                onChange={(e) => updateTheme(index, "exclude", e.target.value)}
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
              <div className={`meta-row ${weightTotalWarn ? "meta-warn" : ""}`}>
                <span>{t("projects.config.weightTotal")}</span>
                <strong>{formatPercent(weightTotal)}</strong>
              </div>
              {configMessage && <div className="form-hint">{configMessage}</div>}
              <button className="button-primary" onClick={saveProjectConfig}>
                {t("projects.config.save")}
              </button>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">{t("projects.config.systemThemeTitle")}</div>
          <div className="card-meta">{t("projects.config.systemThemeMeta")}</div>
          {systemThemeMessage && <div className="form-hint">{systemThemeMessage}</div>}
          {!systemThemes.length ? (
            <div className="empty-state">{t("projects.config.systemThemeEmpty")}</div>
          ) : (
            <div className="theme-table-wrapper">
              <table className="theme-table system-theme-table">
                <thead>
                  <tr>
                    <th>{t("projects.config.systemThemeLabel")}</th>
                    <th>{t("projects.config.systemThemeSource")}</th>
                    <th>{t("projects.config.systemThemeVersion")}</th>
                    <th>{t("projects.config.systemThemeMode")}</th>
                    <th>{t("projects.config.systemThemeWeight")}</th>
                    <th>{t("projects.config.systemThemeActions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {systemThemes.map((theme) => {
                    const option = getSystemImportOption(theme.id);
                    const bound = boundSystemThemeIds.has(theme.id);
                    return (
                      <tr key={theme.id}>
                        <td>
                          <div className="theme-name">
                            <span className="theme-label">{theme.label}</span>
                            <span className="theme-key">{theme.key}</span>
                          </div>
                        </td>
                        <td>{theme.source || "-"}</td>
                        <td>{formatDateTime(theme.latest_version)}</td>
                        <td>
                          <select
                            className="table-select"
                            value={option.mode}
                            onChange={(e) =>
                              updateSystemImportOption(theme.id, "mode", e.target.value)
                            }
                          >
                            <option value="follow_latest">
                              {t("projects.config.systemThemeModeFollow")}
                            </option>
                            <option value="pin_version">
                              {t("projects.config.systemThemeModePin")}
                            </option>
                            <option value="snapshot">
                              {t("projects.config.systemThemeModeSnapshot")}
                            </option>
                          </select>
                        </td>
                        <td>
                          <input
                            className="table-input"
                            type="number"
                            step="0.01"
                            value={option.weight}
                            onChange={(e) =>
                              updateSystemImportOption(theme.id, "weight", e.target.value)
                            }
                            placeholder="0"
                          />
                        </td>
                        <td className="theme-actions">
                          <button
                            type="button"
                            className="button-secondary"
                            disabled={!selectedProjectId}
                            onClick={() => importSystemTheme(theme.id)}
                          >
                            {bound
                              ? t("projects.config.systemThemeReimport")
                              : t("projects.config.systemThemeImport")}
                          </button>
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => refreshSystemTheme(theme.id)}
                          >
                            {t("projects.config.systemThemeRefresh")}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">{t("projects.config.systemThemeReportTitle")}</div>
          <div className="card-meta">{t("projects.config.systemThemeReportMeta")}</div>
          {!selectedProjectId ? (
            <div className="empty-state">{t("projects.config.systemThemeReportEmpty")}</div>
          ) : (
            <div className="form-grid">
              <div className="theme-table-wrapper">
                <table className="theme-table system-theme-report-table">
                  <thead>
                    <tr>
                      <th>{t("projects.config.systemThemeLabel")}</th>
                      <th>{t("projects.config.systemThemeReportVersion")}</th>
                      <th>{t("projects.config.systemThemeReportDiff")}</th>
                      <th>{t("projects.config.systemThemeReportTime")}</th>
                      <th>{t("projects.config.systemThemeReportActions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {systemReports.length ? (
                      systemReports.map((report) => {
                        const theme = systemThemeMap.get(report.theme_id);
                        const isExpanded = Boolean(expandedReportIds[report.id]);
                        return (
                          <Fragment key={report.id}>
                            <tr>
                              <td>
                                <div className="theme-name">
                                  <span className="theme-label">
                                    {theme?.label || `#${report.theme_id}`}
                                  </span>
                                  <span className="theme-key">{theme?.key || "-"}</span>
                                </div>
                              </td>
                              <td>
                                {report.from_version_id
                                  ? `${report.from_version_id} → ${report.to_version_id}`
                                  : `→ ${report.to_version_id}`}
                              </td>
                              <td>{renderDiffSummary(report.diff)}</td>
                              <td>{formatDateTime(report.created_at)}</td>
                              <td className="theme-actions">
                                <button
                                  type="button"
                                  className="link-button"
                                  onClick={() => toggleReportExpanded(report.id)}
                                >
                                  {isExpanded
                                    ? t("projects.config.systemThemeReportCollapse")
                                    : t("projects.config.systemThemeReportExpand")}
                                </button>
                              </td>
                            </tr>
                            {isExpanded && (
                              <tr className="theme-expand-row report-detail-row">
                                <td colSpan={5}>{renderDiffDetails(report.diff)}</td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })
                    ) : (
                      <tr>
                        <td colSpan={5}>{t("projects.config.systemThemeReportEmpty")}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <PaginationBar
                page={systemReportPage}
                pageSize={systemReportPageSize}
                total={systemReportTotal}
                onPageChange={setSystemReportPage}
                onPageSizeChange={(size) => {
                  setSystemReportPage(1);
                  setSystemReportPageSize(size);
                }}
                pageSizeOptions={[5, 10, 20]}
              />
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">{t("themes.composition.title")}</div>
          <div className="card-meta">{t("themes.composition.meta")}</div>
          {!themeRows.length ? (
            <div className="empty-state">{t("projects.config.themesEmpty")}</div>
          ) : (
            <div className="form-grid">
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
                    <label className="form-label">{t("projects.config.themeSearchSymbol")}</label>
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
                    <div className="form-hint">{t("projects.config.themeSearchHint")}</div>
                  </div>
                </div>
                <div className="theme-toolbar-row theme-toolbar-meta">
                  <span>
                    {t("projects.config.themeSearchMatches", {
                      count: themeSearchResult?.themes.length ?? 0,
                    })}
                  </span>
                  {themeSearchMessage && <span className="form-hint">{themeSearchMessage}</span>}
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
                        <th>{t("projects.config.themeManualShort")}</th>
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
                                      item.symbols / Math.max(themeSummary?.total_symbols ?? 0, 1)
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
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">{t("projects.config.themeCompareTitle")}</div>
          <div className="card-meta">{t("themes.compare.meta")}</div>
          <div className="theme-compare-panel">
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
                <div className="theme-compare-title">{t("projects.config.themeCompareOnlyA")}</div>
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
                <div className="theme-compare-title">{t("projects.config.themeCompareOnlyB")}</div>
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
      </div>
    </div>
  );
}
