import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Rocket } from "lucide-react";
import { api, ApiError } from "../api/client";
import CampaignDocuments from "../components/CampaignDocuments";
import CampaignSigners from "../components/CampaignSigners";
import ConfirmButton from "../components/ConfirmButton";
import RecipientPicker from "../components/RecipientPicker";
import ScheduleFields, {
  EMPTY_SCHEDULE,
  describeSchedule,
  scheduleBody,
  scheduleProblem,
  type Schedule,
} from "../components/Schedule";
import type { Campaign, DirectoryGroup, DocumentDetail } from "../api/types";

interface TargetUserOption {
  id: string;
  email: string;
  display_name: string;
}

const STEPS = ["Signataires et relances", "Documents et éléments", "Vérifier et envoyer"];

/** Preparing and sending a request for signature: who signs, what, for which people.
 *  Once launched it is followed in Campagnes (the reporting). */
export default function SignRequestPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [query, setQuery] = useSearchParams();
  const step = Math.min(3, Math.max(1, Number(query.get("step")) || 1));
  const goTo = (n: number) => setQuery({ step: String(n) }, { replace: false });
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
  const [schedule, setSchedule] = useState<Schedule>(EMPTY_SCHEDULE);

  const load = () => {
    if (!id) return;
    api.get<Campaign>(`/campaigns/${id}`).then(setCampaign);
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

  if (!campaign) return <p className="muted">Chargement…</p>;
  // Already launched: it is followed in Campagnes.
  if (campaign.status !== "DRAFT") return <Navigate to={`/campaigns/${campaign.id}`} replace />;

  // Nobody chosen yet means the usual case: everyone targeted signs their own copy.
  const hasList = campaign.roles.length === 0 || campaign.roles.some((r) => r.mode === "EACH");

  const scheduled = scheduleBody(schedule).start_at !== null;
  const unprepared = campaign.documents.filter((d) => d.elements === 0);
  const blocker =
    hasList && recipientCount === 0
      ? "Choisissez les personnes concernées (écran « Signataires et relances »)."
      : campaign.documents.length === 0
      ? "Ajoutez au moins un document."
      : unprepared.length > 0
        ? `Placez les éléments (signature, date, nom…) sur : ${unprepared.map((d) => d.title).join(", ")}.`
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
      navigate(`/campaigns/${id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Le lancement a échoué.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <Link to="/sign" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> Faire signer
      </Link>

      <div className="page-title-row">
        <h1 className="page-title">{campaign.name}</h1>
        <span className="badge badge--draft">En préparation</span>
      </div>

      <ol className="wizard-steps" data-testid="wizard-steps">
        {STEPS.map((label, i) => (
          <li key={label} className={step === i + 1 ? "is-current" : step > i + 1 ? "is-done" : ""}>
            <button type="button" onClick={() => goTo(i + 1)} aria-current={step === i + 1 ? "step" : undefined}>
              <span className="wizard-steps__n">{step > i + 1 ? <Check size={13} aria-hidden="true" /> : i + 1}</span>
              {label}
            </button>
          </li>
        ))}
      </ol>

      {step === 1 && (
        <>
          <CampaignSigners campaign={campaign} users={users} onSaved={load} />
          <div className="card">
            <div className="card-title">{hasList ? "Pour quelles personnes ? (publipostage)" : "Personnes sollicitées"}</div>
            {!hasList && (
              <p className="muted small">
                Chaque signataire est une personne précise : personne d&apos;autre n&apos;est sollicité.
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
              />
            )}
          </div>

          <div className="card" data-testid="policy-card">
            <div className="card-title">Planning</div>
            <p className="muted small">
              Quand cela commence, jusqu&apos;à quand on peut signer, à quel rythme relancer ceux qui n&apos;ont
              pas répondu, et s&apos;il faut redemander la signature régulièrement. Tout est facultatif.
            </p>
            <ScheduleFields value={schedule} onChange={setSchedule} />
          </div>

          <div className="row-actions">
            <button type="button" className="button button--primary" onClick={() => goTo(2)} disabled={campaign.roles.length === 0}>
              Suivant : les documents <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <CampaignDocuments campaign={campaign} library={documents} onChanged={load} />
          <div className="row-actions">
            <button type="button" className="button button--ghost" onClick={() => goTo(1)}>
              <ArrowLeft size={14} aria-hidden="true" /> Les signataires
            </button>
            <button type="button" className="button button--primary" onClick={() => goTo(3)}>
              Suivant : vérifier et envoyer <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <div className="card" data-testid="recap-card">
            <div className="card-title">Récapitulatif</div>
            <dl className="recap">
              <div>
                <dt>
                  Signataires, dans l&apos;ordre <button className="link-button" onClick={() => goTo(1)}>Modifier</button>
                </dt>
                <dd>
                  <ol className="plain-list">
                    {campaign.roles.map((r) => (
                      <li key={r.role}>
                        {r.role}.{" "}
                        {r.mode === "EACH"
                          ? `Chaque destinataire${recipientCount !== null ? ` (${recipientCount} personne(s))` : ""}`
                          : r.user_display_name}
                      </li>
                    ))}
                  </ol>
                </dd>
              </div>
              <div>
                <dt>
                  Documents <button className="link-button" onClick={() => goTo(2)}>Modifier</button>
                </dt>
                <dd>
                  <ul className="plain-list">
                    {campaign.documents.map((d) => (
                      <li key={d.version_id}>
                        {d.title} — {d.elements} élément(s) placé(s)
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
              <div>
                <dt>
                  Planning <button className="link-button" onClick={() => goTo(1)}>Modifier</button>
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
            <div className="card-title">Envoyer</div>
            <p data-testid="send-summary">
              <strong>{campaign.documents.length}</strong> document(s) à signer par{" "}
              <strong>
                {campaign.roles
                  .map((r) => (r.mode === "EACH" ? "chaque destinataire" : r.user_display_name))
                  .join(", puis ")}
              </strong>
              .{" "}
              {schedule.startDate && schedule.startDate > new Date().toISOString().slice(0, 10)
                ? "L'envoi est programmé : personne n'est prévenu avant la date de début."
                : "Les personnes concernées sont prévenues par e-mail dès l'envoi."}
            </p>
            <p className="muted small">
              Une fois envoyée, la demande ne se modifie plus : pour changer quelque chose, on l&apos;annule
              et on en crée une autre. Elle se suit ensuite dans Suivi.
            </p>
            {blocker && (
              <p className="muted small" data-testid="launch-blocker">
                {blocker}
              </p>
            )}
            {error && <p className="error-text">{error}</p>}
            <div className="row-actions">
              <button type="button" className="button button--ghost" onClick={() => goTo(2)}>
                <ArrowLeft size={14} aria-hidden="true" /> Les documents
              </button>
              <ConfirmButton
                className="button button--primary"
                confirmClassName="button button--primary"
                confirmLabel={scheduled ? "Oui, programmer" : "Oui, envoyer maintenant"}
                disabled={busy || blocker !== null}
                onConfirm={launch}
              >
                <Rocket size={14} aria-hidden="true" />{" "}
                {scheduled ? "Programmer l'envoi" : "Envoyer pour signature"}
              </ConfirmButton>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
