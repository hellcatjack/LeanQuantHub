import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import PaginationBar from "../components/PaginationBar";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { Paginated } from "../types";

interface Dataset {
  id: number;
  name: string;
  vendor?: string | null;
  asset_class?: string | null;
  region?: string | null;
  frequency?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  source_path?: string | null;
  updated_at: string;
}

interface DatasetQuality {
  dataset_id: number;
  frequency?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  coverage_days?: number | null;
  expected_points_estimate?: number | null;
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

interface DatasetFetchResult {
  dataset: Dataset;
  job?: DataSyncJob | null;
  created: boolean;
}

export default function DataPage() {
  const { t } = useI18n();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetTotal, setDatasetTotal] = useState(0);
  const [datasetPage, setDatasetPage] = useState(1);
  const [datasetPageSize, setDatasetPageSize] = useState(10);
  const [frequencyFilter, setFrequencyFilter] = useState<"all" | "daily" | "minute">("all");
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
  const [fetchForm, setFetchForm] = useState({
    symbol: "",
    vendor: "stooq",
    asset_class: "Equity",
    region: "US",
    frequency: "daily",
  });
  const [fetchLoading, setFetchLoading] = useState(false);
  const [fetchError, setFetchError] = useState("");
  const [fetchResult, setFetchResult] = useState<DatasetFetchResult | null>(null);
  const [formError, setFormError] = useState("");
  const [qualityMap, setQualityMap] = useState<Record<number, DatasetQuality>>({});
  const [qualityLoading, setQualityLoading] = useState<Record<number, boolean>>({});
  const [qualityErrors, setQualityErrors] = useState<Record<number, string>>({});
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

