import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Megaphone, PenLine } from "lucide-react";
import { api } from "../api/client";
import DashboardCards from "../components/DashboardCards";
import type { Campaign, OperatorDashboard } from "../api/types";

const TARGETS: Record<string, string> = {
  SPECIFIC_USERS: "Utilisateurs",
  GROUPS: "Groupes",
  GROUPS_AND_USERS: "Groupes + utilisateurs",
  ALL_USERS: "Tous les utilisateurs",
};

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Brouillon",
  SCHEDULED: "Programmée",
  ACTIVE: "Active",
  CLOSED: "Clôturée",
  CANCELLED: "Annulée",
  ARCHIVED: "Archivée",
};

function totals(c: Campaign): { signed: number; total: number } {
  const counts = c.assignment_counts;
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  return { signed: counts.SIGNED, total };
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString("fr-FR") : "—";
}

export default function OperatorCampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [dashboard, setDashboard] = useState<OperatorDashboard | null>(null);

  const load = () => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns);
    api.get<OperatorDashboard>("/campaigns/_meta/dashboard").then(setDashboard);
  };

  useEffect(load, []);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <Megaphone size={22} aria-hidden="true" /> Suivi
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            Le suivi et le reporting de ce qui a été envoyé à la signature : qui a signé, qui reste à faire.
          </p>
        </div>
        <Link className="button button--primary" to="/sign">
          <PenLine size={14} aria-hidden="true" /> Nouvelle demande de signature
        </Link>
      </div>

      {dashboard && <DashboardCards data={dashboard} />}

      <div className="table-wrap">
        <table className="simple-table campaigns-table">
          <thead>
            <tr>
              <th>Campagne</th>
              <th>Statut</th>
              <th>Cible</th>
              <th>Avancement</th>
              <th>Lancée le</th>
              <th>Échéance</th>
            </tr>
          </thead>
          <tbody>
            {campaigns?.filter((c) => c.status !== "DRAFT").length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Rien n&apos;a encore été envoyé à la signature.
                </td>
              </tr>
            )}
            {campaigns?.filter((c) => c.status !== "DRAFT").map((c) => {
              const { signed, total } = totals(c);
              const pct = total ? Math.round((100 * signed) / total) : 0;
              return (
                <tr key={c.id}>
                  <td>
                    <Link className="row-link" to={`/campaigns/${c.id}`}>
                      {c.name}
                    </Link>
                    <div className="muted small">{c.document_version_ids.length} document(s)</div>
                  </td>
                  <td>
                    <span className={`badge badge--${c.status.toLowerCase()}`}>{STATUS_LABELS[c.status]}</span>
                  </td>
                  <td>{c.status === "DRAFT" ? "—" : (TARGETS[c.target_mode] ?? c.target_mode)}</td>
                  <td>
                    {total > 0 ? (
                      <div className="table-progress" title={`${signed} signé(s) sur ${total}`}>
                        <div>
                          <span style={{ width: `${pct}%` }} />
                        </div>
                        {signed}/{total}
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{c.status === "SCHEDULED" ? `dès le ${formatDate(c.scheduled_start)}` : formatDate(c.launch_at)}</td>
                  <td>{formatDate(c.deadline)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
