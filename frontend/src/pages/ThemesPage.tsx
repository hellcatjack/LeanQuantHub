import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { Paginated } from "../types";

interface Project {
  id: number;
  name: string;
  description?: string | null;
  created_at: string;
}

interface ThemeConfigItem {
  key: string;
  label: string;
  weight: number;
  keywords?: string[];
  manual?: string[];
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
  manual_symbols?: string[];
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
  manual_symbols?: string[];
}

interface ThemeSearchItem {
  key: string;
  label: string;
  is_manual?: boolean;
}

interface ProjectThemeSearch {
  project_id: number;
  symbol: string;
  themes: ThemeSearchItem[];
}

export default function ThemesPage() {
  const { t } = useI18n();
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

  const normalizeThemeDrafts = (config: ProjectConfig): ThemeConfigItem[] => {
    if (config.themes && config.themes.length) {
      return config.themes.map((item) => ({
        key: item.key || "",
        label: item.label || item.key || "",
        weight: Number(item.weight ?? config.weights?.[item.key] ?? 0),
        keywords: item.keywords || [],
        manual: item.manual || [],
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
      keywords: [],
      manual: [],
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

  const updateTheme = (
    index: number,
    field: "key" | "label" | "weight" | "keywords" | "manual",
    value: string | number
  ) => {
    setThemeDrafts((prev) =>
      prev.map((item, idx) => {
        if (idx !== index) {
          return item;
        }
        if (field === "keywords" || field === "manual") {
          return { ...item, [field]: parseListInput(String(value)) };
        }
        if (field === "weight") {
          return { ...item, weight: Number(value) || 0 };
        }
        return { ...item, [field]: String(value) };
      })
    );
  };

  const addTheme = () => {
    setThemeDrafts((prev) => [
      ...prev,
      { key: "", label: "", weight: 0, keywords: [], manual: [] },
    ]);
  };

  const removeTheme = (index: number) => {
    setThemeDrafts((prev) => prev.filter((_, idx) => idx !== index));
  };

  const saveProjectConfig = async () => {
    if (!selectedProjectId || !configDraft) {
      return;
    }
    const themePayload = themeDrafts
      .map((theme) => ({
        key: theme.key.trim(),
        label: theme.label.trim() || theme.key.trim(),
        weight: Number(theme.weight) || 0,
        keywords: theme.keywords || [],
        manual: theme.manual || [],
      }))
      .filter((theme) => theme.key);
    const keys = themePayload.map((theme) => theme.key);
    if (new Set(keys).size !== keys.length) {
      setConfigMessage(t("projects.config.themeDuplicate"));
      return;
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
    try {
      await api.post(`/api/projects/${selectedProjectId}/config`, {
        config: payloadConfig,
        version: new Date().toISOString(),
      });
      setConfigMessage(t("projects.config.saved"));
      await loadProjectConfig(selectedProjectId);
      await loadThemeSummary(selectedProjectId);
    } catch (err) {
      setConfigMessage(t("projects.config.error"));
    }
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
    const rows = ["symbol", ...filteredActiveSymbols];
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
    }
  }, [selectedProjectId]);

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
  const activeManualSet = useMemo(
    () => new Set(activeThemeSymbols?.manual_symbols || []),
    [activeThemeSymbols]
  );
  const activeSymbols = activeThemeSymbols?.symbols || [];
  const filteredActiveSymbols = useMemo(() => {
    const keyword = themeSymbolQuery.trim().toUpperCase();
    if (!keyword) {
      return activeSymbols;
    }
    return activeSymbols.filter((symbol) => symbol.includes(keyword));
  }, [activeSymbols, themeSymbolQuery]);
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

  const formatPercent = (value?: number | null) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    return `${(value * 100).toFixed(2)}%`;
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
                <strong>{configMeta?.updated_at || t("common.none")}</strong>
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
                    {themeSummary?.updated_at || t("common.none")}
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
                        <th>{t("projects.config.themeKeywords")}</th>
                        <th>{t("projects.config.themeManual")}</th>
                        <th>{t("projects.config.themeActions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {themeDrafts.length ? (
                        themeDrafts.map((theme, index) => (
                          <tr key={`${theme.key}-${index}`}>
                            <td>
                              <input
                                className="table-input"
                                value={theme.key}
                                onChange={(e) => updateTheme(index, "key", e.target.value)}
                                placeholder={t("projects.config.themeKey")}
                              />
                            </td>
                            <td>
                              <input
                                className="table-input"
                                value={theme.label}
                                onChange={(e) => updateTheme(index, "label", e.target.value)}
                                placeholder={t("projects.config.themeLabel")}
                              />
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
                                value={(theme.keywords || []).join(", ")}
                                onChange={(e) => updateTheme(index, "keywords", e.target.value)}
                                placeholder={t("projects.config.themeKeywords")}
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
                        ))
                      ) : (
                        <tr>
                          <td colSpan={6}>{t("projects.config.themesEmpty")}</td>
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
                                        <button
                                          key={symbol}
                                          type="button"
                                          className="theme-chip"
                                          onClick={() => applyThemeSymbolFilter(symbol)}
                                        >
                                          {symbol}
                                        </button>
                                      ))
                                    : "-"}
                                </div>
                              </td>
                              <td>
                                <div className="theme-samples">
                                  {(item.manual_symbols || []).length
                                    ? (item.manual_symbols || []).map((symbol) => (
                                        <button
                                          key={symbol}
                                          type="button"
                                          className="theme-chip manual"
                                          onClick={() => applyThemeSymbolFilter(symbol)}
                                        >
                                          {symbol}
                                        </button>
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
                          <td colSpan={7}>{t("projects.config.themesEmpty")}</td>
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
                            total: activeThemeSymbols.symbols.length,
                            manual: activeManualSet.size,
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
                    </div>
                    <div className="theme-detail-list">
                      {filteredActiveSymbols.length ? (
                        filteredActiveSymbols.map((symbol) => (
                          <button
                            key={symbol}
                            type="button"
                            className={`theme-chip ${activeManualSet.has(symbol) ? "manual" : ""}`}
                            onClick={() => applyThemeSymbolFilter(symbol)}
                          >
                            {symbol}
                          </button>
                        ))
                      ) : (
                        <span className="theme-detail-empty">
                          {t("projects.config.themeEmptySymbols")}
                        </span>
                      )}
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
                        <button
                          key={symbol}
                          type="button"
                          className="theme-chip"
                          onClick={() => applyThemeSymbolFilter(symbol)}
                        >
                          {symbol}
                        </button>
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
                        <button
                          key={symbol}
                          type="button"
                          className="theme-chip"
                          onClick={() => applyThemeSymbolFilter(symbol)}
                        >
                          {symbol}
                        </button>
                      ))
                    : t("projects.config.themeEmptySymbols")}
                </div>
              </div>
              <div className="theme-compare-block">
                <div className="theme-compare-title">{t("projects.config.themeCompareOnlyB")}</div>
                <div className="theme-compare-list">
                  {compareSets.onlyB.length
                    ? compareSets.onlyB.map((symbol) => (
                        <button
                          key={symbol}
                          type="button"
                          className="theme-chip"
                          onClick={() => applyThemeSymbolFilter(symbol)}
                        >
                          {symbol}
                        </button>
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
