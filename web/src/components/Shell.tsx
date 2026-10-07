import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  BadgeCheck,
  ChevronRight,
  FileSignature,
  FileText,
  FolderCog,
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

const TITLES: [prefix: string, label: string][] = [
  ["/signatures", "Mes signatures"],
  ["/assignments", "Document à signer"],
  ["/documents", "Documents"],
  ["/sign", "Faire signer"],
  ["/campaigns", "Suivi"],
  ["/admin/users", "Utilisateurs"],
  ["/admin/branding", "Logo"],
  ["/admin/login", "Connexion"],
  ["/admin/directory", "Annuaire"],
  ["/admin/mail", "E-mail"],
  ["/admin/docusign", "DocuSign"],
  ["/admin/audit", "Audit"],
  ["/admin/signing-keys", "Clés de signature"],
  ["/admin/diagnostics", "Diagnostic"],
];

function sectionTitle(pathname: string): string {
  return TITLES.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "Mes signatures";
}

export default function Shell() {
  const { user, hasRole, refresh } = useAuth();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  // The company's own logo when an administrator set one, the LCIT one otherwise.
  const companyLogo = useCompanyLogo();
  const isOperator = hasRole("PREPARER") || hasRole("OPERATOR") || hasRole("ADMIN");
  const isAdmin = hasRole("ADMIN");
  const close = () => setOpen(false);

  const roleLabel = isAdmin
    ? "Administrateur"
    : hasRole("OPERATOR")
      ? "Opérateur"
      : hasRole("PREPARER")
        ? "Préparateur"
        : "Signataire";

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
          <img className="brand-logo" src={companyLogo ?? "/lcit-mark.png"} alt={companyLogo ? "Logo" : "LCIT"} />
          <div>
            <span>Sign</span>
            <small>Signature &amp; attestation</small>
          </div>
        </div>
        <nav aria-label="Navigation principale">
          <div className="nav-heading">Mon espace</div>
          <NavItem to="/" end icon={<FileSignature size={18} />} label="Mes signatures" onNavigate={close} />
          {isOperator && (
            <>
              <div className="nav-heading">Opérateur</div>
              <NavItem to="/documents" icon={<FileText size={18} />} label="Documents" onNavigate={close} />
              <NavItem to="/sign" icon={<PenLine size={18} />} label="Faire signer" onNavigate={close} />
              <NavItem to="/campaigns" icon={<Megaphone size={18} />} label="Suivi" onNavigate={close} />
            </>
          )}
          {isAdmin && (
            <>
              <div className="nav-heading">Administration</div>
              <NavItem to="/admin/users" icon={<Users size={18} />} label="Utilisateurs" onNavigate={close} />
              <NavItem to="/admin/branding" icon={<ImageIcon size={18} />} label="Logo" onNavigate={close} />
              <NavItem to="/admin/login" icon={<KeyRound size={18} />} label="Connexion" onNavigate={close} />
              <NavItem to="/admin/directory" icon={<FolderCog size={18} />} label="Annuaire" onNavigate={close} />
              <NavItem to="/admin/mail" icon={<Mail size={18} />} label="Email" onNavigate={close} />
              <NavItem
                to="/admin/docusign"
                icon={<BadgeCheck size={18} />}
                label="DocuSign"
                onNavigate={close}
              />
              <NavItem to="/admin/audit" icon={<ScrollText size={18} />} label="Audit" onNavigate={close} />
              <NavItem
                to="/admin/signing-keys"
                icon={<KeyRound size={18} />}
                label="Clés de signature"
                onNavigate={close}
              />
              <NavItem
                to="/admin/diagnostics"
                icon={<Activity size={18} />}
                label="Diagnostic"
                onNavigate={close}
              />
            </>
          )}
        </nav>
        <div className="sidebar-footer">
          <strong>
            <ShieldCheck size={13} aria-hidden="true" /> LCIT Cybersecurity
          </strong>
          Connecté en tant que {roleLabel.toLowerCase()}
        </div>
      </aside>
      {open && <div className="sidebar-scrim" onClick={close} aria-hidden="true" />}

      <div className="page">
        <header className="topbar">
          <div className="crumb">
            <button
              className="button button--ghost button--sm mobile-menu"
              onClick={() => setOpen(true)}
              aria-label="Ouvrir le menu"
            >
              <Menu size={18} />
            </button>
            <span>LCIT Sign</span>
            <ChevronRight size={14} aria-hidden="true" />
            <strong>{sectionTitle(pathname)}</strong>
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
