import { TimeZone, useI18n } from "../i18n";

interface TopBarProps {
  title: string;
}

export default function TopBar({ title }: TopBarProps) {
  const { locale, setLocale, timeZone, setTimeZone, t } = useI18n();
  const nextLocale = locale === "zh" ? "en" : "zh";
  const timeZoneOptions = [
    { value: "America/New_York", label: t("topbar.timezoneOptions.et") },
    { value: "UTC", label: t("topbar.timezoneOptions.utc") },
    { value: "Asia/Shanghai", label: t("topbar.timezoneOptions.cn") },
    { value: "Asia/Hong_Kong", label: t("topbar.timezoneOptions.hk") },
  ];

  return (
    <header className="topbar">
      <div className="topbar-title">{title}</div>
      <div className="topbar-actions">
        <span className="badge">{t("topbar.localRunner")}</span>
        <span className="badge">{t("topbar.leanEngine")}</span>
        <div className="timezone-control">
          <span className="badge">{t("topbar.timezone")}</span>
          <select
            className="timezone-select"
            value={timeZone}
            onChange={(event) => setTimeZone(event.target.value as TimeZone)}
          >
            {timeZoneOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
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
