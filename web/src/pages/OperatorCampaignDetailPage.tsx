import { useEffect, useState } from "react";
import { Navigate, useParams, Link } from "react-router-dom";
import { ArrowLeft, Bell, StopCircle, FileBarChart, Download } from "lucide-react";
import { api } from "../api/client";
import { describePolicies } from "../components/PolicyFields";
import type { Campaign, CampaignAssignment, DirectoryGroup, ReportSummary } from "../api/types";

/** Follow-up of a launched campaign (the reporting): who signed, who still has to,
 *  who is waiting for an earlier signer, reminders, closing, reports. Preparing and
 *  sending is done in Signer. */
export default function OperatorCampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [assignments, setAssignments] = useState<CampaignAssignment[] | null>(null);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [filters, setFilters] = useState({
    status: "",
    document_version_id: "",
    group_id: "",
    viewed: "",
    overdue: false,
  });

  const loadAssignments = (f = filters) => {
    if (!id) return;
    const query = new URLSearchParams();
    if (f.status) query.set("status", f.status);
    if (f.document_version_id) query.set("document_version_id", f.document_version_id);
    if (f.group_id) query.set("group_id", f.group_id);
    if (f.viewed) query.set("viewed", f.viewed);
    if (f.overdue) query.set("overdue", "true");
    const suffix = query.toString() ? `?${query.toString()}` : "";
    api.get<CampaignAssignment[]>(`/campaigns/${id}/assignments${suffix}`).then(setAssignments);
  };

  const changeFilters = (patch: Partial<typeof filters>) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    loadAssignments(next);
  };

  const load = () => {
    if (!id) return;
    api.get<Campaign>(`/campaigns/${id}`).then(setCampaign);
    loadAssignments();
    api.get<ReportSummary[]>(`/campaigns/${id}/reports`).then(setReports);
  };

  useEffect(() => {
    load();
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups).catch(() => setGroups([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!campaign) return <p className="muted">Chargement…</p>;
  // Not launched yet: it is still being prepared, in Signer.
  if (campaign.status === "DRAFT") return <Navigate to={`/sign/${campaign.id}`} replace />;

  const publishedAndUsed = campaign.documents.map((d) => ({
    id: d.version_id,
    label: `${d.title} — v${d.version_label}`,
  }));

  const remind = async () => {
    await api.post(`/campaigns/${id}/remind`);
    load();
  };

  const close = async () => {
    await api.post(`/campaigns/${id}/close`);
    load();
  };

  const generateReport = async () => {
    await api.post(`/campaigns/${id}/reports`);
    load();
  };

  return (
    <div className="stack">
      <Link to="/campaigns" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> Suivi
      </Link>

      <div className="page-title-row">
        <h1 className="page-title">{campaign.name}</h1>
        <span className={`badge badge--${campaign.status.toLowerCase()}`}>{campaign.status}</span>
      </div>

      {describePolicies(campaign.policies).length > 0 && (
        <div className="card">
          <div className="card-title">Politiques</div>
          <ul className="plain-list">
            {describePolicies(campaign.policies).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {campaign.status === "ACTIVE" && (
        <div className="button-row">
          <button className="button button--secondary" onClick={remind}>
            <Bell size={14} aria-hidden="true" /> Relancer les retardataires
          </button>
          <button className="button button--secondary" onClick={close}>
            <StopCircle size={14} aria-hidden="true" /> Clôturer
          </button>
        </div>
      )}

      {(
        <div className="card">
          <div className="card-title">Suivi</div>
          <div className="filter-bar">
            <label>
              Statut
              <select value={filters.status} onChange={(e) => changeFilters({ status: e.target.value })}>
                <option value="">Tous</option>
                <option value="WAITING">Pas encore leur tour</option>
                <option value="PENDING">À signer</option>
                <option value="VIEWED">Consulté</option>
                <option value="SIGNED">Signé</option>
                <option value="EXPIRED">Expiré</option>
              </select>
            </label>
            <label>
              Document
              <select
                value={filters.document_version_id}
                onChange={(e) => changeFilters({ document_version_id: e.target.value })}
              >
                <option value="">Tous</option>
                {publishedAndUsed.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Groupe
              <select value={filters.group_id} onChange={(e) => changeFilters({ group_id: e.target.value })}>
                <option value="">Tous</option>
                {groups?.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Consultation
              <select value={filters.viewed} onChange={(e) => changeFilters({ viewed: e.target.value })}>
                <option value="">Tous</option>
                <option value="true">Consulté</option>
                <option value="false">Non consulté</option>
              </select>
            </label>
            <label className="consent-row">
              <input
                type="checkbox"
                checked={filters.overdue}
                onChange={(e) => changeFilters({ overdue: e.target.checked })}
              />
              En retard
            </label>
          </div>
          <table className="simple-table">
            <thead>
              <tr>
                <th>Destinataire</th>
                <th>Groupe</th>
                <th>Document</th>
                <th>Statut</th>
                <th>Consulté</th>
                <th>Signé</th>
                <th>Relances</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {assignments?.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.user_display_name}
                    <div className="muted small">{a.user_email}</div>
                  </td>
                  <td>{a.groups.join(", ") || "—"}</td>
                  <td>
                    {a.document_title}
                    {a.role_label && (campaign.roles_required ?? 1) > 1 && (
                      <div className="muted small">{a.role_label}</div>
                    )}
                  </td>
                  <td>
                    <span className={`badge badge--${a.status.toLowerCase()}`}>{a.status}</span>
                    {a.status === "WAITING" && a.waiting_on && a.waiting_on.length > 0 && (
                      <div className="muted small">après {a.waiting_on.join(", ")}</div>
                    )}
                  </td>
                  <td>{a.first_viewed_at ? new Date(a.first_viewed_at).toLocaleDateString("fr-FR") : "—"}</td>
                  <td>{a.signed_at ? new Date(a.signed_at).toLocaleDateString("fr-FR") : "—"}</td>
                  <td>{a.reminder_count}</td>
                  <td>
                    {a.signature_id && (
                      <Link className="button button--ghost button--sm" to={`/signatures/${a.signature_id}`}>
                        Voir la signature
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(
        <div className="card">
          <div className="card-title">
            <FileBarChart size={16} aria-hidden="true" /> Procès-verbaux
          </div>
          <button className="button button--secondary" onClick={generateReport}>
            Générer un PV
          </button>
          <ul className="plain-list">
            {reports?.map((r) => (
              <li key={r.id} className="report-row">
                {r.display_id} — {new Date(r.generated_at).toLocaleString("fr-FR")}
                <a className="button button--ghost button--sm" href={`/api/reports/${r.id}/pdf`}>
                  <Download size={12} aria-hidden="true" /> PDF
                </a>
                <a className="button button--ghost button--sm" href={`/api/reports/${r.id}/csv`}>
                  <Download size={12} aria-hidden="true" /> CSV
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
