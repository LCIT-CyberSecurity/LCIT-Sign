import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Rocket, Bell, StopCircle, FileBarChart, Download } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
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
  const [groupQuery, setGroupQuery] = useState("");
  const [recipientCount, setRecipientCount] = useState<number | null>(null);
  const [policy, setPolicy] = useState<PolicyForm>(EMPTY_POLICY);
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
    api.get<DocumentDetail[]>("/documents").then(setDocuments);
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups).catch(() => setGroups([]));
    api.get<TargetUserOption[]>("/campaigns/_meta/users").then(setUsers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Live count of who the current selection would reach (groups and people are
  // de-duplicated server-side, nested groups already expanded by the sync).
  useEffect(() => {
    if (!id || campaign?.status !== "DRAFT") return;
    api
      .post<{ population_count: number }>(`/campaigns/${id}/targets/preview`, {
        all_users: allUsers,
        group_ids: allUsers ? [] : selectedGroupIds,
        user_ids: allUsers ? [] : selectedUserIds,
      })
      .then((r) => setRecipientCount(r.population_count))
      .catch(() => setRecipientCount(null));
  }, [id, campaign?.status, allUsers, selectedGroupIds, selectedUserIds]);

  const visibleGroups = useMemo(() => {
    const q = groupQuery.trim().toLowerCase();
    return (groups ?? [])
      .filter((g) => g.active && (!q || g.name.toLowerCase().includes(q)))
      .sort((a, b) => b.member_count - a.member_count || a.name.localeCompare(b.name));
  }, [groups, groupQuery]);

  if (!campaign) return <p className="muted">Chargement…</p>;

  const versionLabels = new Map(
    (documents ?? []).flatMap((doc) =>
      doc.versions.map((v) => [v.id, `${doc.title} — v${v.version_label}`] as const),
    ),
  );

  // Alphabetical, so a long list stays findable. Versions already in the campaign
  // are not offered twice; drafts are listed apart, with the reason they cannot be
  // added yet, instead of silently missing.
  const byLabel = (a: { label: string }, b: { label: string }) =>
    a.label.localeCompare(b.label, "fr", { sensitivity: "base", numeric: true });
  const versionsWith = (status: string) =>
    (documents ?? [])
      .flatMap((doc) =>
        doc.versions
          .filter((v) => v.status === status && !campaign.document_version_ids.includes(v.id))
          .map((v) => ({ id: v.id, label: `${doc.title} — v${v.version_label}` })),
      )
      .sort(byLabel);
  const publishedVersions = versionsWith("PUBLISHED");
  const draftVersions = versionsWith("DRAFT");

  const publishedAndUsed = (documents ?? []).flatMap((doc) =>
    doc.versions
      .filter((v) => campaign.document_version_ids.includes(v.id))
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
              {campaign.document_version_ids.length === 0 && (
                <li className="muted">Aucun document pour le moment.</li>
              )}
              {campaign.document_version_ids.map((vid) => (
                <li key={vid} className="report-row">
                  {versionLabels.get(vid) ?? vid}
                  <ConfirmButton
                    confirmLabel="Retirer de la campagne"
                    onConfirm={async () => {
                      await api.del(`/campaigns/${id}/documents/${vid}`);
                      load();
                    }}
                  >
                    Retirer
                  </ConfirmButton>
                </li>
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
                {draftVersions.length > 0 && (
                  <optgroup label="Brouillons — à publier avant de pouvoir être ajoutés">
                    {draftVersions.map((v) => (
                      <option key={v.id} value={v.id} disabled>
                        {v.label}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              <button className="button button--secondary" onClick={addDocument} disabled={!selectedVersionId}>
                Ajouter
              </button>
            </div>
            {draftVersions.length > 0 && (
              <p className="muted small" data-testid="draft-hint">
                {draftVersions.length} document(s) en brouillon ne sont pas proposés : publiez-les depuis la page{" "}
                <Link to="/documents">Documents</Link> pour pouvoir les ajouter.
              </p>
            )}
          </div>

          <div className="card">
            <div className="card-title">Ciblage</div>
            <label className="consent-row">
              <input type="checkbox" checked={allUsers} onChange={(e) => setAllUsers(e.target.checked)} />
              <span>Tous les utilisateurs</span>
            </label>

            {!allUsers && (
              <>
                <div className="field-label">
                  Groupes de l&apos;annuaire
                  {selectedGroupIds.length > 0 && (
                    <span className="muted small"> — {selectedGroupIds.length} sélectionné(s)</span>
                  )}
                </div>
                <input
                  type="search"
                  placeholder="Rechercher un groupe (ex : SRE)…"
                  aria-label="Rechercher un groupe"
                  value={groupQuery}
                  onChange={(e) => setGroupQuery(e.target.value)}
                />
                {visibleGroups.length === 0 && <p className="muted small">Aucun groupe ne correspond.</p>}
                <div className="chip-list">
                  {visibleGroups.map((g) => (
                    <button
                      key={g.id}
                      type="button"
                      className={`chip${selectedGroupIds.includes(g.id) ? " chip--active" : ""}`}
                      onClick={() => toggle(selectedGroupIds, g.id, setSelectedGroupIds)}
                    >
                      {g.name} · {g.member_count}
                      <span className="muted small"> {g.source}</span>
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

            <p className="muted" data-testid="recipient-count">
              {recipientCount === null
                ? ""
                : `${recipientCount} destinataire(s) seront sollicités (doublons éliminés).`}
            </p>

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
          <div className="filter-bar">
            <label>
              Statut
              <select value={filters.status} onChange={(e) => changeFilters({ status: e.target.value })}>
                <option value="">Tous</option>
                <option value="PENDING">En attente</option>
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
                  <td>{a.document_title}</td>
                  <td>
                    <span className={`badge badge--${a.status.toLowerCase()}`}>{a.status}</span>
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
