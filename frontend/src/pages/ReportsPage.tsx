import ReportsPanel from "../components/ReportsPanel";
import TopBar from "../components/TopBar";
import { useI18n } from "../i18n";

export default function ReportsPage() {
  const { t } = useI18n();

  return (
    <div className="main">
      <TopBar title={t("reports.title")} />
      <div className="content">
        <ReportsPanel />
      </div>
    </div>
  );
}
