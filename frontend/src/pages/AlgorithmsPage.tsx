import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import PaginationBar from "../components/PaginationBar";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { Paginated } from "../types";

interface Algorithm {
  id: number;
  name: string;
  description?: string | null;
  language: string;
  file_path?: string | null;
  type_name?: string | null;
  version?: string | null;
  created_at: string;
  updated_at: string;
}

interface AlgorithmVersion {
  id: number;
  algorithm_id: number;
  version?: string | null;
  description?: string | null;
  language: string;
  file_path?: string | null;
  type_name?: string | null;
  content_hash?: string | null;
  created_at: string;
}

interface AlgorithmVersionDetail extends AlgorithmVersion {
  content?: string | null;
  params?: AlgorithmParams | null;
}

interface AlgorithmDiff {
  algorithm_id: number;
  from_version_id: number;
  to_version_id: number;
  diff: string;
}

interface BacktestRun {
  id: number;
  status: string;
}

interface SystemThemeItem {
  id: number;
  key: string;
  label: string;
}

interface SystemThemePage {
  items: SystemThemeItem[];
}

type CoreRedistribute = "cash" | "core";

type AlgorithmParams = {
  cadence: "weekly" | "monthly";
  universe: {
    market: "US";
    asset_class: "Equity";
    allow_etf: boolean;
  };
  core: {
    symbols: string[];
    total_weight: number;
    redistribute: CoreRedistribute;
  };
  defensive: {
    symbols: string[];
  };
  theme_weights: Record<string, number>;
  blend: {
    momentum_weight: number;
    lowvol_weight: number;
  };
  selection: {
    top_n: number;
    top_n_momentum: number;
    top_n_lowvol: number;
    min_positions: number;
    trend_weeks: number;
    risk_on_weeks: number;
    lowvol_days: number;
    momentum_short_days: number;
    momentum_long_days: number;
    momentum_12w: number;
    momentum_4w: number;
    volatility_20d: number;
  };
  risk: {
    max_position: number;
    vol_target: number;
    drawdown_cut: number;
    inverse_vol: boolean;
    min_vol: number;
    theme_tilt: number;
  };
  notes?: string;
};

const defaultParams: AlgorithmParams = {
  cadence: "weekly",
  universe: {
    market: "US",
    asset_class: "Equity",
    allow_etf: false,
  },
  core: {
    symbols: [],
    total_weight: 0,
    redistribute: "cash",
  },
  defensive: {
    symbols: ["SHY", "IEF"],
  },
  theme_weights: {},
  blend: {
    momentum_weight: 0.8,
    lowvol_weight: 0.2,
  },
  selection: {
    top_n: 6,
    top_n_momentum: 10,
    top_n_lowvol: 20,
    min_positions: 6,
    trend_weeks: 30,
    risk_on_weeks: 50,
    lowvol_days: 63,
    momentum_short_days: 63,
    momentum_long_days: 252,
    momentum_12w: 0.6,
    momentum_4w: 0.4,
    volatility_20d: 0.2,
  },
  risk: {
    max_position: 0.2,
    vol_target: 0.1,
    drawdown_cut: 0.12,
    inverse_vol: true,
    min_vol: 0.01,
    theme_tilt: 0.5,
  },
  notes: "",
};

const normalizeParams = (input?: AlgorithmParams | null): AlgorithmParams => {
  if (!input) {
    return { ...defaultParams };
  }
  return {
    ...defaultParams,
    ...input,
    universe: { ...defaultParams.universe, ...(input.universe || {}) },
    core: { ...defaultParams.core, ...(input.core || {}) },
    defensive: { ...defaultParams.defensive, ...(input.defensive || {}) },
    theme_weights: { ...defaultParams.theme_weights, ...(input.theme_weights || {}) },
    blend: { ...defaultParams.blend, ...(input.blend || {}) },
    selection: { ...defaultParams.selection, ...(input.selection || {}) },
    risk: { ...defaultParams.risk, ...(input.risk || {}) },
  };
};

