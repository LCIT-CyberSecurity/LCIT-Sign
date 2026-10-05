import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  FileSignature,
  FileText,
  Megaphone,
  Users,
  FolderCog,
  Mail,
  ScrollText,
  KeyRound,
  Activity,
  LogOut,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";

function NavItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <NavLink to={to} className={({ isActive }) => `nav-item${isActive ? " nav-item--active" : ""}`}>
      {icon}
      <span>{label}</span>
    </NavLink>
  );
}

export default function Shell() {
  const { user, hasRole, refresh } = useAuth();
  const isOperator = hasRole("OPERATOR") || hasRole("ADMIN");
  const isAdmin = hasRole("ADMIN");

  const logout = async () => {
    await api.post("/auth/logout");
    await refresh();
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <FileSignature size={20} aria-hidden="true" />
          <span>LCIT Sign</span>
        </div>
        <div className="header-user">
          <span className="header-user__name">{user?.display_name}</span>
          <button className="button button--ghost" onClick={logout}>
            <LogOut size={14} aria-hidden="true" />
            Déconnexion
          </button>
        </div>
      </header>
      <div className="app-body">
        <nav className="app-nav">
          <NavItem to="/" icon={<FileText size={16} />} label="Mes documents" />
          {isOperator && (
            <>
              <div className="nav-section">Opérateur</div>
              <NavItem to="/documents" icon={<FileText size={16} />} label="Documents" />
              <NavItem to="/campaigns" icon={<Megaphone size={16} />} label="Campagnes" />
            </>
          )}
          {isAdmin && (
            <>
              <div className="nav-section">Administration</div>
              <NavItem to="/admin/users" icon={<Users size={16} />} label="Utilisateurs" />
              <NavItem to="/admin/directory" icon={<FolderCog size={16} />} label="Annuaire" />
              <NavItem to="/admin/mail" icon={<Mail size={16} />} label="Email" />
              <NavItem to="/admin/audit" icon={<ScrollText size={16} />} label="Audit" />
              <NavItem to="/admin/signing-keys" icon={<KeyRound size={16} />} label="Clés de signature" />
              <NavItem to="/admin/diagnostics" icon={<Activity size={16} />} label="Diagnostic" />
            </>
          )}
        </nav>
        <main className="app-main app-main--shell">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
