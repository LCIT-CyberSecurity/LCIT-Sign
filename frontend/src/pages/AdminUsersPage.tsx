import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Download, Trash2, UserPlus, Users } from "lucide-react";
import { api } from "../api/client";
import i18n from "../i18n";
import { blockerText, errorText } from "../i18n/errors";
import { collator, formatDate } from "../i18n/format";
import ConfirmButton from "../components/ConfirmButton";
import type { AdminUser, Role } from "../api/types";

const ALL_ROLES: Role[] = ["SIGNER", "OPERATOR", "ADMIN"];
// Catalogue keys of what is displayed for each API role value (the values themselves never change).
const ROLE_KEYS: Record<Role, string> = {
  SIGNER: "roles.signer",
  OPERATOR: "roles.operator",
  ADMIN: "roles.adminShort",
};
const KNOWN_SOURCES = ["sso", "manual", "builtin", "password", "local", "entra", "google", "ldap"];

/** A user's origin as displayed; a source this build does not know is shown as the API sent it. */
export function sourceLabel(source: string): string {
  return KNOWN_SOURCES.includes(source) ? i18n.t(`users.source.${source}`) : source;
}

export default function AdminUsersPage() {
  const { t } = useTranslation();
  const roleLabel = (role: Role) => t(ROLE_KEYS[role]);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [showDisabled, setShowDisabled] = useState(true);
  const [email, setEmail] = useState("");
  const [given, setGiven] = useState("");
  const [family, setFamily] = useState("");
  const [method, setMethod] = useState<"sso" | "local">("sso");
  const [password, setPassword] = useState("");
  const [newRoles, setNewRoles] = useState<Role[]>(["SIGNER"]);
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
      setError(errorText(err, "users.actionFailed"));
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
      () =>
        api.post("/admin/users", {
          email,
          given_name: given,
          family_name: family,
          roles: newRoles,
          auth_method: method,
          password: method === "local" ? password : undefined,
        }),
      method === "local"
        ? t("users.addedLocal", { email })
        : t("users.addedSso", { email }),
    );
    setEmail("");
    setGiven("");
    setFamily("");
    // The password never stays in the page once it has been sent.
    setPassword("");
  };

  const sources = useMemo(() => [...new Set((users ?? []).map((u) => u.source))].sort(), [users]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (users ?? [])
      .filter((u) => (showDisabled || u.active) && (!sourceFilter || u.source === sourceFilter))
      .filter((u) => !q || `${u.display_name} ${u.email}`.toLowerCase().includes(q))
      .sort((a, b) => collator().compare(a.display_name, b.display_name));
  }, [users, query, sourceFilter, showDisabled, i18n.language]);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <Users size={22} aria-hidden="true" /> {t("users.title")}
            <span className="count-badge">{users?.length ?? 0}</span>
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            {t("users.subtitle")}
          </p>
        </div>
        <Link className="button button--secondary" to="/admin/directory">
          <Download size={14} aria-hidden="true" /> {t("users.importFromDirectory")}
        </Link>
      </div>

      <form className="card form" onSubmit={add} aria-label={t("users.addForm")}>
        <div className="card-title">
          <UserPlus size={16} aria-hidden="true" /> {t("users.addByEmail")}
        </div>
        <div className="form-row">
          <label>
            {t("users.email")}
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder={t("users.emailPlaceholder")} />
          </label>
          <label>
            {t("users.givenName")}
            <input value={given} onChange={(e) => setGiven(e.target.value)} />
          </label>
          <label>
            {t("users.familyName")}
            <input value={family} onChange={(e) => setFamily(e.target.value)} />
          </label>
          <button className="button button--primary" type="submit" style={{ alignSelf: "end" }}>
            {t("users.add")}
          </button>
        </div>
        <fieldset className="form-row" style={{ border: 0, padding: 0 }}>
          <legend className="muted small">{t("users.authMethod")}</legend>
          <label>
            <input type="radio" name="auth-method" checked={method === "sso"} onChange={() => setMethod("sso")} /> {t("users.sso")}
          </label>
          <label>
            <input type="radio" name="auth-method" checked={method === "local"} onChange={() => setMethod("local")} /> {t("users.localAccount")}
          </label>
          {method === "local" && (
            <label>
              {t("users.initialPassword")}
              <input
                type="password"
                value={password}
                autoComplete="new-password"
                minLength={8}
                required
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
          )}
        </fieldset>
        <fieldset className="form-row" style={{ border: 0, padding: 0 }}>
          <legend className="muted small">{t("users.roles")}</legend>
          {ALL_ROLES.map((role) => (
            <label key={role}>
              <input
                type="checkbox"
                checked={newRoles.includes(role)}
                onChange={() =>
                  setNewRoles((all) => (all.includes(role) ? all.filter((r) => r !== role) : [...all, role]))
                }
              />{" "}
              {roleLabel(role)}
            </label>
          ))}
        </fieldset>
      </form>

      {error && <p className="error-text" role="alert">{error}</p>}
      {message && <p className="muted" role="status">{message}</p>}

      <div className="filter-bar">
        <input
          type="search"
          placeholder={t("users.searchPlaceholder")}
          aria-label={t("users.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label>
          {t("users.sourceFilter")}
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value="">{t("users.allSources")}</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {sourceLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="consent-row">
          <input type="checkbox" checked={showDisabled} onChange={(e) => setShowDisabled(e.target.checked)} />
          {t("users.showDisabled")}
        </label>
      </div>

      <div className="table-wrap">
        <table className="simple-table">
          <thead>
            <tr>
              <th>{t("users.columns.user")}</th>
              <th>{t("users.columns.source")}</th>
              <th>{t("users.columns.status")}</th>
              {ALL_ROLES.map((role) => (
                <th key={role}>{roleLabel(role)}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  {users ? t("users.noMatch") : t("common.loading")}
                </td>
              </tr>
            )}
            {visible.map((u) => (
              <tr key={u.id} data-testid={`user-${u.email}`}>
                <td>
                  <strong>{u.display_name}</strong>
                  {u.external && (
                    <span className="badge badge--viewed" style={{ marginLeft: 8 }}>
                      {t("users.external")}
                    </span>
                  )}
                  <div className="muted small">{u.email}</div>
                </td>
                <td>{sourceLabel(u.source)}</td>
                <td>
                  <span className={`badge badge--${u.active ? "signed" : "cancelled"}`}>
                    {u.active ? t("users.active") : t("users.disabled")}
                  </span>
                  <div className="muted small">
                    {u.last_login_at
                      ? t("users.lastSeen", { date: formatDate(u.last_login_at) })
                      : t("users.neverSignedIn")}
                  </div>
                </td>
                {ALL_ROLES.map((role) => (
                  <td key={role}>
                    <input
                      type="checkbox"
                      aria-label={t("users.roleOf", { role: roleLabel(role), email: u.email })}
                      checked={u.roles.includes(role)}
                      onChange={() => void toggleRole(u, role)}
                    />
                  </td>
                ))}
                <td>
                  <div className="row-actions">
                    {u.active ? (
                      <ConfirmButton
                        confirmLabel={t("users.confirmDisable")}
                        onConfirm={() => run(() => api.patch(`/admin/users/${u.id}`, { active: false }))}
                      >
                        {t("users.disable")}
                      </ConfirmButton>
                    ) : (
                      <button
                        className="button button--secondary button--sm"
                        onClick={() => void run(() => api.patch(`/admin/users/${u.id}`, { active: true }))}
                      >
                        {t("users.enable")}
                      </button>
                    )}
                    {u.can_delete && (
                      <ConfirmButton onConfirm={() => run(() => api.del(`/admin/users/${u.id}`))}>
                        <Trash2 size={13} aria-hidden="true" /> {t("common.delete")}
                      </ConfirmButton>
                    )}
                  </div>
                  {!u.can_delete && (
                    <p className="blocker-note" title={t("users.keptHint")}>
                      {t("users.kept", { reasons: u.delete_blockers.map(blockerText).join(" ; ") })}
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
