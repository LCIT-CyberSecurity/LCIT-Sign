import { useEffect, useState } from "react";
import { Navigate, useParams, Link } from "react-router-dom";
import { ArrowLeft, Bell, StopCircle, FileBarChart, Download } from "lucide-react";
import { api, ApiError } from "../api/client";
import CampaignDocuments from "../components/CampaignDocuments";
import ConfirmButton from "../components/ConfirmButton";
import SignedDocuments from "../components/SignedDocuments";
import { describePolicies } from "../components/Schedule";
import RecipientPicker, { NO_RECIPIENTS, type Recipients } from "../components/RecipientPicker";
import type {
  Campaign,
  CampaignAssignment,
  DirectoryGroup,
  DocumentDetail,
  ReportSummary,
} from "../api/types";

/** Follow-up of a launched campaign (the reporting): who signed, who still has to,
 *  who is waiting for an earlier signer, reminders, closing, reports. Preparing and
 *  sending is done in Signer. */
export default function OperatorCampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [assignments, setAssignments] = useState<CampaignAssignment[] | null>(null);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [library, setLibrary] = useState<DocumentDetail[] | null>(null);
  const [users, setUsers] = useState<{ id: string; email: string; display_name: string }[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [adding, setAdding] = useState<Recipients>(NO_RECIPIENTS);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
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
    api.get<DocumentDetail[]>("/documents").then(setLibrary);
    api.get<{ id: string; email: string; display_name: string }[]>("/campaigns/_meta/users").then(setUsers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!campaign) return <p className="muted">Chargement…</p>;
  // Not launched yet: it is still being prepared, in Signer.
  if (campaign.status === "DRAFT") return <Navigate to={`/sign/${campaign.id}`} replace />;

  const publishedAndUsed = campaign.documents.map((d) => ({
    id: d.version_id,
    label: `${d.title} — v${d.version_label}`,
  }));

  const run = async (action: () => Promise<string>) => {
    setNotice(null);
    setProblem(null);
    try {
      setNotice(await action());
      load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "L'opération a échoué.");
    }
  };

  const plural = (n: number, one: string, many: string) => `${n} ${n > 1 ? many : one}`;

  // Everyone still outstanding, or only some people / rows.
  const remind = (body?: { assignment_ids?: string[]; user_ids?: string[] }) =>
    run(async () => {
      const done = await api.post<{ reminders_queued: number }>(`/campaigns/${id}/remind`, body);
      setSelected([]);
      return done.reminders_queued === 0
        ? "Personne à relancer : ceux qui ont signé, ou dont ce n'est pas encore le tour, ne sont pas relancés."
        : `${plural(done.reminders_queued, "relance envoyée", "relances envoyées")}.`;
    });

  const addPeople = () =>
    run(async () => {
      const done = await api.post<{ added: number }>(`/campaigns/${id}/recipients`, {
        all_users: adding.allUsers,
        group_ids: adding.allUsers ? [] : adding.groupIds,
        user_ids: adding.allUsers ? [] : adding.userIds,
      });
      setAdding(NO_RECIPIENTS);
      return done.added === 0
        ? "Ces personnes étaient déjà dans la campagne."
        : `${plural(done.added, "personne ajoutée", "personnes ajoutées")} : elles reçoivent leur exemplaire.`;
    });

  const removePerson = (userId: string, name: string) =>
    run(async () => {
      const done = await api.del<{ cancelled: number }>(`/campaigns/${id}/recipients/${userId}`);
      return `${name} n'est plus sollicité(e) (${plural(done.cancelled, "exemplaire annulé", "exemplaires annulés")} ; ce qui était signé est conservé).`;
    });

  const cancelCampaign = () =>
    run(async () => {
      await api.post(`/campaigns/${id}/cancel`);
      return "Campagne annulée : plus personne ne peut signer. Ce qui était signé est conservé.";
    });
  const archiveCampaign = () =>
    run(async () => {
      await api.post(`/campaigns/${id}/archive`);
      return "Campagne archivée.";
    });
  const deleteCampaign = async () => {
    setProblem(null);
    try {
      await api.del(`/campaigns/${id}`);
      window.location.assign("/campaigns");
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "La suppression a échoué.");
    }
  };

  const asked = campaign.roles.find((r) => r.mode === "EACH");
  const isOutstanding = (status: string) => status === "PENDING" || status === "VIEWED";

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

      {notice && <p className="status-ok" role="status">{notice}</p>}
      {problem && <p className="error-text" role="alert">{problem}</p>}

      {campaign.status === "SCHEDULED" && (
        <div className="card" data-testid="scheduled-card">
          <div className="card-title">Programmée</div>
          <p>
            Cette campagne démarre le{" "}
            <strong>{campaign.scheduled_start ? new Date(campaign.scheduled_start).toLocaleString("fr-FR") : ""}</strong>.
            Personne n&apos;est prévenu avant. Pour la changer, annulez-la et recréez-en une.
          </p>
          <ConfirmButton confirmLabel="Oui, annuler la programmation" onConfirm={cancelCampaign}>
            Annuler la programmation
          </ConfirmButton>
        </div>
      )}

      {campaign.status === "ACTIVE" && (
        <div className="card" data-testid="edit-card">
          <div className="card-title">Modifier la campagne en cours</div>
          <p className="muted small">
            Vous pouvez ajouter des personnes ou des documents, et ne plus solliciter quelqu&apos;un. Ce qui a
            déjà été signé est conservé.
          </p>
          {asked && (
            <>
              <div className="field-label">Ajouter des personnes</div>
              <RecipientPicker value={adding} onChange={setAdding} groups={groups} users={users} />
              <div className="row-actions">
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => void addPeople()}
                  disabled={!adding.allUsers && adding.groupIds.length === 0 && adding.userIds.length === 0}
                >
                  Ajouter à la campagne
                </button>
              </div>
            </>
          )}
          <div className="field-label">Documents</div>
          <CampaignDocuments campaign={campaign} library={library} onChanged={load} active />
        </div>
      )}

      {campaign.status === "ACTIVE" && (
        <div className="button-row">
          <button className="button button--secondary" onClick={() => void remind()}>
            <Bell size={14} aria-hidden="true" /> Relancer les retardataires
          </button>
          {selected.length > 0 && (
            <button
              className="button button--secondary"
              onClick={() => void remind({ assignment_ids: selected })}
            >
              <Bell size={14} aria-hidden="true" /> Relancer la sélection ({selected.length})
            </button>
          )}
          <button className="button button--secondary" onClick={close}>
            <StopCircle size={14} aria-hidden="true" /> Clôturer
          </button>
          <ConfirmButton
            className="button button--secondary"
            confirmLabel="Oui, annuler la campagne"
            onConfirm={cancelCampaign}
          >
            Annuler la campagne
          </ConfirmButton>
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
                {campaign.status === "ACTIVE" && <th aria-label="Sélection" />}
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
                  {campaign.status === "ACTIVE" && (
                    <td>
                      {isOutstanding(a.status) && (
                        <input
                          type="checkbox"
                          aria-label={`Sélectionner ${a.user_display_name}`}
                          checked={selected.includes(a.id)}
                          onChange={() =>
                            setSelected(
                              selected.includes(a.id) ? selected.filter((x) => x !== a.id) : [...selected, a.id],
                            )
                          }
                        />
                      )}
                    </td>
                  )}
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
                    <div className="row-actions">
                      {a.signature_id && (
                        <Link className="button button--ghost button--sm" to={`/signatures/${a.signature_id}`}>
                          Voir la signature
                        </Link>
                      )}
                      {campaign.status === "ACTIVE" && isOutstanding(a.status) && (
                        <button
                          type="button"
                          className="button button--ghost button--sm"
                          onClick={() => void remind({ assignment_ids: [a.id] })}
                        >
                          <Bell size={12} aria-hidden="true" /> Relancer
                        </button>
                      )}
                      {campaign.status === "ACTIVE" &&
                        asked &&
                        a.role === asked.role &&
                        a.status !== "SIGNED" &&
                        a.status !== "CANCELLED" &&
                        a.status !== "EXPIRED" && (
                          <ConfirmButton
                            confirmLabel="Ne plus solliciter"
                            onConfirm={() => removePerson(a.user_id, a.user_display_name)}
                          >
                            Retirer
                          </ConfirmButton>
                        )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(campaign.status === "CLOSED" || campaign.status === "CANCELLED") && (
        <div className="button-row">
          <button className="button button--secondary" onClick={() => void archiveCampaign()}>
            Archiver
          </button>
        </div>
      )}
      {campaign.status !== "ACTIVE" && campaign.status !== "SCHEDULED" && (
        <div className="button-row" data-testid="delete-row">
          {campaign.delete_blockers.length === 0 ? (
            <ConfirmButton confirmLabel="Oui, supprimer la campagne" onConfirm={deleteCampaign}>
              Supprimer la campagne
            </ConfirmButton>
          ) : (
            <p className="blocker-note" title="Une campagne signée fait partie de la preuve">
              Conservée — {campaign.delete_blockers.join(" ; ")}
            </p>
          )}
        </div>
      )}

      <section data-testid="campaign-signed">
        <h2 className="card-title">Documents signés</h2>
        <SignedDocuments campaignIds={[campaign.id]} refreshKey={assignments?.length ?? 0} />
      </section>

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