  const loadDatasets = async () => {
    const res = await api.get<Paginated<Dataset>>("/api/datasets/page", {
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

  useEffect(() => {
    loadDatasets();
  }, [datasetPage, datasetPageSize]);

  useEffect(() => {
    loadSyncJobs();
  }, [syncPage, syncPageSize]);

  const updateForm = (key: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateFetchForm = (key: keyof typeof fetchForm, value: string) => {
    setFetchForm((prev) => ({ ...prev, [key]: value }));
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

  const syncDataset = async (dataset: Dataset) => {
    setSyncError("");
    setListError("");
    setSyncing((prev) => ({ ...prev, [dataset.id]: true }));
    try {
      await api.post(`/api/datasets/${dataset.id}/sync`, {
        source_path: dataset.source_path || null,
        date_column: "date",
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
    if (!force && (qualityMap[datasetId] || qualityLoading[datasetId])) {
      return;
    }
    setQualityLoading((prev) => ({ ...prev, [datasetId]: true }));
    setQualityErrors((prev) => ({ ...prev, [datasetId]: "" }));
    try {
      const res = await api.get<DatasetQuality>(`/api/datasets/${datasetId}/quality`);
      setQualityMap((prev) => ({ ...prev, [datasetId]: res.data }));
    } catch {
      if (!silent) {
        setQualityErrors((prev) => ({ ...prev, [datasetId]: t("data.list.quality.error") }));
      }
    } finally {
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
      .filter((id) => !qualityMap[id] && !qualityLoading[id]);
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
      await api.post("/api/datasets/sync-all", {});
      loadSyncJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.sync.errorBatch");
      setSyncError(String(detail));
      setListError(String(detail));
    } finally {
      setSyncAllLoading(false);
    }
  };

  const fetchHistory = async () => {
    const symbol = normalizeSymbolInput(fetchForm.symbol);
    if (!symbol) {
      setFetchError(t("data.fetch.errorSymbol"));
      return;
    }
    if (fetchForm.vendor === "stooq" && fetchForm.frequency === "minute") {
      setFetchError(t("data.fetch.errorFrequency"));
      return;
    }
    setFetchError("");
    setFetchResult(null);
    setFetchLoading(true);
    try {
      const res = await api.post<DatasetFetchResult>("/api/datasets/actions/fetch", {
        symbol,
        vendor: fetchForm.vendor,
        asset_class: fetchForm.asset_class,
        region: fetchForm.region,
        frequency: fetchForm.frequency,
        auto_sync: true,
      });
      setFetchResult(res.data);
      setDatasetPage(1);
      setSyncPage(1);
      await loadDatasets();
      await loadSyncJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || t("data.fetch.error");
      setFetchError(String(detail));
    } finally {
      setFetchLoading(false);
    }
  };

  const deleteGroup = async (group: {
    key: string;
    symbol: string;
    region: string;
    items: Dataset[];
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
    try {
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
    if (value === "failed") {
      return "danger";
    }
    return "";
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

  const deriveSymbol = (dataset: Dataset) => {
    const source = (dataset.source_path || "").trim();
    let symbol = "";
    if (source) {
      const lower = source.toLowerCase();
      if (lower.startsWith("stooq://")) {
        symbol = source.slice(8);
      } else if (lower.startsWith("stooq:")) {
        symbol = source.slice(6);
      } else {
        const normalized = source.replace(/\\/g, "/");
        const parts = normalized.split("/");
        const last = parts[parts.length - 1] || normalized;
        symbol = last.replace(/\.csv$/i, "");
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

  const fetchPreview = useMemo(() => {
    const symbol = fetchForm.symbol
      .trim()
      .toUpperCase()
      .replace(/[^A-Z0-9.]/g, "");
    const vendorLabel =
      fetchForm.vendor === "stooq" ? "Stooq" : fetchForm.vendor.toUpperCase();
    const frequencyLabel = fetchForm.frequency === "minute" ? "Minute" : "Daily";
    return {
      symbol,
      datasetName: symbol ? `${vendorLabel}_${symbol}_${frequencyLabel}` : t("common.none"),
      sourcePath: symbol ? `${fetchForm.vendor}:${symbol}` : t("common.none"),
    };
  }, [fetchForm, t]);

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
      `${t("data.quality.status")}：${renderStatus(quality.status)}`,
      `${t("data.quality.coverage")}：${quality.coverage_start || t("common.none")} ~ ${quality.coverage_end || t("common.none")}`,
      `${t("data.quality.days")}：${quality.coverage_days ?? t("common.none")}`,
      `${t("data.quality.expected")}：${
        quality.expected_points_estimate ?? t("common.none")
      }`,
      `${t("data.quality.issues")}：${
        quality.issues.length ? quality.issues.join("；") : t("common.noneText")
      }`,
    ].join("\n");
  };

  const renderQualitySummary = (datasetId: number) => {
    if (qualityLoading[datasetId]) {
      return <span className="market-subtle">{t("data.list.quality.loading")}</span>;
    }
    const error = qualityErrors[datasetId];
    if (error) {
      return <span className="market-subtle">{error}</span>;
    }
    const quality = qualityMap[datasetId];
    if (!quality) {
      return <span className="market-subtle">{t("common.none")}</span>;
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
        items: Dataset[];
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
  }, [datasets, frequencyFilter]);
  const filteredDatasetTotal = groupedDatasets.reduce(
    (sum, group) => sum + group.items.length,
    0
  );

  return (
    <div className="main">
      <TopBar title={t("data.title")} />
      <div className="content">
        <div className="grid-2">
          <div className="card">
            <div className="card-title">{t("data.coverage.title")}</div>
            <div className="card-meta">{t("data.coverage.meta")}</div>
            <div style={{ fontSize: "32px", fontWeight: 600, marginTop: "12px" }}>
              {datasetTotal}
            </div>
          </div>
          <div className="card">
            <div className="card-title">{t("data.fetch.title")}</div>
            <div className="card-meta">{t("data.fetch.meta")}</div>
            <div className="form-grid">
              <input
                className="form-input"
                value={fetchForm.symbol}
                onChange={(e) => updateFetchForm("symbol", e.target.value)}
                placeholder={t("data.fetch.symbol")}
              />
              <div className="form-grid two-col">
                <select
                  className="form-select"
                  value={fetchForm.vendor}
                  onChange={(e) => updateFetchForm("vendor", e.target.value)}
                >
                  <option value="stooq">{t("data.fetch.vendor.stooq")}</option>
                </select>
                <select
                  className="form-select"
                  value={fetchForm.frequency}
                  onChange={(e) => updateFetchForm("frequency", e.target.value)}
                >
                  <option value="daily">{t("data.fetch.frequency.daily")}</option>
                  <option value="minute" disabled={fetchForm.vendor === "stooq"}>
                    {t("data.fetch.frequency.minute")}
                  </option>
                </select>
              </div>
              <div className="form-grid two-col">
                <select
                  className="form-select"
                  value={fetchForm.region}
                  onChange={(e) => updateFetchForm("region", e.target.value)}
                >
                  <option value="US">{t("data.fetch.region.us")}</option>
                  <option value="HK">{t("data.fetch.region.hk")}</option>
                </select>
                <select
                  className="form-select"
                  value={fetchForm.asset_class}
                  onChange={(e) => updateFetchForm("asset_class", e.target.value)}
                >
                  <option value="Equity">{t("data.fetch.asset.equity")}</option>
                  <option value="ETF">{t("data.fetch.asset.etf")}</option>
                </select>
              </div>
              <div className="form-hint">
                {t("data.fetch.preview", {
                  dataset: fetchPreview.datasetName,
                  source: fetchPreview.sourcePath,
                })}
              </div>
              {fetchError && <div className="form-error">{fetchError}</div>}
              {fetchResult && (
                <div className="form-success">
                  {fetchResult.job
                    ? t(
                        fetchResult.created
                          ? "data.fetch.successCreated"
                          : "data.fetch.successQueued",
                        {
                          name: fetchResult.dataset.name,
                          jobId: fetchResult.job.id,
                        }
                      )
                    : t("data.fetch.successNoJob", { name: fetchResult.dataset.name })}
                </div>
              )}
              <div className="form-actions">
                <button
                  type="button"
                  className="primary-button large"
                  onClick={fetchHistory}
                  disabled={fetchLoading}
                >
                  {fetchLoading ? t("data.fetch.loading") : t("data.fetch.action")}
                </button>
                <span className="form-note">{t("data.fetch.hint")}</span>
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
        </div>



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
          {listError && <div className="market-inline-error">{listError}</div>}
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
                {groupedDatasets.map((group) => (
                  <tr key={group.key}>
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
                            {new Date(item.updated_at).toLocaleString()}
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
                            {renderQualitySummary(item.id)}
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="market-actions">
                      <div className="market-stack">
                        {group.items.map((item) => {
                          const job = latestSyncByDataset.get(item.id);
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
                                <span className={`pill ${statusClass(job.status) || ""}`}>
                                  {renderStatus(job.status)}
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
                    </td>
                  </tr>
                ))}
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
          <div className="card-title">{t("data.jobs.title")}</div>
          <div className="card-meta">{t("data.jobs.meta", { total: syncTotal })}</div>
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
              {syncJobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.id}</td>
                  <td>{job.dataset_name || `#${job.dataset_id}`}</td>
                  <td>
                    <span className={`pill ${statusClass(job.status) || ""}`}>
                      {renderStatus(job.status)}
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
                  <td>{job.message || t("common.none")}</td>
                  <td>{new Date(job.created_at).toLocaleString()}</td>
                </tr>
              ))}
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
