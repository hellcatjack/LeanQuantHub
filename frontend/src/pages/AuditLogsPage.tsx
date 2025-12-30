import { useEffect, useState } from "react";
import { api } from "../api";
import PaginationBar from "../components/PaginationBar";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { Paginated } from "../types";

interface AuditLog {
  id: number;
  actor: string;
  action: string;
  resource_type: string;
  resource_id?: number | null;
  detail?: Record<string, unknown> | null;
  created_at: string;
}

export default function AuditLogsPage() {
  const { t } = useI18n();
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [logTotal, setLogTotal] = useState(0);
  const [logPage, setLogPage] = useState(1);
  const [logPageSize, setLogPageSize] = useState(10);
  const [filters, setFilters] = useState({
    action: "",
    resource_type: "",
    resource_id: "",
  });

  const load = async (pageOverride?: number, pageSizeOverride?: number) => {
    const nextPage = pageOverride ?? logPage;
    const nextSize = pageSizeOverride ?? logPageSize;
    const params: Record<string, string | number> = {
      page: nextPage,
      page_size: nextSize,
    };
    if (filters.action.trim()) {
      params.action = filters.action.trim();
    }
    if (filters.resource_type.trim()) {
      params.resource_type = filters.resource_type.trim();
    }
    if (filters.resource_id.trim()) {
      params.resource_id = filters.resource_id.trim();
    }
    const res = await api.get<Paginated<AuditLog>>("/api/audit-logs/page", { params });
    setLogs(res.data.items);
    setLogTotal(res.data.total);
  };

  useEffect(() => {
    load();
  }, [logPage, logPageSize]);

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const applyFilters = () => {
    setLogPage(1);
    load(1, logPageSize);
  };

  return (
    <div className="main">
      <TopBar title={t("audit.title")} />
      <div className="content">
        <div className="card">
          <div className="card-title">{t("audit.filters.title")}</div>
          <div className="card-meta">{t("audit.filters.meta")}</div>
          <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
            <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr 1fr" }}>
              <input
                value={filters.action}
                onChange={(e) => updateFilter("action", e.target.value)}
                placeholder={t("audit.filters.action")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={filters.resource_type}
                onChange={(e) => updateFilter("resource_type", e.target.value)}
                placeholder={t("audit.filters.resourceType")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
              <input
                value={filters.resource_id}
                onChange={(e) => updateFilter("resource_id", e.target.value)}
                placeholder={t("audit.filters.resourceId")}
                style={{ padding: "10px", borderRadius: "10px", border: "1px solid #e3e6ee" }}
              />
            </div>
            <button
              onClick={applyFilters}
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
              {t("common.actions.query")}
            </button>
          </div>
        </div>

        <table className="table">
          <thead>
            <tr>
              <th>{t("audit.table.id")}</th>
              <th>{t("audit.table.time")}</th>
              <th>{t("audit.table.action")}</th>
              <th>{t("audit.table.resource")}</th>
              <th>{t("audit.table.detail")}</th>
            </tr>
          </thead>
          <tbody>
            {logs.length === 0 && (
              <tr>
                <td colSpan={5}>{t("audit.table.empty")}</td>
              </tr>
            )}
            {logs.map((log) => (
              <tr key={log.id}>
                <td>{log.id}</td>
                <td>{new Date(log.created_at).toLocaleString()}</td>
                <td>{log.action}</td>
                <td>
                  {log.resource_type}
                  {log.resource_id ? ` #${log.resource_id}` : ""}
                </td>
                <td>
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: "pre-wrap",
                      fontSize: "12px",
                      color: "#334155",
                    }}
                  >
                    {log.detail ? JSON.stringify(log.detail, null, 2) : "-"}
                  </pre>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <PaginationBar
          page={logPage}
          pageSize={logPageSize}
          total={logTotal}
          onPageChange={setLogPage}
          onPageSizeChange={(size) => {
            setLogPage(1);
            setLogPageSize(size);
          }}
        />
      </div>
    </div>
  );
}
