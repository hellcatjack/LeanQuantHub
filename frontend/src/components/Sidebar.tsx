import { NavLink } from "react-router-dom";
import { useI18n } from "../i18n";

export default function Sidebar() {
  const { t } = useI18n();
  const links = [
    { to: "/projects", label: t("nav.projects") },
    { to: "/data", label: t("nav.data") },
    { to: "/backtests", label: t("nav.backtests") },
    { to: "/live-trade", label: t("nav.liveTrade") },
    { to: "/themes", label: t("nav.themes") },
    { to: "/audit-logs", label: t("nav.audit") },
  ];

  return (
    <aside className="sidebar">
      <div className="brand">LeanQuant Hub</div>
      <nav className="nav-group">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          >
            <span>{link.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">{t("app.footer")}</div>
    </aside>
  );
}
