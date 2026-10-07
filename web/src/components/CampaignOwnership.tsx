import { useEffect, useState } from "react";
import { UserCog } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConfirmButton from "./ConfirmButton";
import type { Campaign, PersonRef } from "../api/types";

/** Who runs a campaign: its owner, who started it (never rewritten), and the preparers allowed on
 *  it. Whoever may operate it can add a preparer — an operator who must read the content adds
 *  themselves, which leaves a trace — or hand it over to someone else. */
export default function CampaignOwnership({
  campaign,
  onChanged,
}: {
  campaign: Campaign;
  onChanged: (next: Campaign) => void;
}) {
  const canOperate = campaign.access?.operate ?? false;
  const [candidates, setCandidates] = useState<PersonRef[]>([]);
  const [adding, setAdding] = useState("");
  const [handingOver, setHandingOver] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!canOperate) return;
    api
      .get<PersonRef[]>("/campaigns/_meta/preparers")
      .then((all) => setCandidates(Array.isArray(all) ? all : []))
      .catch(() => setCandidates([]));
  }, [canOperate]);

  const call = async (action: () => Promise<Campaign>) => {
    setProblem(null);
    try {
      onChanged(await action());
      setAdding("");
      setHandingOver("");
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "L'opération a échoué.");
    }
  };

  const preparers = (campaign.preparers ?? []).filter((p): p is PersonRef => p !== null);
  const taken = new Set([campaign.owner?.id, ...preparers.map((p) => p.id)]);
  const addable = candidates.filter((c) => !taken.has(c.id));
  const heirs = candidates.filter((c) => c.id !== campaign.owner?.id);

  return (
    <div className="card" data-testid="ownership-card">
      <div className="card-title">
        <UserCog size={16} aria-hidden="true" /> Propriétaire et préparateurs
      </div>
      <dl className="detail-list">
        <div>
          <dt>Propriétaire</dt>
          <dd data-testid="owner">{campaign.owner?.display_name ?? "—"}</dd>
        </div>
        {campaign.created_by && campaign.created_by.id !== campaign.owner?.id && (
          <div>
            <dt>Créée par</dt>
            <dd data-testid="created-by">{campaign.created_by.display_name}</dd>
          </div>
        )}
        <div>
          <dt>Préparateurs</dt>
          <dd>
            {preparers.length === 0 ? (
              <span className="muted">Aucun autre que le propriétaire.</span>
            ) : (
              <ul className="plain-list" data-testid="preparers">
                {preparers.map((p) => (
                  <li key={p.id}>
                    {p.display_name}{" "}
                    {canOperate && (
                      <ConfirmButton
                        confirmLabel="Oui, retirer"
                        onConfirm={() =>
                          call(() => api.del<Campaign>(`/campaigns/${campaign.id}/preparers/${p.id}`))
                        }
                      >
                        Retirer
                      </ConfirmButton>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
      {!campaign.access?.content && (
        <p className="muted small" data-testid="confidential-note">
          Le contenu de cette campagne (documents, PDF signés, preuves) est confidentiel : il faut en être le
          propriétaire ou un préparateur pour y accéder.
        </p>
      )}
      {problem && <p className="error-text" role="alert">{problem}</p>}
      {canOperate && (
        <div className="form-row">
          <label>
            Ajouter un préparateur
            <select value={adding} onChange={(e) => setAdding(e.target.value)}>
              <option value="">Choisir…</option>
              {addable.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button button--secondary"
            disabled={!adding}
            onClick={() => void call(() => api.post<Campaign>(`/campaigns/${campaign.id}/preparers`, { user_id: adding }))}
          >
            Ajouter
          </button>
          <label>
            Changer le propriétaire
            <select value={handingOver} onChange={(e) => setHandingOver(e.target.value)}>
              <option value="">Choisir…</option>
              {heirs.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </label>
          <ConfirmButton
            confirmLabel="Oui, changer de propriétaire"
            disabled={!handingOver}
            onConfirm={() =>
              call(() => api.put<Campaign>(`/campaigns/${campaign.id}/owner`, { user_id: handingOver }))
            }
          >
            Changer
          </ConfirmButton>
        </div>
      )}
    </div>
  );
}
