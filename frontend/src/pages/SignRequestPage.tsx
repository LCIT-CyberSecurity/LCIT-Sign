import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, RefreshCw, Rocket } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import CampaignDocuments from "../components/CampaignDocuments";
import CampaignSigners from "../components/CampaignSigners";
import PrepareStep from "../components/PrepareStep";
import { missingSignatureText, missingSignatures } from "../lib/signatures";
import ConfirmButton from "../components/ConfirmButton";
import RecipientPicker from "../components/RecipientPicker";
import SignedDocuments from "../components/SignedDocuments";
import ScheduleFields, {
  defaultSchedule,
  describeSchedule,
  scheduleBody,
  scheduleFromPlan,
  scheduleProblem,
  type Schedule,
} from "../components/Schedule";
import type { Campaign, DirectoryGroup, DocumentDetail } from "../api/types";

interface TargetUserOption {
  id: string;
  email: string;
  display_name: string;
  external?: boolean;
}

const STEP_KEYS = [
  "signRequest.steps.signers",
  "signRequest.steps.documents",
  "signRequest.steps.prepare",
  "signRequest.steps.review",
  "signRequest.steps.signed",
];

/** Preparing and sending a request for signature: who signs, what, for which people.
 *  The last step shows what comes back: the signed documents, live. A request already sent
 *  opens on it, and the whole follow-up (reminders, changes…) is in Suivi. */