export default function AlgorithmsPage() {
  const { t, formatDateTime } = useI18n();
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [algorithmTotal, setAlgorithmTotal] = useState(0);
  const [algorithmPage, setAlgorithmPage] = useState(1);
  const [algorithmPageSize, setAlgorithmPageSize] = useState(10);
  const [searchText, setSearchText] = useState("");
  const [form, setForm] = useState({
    name: "",
    description: "",
    language: "Python",
    file_path: "",
    type_name: "",
    version: "",
  });
  const [formErrorKey, setFormErrorKey] = useState("");
  const [selectedAlgorithmId, setSelectedAlgorithmId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    description: "",
    language: "Python",
    file_path: "",
    type_name: "",
    version: "",
  });
  const [editMessage, setEditMessage] = useState("");
  const [versions, setVersions] = useState<AlgorithmVersion[]>([]);
  const [versionOptions, setVersionOptions] = useState<AlgorithmVersion[]>([]);
  const [versionTotal, setVersionTotal] = useState(0);
  const [versionPage, setVersionPage] = useState(1);
  const [versionPageSize, setVersionPageSize] = useState(10);
  const [versionForm, setVersionForm] = useState({
    version: "",
    description: "",
    language: "",
    file_path: "",
    type_name: "",
    content: "",
  });
  const [versionErrorKey, setVersionErrorKey] = useState("");
  const [activeVersionId, setActiveVersionId] = useState("");
  const [paramsForm, setParamsForm] = useState<AlgorithmParams>(defaultParams);
  const [diffFromId, setDiffFromId] = useState("");
  const [diffToId, setDiffToId] = useState("");
  const [diffResult, setDiffResult] = useState("");
  const [diffErrorKey, setDiffErrorKey] = useState("");
  const [selfTestVersionId, setSelfTestVersionId] = useState("");
  const [selfTestBenchmark, setSelfTestBenchmark] = useState("SPY");
  const [selfTestMessage, setSelfTestMessage] = useState("");
  const [selfTestRunId, setSelfTestRunId] = useState<number | null>(null);
  const [selfTestLoading, setSelfTestLoading] = useState(false);
  const [paramsMode, setParamsMode] = useState<"form" | "json">("form");
  const [paramsJson, setParamsJson] = useState("{}");
  const [coreEnabled, setCoreEnabled] = useState(false);
  const [themeOptions, setThemeOptions] = useState<SystemThemeItem[]>([]);
  const [themeRows, setThemeRows] = useState<Array<{ key: string; weight: string }>>([]);
  const [projectForm, setProjectForm] = useState({
    name: "",
    description: "",
    versionId: "",
    lockVersion: true,
  });
  const [projectMessage, setProjectMessage] = useState("");
  const [activeTab, setActiveTab] = useState("params");

  const themeOptionMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const theme of themeOptions) {
      map.set(theme.key.toUpperCase(), theme.label);
    }
    return map;
  }, [themeOptions]);

  const themeRowsFromWeights = (weights: Record<string, number>) =>
    Object.entries(weights || {}).map(([key, weight]) => ({
      key,
      weight: Number.isFinite(weight) ? String(weight) : "",
    }));

  const themeWeightsFromRows = (rows: Array<{ key: string; weight: string }>) => {
    const output: Record<string, number> = {};
    for (const row of rows) {
      const key = row.key.trim().toUpperCase();
      if (!key) {
        continue;
      }
      const value = Number(row.weight);
      if (!Number.isFinite(value)) {
        continue;
      }
      output[key] = value;
    }
    return output;
  };

  const updateThemeRows = (
    updater:
      | Array<{ key: string; weight: string }>
      | ((prev: Array<{ key: string; weight: string }>) => Array<{ key: string; weight: string }>)
  ) => {
    setThemeRows((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      setParamsForm((params) => ({
        ...params,
        theme_weights: themeWeightsFromRows(next),
      }));
      return next;
    });
  };

  const loadAlgorithms = async (pageOverride?: number, pageSizeOverride?: number) => {
    const nextPage = pageOverride ?? algorithmPage;
    const nextSize = pageSizeOverride ?? algorithmPageSize;
    const res = await api.get<Paginated<Algorithm>>("/api/algorithms/page", {
      params: { page: nextPage, page_size: nextSize },
    });
    setAlgorithms(res.data.items);
    setAlgorithmTotal(res.data.total);
    if (
      res.data.items.length &&
      (!selectedAlgorithmId || !res.data.items.some((item) => item.id === selectedAlgorithmId))
    ) {
      setSelectedAlgorithmId(res.data.items[0].id);
    }
    if (!res.data.items.length) {
      setSelectedAlgorithmId(null);
    }
  };

  const loadVersions = async (
    algorithmId: number,
    pageOverride?: number,
    pageSizeOverride?: number
  ) => {
    const nextPage = pageOverride ?? versionPage;
    const nextSize = pageSizeOverride ?? versionPageSize;
    const res = await api.get<Paginated<AlgorithmVersion>>(
      `/api/algorithms/${algorithmId}/versions/page`,
      { params: { page: nextPage, page_size: nextSize } }
    );
    setVersions(res.data.items);
    setVersionTotal(res.data.total);
  };

  const loadVersionOptions = async (algorithmId: number) => {
    const res = await api.get<AlgorithmVersion[]>(`/api/algorithms/${algorithmId}/versions`);
    setVersionOptions(res.data);
  };

  const loadVersionDetail = async (algorithmId: number, versionId: number) => {
    const res = await api.get<AlgorithmVersionDetail>(
      `/api/algorithms/${algorithmId}/versions/${versionId}`
    );
    const detail = res.data;
    const normalized = normalizeParams(detail.params);
    setVersionForm({
      version: detail.version || "",
      description: detail.description || "",
      language: detail.language || "",
      file_path: detail.file_path || "",
      type_name: detail.type_name || "",
      content: detail.content || "",
    });
    setParamsForm(normalized);
    setThemeRows(themeRowsFromWeights(normalized.theme_weights));
    const core = detail.params?.core;
    const hasCore =
      Array.isArray(core?.symbols) && core?.symbols.length > 0
        ? true
        : Number(core?.total_weight || 0) > 0;
    setCoreEnabled(hasCore);
    setParamsJson(JSON.stringify(detail.params || {}, null, 2));
  };

  useEffect(() => {
    loadAlgorithms();
  }, [algorithmPage, algorithmPageSize]);

  useEffect(() => {
    const loadThemeOptions = async () => {
      try {
        const res = await api.get<SystemThemePage>("/api/system-themes", {
          params: { page: 1, page_size: 200 },
        });
        setThemeOptions(res.data.items || []);
      } catch (err) {
        setThemeOptions([]);
      }
    };
    loadThemeOptions();
  }, []);

  useEffect(() => {
    if (selectedAlgorithmId) {
      setVersionPage(1);
      loadVersions(selectedAlgorithmId, 1, versionPageSize);
      loadVersionOptions(selectedAlgorithmId);
      setActiveTab("params");
      setParamsForm(normalizeParams(null));
      setParamsMode("form");
      setParamsJson("{}");
      setCoreEnabled(false);
      setThemeRows([]);
      setVersionForm({
        version: "",
        description: "",
        language: "",
        file_path: "",
        type_name: "",
        content: "",
      });
      setActiveVersionId("");
    } else {
      setVersions([]);
      setVersionOptions([]);
      setVersionTotal(0);
    }
  }, [selectedAlgorithmId]);

  useEffect(() => {
    if (selectedAlgorithmId) {
      loadVersions(selectedAlgorithmId);
    }
  }, [versionPage, versionPageSize]);

  useEffect(() => {
    if (!selectedAlgorithmId) {
      return;
    }
    if (!versions.length) {
      return;
    }
    const latest = versions[0];
    setActiveVersionId(String(latest.id));
    setSelfTestVersionId(String(latest.id));
    loadVersionDetail(selectedAlgorithmId, latest.id);
  }, [versions, selectedAlgorithmId]);

  const updateForm = (key: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateEditForm = (key: keyof typeof editForm, value: string) => {
    setEditForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateVersionForm = (key: keyof typeof versionForm, value: string) => {
    setVersionForm((prev) => ({ ...prev, [key]: value }));
  };

  const createAlgorithm = async () => {
    if (!form.name.trim()) {
      setFormErrorKey("algorithms.register.errorName");
      return;
    }
    setFormErrorKey("");
    await api.post("/api/algorithms", {
      name: form.name.trim(),
      description: form.description.trim() || null,
      language: form.language,
      file_path: form.file_path.trim() || null,
      type_name: form.type_name.trim() || null,
      version: form.version.trim() || null,
    });
    setForm({
      name: "",
      description: "",
      language: "Python",
      file_path: "",
      type_name: "",
      version: "",
    });
    setAlgorithmPage(1);
    loadAlgorithms(1, algorithmPageSize);
  };

  const saveAlgorithm = async () => {
    if (!selectedAlgorithmId) {
      setEditMessage(t("algorithms.detail.empty"));
      return;
    }
    if (!editForm.name.trim()) {
      setEditMessage(t("algorithms.register.errorName"));
      return;
    }
    setEditMessage("");
    try {
      await api.put(`/api/algorithms/${selectedAlgorithmId}`, {
        name: editForm.name.trim(),
        description: editForm.description.trim() || null,
        language: editForm.language,
        file_path: editForm.file_path.trim() || null,
        type_name: editForm.type_name.trim() || null,
        version: editForm.version.trim() || null,
      });
      setEditMessage(t("common.actions.saved"));
      loadAlgorithms(algorithmPage, algorithmPageSize);
    } catch (err) {
      setEditMessage(t("algorithms.detail.error"));
    }
  };

  const createVersion = async () => {
    if (!selectedAlgorithmId) {
      setVersionErrorKey("algorithms.versions.errorSelect");
      return;
    }
    let paramsPayload: Record<string, unknown> | null = null;
    if (paramsMode === "json") {
      const raw = paramsJson.trim();
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          if (!parsed || typeof parsed !== "object") {
            setVersionErrorKey("algorithms.params.jsonError");
            return;
          }
          paramsPayload = parsed as Record<string, unknown>;
        } catch (err) {
          setVersionErrorKey("algorithms.params.jsonError");
          return;
        }
      }
    } else {
      paramsPayload = buildParamsPayload();
    }
    const hasParams = paramsPayload && Object.keys(paramsPayload).length > 0;
    if (!versionForm.version.trim() && !versionForm.file_path && !versionForm.content && !hasParams) {
      setVersionErrorKey("algorithms.versions.errorContent");
      return;
    }
    setVersionErrorKey("");
    await api.post(`/api/algorithms/${selectedAlgorithmId}/versions`, {
      version: versionForm.version || null,
      description: versionForm.description || null,
      language: versionForm.language || null,
      file_path: versionForm.file_path || null,
      type_name: versionForm.type_name || null,
      content: versionForm.content || null,
      params: paramsPayload || null,
    });
    setVersionForm({
      version: "",
      description: "",
      language: "",
      file_path: "",
      type_name: "",
      content: "",
    });
    setVersionPage(1);
    loadVersions(selectedAlgorithmId, 1, versionPageSize);
    loadVersionOptions(selectedAlgorithmId);
  };

  const runDiff = async () => {
    if (!selectedAlgorithmId) {
      setDiffErrorKey("algorithms.versions.errorSelect");
      return;
    }
    if (!diffFromId || !diffToId) {
      setDiffErrorKey("algorithms.diff.errorSelect");
      return;
    }
    setDiffErrorKey("");
    const res = await api.get<AlgorithmDiff>(`/api/algorithms/${selectedAlgorithmId}/diff`, {
      params: { from_id: Number(diffFromId), to_id: Number(diffToId) },
    });
    setDiffResult(res.data.diff || "");
  };

  const createProjectFromVersion = async () => {
    if (!selectedAlgorithmId) {
      setProjectMessage(t("algorithms.versions.errorSelect"));
      return;
    }
    if (!projectForm.versionId) {
      setProjectMessage(t("algorithms.projectCreate.errorSelect"));
      return;
    }
    if (!projectForm.name.trim()) {
      setProjectMessage(t("projects.new.errorName"));
      return;
    }
    setProjectMessage("");
    try {
      await api.post(
        `/api/algorithms/${selectedAlgorithmId}/versions/${projectForm.versionId}/projects`,
        {
          name: projectForm.name.trim(),
          description: projectForm.description || null,
          lock_version: projectForm.lockVersion,
        }
      );
      setProjectForm({ name: "", description: "", versionId: "", lockVersion: true });
      setProjectMessage(t("algorithms.projectCreate.success"));
    } catch (err) {
      setProjectMessage(t("algorithms.projectCreate.error"));
    }
  };

  const runSelfTest = async () => {
    if (!selectedAlgorithmId) {
      setSelfTestMessage(t("algorithms.selftest.errorSelect"));
      return;
    }
    if (!selfTestVersionId) {
      setSelfTestMessage(t("algorithms.selftest.errorSelect"));
      return;
    }
    setSelfTestMessage("");
    setSelfTestLoading(true);
    try {
      const res = await api.post<BacktestRun>(
        `/api/algorithms/${selectedAlgorithmId}/self-test`,
        {
          version_id: Number(selfTestVersionId),
          benchmark: selfTestBenchmark,
        }
      );
      setSelfTestRunId(res.data.id);
      setSelfTestMessage(
        t("algorithms.selftest.queued", { id: res.data.id })
      );
    } catch (err) {
      setSelfTestMessage(t("algorithms.selftest.error"));
    } finally {
      setSelfTestLoading(false);
    }
  };

  const selectedAlgorithm = useMemo(
    () => algorithms.find((item) => item.id === selectedAlgorithmId),
    [algorithms, selectedAlgorithmId]
  );

  const filteredAlgorithms = useMemo(() => {
    const keyword = searchText.trim().toLowerCase();
    if (!keyword) {
      return algorithms;
    }
    return algorithms.filter((algo) => algo.name.toLowerCase().includes(keyword));
  }, [algorithms, searchText]);

  const defaultLanguage = selectedAlgorithm?.language || "Python";
  const latestVersion = versions.length ? versions[0] : null;

  useEffect(() => {
    if (!selectedAlgorithm) {
      setEditForm({
        name: "",
        description: "",
        language: "Python",
        file_path: "",
        type_name: "",
        version: "",
      });
      return;
    }
    setEditForm({
      name: selectedAlgorithm.name,
      description: selectedAlgorithm.description || "",
      language: selectedAlgorithm.language,
      file_path: selectedAlgorithm.file_path || "",
      type_name: selectedAlgorithm.type_name || "",
      version: selectedAlgorithm.version || "",
    });
  }, [selectedAlgorithm]);

  const buildParamsPayload = () => {
    const payload = { ...paramsForm } as Record<string, unknown>;
    if (!coreEnabled) {
      delete payload.core;
    }
    return payload;
  };

  const updateParam = (
    key: keyof AlgorithmParams,
    value: AlgorithmParams[keyof AlgorithmParams]
  ) => {
    setParamsForm((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="main">
      <TopBar title={t("algorithms.title")} />
      <div className="content">
        <div className="algorithms-layout">
          <div className="algorithms-sidebar">
            <div className="card">
              <div className="card-title">{t("algorithms.register.title")}</div>
              <div className="card-meta">{t("algorithms.register.meta")}</div>
              <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
                <input
                  value={form.name}
                  onChange={(e) => updateForm("name", e.target.value)}
                  placeholder={t("algorithms.register.name")}
                  className="form-input"
                />
                <input
                  value={form.description}
                  onChange={(e) => updateForm("description", e.target.value)}
                  placeholder={t("algorithms.register.description")}
                  className="form-input"
                />
                <input
                  value={form.language}
                  onChange={(e) => updateForm("language", e.target.value)}
                  placeholder={t("algorithms.register.language")}
                  className="form-input"
                />
                <input
                  value={form.version}
                  onChange={(e) => updateForm("version", e.target.value)}
                  placeholder={t("algorithms.register.version")}
                  className="form-input"
                />
                <input
                  value={form.file_path}
                  onChange={(e) => updateForm("file_path", e.target.value)}
                  placeholder={t("algorithms.register.path")}
                  className="form-input"
                />
                <input
                  value={form.type_name}
                  onChange={(e) => updateForm("type_name", e.target.value)}
                  placeholder={t("algorithms.register.typeName")}
                  className="form-input"
                />
                {formErrorKey && (
                  <div style={{ color: "#d64545", fontSize: "13px" }}>{t(formErrorKey)}</div>
                )}
                <button className="button-primary" onClick={createAlgorithm}>
                  {t("common.actions.save")}
                </button>
              </div>
            </div>

            <div className="card">
              <div className="card-title">{t("algorithms.overview.title")}</div>
              <div className="card-meta">{t("algorithms.overview.meta")}</div>
              <div style={{ fontSize: "28px", fontWeight: 600, marginTop: "12px" }}>
                {algorithmTotal}
              </div>
            </div>

            <div className="card">
              <div className="card-title">{t("algorithms.list.title")}</div>
              <div className="card-meta">{t("algorithms.list.meta")}</div>
              <input
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder={t("algorithms.list.search")}
                className="form-input"
                style={{ marginTop: "12px" }}
              />
              <div className="algo-list">
                {filteredAlgorithms.map((algo) => (
                  <div
                    key={algo.id}
                    className={
                      algo.id === selectedAlgorithmId ? "algo-item algo-item-active" : "algo-item"
                    }
                    onClick={() => setSelectedAlgorithmId(algo.id)}
                  >
                    <div className="algo-item-title">{algo.name}</div>
                    <div className="algo-item-meta">
                      {algo.language} · {formatDateTime(algo.updated_at)}
                    </div>
                  </div>
                ))}
                {filteredAlgorithms.length === 0 && (
                  <div className="form-hint">{t("algorithms.list.empty")}</div>
                )}
              </div>
              <PaginationBar
                page={algorithmPage}
                pageSize={algorithmPageSize}
                total={algorithmTotal}
                onPageChange={setAlgorithmPage}
                onPageSizeChange={(size) => {
                  setAlgorithmPage(1);
                  setAlgorithmPageSize(size);
                }}
              />
            </div>
          </div>

          <div className="algorithms-main">
            <div className="card">
              <div className="algo-header">
                <div>
                  <div className="card-title">{t("algorithms.detail.title")}</div>
                  <div className="card-meta">{t("algorithms.detail.meta")}</div>
                </div>
                <div className="algo-badges">
                  <span className="badge">{selectedAlgorithm?.language || "-"}</span>
                  <span className="badge">
                    {t("algorithms.detail.latest", {
                      id: latestVersion ? latestVersion.id : "-",
                    })}
                  </span>
                  <span className="badge">
                    {t("algorithms.detail.versions", { count: versionTotal })}
                  </span>
                </div>
              </div>
              <div className="algo-edit-grid">
                <div className="form-row">
                  <label className="form-label">{t("algorithms.detail.name")}</label>
                  <input
                    className="form-input"
                    value={editForm.name}
                    onChange={(e) => updateEditForm("name", e.target.value)}
                  />
                </div>
                <div className="form-row">
                  <label className="form-label">{t("algorithms.detail.description")}</label>
                  <input
                    className="form-input"
                    value={editForm.description}
                    onChange={(e) => updateEditForm("description", e.target.value)}
                  />
                </div>
                <div className="form-row">
                  <label className="form-label">{t("algorithms.detail.language")}</label>
                  <input
                    className="form-input"
                    value={editForm.language}
                    onChange={(e) => updateEditForm("language", e.target.value)}
                  />
                </div>
                <div className="form-row">
                  <label className="form-label">{t("algorithms.detail.version")}</label>
                  <input
                    className="form-input"
                    value={editForm.version}
                    onChange={(e) => updateEditForm("version", e.target.value)}
                  />
                </div>
                <div className="form-row">
                  <label className="form-label">{t("algorithms.detail.path")}</label>
                  <input
                    className="form-input"
                    value={editForm.file_path}
                    onChange={(e) => updateEditForm("file_path", e.target.value)}
                  />
                </div>
                <div className="form-row">
                  <label className="form-label">{t("algorithms.detail.typeName")}</label>
                  <input
                    className="form-input"
                    value={editForm.type_name}
                    onChange={(e) => updateEditForm("type_name", e.target.value)}
                  />
                </div>
              </div>
              <div className="algo-actions">
                <button className="button-primary" onClick={saveAlgorithm}>
                  {t("common.actions.save")}
                </button>
                {editMessage && <span className="form-hint">{editMessage}</span>}
              </div>
            </div>

            <div className="algo-tabs">
              <button
                className={activeTab === "params" ? "tab-button active" : "tab-button"}
                onClick={() => setActiveTab("params")}
              >
                {t("algorithms.tabs.params")}
              </button>
              <button
                className={activeTab === "versions" ? "tab-button active" : "tab-button"}
                onClick={() => setActiveTab("versions")}
              >
                {t("algorithms.tabs.versions")}
              </button>
              <button
                className={activeTab === "diff" ? "tab-button active" : "tab-button"}
                onClick={() => setActiveTab("diff")}
              >
                {t("algorithms.tabs.diff")}
              </button>
              <button
                className={activeTab === "project" ? "tab-button active" : "tab-button"}
                onClick={() => setActiveTab("project")}
              >
                {t("algorithms.tabs.project")}
              </button>
              <button
                className={activeTab === "selftest" ? "tab-button active" : "tab-button"}
                onClick={() => setActiveTab("selftest")}
              >
                {t("algorithms.tabs.selftest")}
              </button>
            </div>

            {activeTab === "params" && (
              <div className="card">
                <div className="card-title">{t("algorithms.params.title")}</div>
                <div className="card-meta">{t("algorithms.params.meta")}</div>
                <div className="algo-tabs" style={{ marginTop: "8px" }}>
                  <button
                    className={paramsMode === "form" ? "tab-button active" : "tab-button"}
                    onClick={() => setParamsMode("form")}
                  >
                    {t("algorithms.params.modeForm")}
                  </button>
                  <button
                    className={paramsMode === "json" ? "tab-button active" : "tab-button"}
                    onClick={() => {
                      setParamsMode("json");
                      setParamsJson(JSON.stringify(buildParamsPayload(), null, 2));
                    }}
                  >
                    {t("algorithms.params.modeJson")}
                  </button>
                </div>
                <div className="form-hint" style={{ marginTop: "6px" }}>
                  {t("algorithms.params.modeHint")}
                </div>
                <div style={{ display: paramsMode === "json" ? "none" : "block" }}>
                  <div className="algo-params-grid">
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.params.cadence")}</label>
                    <select
                      className="form-select"
                      value={paramsForm.cadence}
                      onChange={(e) =>
                        updateParam("cadence", e.target.value as AlgorithmParams["cadence"])
                      }
                    >
                      <option value="weekly">{t("algorithms.params.weekly")}</option>
                      <option value="monthly">{t("algorithms.params.monthly")}</option>
                    </select>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.params.market")}</label>
                    <select
                      className="form-select"
                      value={paramsForm.universe.market}
                      onChange={() =>
                        updateParam("universe", { ...paramsForm.universe, market: "US" })
                      }
                    >
                      <option value="US">{t("algorithms.params.us")}</option>
                    </select>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.params.assetClass")}</label>
                    <select
                      className="form-select"
                      value={paramsForm.universe.asset_class}
                      onChange={() =>
                        updateParam("universe", { ...paramsForm.universe, asset_class: "Equity" })
                      }
                    >
                      <option value="Equity">{t("algorithms.params.equity")}</option>
                    </select>
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={paramsForm.universe.allow_etf}
                      onChange={(e) =>
                        updateParam("universe", {
                          ...paramsForm.universe,
                          allow_etf: e.target.checked,
                        })
                      }
                    />
                    {t("algorithms.params.allowEtf")}
                  </label>
                </div>

                <label className="checkbox-row" style={{ marginTop: "8px" }}>
                  <input
                    type="checkbox"
                    checked={coreEnabled}
                    onChange={(e) => {
                      const enabled = e.target.checked;
                      setCoreEnabled(enabled);
                      if (!enabled) {
                        updateParam("core", {
                          ...paramsForm.core,
                          symbols: [],
                          total_weight: 0,
                          redistribute: "cash",
                        });
                      }
                    }}
                  />
                  {t("algorithms.params.coreEnable")}
                </label>
                {!coreEnabled && (
                  <div className="form-hint">{t("algorithms.params.coreDisabledHint")}</div>
                )}

                {coreEnabled && (
                  <div className="algo-params-section">
                    <div className="section-title">{t("algorithms.params.coreTitle")}</div>
                    <div className="algo-params-grid">
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.coreSymbols")}</label>
                        <input
                          className="form-input"
                          value={paramsForm.core.symbols.join(", ")}
                          onChange={(e) =>
                            updateParam("core", {
                              ...paramsForm.core,
                              symbols: e.target.value
                                .split(",")
                                .map((item) => item.trim().toUpperCase())
                                .filter((item) => item),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.coreWeight")}</label>
                        <input
                          className="form-input"
                          type="number"
                          step="0.01"
                          value={paramsForm.core.total_weight}
                          onChange={(e) =>
                            updateParam("core", {
                              ...paramsForm.core,
                              total_weight: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.coreFallback")}</label>
                        <select
                          className="form-select"
                          value={paramsForm.core.redistribute}
                          onChange={(e) =>
                            updateParam("core", {
                              ...paramsForm.core,
                              redistribute: e.target.value as CoreRedistribute,
                            })
                          }
                        >
                          <option value="cash">{t("algorithms.params.cash")}</option>
                          <option value="core">{t("algorithms.params.redistribute")}</option>
                        </select>
                      </div>
                    </div>
                  </div>
                )}

                <div className="algo-params-section">
                  <div className="section-title">{t("algorithms.params.themeTitle")}</div>
                  <div className="form-hint">{t("algorithms.params.themeOptionHint")}</div>
                  {themeRows.length === 0 && (
                    <div className="form-hint">{t("algorithms.params.themeEmpty")}</div>
                  )}
                  <div style={{ display: "grid", gap: "12px", marginTop: "8px" }}>
                    {themeRows.map((row, index) => {
                      const label = themeOptionMap.get(row.key.trim().toUpperCase());
                      return (
                        <div
                          key={`${row.key}-${index}`}
                          style={{
                            display: "grid",
                            gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr) auto",
                            gap: "12px",
                            alignItems: "end",
                          }}
                        >
                          <div className="form-row">
                            <label className="form-label">{t("algorithms.params.themeKey")}</label>
                            <input
                              className="form-input"
                              value={row.key}
                              list="algorithm-theme-options"
                              onChange={(e) =>
                                updateThemeRows((prev) =>
                                  prev.map((item, rowIndex) =>
                                    rowIndex === index
                                      ? { ...item, key: e.target.value.toUpperCase() }
                                      : item
                                  )
                                )
                              }
                            />
                            {label && <div className="form-hint">{label}</div>}
                          </div>
                          <div className="form-row">
                            <label className="form-label">
                              {t("algorithms.params.themeWeight")}
                            </label>
                            <input
                              className="form-input"
                              type="number"
                              step="0.01"
                              value={row.weight}
                              onChange={(e) =>
                                updateThemeRows((prev) =>
                                  prev.map((item, rowIndex) =>
                                    rowIndex === index
                                      ? { ...item, weight: e.target.value }
                                      : item
                                  )
                                )
                              }
                            />
                          </div>
                          <button
                            className="button-secondary"
                            style={{ alignSelf: "end" }}
                            onClick={() =>
                              updateThemeRows((prev) => prev.filter((_, rowIndex) => rowIndex !== index))
                            }
                          >
                            {t("algorithms.params.themeRemove")}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                  <button
                    className="button-secondary"
                    style={{ marginTop: "12px" }}
                    onClick={() => updateThemeRows((prev) => [...prev, { key: "", weight: "" }])}
                  >
                    {t("algorithms.params.themeAdd")}
                  </button>
                  {themeOptions.length > 0 && (
                    <datalist id="algorithm-theme-options">
                      {themeOptions.map((theme) => (
                        <option key={theme.id} value={theme.key} label={theme.label} />
                      ))}
                    </datalist>
                  )}
                </div>

                <div className="algo-params-section">
                  <div className="section-title">{t("algorithms.params.selectionTitle")}</div>
                  <div className="algo-params-grid">
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.topN")}</label>
                      <input
                        className="form-input"
                        type="number"
                        value={paramsForm.selection.top_n}
                        onChange={(e) =>
                          updateParam("selection", {
                            ...paramsForm.selection,
                            top_n: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.trendWeeks")}</label>
                      <input
                        className="form-input"
                        type="number"
                        value={paramsForm.selection.trend_weeks}
                        onChange={(e) =>
                          updateParam("selection", {
                            ...paramsForm.selection,
                            trend_weeks: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.mom12w")}</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        value={paramsForm.selection.momentum_12w}
                        onChange={(e) =>
                          updateParam("selection", {
                            ...paramsForm.selection,
                            momentum_12w: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.mom4w")}</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        value={paramsForm.selection.momentum_4w}
                        onChange={(e) =>
                          updateParam("selection", {
                            ...paramsForm.selection,
                            momentum_4w: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.vol20d")}</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        value={paramsForm.selection.volatility_20d}
                        onChange={(e) =>
                          updateParam("selection", {
                            ...paramsForm.selection,
                            volatility_20d: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                  </div>
                  <details className="algo-advanced">
                    <summary>{t("algorithms.params.advancedTitle")}</summary>
                    <div className="form-hint">{t("algorithms.params.advancedHint")}</div>
                    <div className="algo-params-grid">
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.topMomentum")}</label>
                        <input
                          className="form-input"
                          type="number"
                          value={paramsForm.selection.top_n_momentum}
                          onChange={(e) =>
                            updateParam("selection", {
                              ...paramsForm.selection,
                              top_n_momentum: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.topLowVol")}</label>
                        <input
                          className="form-input"
                          type="number"
                          value={paramsForm.selection.top_n_lowvol}
                          onChange={(e) =>
                            updateParam("selection", {
                              ...paramsForm.selection,
                              top_n_lowvol: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.minPositions")}</label>
                        <input
                          className="form-input"
                          type="number"
                          value={paramsForm.selection.min_positions}
                          onChange={(e) =>
                            updateParam("selection", {
                              ...paramsForm.selection,
                              min_positions: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.riskOnWeeks")}</label>
                        <input
                          className="form-input"
                          type="number"
                          value={paramsForm.selection.risk_on_weeks}
                          onChange={(e) =>
                            updateParam("selection", {
                              ...paramsForm.selection,
                              risk_on_weeks: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.lowvolDays")}</label>
                        <input
                          className="form-input"
                          type="number"
                          value={paramsForm.selection.lowvol_days}
                          onChange={(e) =>
                            updateParam("selection", {
                              ...paramsForm.selection,
                              lowvol_days: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.momShortDays")}</label>
                        <input
                          className="form-input"
                          type="number"
                          value={paramsForm.selection.momentum_short_days}
                          onChange={(e) =>
                            updateParam("selection", {
                              ...paramsForm.selection,
                              momentum_short_days: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.momLongDays")}</label>
                        <input
                          className="form-input"
                          type="number"
                          value={paramsForm.selection.momentum_long_days}
                          onChange={(e) =>
                            updateParam("selection", {
                              ...paramsForm.selection,
                              momentum_long_days: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                    </div>
                    <div className="algo-params-section">
                      <div className="section-title">{t("algorithms.params.blendTitle")}</div>
                      <div className="algo-params-grid">
                        <div className="form-row">
                          <label className="form-label">{t("algorithms.params.momentumWeight")}</label>
                          <input
                            className="form-input"
                            type="number"
                            step="0.01"
                            value={paramsForm.blend.momentum_weight}
                            onChange={(e) =>
                              updateParam("blend", {
                                ...paramsForm.blend,
                                momentum_weight: Number(e.target.value),
                              })
                            }
                          />
                        </div>
                        <div className="form-row">
                          <label className="form-label">{t("algorithms.params.lowvolWeight")}</label>
                          <input
                            className="form-input"
                            type="number"
                            step="0.01"
                            value={paramsForm.blend.lowvol_weight}
                            onChange={(e) =>
                              updateParam("blend", {
                                ...paramsForm.blend,
                                lowvol_weight: Number(e.target.value),
                              })
                            }
                          />
                        </div>
                      </div>
                    </div>
                  </details>
                </div>

                <div className="algo-params-section">
                  <div className="section-title">{t("algorithms.params.riskTitle")}</div>
                  <div className="algo-params-grid">
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.maxWeight")}</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        value={paramsForm.risk.max_position}
                        onChange={(e) =>
                          updateParam("risk", {
                            ...paramsForm.risk,
                            max_position: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.volTarget")}</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        value={paramsForm.risk.vol_target}
                        onChange={(e) =>
                          updateParam("risk", {
                            ...paramsForm.risk,
                            vol_target: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.drawdown")}</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        value={paramsForm.risk.drawdown_cut}
                        onChange={(e) =>
                          updateParam("risk", {
                            ...paramsForm.risk,
                            drawdown_cut: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                  </div>
                  <details className="algo-advanced">
                    <summary>{t("algorithms.params.advancedTitle")}</summary>
                    <div className="form-hint">{t("algorithms.params.advancedHint")}</div>
                    <div className="algo-params-grid">
                      <label className="checkbox-row" style={{ alignItems: "center" }}>
                        <input
                          type="checkbox"
                          checked={paramsForm.risk.inverse_vol}
                          onChange={(e) =>
                            updateParam("risk", {
                              ...paramsForm.risk,
                              inverse_vol: e.target.checked,
                            })
                          }
                        />
                        {t("algorithms.params.inverseVol")}
                      </label>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.minVol")}</label>
                        <input
                          className="form-input"
                          type="number"
                          step="0.001"
                          value={paramsForm.risk.min_vol}
                          onChange={(e) =>
                            updateParam("risk", {
                              ...paramsForm.risk,
                              min_vol: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="form-row">
                        <label className="form-label">{t("algorithms.params.themeTilt")}</label>
                        <input
                          className="form-input"
                          type="number"
                          step="0.05"
                          value={paramsForm.risk.theme_tilt}
                          onChange={(e) =>
                            updateParam("risk", {
                              ...paramsForm.risk,
                              theme_tilt: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                    </div>
                  </details>
                </div>

                <div className="algo-params-section">
                  <div className="section-title">{t("algorithms.params.defensiveTitle")}</div>
                  <div className="algo-params-grid">
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.params.defensiveSymbols")}</label>
                      <input
                        className="form-input"
                        value={paramsForm.defensive.symbols.join(", ")}
                        onChange={(e) =>
                          updateParam("defensive", {
                            ...paramsForm.defensive,
                            symbols: e.target.value
                              .split(",")
                              .map((item) => item.trim().toUpperCase())
                              .filter(Boolean),
                          })
                        }
                        placeholder="SHY, IEF"
                      />
                      <div className="form-hint">{t("algorithms.params.defensiveHint")}</div>
                    </div>
                  </div>
                </div>

                <div className="form-row" style={{ marginTop: "12px" }}>
                  <label className="form-label">{t("algorithms.params.notes")}</label>
                  <textarea
                    className="form-input"
                    rows={3}
                    value={paramsForm.notes || ""}
                    onChange={(e) => updateParam("notes", e.target.value)}
                  />
                </div>
                </div>

                {paramsMode === "json" && (
                  <div style={{ marginTop: "12px" }}>
                    <label className="form-label">{t("algorithms.params.jsonTitle")}</label>
                    <textarea
                      className="form-input"
                      rows={10}
                      value={paramsJson}
                      onChange={(e) => setParamsJson(e.target.value)}
                      placeholder={t("algorithms.params.jsonPlaceholder")}
                    />
                    <div className="form-hint">{t("algorithms.params.jsonHint")}</div>
                  </div>
                )}
                {versionErrorKey && (
                  <div style={{ color: "#d64545", fontSize: "13px", marginTop: "8px" }}>
                    {t(versionErrorKey)}
                  </div>
                )}
                <div className="algo-actions">
                  <button className="button-secondary" onClick={() => setParamsForm(defaultParams)}>
                    {t("algorithms.params.reset")}
                  </button>
                  <button className="button-primary" onClick={createVersion}>
                    {t("algorithms.params.saveVersion")}
                  </button>
                </div>
              </div>
            )}

            {activeTab === "versions" && (
              <div className="card">
                <div className="card-title">{t("algorithms.versions.title")}</div>
                <div className="card-meta">{t("algorithms.versions.meta")}</div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.versions.pick")}</label>
                    <select
                      className="form-select"
                      value={activeVersionId}
                      onChange={(e) => {
                        const value = e.target.value;
                        setActiveVersionId(value);
                        if (selectedAlgorithmId && value) {
                          loadVersionDetail(selectedAlgorithmId, Number(value));
                        }
                      }}
                    >
                      <option value="">{t("algorithms.versions.pick")}</option>
                      {versionOptions.map((item) => (
                        <option key={item.id} value={item.id}>
                          #{item.id} {item.version || t("algorithms.diff.unnamed")}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.versions.version")}</label>
                    <input
                      className="form-input"
                      value={versionForm.version}
                      onChange={(e) => updateVersionForm("version", e.target.value)}
                      placeholder={t("algorithms.versions.version")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.versions.description")}</label>
                    <input
                      className="form-input"
                      value={versionForm.description}
                      onChange={(e) => updateVersionForm("description", e.target.value)}
                      placeholder={t("algorithms.versions.description")}
                    />
                  </div>
                  <div className="algo-params-grid">
                    <div className="form-row">
                      <label className="form-label">
                        {t("algorithms.versions.language", { language: defaultLanguage })}
                      </label>
                      <input
                        className="form-input"
                        value={versionForm.language}
                        onChange={(e) => updateVersionForm("language", e.target.value)}
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.versions.typeName")}</label>
                      <input
                        className="form-input"
                        value={versionForm.type_name}
                        onChange={(e) => updateVersionForm("type_name", e.target.value)}
                      />
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t("algorithms.versions.filePath")}</label>
                      <input
                        className="form-input"
                        value={versionForm.file_path}
                        onChange={(e) => updateVersionForm("file_path", e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.versions.content")}</label>
                    <textarea
                      className="form-input"
                      rows={6}
                      value={versionForm.content}
                      onChange={(e) => updateVersionForm("content", e.target.value)}
                    />
                  </div>
                  {versionErrorKey && (
                    <div style={{ color: "#d64545", fontSize: "13px" }}>{t(versionErrorKey)}</div>
                  )}
                  <button className="button-primary" onClick={createVersion}>
                    {t("common.actions.saveVersion")}
                  </button>
                </div>

                <table className="table" style={{ marginTop: "16px" }}>
                  <thead>
                    <tr>
                      <th>{t("algorithms.versionsTable.id")}</th>
                      <th>{t("algorithms.versionsTable.version")}</th>
                      <th>{t("algorithms.versionsTable.summary")}</th>
                      <th>{t("algorithms.versionsTable.hash")}</th>
                      <th>{t("algorithms.versionsTable.createdAt")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versions.length === 0 && (
                      <tr>
                        <td colSpan={5}>{t("algorithms.versionsTable.empty")}</td>
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
              </div>
            )}

            {activeTab === "diff" && (
              <div className="card">
                <div className="card-title">{t("algorithms.diff.title")}</div>
                <div className="card-meta">{t("algorithms.diff.meta")}</div>
                <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
                  <select
                    value={diffFromId}
                    onChange={(e) => setDiffFromId(e.target.value)}
                    className="form-select"
                  >
                    <option value="">{t("algorithms.diff.selectFrom")}</option>
                    {versionOptions.map((item) => (
                      <option key={item.id} value={item.id}>
                        #{item.id} {item.version || t("algorithms.diff.unnamed")}
                      </option>
                    ))}
                  </select>
                  <select
                    value={diffToId}
                    onChange={(e) => setDiffToId(e.target.value)}
                    className="form-select"
                  >
                    <option value="">{t("algorithms.diff.selectTo")}</option>
                    {versionOptions.map((item) => (
                      <option key={item.id} value={item.id}>
                        #{item.id} {item.version || t("algorithms.diff.unnamed")}
                      </option>
                    ))}
                  </select>
                  {diffErrorKey && (
                    <div style={{ color: "#d64545", fontSize: "13px" }}>{t(diffErrorKey)}</div>
                  )}
                  <button className="button-primary" onClick={runDiff}>
                    {t("common.actions.generateDiff")}
                  </button>
                  <pre className="diff-box">{diffResult || t("algorithms.diff.none")}</pre>
                </div>
              </div>
            )}

            {activeTab === "project" && (
              <div className="card">
                <div className="card-title">{t("algorithms.projectCreate.title")}</div>
                <div className="card-meta">{t("algorithms.projectCreate.meta")}</div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.projectCreate.name")}</label>
                    <input
                      className="form-input"
                      value={projectForm.name}
                      onChange={(e) =>
                        setProjectForm((prev) => ({ ...prev, name: e.target.value }))
                      }
                      placeholder={t("algorithms.projectCreate.name")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.projectCreate.description")}</label>
                    <input
                      className="form-input"
                      value={projectForm.description}
                      onChange={(e) =>
                        setProjectForm((prev) => ({ ...prev, description: e.target.value }))
                      }
                      placeholder={t("algorithms.projectCreate.description")}
                    />
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.projectCreate.version")}</label>
                    <select
                      className="form-select"
                      value={projectForm.versionId}
                      onChange={(e) =>
                        setProjectForm((prev) => ({ ...prev, versionId: e.target.value }))
                      }
                    >
                      <option value="">{t("algorithms.projectCreate.version")}</option>
                      {versionOptions.map((item) => (
                        <option key={item.id} value={item.id}>
                          #{item.id} {item.version || t("common.none")}
                        </option>
                      ))}
                    </select>
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={projectForm.lockVersion}
                      onChange={(e) =>
                        setProjectForm((prev) => ({ ...prev, lockVersion: e.target.checked }))
                      }
                    />
                    {t("algorithms.projectCreate.lock")}
                  </label>
                  {projectMessage && <div className="form-hint">{projectMessage}</div>}
                  <button className="button-primary" onClick={createProjectFromVersion}>
                    {t("algorithms.projectCreate.action")}
                  </button>
                </div>
              </div>
            )}

            {activeTab === "selftest" && (
              <div className="card">
                <div className="card-title">{t("algorithms.selftest.title")}</div>
                <div className="card-meta">{t("algorithms.selftest.meta")}</div>
                <div className="form-grid">
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.selftest.version")}</label>
                    <select
                      className="form-select"
                      value={selfTestVersionId}
                      onChange={(e) => setSelfTestVersionId(e.target.value)}
                    >
                      <option value="">{t("algorithms.selftest.version")}</option>
                      {versionOptions.map((item) => (
                        <option key={item.id} value={item.id}>
                          #{item.id} {item.version || t("algorithms.diff.unnamed")}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t("algorithms.selftest.benchmark")}</label>
                    <input
                      className="form-input"
                      list="benchmark-options"
                      value={selfTestBenchmark}
                      onChange={(e) => setSelfTestBenchmark(e.target.value.toUpperCase())}
                    />
                    <datalist id="benchmark-options">
                      <option value="SPY" />
                      <option value="QQQ" />
                      <option value="VTI" />
                      <option value="IWM" />
                      <option value="DIA" />
                    </datalist>
                    <div className="form-hint">{t("algorithms.selftest.hint")}</div>
                  </div>
                  {selfTestMessage && <div className="form-hint">{selfTestMessage}</div>}
                  <button
                    className="button-primary"
                    onClick={runSelfTest}
                    disabled={selfTestLoading}
                  >
                    {selfTestLoading
                      ? t("algorithms.selftest.running")
                      : t("algorithms.selftest.action")}
                  </button>
                  {selfTestRunId && (
                    <div className="form-hint">
                      {t("algorithms.selftest.lastRun", { id: selfTestRunId })} ·{" "}
                      <a href="/reports" target="_blank" rel="noreferrer">
                        {t("algorithms.selftest.viewReports")}
                      </a>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
