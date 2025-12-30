import { useEffect, useMemo, useState } from "react";
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

interface ProjectThematicBacktest {
  project_id: number;
  status: string;
  summary?: Record<string, any> | null;
  updated_at?: string | null;
  source?: string | null;
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
  const { t } = useI18n();
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
  const [configSection, setConfigSection] = useState<
    "universe" | "data" | "themes" | "portfolio"
  >("universe");
  const [dataStatus, setDataStatus] = useState<ProjectDataStatus | null>(null);
  const [dataMessage, setDataMessage] = useState("");
  const [thematicBacktest, setThematicBacktest] = useState<ProjectThematicBacktest | null>(null);
  const [backtestMessage, setBacktestMessage] = useState("");
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [algorithmVersions, setAlgorithmVersions] = useState<AlgorithmVersion[]>([]);
  const [binding, setBinding] = useState<ProjectAlgorithmBinding | null>(null);
  const [bindingForm, setBindingForm] = useState({
    algorithmId: "",
    versionId: "",
    isLocked: true,
  });
  const [bindingMessage, setBindingMessage] = useState("");

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

  const loadThematicBacktest = async (projectId: number) => {
    try {
      const res = await api.get<ProjectThematicBacktest>(
        `/api/projects/${projectId}/thematic-backtest`
      );
      setThematicBacktest(res.data);
    } catch (err) {
      setThematicBacktest(null);
      setBacktestMessage(t("projects.backtest.error"));
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
      loadThematicBacktest(selectedProjectId);
      loadProjectBinding(selectedProjectId);
      setConfigMessage("");
      setDataMessage("");
      setBacktestMessage("");
      setBindingMessage("");
    } else {
      setVersions([]);
      setVersionOptions([]);
      setVersionTotal(0);
      setConfigDraft(null);
      setConfigMeta(null);
      setDataStatus(null);
      setThematicBacktest(null);
      setBinding(null);
    }
  }, [selectedProjectId]);

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
    value: string | number | boolean
  ) => {
    setConfigDraft((prev) => {
      const next = { ...(prev || {}) };
      const sectionValue = { ...(next[section] as Record<string, any> | undefined) };
      sectionValue[key] = value;
      (next as Record<string, any>)[section] = sectionValue;
      return next;
    });
  };

  const addTheme = () => {
    setThemeDrafts((prev) => [
      ...prev,
      { key: "", label: "", weight: 0, keywords: [], manual: [] },
    ]);
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
    } catch (err) {
      setConfigMessage(t("projects.config.error"));
    }
  };

  const refreshProjectData = async () => {
    if (!selectedProjectId) {
      return;
    }
    try {
      await api.post(`/api/projects/${selectedProjectId}/actions/refresh-data`, {});
      setDataMessage(t("projects.dataStatus.queued"));
      await loadProjectDataStatus(selectedProjectId);
    } catch (err) {
      setDataMessage(t("projects.dataStatus.error"));
    }
  };

  const runThematicBacktest = async () => {
    if (!selectedProjectId) {
      return;
    }
    try {
      await api.post(`/api/projects/${selectedProjectId}/actions/thematic-backtest`, {});
      setBacktestMessage(t("projects.backtest.queued"));
      await loadThematicBacktest(selectedProjectId);
    } catch (err) {
      setBacktestMessage(t("projects.backtest.error"));
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

  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    return value.toFixed(4);
  };

  const weightTotalWarn = Math.abs(weightTotal - 1) > 0.02;
  const metricRows = [
    { key: "cagr", label: t("projects.backtest.metrics.cagr"), format: formatPercent },
    { key: "volatility", label: t("projects.backtest.metrics.volatility"), format: formatPercent },
    { key: "sharpe", label: t("projects.backtest.metrics.sharpe"), format: formatNumber },
    { key: "max_drawdown", label: t("projects.backtest.metrics.maxDrawdown"), format: formatPercent },
  ];

  const placeholderDescription = selectedProject?.description || t("common.none");
  const configTabs = [
    { key: "universe", label: t("projects.config.sectionUniverse") },
    { key: "data", label: t("projects.config.sectionData") },
    { key: "themes", label: t("projects.config.sectionThemes") },
    { key: "portfolio", label: t("projects.config.sectionPortfolio") },
  ] as const;

  return (
    <div className="main">
      <TopBar title={t("projects.title")} />
      <div className="content">
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

        <div className="grid-2">
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
                        value={configDraft.data?.primary_vendor || "stooq"}
                        onChange={(e) =>
                          updateConfigSection("data", "primary_vendor", e.target.value)
                        }
                      >
                        <option value="stooq">Stooq</option>
                        <option value="yahoo">Yahoo</option>
                      </select>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("projects.config.vendorFallback")}</label>
                      <select
                        className="form-select"
                        value={configDraft.data?.fallback_vendor || "yahoo"}
                        onChange={(e) =>
                          updateConfigSection("data", "fallback_vendor", e.target.value)
                        }
                      >
                        <option value="yahoo">Yahoo</option>
                        <option value="stooq">Stooq</option>
                      </select>
                    </div>
                  </div>
                )}

                {configSection === "themes" && (
                  <div className="config-section">
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
                                      onChange={(e) =>
                                        updateTheme(index, "keywords", e.target.value)
                                      }
                                      placeholder={t("projects.config.themeKeywords")}
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
                  <strong>{configMeta?.updated_at || t("common.none")}</strong>
                </div>
                {configMessage && <div className="form-hint">{configMessage}</div>}
                <button className="button-primary" onClick={saveProjectConfig}>
                  {t("projects.config.save")}
                </button>
              </div>
            )}
          </div>

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
                <strong>{binding?.updated_at || t("common.none")}</strong>
              </div>
              {bindingMessage && <div className="form-hint">{bindingMessage}</div>}
              <button className="button-primary" onClick={saveAlgorithmBinding}>
                {t("projects.algorithm.save")}
              </button>
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
                  <strong>{dataStatus.prices.updated_at || t("common.none")}</strong>
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

          <div className="card">
            <div className="card-title">{t("projects.backtest.title")}</div>
            <div className="card-meta">{t("projects.backtest.meta")}</div>
            {thematicBacktest?.summary ? (
              <div className="metric-table">
                <div className="metric-header">
                  <span>{t("projects.backtest.metric")}</span>
                  <span>{t("projects.backtest.portfolio")}</span>
                  <span>{t("projects.backtest.benchmark")}</span>
                </div>
                {metricRows.map((metric) => (
                  <div className="metric-row" key={metric.key}>
                    <span>{metric.label}</span>
                    <span>
                      {metric.format(
                        Number((thematicBacktest.summary?.portfolio || {})[metric.key])
                      )}
                    </span>
                    <span>
                      {metric.format(
                        Number((thematicBacktest.summary?.benchmark || {})[metric.key])
                      )}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">{t("projects.backtest.empty")}</div>
            )}
            <div className="meta-row">
              <span>{t("common.labels.updatedAt")}</span>
              <strong>{thematicBacktest?.updated_at || t("common.none")}</strong>
            </div>
            {backtestMessage && <div className="form-hint">{backtestMessage}</div>}
            <button className="button-primary" onClick={runThematicBacktest}>
              {t("projects.backtest.action")}
            </button>
          </div>
        </div>

        <table className="table">
          <thead>
            <tr>
              <th>{t("projects.table.project")}</th>
              <th>{t("projects.table.description")}</th>
              <th>{t("projects.table.createdAt")}</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => (
              <tr key={project.id}>
                <td>{project.name}</td>
                <td>{project.description || t("common.none")}</td>
                <td>{new Date(project.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
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

        <div className="grid-2">
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
        </div>

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
                <td>{new Date(ver.created_at).toLocaleString()}</td>
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
      </div>
    </div>
  );
}
