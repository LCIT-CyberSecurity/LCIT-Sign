import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Rocket } from "lucide-react";
import { api, ApiError } from "../api/client";
import CampaignDocuments from "../components/CampaignDocuments";
import CampaignSigners from "../components/CampaignSigners";
import PolicyFields, {
  EMPTY_POLICY,
  buildPolicyPayload,
  policyProblem,
  type PolicyForm,
} from "../components/PolicyFields";
import type { Campaign, DirectoryGroup, DocumentDetail } from "../api/types";

interface TargetUserOption {
  id: string;
  email: string;
  display_name: string;
}

/** Preparing and sending a request for signature: who signs, what, for which people.
 *  Once launched it is followed in Campagnes (the reporting). */
export default function SignRequestPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [documents, setDocuments] = useState<DocumentDetail[] | null>(null);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [users, setUsers] = useState<TargetUserOption[] | null>(null);
  const [allUsers, setAllUsers] = useState(false);
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [groupQuery, setGroupQuery] = useState("");
  const [recipientCount, setRecipientCount] = useState<number | null>(null);
  const [policy, setPolicy] = useState<PolicyForm>(EMPTY_POLICY);
  const [deadline, setDeadline] = useState("");

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

  const visibleGroups = useMemo(() => {
    const q = groupQuery.trim().toLowerCase();
    return (groups ?? [])
      .filter((g) => g.active && (!q || g.name.toLowerCase().includes(q)))
      .sort((a, b) => b.member_count - a.member_count || a.name.localeCompare(b.name));
  }, [groups, groupQuery]);

  if (!campaign) return <p className="muted">Chargement…</p>;
  // Already launched: it is followed in Campagnes.
  if (campaign.status !== "DRAFT") return <Navigate to={`/campaigns/${campaign.id}`} replace />;

  // Nobody chosen yet means the usual case: everyone targeted signs their own copy.
  const hasList = campaign.roles.length === 0 || campaign.roles.some((r) => r.mode === "EACH");

  const toggle = (list: string[], value: string, setList: (v: string[]) => void) => {
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  };

  const launch = async () => {
    const problem =
      policyProblem(policy) ??
      (policy.reminderBeforeDeadlineDays.trim() && !deadline
        ? "Pour une relance avant l'échéance, indiquez l'échéance."
        : null);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post(`/campaigns/${id}/launch`, {
        ...buildPolicyPayload(policy),
        // Last day to sign, until the end of that day (company time is the server's concern).
        deadline: deadline ? new Date(`${deadline}T23:59:59`).toISOString() : null,
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
        <ArrowLeft size={14} aria-hidden="true" /> Signer
      </Link>

      <div className="page-title-row">
        <h1 className="page-title">{campaign.name}</h1>
        <span className="badge badge--draft">En préparation</span>
      </div>

      <CampaignSigners campaign={campaign} users={users} onSaved={load} />
      <CampaignDocuments campaign={campaign} library={documents} onChanged={load} />

          <div className="card">
            <div className="card-title">3. {hasList ? "Pour quelles personnes ?" : "Récapitulatif"}</div>
            {!hasList && (
              <p className="muted small">
                Chaque signataire est une personne précise : personne d&apos;autre n&apos;est sollicité.
              </p>
            )}
            {hasList && (
            <>
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
            </>
            )}

          </div>

          <div className="card" data-testid="policy-card">
            <div className="card-title">4. Échéance, relances et renouvellement</div>
            <p className="muted small">
              Facultatif. Les relances partent toutes seules vers ceux qui n&apos;ont pas encore signé ; le
              renouvellement redemande les mêmes signatures à intervalle régulier.
            </p>
            <label>
              Échéance <span className="muted small">(dernier jour pour signer)</span>
              <input
                type="date"
                value={deadline}
                min={new Date().toISOString().slice(0, 10)}
                onChange={(e) => setDeadline(e.target.value)}
              />
            </label>
            <PolicyFields value={policy} onChange={setPolicy} />
          </div>

          <div className="card" data-testid="launch-card">
            <div className="card-title">5. Envoyer</div>
            <p className="muted small">
              Une fois envoyée, la demande ne se modifie plus : pour changer quelque chose, on l&apos;annule
              et on en crée une autre. Elle se suit ensuite dans Suivi.
            </p>
            {error && <p className="error-text">{error}</p>}
            <button className="button button--primary" onClick={launch} disabled={busy}>
              <Rocket size={14} aria-hidden="true" /> Envoyer pour signature
            </button>
          </div>
    </div>
  );
}
