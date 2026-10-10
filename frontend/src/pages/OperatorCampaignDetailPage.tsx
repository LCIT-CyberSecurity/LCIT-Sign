import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Navigate, useParams, Link } from "react-router-dom";
import { ArrowLeft, Bell, StopCircle, FileBarChart, Download } from "lucide-react";
import { api } from "../api/client";
import { blockerText, errorText, roleLabelText } from "../i18n/errors";
import { assignmentStatus, campaignStatus } from "../i18n/enums";
import { formatDate, formatDateTime } from "../i18n/format";
import CampaignDocuments from "../components/CampaignDocuments";
import CampaignOwnership from "../components/CampaignOwnership";
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
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [assignments, setAssignments] = useState<CampaignAssignment[] | null>(null);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [library, setLibrary] = useState<DocumentDetail[] | null>(null);
  const [users, setUsers] = useState<
    { id: string; email: string; display_name: string; external?: boolean }[] | null
  >(null);
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
    // The reports are confidential content: refused to an operator who is not on the campaign.
    api.get<ReportSummary[]>(`/campaigns/${id}/reports`).then(setReports).catch(() => setReports([]));
  };

  useEffect(() => {
    load();
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups).catch(() => setGroups([]));
    api.get<DocumentDetail[]>("/documents").then(setLibrary);
    api.get<{ id: string; email: string; display_name: string; external?: boolean }[]>(
      "/campaigns/_meta/users",
    ).then(setUsers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!campaign) return <p className="muted">{t("common.loading")}</p>;
  // Not launched yet: it is still being prepared, in Signer.
  if (campaign.status === "DRAFT") return <Navigate to={`/sign/${campaign.id}`} replace />;

  // Without the access, the documents, signed PDFs, proofs and reports stay out of sight.
  const canContent = campaign.access?.content ?? true;
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
      setProblem(errorText(err, "campaignDetail.opFailed"));
    }
  };

  // Everyone still outstanding, or only some people / rows.
  const remind = (body?: { assignment_ids?: string[]; user_ids?: string[] }) =>
    run(async () => {
      const done = await api.post<{ reminders_queued: number }>(`/campaigns/${id}/remind`, body);
      setSelected([]);
      return done.reminders_queued === 0
        ? t("campaignDetail.nobodyToRemind")
        : t("campaignDetail.reminded", { count: done.reminders_queued });
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
        ? t("campaignDetail.alreadyIn")
        : t("campaignDetail.added", { count: done.added });
    });

  const removePerson = (userId: string, name: string) =>
    run(async () => {
      const done = await api.del<{ cancelled: number }>(`/campaigns/${id}/recipients/${userId}`);
      return t("campaignDetail.removed", {
        name,
        cancelled: t("campaignDetail.cancelledCopies", { count: done.cancelled }),
      });
    });

  const cancelCampaign = () =>
    run(async () => {
      await api.post(`/campaigns/${id}/cancel`);
      return t("campaignDetail.cancelled");
    });
  const archiveCampaign = () =>
    run(async () => {
      await api.post(`/campaigns/${id}/archive`);
      return t("campaignDetail.archived");
    });
  const deleteCampaign = async () => {
    setProblem(null);
    try {
      await api.del(`/campaigns/${id}`);
      window.location.assign("/campaigns");
    } catch (err) {
      setProblem(errorText(err, "campaignDetail.deleteFailed"));
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
        <ArrowLeft size={14} aria-hidden="true" /> {t("nav.tracking")}
      </Link>

      <div className="page-title-row">
        <h1 className="page-title">{campaign.name}</h1>
        <span className={`badge badge--${campaign.status.toLowerCase()}`}>{campaignStatus(campaign.status)}</span>
      </div>

      <CampaignOwnership campaign={campaign} onChanged={setCampaign} />

      {describePolicies(campaign.policies).length > 0 && (
        <div className="card">
          <div className="card-title">{t("campaignDetail.policies")}</div>
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
          <div className="card-title">{t("campaignDetail.scheduledTitle")}</div>
          <p>
            <Trans
              i18nKey="campaignDetail.scheduledText"
              values={{ date: campaign.scheduled_start ? formatDateTime(campaign.scheduled_start) : "" }}
              components={{ strong: <strong /> }}
            />
          </p>
          <ConfirmButton confirmLabel={t("campaignDetail.confirmCancelSchedule")} onConfirm={cancelCampaign}>
            {t("campaignDetail.cancelSchedule")}
          </ConfirmButton>
        </div>
      )}

      {campaign.status === "ACTIVE" && (
        <div className="card" data-testid="edit-card">
          <div className="card-title">{t("campaignDetail.editTitle")}</div>
          <p className="muted small">
            {t("campaignDetail.editHelp")}
          </p>
          {asked && (
            <>
              <div className="field-label">{t("campaignDetail.addPeople")}</div>
              <RecipientPicker
                value={adding}
                onChange={setAdding}
                groups={groups}
                users={users}
                onAddExternal={(person) => setUsers((all) => [...(all ?? []), person])}
              />
              <div className="row-actions">
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => void addPeople()}
                  disabled={!adding.allUsers && adding.groupIds.length === 0 && adding.userIds.length === 0}
                >
                  {t("campaignDetail.addToCampaign")}
                </button>
              </div>
            </>
          )}
          {canContent && (
            <>
              <div className="field-label">{t("campaignDetail.documents")}</div>
              <CampaignDocuments campaign={campaign} library={library} onChanged={load} active />
            </>
          )}
        </div>
      )}

      {campaign.status === "ACTIVE" && (
        <div className="button-row">
          <button className="button button--secondary" onClick={() => void remind()}>
            <Bell size={14} aria-hidden="true" /> {t("campaignDetail.remindLate")}
          </button>
          {selected.length > 0 && (
            <button
              className="button button--secondary"
              onClick={() => void remind({ assignment_ids: selected })}
            >
              <Bell size={14} aria-hidden="true" /> {t("campaignDetail.remindSelection", { count: selected.length })}
            </button>
          )}
          <button className="button button--secondary" onClick={close}>
            <StopCircle size={14} aria-hidden="true" /> {t("campaignDetail.close")}
          </button>
          <ConfirmButton
            className="button button--secondary"
            confirmLabel={t("campaignDetail.confirmCancelCampaign")}
            onConfirm={cancelCampaign}
          >
            {t("campaignDetail.cancelCampaign")}
          </ConfirmButton>
        </div>
      )}

      {(
        <div className="card">
          <div className="card-title">{t("campaignDetail.tracking")}</div>
          <div className="filter-bar">
            <label>
              {t("campaignDetail.filters.status")}
              <select value={filters.status} onChange={(e) => changeFilters({ status: e.target.value })}>
                <option value="">{t("campaignDetail.filters.all")}</option>
                <option value="WAITING">{t("campaignDetail.filters.waiting")}</option>
                <option value="PENDING">{assignmentStatus("PENDING")}</option>
                <option value="VIEWED">{assignmentStatus("VIEWED")}</option>
                <option value="SIGNED">{assignmentStatus("SIGNED")}</option>
                <option value="EXPIRED">{assignmentStatus("EXPIRED")}</option>
              </select>
            </label>
            <label>
              {t("campaignDetail.filters.document")}
              <select
                value={filters.document_version_id}
                onChange={(e) => changeFilters({ document_version_id: e.target.value })}
              >
                <option value="">{t("campaignDetail.filters.all")}</option>
                {publishedAndUsed.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("campaignDetail.filters.group")}
              <select value={filters.group_id} onChange={(e) => changeFilters({ group_id: e.target.value })}>
                <option value="">{t("campaignDetail.filters.all")}</option>
                {groups?.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("campaignDetail.filters.viewing")}
              <select value={filters.viewed} onChange={(e) => changeFilters({ viewed: e.target.value })}>
                <option value="">{t("campaignDetail.filters.all")}</option>
                <option value="true">{t("campaignDetail.filters.viewed")}</option>
                <option value="false">{t("campaignDetail.filters.notViewed")}</option>
              </select>
            </label>
            <label className="consent-row">
              <input
                type="checkbox"
                checked={filters.overdue}
                onChange={(e) => changeFilters({ overdue: e.target.checked })}
              />
              {t("campaignDetail.filters.overdue")}
            </label>
          </div>
          <table className="simple-table">
            <thead>
              <tr>
                {campaign.status === "ACTIVE" && <th aria-label={t("campaignDetail.columns.selection")} />}
                <th>{t("campaignDetail.columns.recipient")}</th>
                <th>{t("campaignDetail.columns.group")}</th>
                <th>{t("campaignDetail.columns.document")}</th>
                <th>{t("campaignDetail.columns.status")}</th>
                <th>{t("campaignDetail.columns.viewed")}</th>
                <th>{t("campaignDetail.columns.signed")}</th>
                <th>{t("campaignDetail.columns.reminders")}</th>
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
                          aria-label={t("campaignDetail.select", { name: a.user_display_name })}
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
                      <div className="muted small">{roleLabelText(a.role_label)}</div>
                    )}
                  </td>
                  <td>
                    <span className={`badge badge--${a.status.toLowerCase()}`}>{assignmentStatus(a.status)}</span>
                    {a.status === "WAITING" && a.waiting_on && a.waiting_on.length > 0 && (
                      <div className="muted small">{t("campaignDetail.after", { names: a.waiting_on.join(", ") })}</div>
                    )}
                  </td>
                  <td>{a.first_viewed_at ? formatDate(a.first_viewed_at) : "—"}</td>
                  <td>{a.signed_at ? formatDate(a.signed_at) : "—"}</td>
                  <td>{a.reminder_count}</td>
                  <td>
                    <div className="row-actions">
                      {a.signature_id && canContent && (
                        <>
                          <a
                            className="button button--secondary button--sm"
                            href={`/api/signatures/${a.signature_id}/signed-pdf?inline=true`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("campaignDetail.openSignedPdf")}
                          </a>
                          <a
                            className="button button--ghost button--sm"
                            href={`/api/signatures/${a.signature_id}/signed-pdf`}
                          >
                            {t("campaignDetail.download")}
                          </a>
                          <Link className="button button--ghost button--sm" to={`/signatures/${a.signature_id}`}>
                            {t("campaignDetail.proof")}
                          </Link>
                        </>
                      )}
                      {campaign.status === "ACTIVE" && isOutstanding(a.status) && (
                        <button
                          type="button"
                          className="button button--ghost button--sm"
                          onClick={() => void remind({ assignment_ids: [a.id] })}
                        >
                          <Bell size={12} aria-hidden="true" /> {t("campaignDetail.remind")}
                        </button>
                      )}
                      {campaign.status === "ACTIVE" &&
                        asked &&
                        a.role === asked.role &&
                        a.status !== "SIGNED" &&
                        a.status !== "CANCELLED" &&
                        a.status !== "EXPIRED" && (
                          <ConfirmButton
                            confirmLabel={t("campaignDetail.stopAsking")}
                            onConfirm={() => removePerson(a.user_id, a.user_display_name)}
                          >
                            {t("campaignDetail.removeOne")}
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
            {t("campaignDetail.archive")}
          </button>
        </div>
      )}
      {campaign.status !== "ACTIVE" && campaign.status !== "SCHEDULED" && (
        <div className="button-row" data-testid="delete-row">
          {campaign.delete_blockers.length === 0 ? (
            <ConfirmButton confirmLabel={t("campaignDetail.confirmDeleteCampaign")} onConfirm={deleteCampaign}>
              {t("campaignDetail.deleteCampaign")}
            </ConfirmButton>
          ) : (
            <p className="blocker-note" title={t("campaignDetail.keptHint")}>
              {t("campaignDetail.kept", { reasons: campaign.delete_blockers.map(blockerText).join(" ; ") })}
            </p>
          )}
        </div>
      )}

      {canContent && (
        <section data-testid="campaign-signed">
          <h2 className="card-title">{t("campaignDetail.signedDocuments")}</h2>
          <SignedDocuments campaignIds={[campaign.id]} refreshKey={assignments?.length ?? 0} />
        </section>
      )}

      {canContent && (
        <div className="card">
          <div className="card-title">
            <FileBarChart size={16} aria-hidden="true" /> {t("campaignDetail.reports")}
          </div>
          <button className="button button--secondary" onClick={generateReport}>
            {t("campaignDetail.generateReport")}
          </button>
          <ul className="plain-list">
            {reports?.map((r) => (
              <li key={r.id} className="report-row">
                {r.display_id} — {formatDateTime(r.generated_at)}
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
