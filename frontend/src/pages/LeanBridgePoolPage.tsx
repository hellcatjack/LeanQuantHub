import { useCallback, useEffect, useState } from "react";
import TopBar from "../components/TopBar";
import { api } from "../api";
import { useI18n } from "../i18n";

interface LeanPoolItem {
  client_id: number;
  role?: string | null;
  status?: string | null;
  pid?: number | null;
  last_heartbeat?: string | null;
  last_order_at?: string | null;
  output_dir?: string | null;
  last_error?: string | null;
}

interface LeanPoolStatus {
  mode: string;
  count: number;
  items: LeanPoolItem[];
}

const formatMaybeDate = (value: string | null | undefined, formatDateTime: (value: string) => string) => {
  if (!value) {
    return "";
  }
  return formatDateTime(value);
};

export default function LeanBridgePoolPage() {
  const { t, formatDateTime } = useI18n();
  const [mode, setMode] = useState("paper");
  const [items, setItems] = useState<LeanPoolItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<LeanPoolStatus>("/api/brokerage/lean/pool/status", {
        params: { mode },
      });
      setItems(res.data.items || []);
    } catch (err) {
      setError(t("trade.bridgePoolError"));
    } finally {
      setLoading(false);
    }
  }, [mode, t]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  return (
    <div className="main">
      <TopBar title={t("trade.bridgePoolTitle")} />
      <div className="content">
        <div className="card">
          <div className="card-title">{t("trade.bridgePoolTitle")}</div>
          <div className="card-meta">{t("trade.bridgePoolMeta")}</div>
          <div className="form-grid two-col" style={{ marginTop: "12px" }}>
            <div className="form-row">
              <label className="form-label">{t("trade.bridgePoolMode")}</label>
              <select
                className="form-select"
                value={mode}
                onChange={(event) => setMode(event.target.value)}
              >
                <option value="paper">{t("trade.mode.paper")}</option>
                <option value="live">{t("trade.mode.live")}</option>
              </select>
            </div>
            <div className="form-row" style={{ alignContent: "end" }}>
              <button
                type="button"
                className="button-secondary"
                onClick={loadStatus}
                disabled={loading}
              >
                {loading ? t("common.loading") : t("trade.bridgePoolRefresh")}
              </button>
            </div>
          </div>
          {error && <div className="form-error" style={{ marginTop: "8px" }}>{error}</div>}
        </div>

        <div className="table-scroll" style={{ marginTop: "16px" }}>
          <table className="table">
            <thead>
              <tr>
                <th>{t("trade.bridgePoolColumns.role")}</th>
                <th>{t("trade.bridgePoolColumns.clientId")}</th>
                <th>{t("trade.bridgePoolColumns.status")}</th>
                <th>{t("trade.bridgePoolColumns.pid")}</th>
                <th>{t("trade.bridgePoolColumns.heartbeat")}</th>
                <th>{t("trade.bridgePoolColumns.lastOrder")}</th>
                <th>{t("trade.bridgePoolColumns.outputDir")}</th>
                <th>{t("trade.bridgePoolColumns.lastError")}</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty-state">
                    {t("trade.bridgePoolEmpty")}
                  </td>
                </tr>
              ) : (
                items.map((item) => {
                  const role = String(item.role || "").toLowerCase();
                  const roleLabel = role === "leader"
                    ? t("trade.bridgePoolRole.leader")
                    : t("trade.bridgePoolRole.worker");
                  return (
                    <tr key={`${item.client_id}-${role}`}>
                      <td>{roleLabel}</td>
                      <td>{item.client_id}</td>
                      <td>{item.status || t("trade.bridgePoolStatus.unknown")}</td>
                      <td>{item.pid ?? ""}</td>
                      <td>{formatMaybeDate(item.last_heartbeat, formatDateTime)}</td>
                      <td>{formatMaybeDate(item.last_order_at, formatDateTime)}</td>
                      <td>{item.output_dir || ""}</td>
                      <td>{item.last_error || ""}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
