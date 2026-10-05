import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Download, Trash2, UserPlus, Users } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
import type { AdminUser, Role } from "../api/types";

const ALL_ROLES: Role[] = ["SIGNER", "OPERATOR", "ADMIN"];
const ROLE_LABELS: Record<Role, string> = {
  SIGNER: "Signataire",
  OPERATOR: "Opérateur",
  ADMIN: "Admin",
};
const SOURCE_LABELS: Record<string, string> = {
  sso: "Connexion SSO",
  manual: "Ajouté à la main",
  builtin: "Compte système",
  local: "Démonstration",
  entra: "Entra ID",
  google: "Google Workspace",
  ldap: "LDAP",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [showDisabled, setShowDisabled] = useState(true);
  const [email, setEmail] = useState("");
  const [given, setGiven] = useState("");
  const [family, setFamily] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => {
    api.get<AdminUser[]>("/admin/users").then(setUsers);
  };
  useEffect(load, []);

  const run = async (action: () => Promise<unknown>, done?: string) => {
    setError(null);
    setMessage(null);
    try {
      await action();
      if (done) setMessage(done);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "L'action a échoué.");
    }
  };

  const toggleRole = (user: AdminUser, role: Role) =>
    run(() =>
      user.roles.includes(role)
        ? api.del(`/admin/users/${user.id}/roles/${role}`)
        : api.post(`/admin/users/${user.id}/roles`, { role }),
    );

  const add = async (e: FormEvent) => {
    e.preventDefault();
    await run(
      () => api.post("/admin/users", { email, given_name: given, family_name: family }),
      `${email} a été ajouté. Cette personne se connectera avec son SSO habituel.`,
    );
    setEmail("");
    setGiven("");
    setFamily("");
  };

  const sources = useMemo(() => [...new Set((users ?? []).map((u) => u.source))].sort(), [users]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (users ?? [])
      .filter((u) => (showDisabled || u.active) && (!sourceFilter || u.source === sourceFilter))
      .filter((u) => !q || `${u.display_name} ${u.email}`.toLowerCase().includes(q))
      .sort((a, b) => a.display_name.localeCompare(b.display_name, "fr", { sensitivity: "base" }));
  }, [users, query, sourceFilter, showDisabled]);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <Users size={22} aria-hidden="true" /> Utilisateurs
            <span className="count-badge">{users?.length ?? 0}</span>
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            Les personnes se connectent par SSO : aucun mot de passe n&apos;est géré ici. Importez-les depuis votre annuaire
            ou ajoutez-les par e-mail.
          </p>
        </div>
        <Link className="button button--secondary" to="/admin/directory">
          <Download size={14} aria-hidden="true" /> Importer depuis l&apos;annuaire
        </Link>
      </div>

      <form className="card form" onSubmit={add} aria-label="Ajouter un utilisateur">
        <div className="card-title">
          <UserPlus size={16} aria-hidden="true" /> Ajouter quelqu&apos;un par e-mail
        </div>
        <div className="form-row">
          <label>
            Adresse e-mail
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="prenom.nom@entreprise.fr" />
          </label>
          <label>
            Prénom
            <input value={given} onChange={(e) => setGiven(e.target.value)} />
          </label>
          <label>
            Nom
            <input value={family} onChange={(e) => setFamily(e.target.value)} />
          </label>
          <button className="button button--primary" type="submit" style={{ alignSelf: "end" }}>
            Ajouter
          </button>
        </div>
      </form>

      {error && <p className="error-text" role="alert">{error}</p>}
      {message && <p className="muted" role="status">{message}</p>}

      <div className="filter-bar">
        <input
          type="search"
          placeholder="Rechercher un nom, une adresse…"
          aria-label="Rechercher un utilisateur"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label>
          Source
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value="">Toutes</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {sourceLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="consent-row">
          <input type="checkbox" checked={showDisabled} onChange={(e) => setShowDisabled(e.target.checked)} />
          Afficher les désactivés
        </label>
      </div>

      <div className="table-wrap">
        <table className="simple-table">
          <thead>
            <tr>
              <th>Utilisateur</th>
              <th>Source</th>
              <th>Statut</th>
              {ALL_ROLES.map((role) => (
                <th key={role}>{ROLE_LABELS[role]}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  {users ? "Aucun utilisateur ne correspond." : "Chargement…"}
                </td>
              </tr>
            )}
            {visible.map((u) => (
              <tr key={u.id} data-testid={`user-${u.email}`}>
                <td>
                  <strong>{u.display_name}</strong>
                  <div className="muted small">{u.email}</div>
                </td>
                <td>{sourceLabel(u.source)}</td>
                <td>
                  <span className={`badge badge--${u.active ? "signed" : "cancelled"}`}>
                    {u.active ? "Actif" : "Désactivé"}
                  </span>
                  <div className="muted small">
                    {u.last_login_at
                      ? `Vu le ${new Date(u.last_login_at).toLocaleDateString("fr-FR")}`
                      : "Jamais connecté"}
                  </div>
                </td>
                {ALL_ROLES.map((role) => (
                  <td key={role}>
                    <input
                      type="checkbox"
                      aria-label={`${ROLE_LABELS[role]} — ${u.email}`}
                      checked={u.roles.includes(role)}
                      onChange={() => void toggleRole(u, role)}
                    />
                  </td>
                ))}
                <td>
                  <div className="row-actions">
                    {u.active ? (
                      <ConfirmButton
                        confirmLabel="Confirmer la désactivation"
                        onConfirm={() => run(() => api.patch(`/admin/users/${u.id}`, { active: false }))}
                      >
                        Désactiver
                      </ConfirmButton>
                    ) : (
                      <button
                        className="button button--secondary button--sm"
                        onClick={() => void run(() => api.patch(`/admin/users/${u.id}`, { active: true }))}
                      >
                        Réactiver
                      </button>
                    )}
                    {u.can_delete && (
                      <ConfirmButton onConfirm={() => run(() => api.del(`/admin/users/${u.id}`))}>
                        <Trash2 size={13} aria-hidden="true" /> Supprimer
                      </ConfirmButton>
                    )}
                  </div>
                  {!u.can_delete && (
                    <p className="blocker-note" title="Conservé : fait partie de l'historique ou géré par une source">
                      Conservé — {u.delete_blockers.join(" ; ")}
                    </p>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
