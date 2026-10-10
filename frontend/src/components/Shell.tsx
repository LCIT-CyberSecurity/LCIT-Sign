import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  ChevronRight,
  FileSignature,
  FileText,
  ImageIcon,
  KeyRound,
  Mail,
  Megaphone,
  PenLine,
  Menu,
  ScrollText,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import { currentLocale } from "../i18n";
import { useCompanyLogo } from "../lib/branding";
import ChangePasswordDialog from "./ChangePasswordDialog";
import PasswordReminder, { REMINDER_KEY } from "./PasswordReminder";
import UserMenu from "./UserMenu";

function NavItem({
  to,
  icon,
  label,
  end,
  onNavigate,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  end?: boolean;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
    >
      {icon}
      <span>{label}</span>
    </NavLink>
  );
}

// Catalogue keys, not texts: the breadcrumb is translated when it is drawn.
const TITLES: [prefix: string, key: string][] = [
  ["/signatures", "nav.mySignatures"],
  ["/assignments", "nav.documentToSign"],
  ["/documents", "nav.documents"],
  ["/sign", "nav.sign"],
  ["/campaigns", "nav.tracking"],
  ["/admin/users", "nav.users"],
  ["/admin/branding", "nav.logo"],
  ["/admin/identity", "nav.identity"],
  ["/admin/mail", "nav.mailTitle"],
  ["/admin/audit", "nav.audit"],
  ["/admin/signing-keys", "nav.signingKeys"],
  ["/admin/diagnostics", "nav.diagnostics"],
];

function sectionTitleKey(pathname: string): string {
  return TITLES.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "nav.mySignatures";
}

export default function Shell() {
  const { t } = useTranslation();
  const { user, hasRole, refresh } = useAuth();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  // The company's own logo when an administrator set one, the LCIT one otherwise.
  const companyLogo = useCompanyLogo();
  const isOperator = hasRole("SIGNER") || hasRole("OPERATOR") || hasRole("ADMIN");
  const isAdmin = hasRole("ADMIN");
  const close = () => setOpen(false);

  const roleLabel = isAdmin
    ? t("roles.admin")
    : hasRole("OPERATOR")
      ? t("roles.operator")
      : hasRole("SIGNER")
        ? t("roles.signer")
        : t("roles.user");

  const logout = async () => {
    try {
      window.sessionStorage.removeItem(REMINDER_KEY);
    } catch {
      // storage unavailable: nothing to forget
    }
    await api.post("/auth/logout");
    await refresh();
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar${open ? " sidebar--open" : ""}`}>
        <div className="brand">
          <img className="brand-logo" src={companyLogo ?? "/lcit-mark.png"} alt={companyLogo ? t("shell.logoAlt") : "LCIT"} />
          <div>
            <span>Sign</span>
            <small>{t("shell.tagline")}</small>
          </div>
        </div>
        <nav aria-label={t("nav.main")}>
          <div className="nav-heading">{t("nav.mySpace")}</div>
          <NavItem to="/" end icon={<FileSignature size={18} />} label={t("nav.mySignatures")} onNavigate={close} />
          {isOperator && (
            <>
              <div className="nav-heading">{t("nav.myRequests")}</div>
              <NavItem to="/documents" icon={<FileText size={18} />} label={t("nav.documents")} onNavigate={close} />
              <NavItem to="/sign" icon={<PenLine size={18} />} label={t("nav.sign")} onNavigate={close} />
              <NavItem to="/campaigns" icon={<Megaphone size={18} />} label={t("nav.tracking")} onNavigate={close} />
            </>
          )}
          {isAdmin && (
            <>
              <div className="nav-heading">{t("nav.administration")}</div>
              <NavItem to="/admin/users" icon={<Users size={18} />} label={t("nav.users")} onNavigate={close} />
              <NavItem to="/admin/branding" icon={<ImageIcon size={18} />} label={t("nav.logo")} onNavigate={close} />
              <NavItem to="/admin/identity" icon={<KeyRound size={18} />} label={t("nav.identity")} onNavigate={close} />
              <NavItem to="/admin/mail" icon={<Mail size={18} />} label={t("nav.mail")} onNavigate={close} />
              <NavItem to="/admin/audit" icon={<ScrollText size={18} />} label={t("nav.audit")} onNavigate={close} />
              <NavItem
                to="/admin/signing-keys"
                icon={<KeyRound size={18} />}
                label={t("nav.signingKeys")}
                onNavigate={close}
              />
              <NavItem
                to="/admin/diagnostics"
                icon={<Activity size={18} />}
                label={t("nav.diagnostics")}
                onNavigate={close}
              />
            </>
          )}
        </nav>
        <div className="sidebar-footer">
          <strong>
            <ShieldCheck size={13} aria-hidden="true" /> LCIT Cybersecurity
          </strong>
          {t("shell.signedInAs", { role: currentLocale() === "de" ? roleLabel : roleLabel.toLowerCase() })}
        </div>
      </aside>
      {open && <div className="sidebar-scrim" onClick={close} aria-hidden="true" />}

      <div className="page">
        <header className="topbar">
          <div className="crumb">
            <button
              className="button button--ghost button--sm mobile-menu"
              onClick={() => setOpen(true)}
              aria-label={t("shell.openMenu")}
            >
              <Menu size={18} />
            </button>
            <span>LCIT Sign</span>
            <ChevronRight size={14} aria-hidden="true" />
            <strong>{t(sectionTitleKey(pathname))}</strong>
          </div>
          <div className="top-actions">
            {user && (
              <UserMenu user={user} onSignOut={logout} onChangePassword={() => setChangingPassword(true)} />
            )}
          </div>
        </header>
        <PasswordReminder />
        {changingPassword && <ChangePasswordDialog onClose={() => setChangingPassword(false)} />}
        <main className="app-main app-main--shell">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