export default function SignRequestPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [query, setQuery] = useSearchParams();
  const asked = Math.min(5, Math.max(1, Number(query.get("step")) || 1));
  const goTo = (n: number) => setQuery({ step: String(n) }, { replace: false });
  const [refresh, setRefresh] = useState(0);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [documents, setDocuments] = useState<DocumentDetail[] | null>(null);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [users, setUsers] = useState<TargetUserOption[] | null>(null);
  const [allUsers, setAllUsers] = useState(false);
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recipientCount, setRecipientCount] = useState<number | null>(null);
  const [schedule, setSchedule] = useState<Schedule>(defaultSchedule);

  const load = () => {
    if (!id) return;
    api.get<Campaign>(`/campaigns/${id}`).then(setCampaign);
  };

  // What was chosen so far (recipients, planning) is kept on the request: found again on a reload
  // or the next day, like the signers, the documents and the elements.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    if (!campaign || hydrated) return;
    const plan = campaign.plan;
    if (plan) {
      setAllUsers(Boolean(plan.all_users));
      setSelectedGroupIds(plan.group_ids ?? []);
      setSelectedUserIds(plan.user_ids ?? []);
      setSchedule(scheduleFromPlan(plan));
    }
    setHydrated(true);
  }, [campaign, hydrated]);
  useEffect(() => {
    if (!hydrated || !id || campaign?.status !== "DRAFT") return;
    // A short pause, so typing is not one request per key.
    const timer = setTimeout(() => {
      api
        .put(`/campaigns/${id}/plan`, {
          ...scheduleBody(schedule),
          all_users: allUsers,
          group_ids: allUsers ? [] : selectedGroupIds,
          user_ids: allUsers ? [] : selectedUserIds,
        })
        .catch(() => undefined);
    }, 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, allUsers, selectedGroupIds, selectedUserIds, schedule]);

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
    // After a reload the count is asked twice in a row (nothing chosen yet, then what was kept):
    // only the answer to the latest choice may be shown, whatever the order they come back in.
    let latest = true;
    api
      .post<{ population_count: number }>(`/campaigns/${id}/targets/preview`, {
        all_users: allUsers,
        group_ids: allUsers ? [] : selectedGroupIds,
        user_ids: allUsers ? [] : selectedUserIds,
      })
      .then((r) => latest && setRecipientCount(r.population_count))
      .catch(() => latest && setRecipientCount(null));
    return () => {
      latest = false;
    };
  }, [id, campaign?.status, allUsers, selectedGroupIds, selectedUserIds]);

  if (!campaign) return <p className="muted">{t("common.loading")}</p>;
  // Sent (or scheduled): only the last step is left; before sending, it is not reachable yet.
  const sent = campaign.status !== "DRAFT";
  const step = sent ? 5 : Math.min(asked, 4);

  // Nobody chosen yet means the usual case: everyone targeted signs their own copy.
  const hasList = campaign.roles.length === 0 || campaign.roles.some((r) => r.mode === "EACH");

  const scheduled = scheduleBody(schedule).start_at !== null;
  const unprepared = campaign.documents.filter((d) => d.elements === 0);
  const noSignature = missingSignatures(campaign);
  // What stops the sending, in the order a person would fix it.
  const blocker =
    hasList && recipientCount === 0
      ? t("signRequest.chooseRecipients")
      : campaign.documents.length === 0
        ? t("signRequest.addOneDocument")
        : unprepared.length > 0
          ? t("signRequest.placeElements", { titles: unprepared.map((d) => d.title).join(", ") })
          : noSignature.length > 0
            ? missingSignatureText(noSignature)
            : null;

  const launch = async () => {
    const problem = scheduleProblem(schedule);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post(`/campaigns/${id}/launch`, {
        ...scheduleBody(schedule),
        all_users: allUsers,
        group_ids: allUsers ? [] : selectedGroupIds,
        user_ids: allUsers ? [] : selectedUserIds,
      });
      // The request is sent: on to the last step, which shows what comes back.
      setCampaign(await api.get<Campaign>(`/campaigns/${id}`));
      navigate(`/sign/${id}?step=5`);
    } catch (err) {
      setError(errorText(err, "signRequest.launchFailed"));
    } finally {
      setBusy(false);
    }
  };

  const deleteDraft = async () => {
    setError(null);
    try {
      await api.del(`/campaigns/${id}`);
      navigate("/sign");
    } catch (err) {
      setError(errorText(err, "signRequest.deleteFailed"));
    }
  };

  return (
    <div className="stack">
      <Link to="/sign" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> {t("nav.sign")}
      </Link>

      <div className="page-title-row">
        <h1 className="page-title">{campaign.name}</h1>
        <span className={`badge badge--${sent ? campaign.status.toLowerCase() : "draft"}`}>
          {sent
            ? campaign.status === "SCHEDULED"
              ? t("signRequest.badgeScheduled")
              : t("signRequest.badgeSent")
            : t("signRequest.badgePreparing")}
        </span>
        {!sent && (
          <ConfirmButton confirmLabel={t("signRequest.confirmDeleteRequest")} onConfirm={deleteDraft}>
            {t("signRequest.deleteRequest")}
          </ConfirmButton>
        )}
      </div>

      <ol className="wizard-steps" data-testid="wizard-steps">
        {STEP_KEYS.map((key, i) => (
          <li key={key} className={step === i + 1 ? "is-current" : step > i + 1 ? "is-done" : ""}>
            <button
              type="button"
              onClick={() => goTo(i + 1)}
              aria-current={step === i + 1 ? "step" : undefined}
              // Once sent, what was prepared no longer changes; before sending, nothing is signed yet.
              disabled={sent ? i < 4 : i === 4}
            >
              <span className="wizard-steps__n">{step > i + 1 ? <Check size={13} aria-hidden="true" /> : i + 1}</span>
              {t(key)}
            </button>
          </li>
        ))}
      </ol>

      {step === 5 && (
        <>
          <div className="card" data-testid="signed-step">
            <div className="card-title">{t("signRequest.signedTitle")}</div>
            <p className="muted small">
              {campaign.status === "SCHEDULED" ? t("signRequest.scheduledNote") : t("signRequest.signedNote")}
            </p>
            <div className="row-actions">
              <button type="button" className="button button--secondary" onClick={() => setRefresh(refresh + 1)}>
                <RefreshCw size={14} aria-hidden="true" /> {t("signRequest.refresh")}
              </button>
              <Link className="button button--ghost" to={`/campaigns/${campaign.id}`}>
                {t("signRequest.openTracking")}
              </Link>
              <Link className="button button--ghost" to="/sign">
                {t("signRequest.newRequest")}
              </Link>
            </div>
          </div>
          <SignedDocuments campaignIds={[campaign.id]} refreshKey={refresh} />
        </>
      )}

      {step === 1 && (
        <>
          <CampaignSigners
            campaign={campaign}
            users={users}
            onSaved={load}
            onUserAdded={(person) => setUsers((all) => [...(all ?? []), person])}
          />
          <div className="card">
            <div className="card-title">{hasList ? t("signRequest.forWhom") : t("signRequest.peopleAsked")}</div>
            {!hasList && (
              <p className="muted small">
                {t("signRequest.oneSpecificPerson")}
              </p>
            )}
            {hasList && (
              <RecipientPicker
                value={{ allUsers, groupIds: selectedGroupIds, userIds: selectedUserIds }}
                onChange={(next) => {
                  setAllUsers(next.allUsers);
                  setSelectedGroupIds(next.groupIds);
                  setSelectedUserIds(next.userIds);
                }}
                groups={groups}
                users={users}
                count={recipientCount}
                onAddExternal={(person) => setUsers((all) => [...(all ?? []), person])}
              />
            )}
          </div>


          <div className="card" data-testid="policy-card">
            <div className="card-title">{t("signRequest.planning")}</div>
            <p className="muted small">{t("signRequest.planningHelp")}</p>
            <ScheduleFields value={schedule} onChange={setSchedule} />
          </div>

          <div className="row-actions">
            <button type="button" className="button button--primary" onClick={() => goTo(2)} disabled={campaign.roles.length === 0}>
              {t("signRequest.nextDocuments")} <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <CampaignDocuments
            campaign={campaign}
            library={documents}
            onChanged={load}
            showPrepare={false}
            onImported={() => goTo(3)}
          />
          <div className="row-actions">
            <button type="button" className="button button--ghost" onClick={() => goTo(1)}>
              <ArrowLeft size={14} aria-hidden="true" /> {t("signRequest.backSigners")}
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={() => goTo(3)}
              disabled={campaign.documents.length === 0}
            >
              {t("signRequest.nextPrepare")} <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <PrepareStep
            campaign={campaign}
            selected={query.get("doc")}
            onSelect={(versionId) => setQuery({ step: "3", doc: versionId })}
            onReload={load}
            onDone={() => goTo(4)}
          />
          <div className="row-actions">
            <button type="button" className="button button--ghost" onClick={() => goTo(2)}>
              <ArrowLeft size={14} aria-hidden="true" /> {t("signRequest.backDocuments")}
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={() => goTo(4)}
              disabled={
                unprepared.length > 0 || noSignature.length > 0 || campaign.documents.length === 0
              }
            >
              {t("signRequest.nextReview")} <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
          {unprepared.length > 0 && (
            <p className="muted small">
              {t("signRequest.stillToPrepare", { titles: unprepared.map((d) => d.title).join(", ") })}
            </p>
          )}
        </>
      )}

      {step === 4 && (
        <>
          <div className="card" data-testid="recap-card">
            <div className="card-title">{t("signRequest.recap")}</div>
            <dl className="recap">
              <div>
                <dt>
                  {t("signRequest.signersInOrder")}{" "}
                  <button className="link-button" onClick={() => goTo(1)}>
                    {t("signRequest.modify")}
                  </button>
                </dt>
                <dd>
                  <ol className="plain-list">
                    {campaign.roles.map((r) => (
                      <li key={r.role}>
                        {r.role}.{" "}
                        {r.mode === "EACH"
                          ? recipientCount !== null
                            ? t("signRequest.eachRecipientCount", { count: recipientCount })
                            : t("signRequest.eachRecipient")
                          : r.user_display_name}
                      </li>
                    ))}
                  </ol>
                </dd>
              </div>
              <div>
                <dt>
                  {t("signRequest.documentsRecap")}{" "}
                  <button className="link-button" onClick={() => goTo(3)}>
                    {t("signRequest.modify")}
                  </button>
                </dt>
                <dd>
                  <ul className="plain-list">
                    {campaign.documents.map((d) => (
                      <li key={d.version_id}>
                        {t("signRequest.elementsLine", { title: d.title, elements: t("counts.elementsPlaced", { count: d.elements }) })}
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
              <div>
                <dt>
                  {t("signRequest.planningRecap")}{" "}
                  <button className="link-button" onClick={() => goTo(1)}>
                    {t("signRequest.modify")}
                  </button>
                </dt>
                <dd>
                  <ul className="plain-list">
                    {describeSchedule(schedule).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </dd>
              </div>
            </dl>
          </div>

          <div className="card" data-testid="launch-card">
            <div className="card-title">{t("signRequest.send")}</div>
            <p data-testid="send-summary">
              <Trans
                i18nKey="signRequest.sendSummary"
                count={campaign.documents.length}
                values={{
                  who: campaign.roles
                    .map((r) => (r.mode === "EACH" ? t("signRequest.eachRecipientLower") : r.user_display_name))
                    .join(t("signRequest.then")),
                }}
                components={{ strong: <strong /> }}
              />{" "}
              {schedule.startDate && schedule.startDate > new Date().toISOString().slice(0, 10)
                ? t("signRequest.scheduledSend")
                : t("signRequest.immediateSend")}
            </p>
            <p className="muted small">
              {t("signRequest.finalNote")}
            </p>
            {blocker && (
              <p className="muted small" data-testid="launch-blocker">
                {blocker}
              </p>
            )}
            {error && <p className="error-text">{error}</p>}
            <div className="row-actions">
              <button type="button" className="button button--ghost" onClick={() => goTo(3)}>
                <ArrowLeft size={14} aria-hidden="true" /> {t("signRequest.backPreparation")}
              </button>
              <ConfirmButton
                className="button button--primary"
                confirmClassName="button button--primary"
                confirmLabel={scheduled ? t("signRequest.confirmSchedule") : t("signRequest.confirmSend")}
                disabled={busy || blocker !== null}
                onConfirm={launch}
              >
                <Rocket size={14} aria-hidden="true" />{" "}
                {scheduled ? t("signRequest.scheduleSend") : t("signRequest.sendForSignature")}
              </ConfirmButton>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
