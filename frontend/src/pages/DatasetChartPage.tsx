import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import DatasetChartPanel from "../components/DatasetChartPanel";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";
import { DatasetSummary } from "../types";

export default function DatasetChartPage() {
  const { t } = useI18n();
  const params = useParams();
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const datasetId = Number(params.datasetId);
    if (!Number.isFinite(datasetId)) {
      setError(t("data.chart.error"));
      setDataset(null);
      return;
    }
    const loadDataset = async () => {
      setLoading(true);
      setError("");
      try {
        const res = await api.get<DatasetSummary>(`/api/datasets/${datasetId}`);
        setDataset(res.data);
      } catch (err: any) {
        setError(t("data.chart.error"));
        setDataset(null);
      } finally {
        setLoading(false);
      }
    };
    void loadDataset();
  }, [params.datasetId, t]);

  return (
    <div className="main">
      <TopBar title={t("data.chart.title")} />
      <div className="content">
        {loading && <div className="card">{t("data.chart.loading")}</div>}
        {!loading && error && <div className="card">{error}</div>}
        {!loading && dataset && <DatasetChartPanel dataset={dataset} />}
      </div>
    </div>
  );
}
