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

interface AlgorithmDiff {
  algorithm_id: number;
  from_version_id: number;
  to_version_id: number;
  diff: string;
}

export default function AlgorithmsPage() {
  const { t } = useI18n();
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [algorithmTotal, setAlgorithmTotal] = useState(0);
  const [algorithmPage, setAlgorithmPage] = useState(1);
  const [algorithmPageSize, setAlgorithmPageSize] = useState(10);
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
  const [diffFromId, setDiffFromId] = useState("");
  const [diffToId, setDiffToId] = useState("");
  const [diffResult, setDiffResult] = useState("");
  const [diffErrorKey, setDiffErrorKey] = useState("");
  const [projectForm, setProjectForm] = useState({
    name: "",
    description: "",
    versionId: "",
    lockVersion: true,
  });
  const [projectMessage, setProjectMessage] = useState("");

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

  const loadVersions = async (algorithmId: number, pageOverride?: number, pageSizeOverride?: number) => {
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

  useEffect(() => {
    loadAlgorithms();
  }, [algorithmPage, algorithmPageSize]);

  useEffect(() => {
    if (selectedAlgorithmId) {
      setVersionPage(1);
      loadVersions(selectedAlgorithmId, 1, versionPageSize);
      loadVersionOptions(selectedAlgorithmId);
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

  const updateForm = (key: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
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
      description: form.description || null,
      language: form.language,
      file_path: form.file_path || null,
      type_name: form.type_name || null,
      version: form.version || null,
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

  const createVersion = async () => {
    if (!selectedAlgorithmId) {
      setVersionErrorKey("algorithms.versions.errorSelect");
      return;
    }
    if (!versionForm.version.trim() && !versionForm.file_path && !versionForm.content) {
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

  const selectedAlgorithm = useMemo(
    () => algorithms.find((item) => item.id === selectedAlgorithmId),
    [algorithms, selectedAlgorithmId]
  );

  const defaultLanguage = selectedAlgorithm?.language || "Python";

  return (
    <div className="main">
      <TopBar title={t("algorithms.title")} />
      <div className="content">
        <div className="grid-2">
          <div className="card">
            <div className="card-title">{t("algorithms.register.title")}</div>
            <div className="card-meta">{t("algorithms.register.meta")}</div>
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
              <input
                value={form.name}
                onChange={(e) => updateForm("name", e.target.value)}
                placeholder={t("algorithms.register.name")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={form.description}
                onChange={(e) => updateForm("description", e.target.value)}
                placeholder={t("algorithms.register.description")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr" }}>
                <input
                  value={form.language}
                  onChange={(e) => updateForm("language", e.target.value)}
                  placeholder={t("algorithms.register.language")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
                <input
                  value={form.version}
                  onChange={(e) => updateForm("version", e.target.value)}
                  placeholder={t("algorithms.register.version")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
              </div>
              <input
                value={form.file_path}
                onChange={(e) => updateForm("file_path", e.target.value)}
                placeholder={t("algorithms.register.path")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={form.type_name}
                onChange={(e) => updateForm("type_name", e.target.value)}
                placeholder={t("algorithms.register.typeName")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              {formErrorKey && (
                <div style={{ color: "#d64545", fontSize: "13px" }}>
                  {t(formErrorKey)}
                </div>
              )}
              <button
                onClick={createAlgorithm}
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
            <div className="card-title">{t("algorithms.overview.title")}</div>
            <div className="card-meta">{t("algorithms.overview.meta")}</div>
            <div style={{ fontSize: "32px", fontWeight: 600, marginTop: "12px" }}>
              {algorithmTotal}
            </div>
          </div>
        </div>

        <table className="table">
          <thead>
            <tr>
              <th>{t("algorithms.table.name")}</th>
              <th>{t("algorithms.table.language")}</th>
              <th>{t("algorithms.table.version")}</th>
              <th>{t("algorithms.table.path")}</th>
              <th>{t("algorithms.table.updatedAt")}</th>
            </tr>
          </thead>
          <tbody>
            {algorithms.map((algo) => (
              <tr key={algo.id}>
                <td>{algo.name}</td>
                <td>{algo.language}</td>
                <td>{algo.version || t("common.none")}</td>
                <td>{algo.file_path || t("common.none")}</td>
                <td>{new Date(algo.updated_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
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

        <div className="grid-2">
          <div className="card">
            <div className="card-title">{t("algorithms.versions.title")}</div>
            <div className="card-meta">{t("algorithms.versions.meta")}</div>
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
              <select
                value={selectedAlgorithmId ?? ""}
                onChange={(e) => setSelectedAlgorithmId(Number(e.target.value) || null)}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              >
                {algorithms.length === 0 && (
                  <option value="">{t("algorithms.versions.empty")}</option>
                )}
                {algorithms.map((algo) => (
                  <option key={algo.id} value={algo.id}>
                    {algo.name}
                  </option>
                ))}
              </select>
              <input
                value={versionForm.version}
                onChange={(e) => updateVersionForm("version", e.target.value)}
                placeholder={t("algorithms.versions.version")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={versionForm.description}
                onChange={(e) => updateVersionForm("description", e.target.value)}
                placeholder={t("algorithms.versions.description")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr" }}>
                <input
                  value={versionForm.language}
                  onChange={(e) => updateVersionForm("language", e.target.value)}
                  placeholder={t("algorithms.versions.language", { language: defaultLanguage })}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
                <input
                  value={versionForm.type_name}
                  onChange={(e) => updateVersionForm("type_name", e.target.value)}
                  placeholder={t("algorithms.versions.typeName")}
                  style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
                />
              </div>
              <input
                value={versionForm.file_path}
                onChange={(e) => updateVersionForm("file_path", e.target.value)}
                placeholder={t("algorithms.versions.filePath")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <textarea
                value={versionForm.content}
                onChange={(e) => updateVersionForm("content", e.target.value)}
                rows={5}
                placeholder={t("algorithms.versions.content")}
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
            <div className="card-title">{t("algorithms.diff.title")}</div>
            <div className="card-meta">{t("algorithms.diff.meta")}</div>
            <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
              <select
                value={diffFromId}
                onChange={(e) => setDiffFromId(e.target.value)}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
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
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              >
                <option value="">{t("algorithms.diff.selectTo")}</option>
                {versionOptions.map((item) => (
                  <option key={item.id} value={item.id}>
                    #{item.id} {item.version || t("algorithms.diff.unnamed")}
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
                  minHeight: "160px",
                  whiteSpace: "pre-wrap",
                }}
              >
                {diffResult || t("algorithms.diff.none")}
              </pre>
            </div>
          </div>
        </div>

        <div className="grid-2">
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
                <label className="form-label">
                  {t("algorithms.projectCreate.description")}
                </label>
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
        </div>

        <table className="table">
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
