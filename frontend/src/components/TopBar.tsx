import { useI18n } from "../i18n";

interface TopBarProps {
  title: string;
}

export default function TopBar({ title }: TopBarProps) {
  const { locale, setLocale, t } = useI18n();
  const nextLocale = locale === "zh" ? "en" : "zh";

  return (
    <header className="topbar">
      <div className="topbar-title">{title}</div>
      <div className="topbar-actions">
        <span className="badge">{t("topbar.localRunner")}</span>
        <span className="badge">{t("topbar.leanEngine")}</span>
        <button
          type="button"
          className="badge lang-toggle"
          title={t("topbar.switchLanguage")}
          onClick={() => setLocale(nextLocale)}
        >
          {locale === "zh" ? t("topbar.localeShort.en") : t("topbar.localeShort.zh")}
        </button>
      </div>
    </header>
  );
}
