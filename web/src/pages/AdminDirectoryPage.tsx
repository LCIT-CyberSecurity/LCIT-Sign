import { useEffect, useMemo, useState } from "react";
import { Cloud, Database, FolderCog, Network, RefreshCw, Settings2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import DirectoryConnectorForm from "./DirectoryConnectorForm";
import type { DirectoryGroup, DirectorySource, DirectorySyncRun } from "../api/types";

interface SourceInfo {
  source: string;
  title: string;
  description: string;
  icon: typeof Cloud;
  remote: boolean;
}

const ICONS: Record<string, typeof Cloud> = { entra: Cloud, google: Cloud, ldap: Network };
const LOCAL: SourceInfo = {
  source: "local",
  title: "Annuaire de démonstration",
  description: "Une organisation fictive (24 personnes, 6 groupes) pour tester sans rien connecter.",
  icon: Database,
  remote: false,
};

/** A card per connector, titled and described by the connector itself. */
function infoFor(source: DirectorySource): SourceInfo {
  if (!source.spec) return LOCAL;
  return {
    source: source.source,
    title: source.spec.label,
    description: source.spec.description,
    icon: ICONS[source.source] ?? Cloud,
    remote: true,
  };
}

const SCHEDULES: { minutes: number | null; label: string }[] = [
  { minutes: null, label: "Manuelle" },
  { minutes: 15, label: "Toutes les 15 minutes" },
  { minutes: 60, label: "Toutes les heures" },
  { minutes: 360, label: "Toutes les 6 heures" },
  { minutes: 1440, label: "Une fois par jour" },
];

export function scheduleLabel(minutes: number | null): string {
  return SCHEDULES.find((s) => s.minutes === minutes)?.label ?? `Toutes les ${minutes} minutes`;
}

function lastRunText(run: DirectorySyncRun | undefined): string {
  if (!run) return "Jamais synchronisée";
  const when = new Date(run.started_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  if (run.status === "SUCCESS") {
    return `${when} — ${run.users_added} ajouté(s), ${run.users_updated} mis à jour, ${run.users_deactivated} désactivé(s)`;
  }
  return `${when} — ${run.status === "FAILED" ? "échec" : run.status}`;
}

function SourceCard({
  info,
  source,
  lastRun,
  onChanged,
}: {
  info: SourceInfo;
  source: DirectorySource;
  lastRun: DirectorySyncRun | undefined;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const Icon = info.icon;
  const ready = !info.remote || source.configured;
  const active = Boolean(source.active);

  const sync = async () => {
    setSyncing(true);
    setError(null);
    try {
      const run = await api.post<DirectorySyncRun>(`/admin/directory/sync?source=${info.source}`);
      if (run.status === "FAILED") setError(run.error ?? "Échec de la synchronisation");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Échec de la synchronisation");
    } finally {
      setSyncing(false);
    }
  };

  const activate = async () => {
    setError(null);
    try {
      await api.post(`/admin/directory/sources/${info.source}/activate`);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Échec de l'activation");
    }
  };

  const setSchedule = async (value: string) => {
    setError(null);
    try {
      await api.put(`/admin/directory/sources/${info.source}/config`, {
        fields: source.fields,
        sync_interval_minutes: value ? Number(value) : null,
      });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Échec de l'enregistrement");
    }
  };

  return (
    <section className="card source-card" data-testid={`source-${info.source}`}>
      <div className="source-card__head">
        <span className="metric-icon" aria-hidden="true">
          <Icon size={16} />
        </span>
        <div>
          <div className="card-title" style={{ margin: 0 }}>
            {info.title}
          </div>
          <div className="muted small">{info.description}</div>
        </div>
        <span className={`badge ${ready ? "badge--signed" : "badge--draft"}`} data-testid="source-state">
          {active ? "Actif" : info.remote ? (source.configured ? "Configuré, inactif" : "Non configuré") : "Inactif"}
        </span>
      </div>

      <dl className="kv" style={{ marginTop: 12 }}>
        <dt>Dernière synchronisation</dt>
        <dd>{lastRunText(lastRun)}</dd>
        <dt>Planification</dt>
        <dd>
          <select
            value={source.sync_interval_minutes ?? ""}
            disabled={!ready || !active}
            aria-label={`Planification — ${info.title}`}
            onChange={(e) => void setSchedule(e.target.value)}
          >
            {SCHEDULES.map((s) => (
              <option key={s.label} value={s.minutes ?? ""}>
                {s.label}
              </option>
            ))}
          </select>
        </dd>
      </dl>

      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="button-row" style={{ marginTop: 14 }}>
        <button className="button button--primary button--sm" onClick={sync} disabled={!ready || !active || syncing}>
          <RefreshCw size={13} aria-hidden="true" /> {syncing ? "Synchronisation…" : "Synchroniser maintenant"}
        </button>
        {ready && !active && (
          <button className="button button--secondary button--sm" onClick={activate}>
            Utiliser cet annuaire
          </button>
        )}
        {info.remote && (
          <button className="button button--secondary button--sm" onClick={() => setOpen(!open)} aria-expanded={open}>
            <Settings2 size={13} aria-hidden="true" /> {source.configured ? "Modifier la connexion" : "Configurer"}
          </button>
        )}
      </div>
      {info.remote && open && (
        <div style={{ marginTop: 14 }}>
          <DirectoryConnectorForm
            source={source}
            onChanged={() => {
              onChanged();
            }}
          />
        </div>
      )}
    </section>
  );
}

export default function AdminDirectoryPage() {
  const [sources, setSources] = useState<DirectorySource[]>([]);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [runs, setRuns] = useState<DirectorySyncRun[] | null>(null);
  const [query, setQuery] = useState("");

  const load = () => {
    api.get<DirectorySource[]>("/admin/directory/sources").then(setSources);
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups);
    api.get<DirectorySyncRun[]>("/admin/directory/sync-runs").then(setRuns);
  };

  useEffect(load, []);

  const visibleGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (groups ?? [])
      .filter((g) => !q || `${g.name} ${g.source}`.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name, "fr", { sensitivity: "base" }));
  }, [groups, query]);

  return (
    <div className="stack">
      <div>
        <h2 className="page-title" style={{ fontSize: 18, marginBottom: 6 }}>
          <FolderCog size={18} aria-hidden="true" /> Annuaire
        </h2>
        <p className="page-subtitle">
          D&apos;où viennent les utilisateurs et les groupes (RH, Compta, SRE…) : <strong>un seul annuaire est actif</strong>,
          le seul qui se synchronise. Ils servent ensuite à cibler les campagnes. L&apos;annuaire n&apos;est jamais modifié, et un utilisateur disparu est désactivé, jamais
          supprimé.
        </p>
      </div>

      <div className="source-grid">
        {[...sources]
          .sort((x, y) => Number(x.source === "local") - Number(y.source === "local"))
          .map((source) => {
            const info = infoFor(source);
            return (
              <SourceCard
                key={info.source}
                info={info}
                source={source}
                lastRun={runs?.find((r) => r.source === info.source)}
                onChanged={load}
              />
            );
          })}
      </div>

      <div className="section-panel">
        <div className="page-title-row" style={{ marginBottom: 12 }}>
          <h2 className="page-title" style={{ margin: 0, fontSize: 18 }}>
            Groupes <span className="count-badge">{groups?.length ?? 0}</span>
          </h2>
          <input
            type="search"
            placeholder="Rechercher un groupe…"
            aria-label="Rechercher un groupe"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="table-wrap">
          <table className="simple-table">
            <thead>
              <tr>
                <th>Nom</th>
                <th>Source</th>
                <th>Membres</th>
              </tr>
            </thead>
            <tbody>
              {visibleGroups.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    {groups ? "Aucun groupe — lancez une synchronisation." : "Chargement…"}
                  </td>
                </tr>
              )}
              {visibleGroups.map((g) => (
                <tr key={g.id}>
                  <td>{g.name}</td>
                  <td>{g.source}</td>
                  <td>{g.member_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section-panel">
        <h2 className="page-title" style={{ margin: "0 0 12px", fontSize: 18 }}>
          Historique de synchronisation
        </h2>
        <div className="table-wrap">
          <table className="simple-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Source</th>
                <th>Statut</th>
                <th>Utilisateurs +/~/−</th>
                <th>Groupes +/~</th>
                <th>Appartenances +/−</th>
              </tr>
            </thead>
            <tbody>
              {runs?.map((r) => (
                <tr key={r.id}>
                  <td>{new Date(r.started_at).toLocaleString("fr-FR")}</td>
                  <td>{r.source}</td>
                  <td>
                    <span className={`badge badge--${r.status === "SUCCESS" ? "signed" : "failed"}`}>{r.status}</span>
                  </td>
                  <td>
                    {r.users_added}/{r.users_updated}/{r.users_deactivated}
                  </td>
                  <td>
                    {r.groups_added}/{r.groups_updated}
                  </td>
                  <td>
                    {r.memberships_added}/{r.memberships_removed}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
