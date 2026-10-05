import { useEffect, useState } from "react";
import { FolderCog, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { DirectoryGroup, DirectorySource, DirectorySyncRun } from "../api/types";

export default function AdminDirectoryPage() {
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [runs, setRuns] = useState<DirectorySyncRun[] | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [sources, setSources] = useState<DirectorySource[]>([{ source: "local", configured: true }]);
  const [source, setSource] = useState("local");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups);
    api.get<DirectorySyncRun[]>("/admin/directory/sync-runs").then(setRuns);
    api.get<DirectorySource[]>("/admin/directory/sources").then(setSources);
  };

  useEffect(load, []);

  const sync = async () => {
    setSyncing(true);
    setError(null);
    try {
      const run = await api.post<DirectorySyncRun>(
        `/admin/directory/sync?source=${encodeURIComponent(source)}`,
      );
      if (run.status === "FAILED") setError(run.error ?? "Échec de la synchronisation");
      load();
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <FolderCog size={20} aria-hidden="true" /> Annuaire
      </h1>

      <div className="card">
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source">
          {sources.map((s) => (
            <option key={s.source} value={s.source} disabled={!s.configured}>
              {s.source}
              {s.configured ? "" : " (non configuré)"}
            </option>
          ))}
        </select>{" "}
        <button className="button button--primary" onClick={sync} disabled={syncing}>
          <RefreshCw size={14} aria-hidden="true" /> {syncing ? "Synchronisation…" : "Synchroniser maintenant"}
        </button>
        {error && <p role="alert">{error}</p>}
      </div>

      <div className="card">
        <div className="card-title">Groupes</div>
        <table className="simple-table">
          <thead>
            <tr>
              <th>Nom</th>
              <th>Source</th>
              <th>Membres</th>
            </tr>
          </thead>
          <tbody>
            {groups?.map((g) => (
              <tr key={g.id}>
                <td>{g.name}</td>
                <td>{g.source}</td>
                <td>{g.member_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-title">Historique de synchronisation</div>
        <table className="simple-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Source</th>
              <th>Statut</th>
              <th>Utilisateurs +/~/-</th>
              <th>Groupes +/~</th>
              <th>Memberships +/-</th>
            </tr>
          </thead>
          <tbody>
            {runs?.map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.started_at).toLocaleString("fr-FR")}</td>
                <td>{r.source}</td>
                <td>{r.status}</td>
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
  );
}
