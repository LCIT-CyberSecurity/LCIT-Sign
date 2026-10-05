import { useEffect, useState } from "react";
import { FolderCog, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { DirectoryGroup, DirectorySyncRun } from "../api/types";

export default function AdminDirectoryPage() {
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [runs, setRuns] = useState<DirectorySyncRun[] | null>(null);
  const [syncing, setSyncing] = useState(false);

  const load = () => {
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups);
    api.get<DirectorySyncRun[]>("/admin/directory/sync-runs").then(setRuns);
  };

  useEffect(load, []);

  const sync = async () => {
    setSyncing(true);
    try {
      await api.post("/admin/directory/sync");
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
        <button className="button button--primary" onClick={sync} disabled={syncing}>
          <RefreshCw size={14} aria-hidden="true" /> {syncing ? "Synchronisation…" : "Synchroniser maintenant"}
        </button>
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
