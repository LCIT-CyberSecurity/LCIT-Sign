import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Rocket, Bell, StopCircle, FileBarChart, Download } from "lucide-react";
import { api, ApiError } from "../api/client";
import PolicyFields, {
  EMPTY_POLICY,
  buildPolicyPayload,
  describePolicies,
  policyProblem,
  type PolicyForm,
} from "../components/PolicyFields";
import type {
  Campaign,
  CampaignAssignment,
  DocumentDetail,
  DirectoryGroup,
  ReportSummary,
} from "../api/types";

interface TargetUserOption {
  id: string;
  email: string;
  display_name: string;
}

export default function OperatorCampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [assignments, setAssignments] = useState<CampaignAssignment[] | null>(null);
  const [documents, setDocuments] = useState<DocumentDetail[] | null>(null);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [users, setUsers] = useState<TargetUserOption[] | null>(null);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);

  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [allUsers, setAllUsers] = useState(false);
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [policy, setPolicy] = useState<PolicyForm>(EMPTY_POLICY);

  const load = () => {
    if (!id) return;
    api.get<Campaign>(`/campaigns/${id}`).then(setCampaign);
    api.get<CampaignAssignment[]>(`/campaigns/${id}/assignments`).then(setAssignments);
    api.get<ReportSummary[]>(`/campaigns/${id}/reports`).then(setReports);
  };

  useEffect(() => {
    load();
    api.get<DocumentDetail[]>("/documents").then(setDocuments);
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups).catch(() => setGroups([]));
    api.get<TargetUserOption[]>("/campaigns/_meta/users").then(setUsers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!campaign) return <p className="muted">Chargement…</p>;

  const publishedVersions = (documents ?? []).flatMap((doc) =>
    doc.versions
      .filter((v) => v.status === "PUBLISHED")
      .map((v) => ({ id: v.id, label: `${doc.title} — v${v.version_label}` })),
  );

  const addDocument = async () => {
    if (!selectedVersionId) return;
    await api.post(`/campaigns/${id}/documents`, { document_version_id: selectedVersionId });
    setSelectedVersionId("");
    load();
  };

  const toggle = (list: string[], value: string, setList: (v: string[]) => void) => {
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  };

  const launch = async () => {
    const problem = policyProblem(policy);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post(`/campaigns/${id}/launch`, {
        ...buildPolicyPayload(policy),
        all_users: allUsers,
        group_ids: allUsers ? [] : selectedGroupIds,
        user_ids: allUsers ? [] : selectedUserIds,
      });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Le lancement a échoué.");
    } finally {
      setBusy(false);
    }
  };

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
        <ArrowLeft size={14} aria-hidden="true" /> Retour aux campagnes
      </Link>

      <div className="page-title-row">
        <h1 className="page-title">{campaign.name}</h1>
        <span className={`badge badge--${campaign.status.toLowerCase()}`}>{campaign.status}</span>
      </div>

      {campaign.status !== "DRAFT" && describePolicies(campaign.policies).length > 0 && (
        <div className="card">
          <div className="card-title">Politiques</div>
          <ul className="plain-list">
            {describePolicies(campaign.policies).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {campaign.status === "DRAFT" && (
        <>
          <div className="card">
            <div className="card-title">Documents</div>
            <ul className="plain-list">
              {campaign.document_version_ids.map((vid) => (
                <li key={vid}>{vid}</li>
              ))}
            </ul>
            <div className="form-row">
              <select value={selectedVersionId} onChange={(e) => setSelectedVersionId(e.target.value)}>
                <option value="">Sélectionner un document publié…</option>
                {publishedVersions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
              <button className="button button--secondary" onClick={addDocument}>
                Ajouter
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Ciblage</div>
            <label className="consent-row">
              <input type="checkbox" checked={allUsers} onChange={(e) => setAllUsers(e.target.checked)} />
              <span>Tous les utilisateurs</span>
            </label>

            {!allUsers && (
              <>
                <div className="field-label">Groupes</div>
                <div className="chip-list">
                  {groups?.map((g) => (
                    <button
                      key={g.id}
                      type="button"
                      className={`chip${selectedGroupIds.includes(g.id) ? " chip--active" : ""}`}
                      onClick={() => toggle(selectedGroupIds, g.id, setSelectedGroupIds)}
                    >
                      {g.name} ({g.member_count})
                    </button>
                  ))}
                </div>

                <div className="field-label">Utilisateurs supplémentaires</div>
                <div className="chip-list">
                  {users?.map((u) => (
                    <button
                      key={u.id}
                      type="button"
                      className={`chip${selectedUserIds.includes(u.id) ? " chip--active" : ""}`}
                      onClick={() => toggle(selectedUserIds, u.id, setSelectedUserIds)}
                    >
                      {u.display_name}
                    </button>
                  ))}
                </div>
              </>
            )}

            <PolicyFields value={policy} onChange={setPolicy} />

            {error && <p className="error-text">{error}</p>}
            <button className="button button--primary" onClick={launch} disabled={busy}>
              <Rocket size={14} aria-hidden="true" /> Lancer la campagne
            </button>
          </div>
        </>
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

      {campaign.status !== "DRAFT" && (
        <div className="card">
          <div className="card-title">Suivi</div>
          <table className="simple-table">
            <thead>
              <tr>
                <th>Destinataire</th>
                <th>Statut</th>
                <th>Consulté</th>
                <th>Signé</th>
              </tr>
            </thead>
            <tbody>
              {assignments?.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.user_display_name}
                    <div className="muted small">{a.user_email}</div>
                  </td>
                  <td>
                    <span className={`badge badge--${a.status.toLowerCase()}`}>{a.status}</span>
                  </td>
                  <td>{a.first_viewed_at ? new Date(a.first_viewed_at).toLocaleDateString("fr-FR") : "—"}</td>
                  <td>{a.signed_at ? new Date(a.signed_at).toLocaleDateString("fr-FR") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {campaign.status !== "DRAFT" && (
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
