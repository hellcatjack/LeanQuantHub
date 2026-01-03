import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import { DatasetSummary } from "../types";
import DatasetChartPanel from "./DatasetChartPanel";

interface BacktestTrade {
  symbol: string;
  time: number;
  price: number;
  quantity: number;
  side: "buy" | "sell";
}

interface BacktestPosition {
  symbol: string;
  start_time: number;
  end_time: number;
  entry_price: number;
  exit_price: number;
  quantity: number;
  profit: boolean;
}

interface BacktestSymbol {
  symbol: string;
  trades: number;
}

interface BacktestChartResponse {
  run_id: number;
  symbol?: string | null;
  symbols: BacktestSymbol[];
  trades: BacktestTrade[];
  positions: BacktestPosition[];
  dataset?: DatasetSummary | null;
}

interface BacktestChartPanelProps {
  runId: number;
}

const MAX_MARKERS = 600;
const MAX_TRADE_ROWS = 30;

export default function BacktestChartPanel({ runId }: BacktestChartPanelProps) {
  const { t, formatDateTime } = useI18n();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [symbols, setSymbols] = useState<BacktestSymbol[]>([]);
  const [activeSymbol, setActiveSymbol] = useState("");
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [positions, setPositions] = useState<BacktestPosition[]>([]);
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);

  const loadChart = async (symbol?: string) => {
    if (!runId) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await api.get<BacktestChartResponse>(`/api/backtests/${runId}/chart`, {
        params: symbol ? { symbol } : undefined,
      });
      const payload = res.data;
      setSymbols(payload.symbols || []);
      setActiveSymbol(payload.symbol || "");
      setTrades(payload.trades || []);
      setPositions(payload.positions || []);
      setDataset(payload.dataset || null);
    } catch (err) {
      setError(t("reports.trades.error"));
      setSymbols([]);
      setActiveSymbol("");
      setTrades([]);
      setPositions([]);
      setDataset(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadChart();
  }, [runId]);

  const markers = useMemo(() => {
    if (!trades.length) {
      return [];
    }
    return trades.slice(-MAX_MARKERS).map((trade) => ({
      time: trade.time,
      position: trade.side === "buy" ? "belowBar" : "aboveBar",
      color: trade.side === "buy" ? "#16a34a" : "#ef4444",
      shape: trade.side === "buy" ? "arrowUp" : "arrowDown",
      text: `${trade.side === "buy" ? t("reports.trades.buy") : t("reports.trades.sell")} ${trade.quantity}`,
    }));
  }, [trades, t]);

  const tradeRows = useMemo(() => {
    if (!trades.length) {
      return [];
    }
    return [...trades].slice(-MAX_TRADE_ROWS).reverse();
  }, [trades]);

  const summary = useMemo(() => {
    if (!trades.length) {
      return "";
    }
    const buyCount = trades.filter((trade) => trade.side === "buy").length;
    const sellCount = trades.filter((trade) => trade.side === "sell").length;
    const wins = positions.filter((item) => item.profit).length;
    const losses = positions.filter((item) => !item.profit).length;
    return t("reports.trades.summary", {
      buys: buyCount,
      sells: sellCount,
      wins,
      losses,
    });
  }, [trades, positions, t]);

  const openUrl = activeSymbol
    ? `https://finance.yahoo.com/quote/${encodeURIComponent(activeSymbol)}`
    : undefined;

  return (
    <div className="card">
      <div className="card-title">{t("reports.trades.title")}</div>
      <div className="card-meta">{t("reports.trades.meta")}</div>
      <div style={{ marginTop: "12px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
        <input
          value={activeSymbol}
          onChange={(e) => setActiveSymbol(e.target.value.toUpperCase())}
          placeholder={t("reports.trades.symbolPlaceholder")}
          className="form-input"
          style={{ maxWidth: 200 }}
        />
        <button className="button-primary" onClick={() => loadChart(activeSymbol || undefined)}>
          {t("reports.trades.load")}
        </button>
        {symbols.length > 0 && (
          <select
            className="form-select"
            value={activeSymbol}
            onChange={(e) => {
              const next = e.target.value.toUpperCase();
              setActiveSymbol(next);
              void loadChart(next);
            }}
          >
            {symbols.map((item) => (
              <option key={item.symbol} value={item.symbol}>
                {item.symbol} · {t("reports.trades.tradesCount", { count: item.trades })}
              </option>
            ))}
          </select>
        )}
        {summary && <div className="form-hint">{summary}</div>}
      </div>
      {loading && <div className="form-hint">{t("reports.trades.loading")}</div>}
      {!loading && error && <div className="form-hint" style={{ color: "#d64545" }}>{error}</div>}
      {!loading && !error && dataset ? (
        <DatasetChartPanel dataset={dataset} markers={markers} openUrl={openUrl} />
      ) : null}
      {!loading && !error && !dataset && (
        <div className="empty-state">{t("reports.trades.empty")}</div>
      )}
      {!loading && !error && tradeRows.length > 0 && (
        <table className="table" style={{ marginTop: "12px" }}>
          <thead>
            <tr>
              <th>{t("reports.trades.table.time")}</th>
              <th>{t("reports.trades.table.side")}</th>
              <th>{t("reports.trades.table.qty")}</th>
              <th>{t("reports.trades.table.price")}</th>
            </tr>
          </thead>
          <tbody>
            {tradeRows.map((trade, idx) => (
              <tr key={`${trade.time}-${trade.side}-${idx}`}>
                <td>{formatDateTime(new Date(trade.time * 1000).toISOString())}</td>
                <td style={{ color: trade.side === "buy" ? "#16a34a" : "#ef4444" }}>
                  {trade.side === "buy" ? t("reports.trades.buy") : t("reports.trades.sell")}
                </td>
                <td>{trade.quantity.toFixed(2)}</td>
                <td>{trade.price.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
