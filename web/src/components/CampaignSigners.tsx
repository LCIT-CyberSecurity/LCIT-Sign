import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Plus, UserPlus, X } from "lucide-react";
import ExternalPersonForm from "./ExternalPersonForm";
import { api, ApiError } from "../api/client";
import type { Campaign } from "../api/types";

export interface SignerOption {
  id: string;
  email: string;
  display_name: string;
  external?: boolean;
}

interface Row {
  key: number;
  mode: "FIXED" | "EACH";
  userId: string;
}

let nextKey = 1;

/** Who signs, in order: named people from the users list (the RSSI) and, last,
 *  "every recipient" — the mail-merge case where each person signs their own copy.
 *  Saved as soon as it is complete, so the editor can offer exactly these people. */
export default function CampaignSigners({
  campaign,
  users,
  onSaved,
  onUserAdded,
}: {
  campaign: Campaign;
  users: SignerOption[] | null;
  onSaved: () => void;
  /** A person from outside was just added: the page's list of people must know them. */
  onUserAdded?: (person: SignerOption) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [rows, setRows] = useState<Row[]>(() =>
    campaign.roles.map((r) => ({ key: nextKey++, mode: r.mode ?? "FIXED", userId: r.user_id ?? "" })),
  );
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(true);

  useEffect(() => {
    // Someone else (or a first load) changed what the server holds.
    setRows(campaign.roles.map((r) => ({ key: nextKey++, mode: r.mode ?? "FIXED", userId: r.user_id ?? "" })));
    setSaved(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaign.id, campaign.roles.length]);

  // Nothing chosen yet: the usual case is that everyone targeted signs their own copy.
  // Propose it (and save it) so the documents can be prepared straight away.
  const [defaulted, setDefaulted] = useState(false);
  useEffect(() => {
    if (defaulted || campaign.roles.length > 0 || rows.length > 0) return;
    setDefaulted(true);
    void persist([{ key: nextKey++, mode: "EACH", userId: "" }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaign.id]);

  const complete = rows.every((r) => r.mode === "EACH" || r.userId);

  const persist = async (next: Row[]) => {
    setRows(next);
    setError(null);
    if (!next.every((r) => r.mode === "EACH" || r.userId)) {
      setSaved(false);
      return;
    }
    try {
      await api.put(`/campaigns/${campaign.id}/signers`, {
        signers: next.map((r, i) => ({
          role: i + 1,
          mode: r.mode,
          user_id: r.mode === "FIXED" ? r.userId : null,
        })),
      });
      setSaved(true);
      onSaved();
    } catch (err) {
      setSaved(false);
      setError(err instanceof ApiError ? err.message : "L'enregistrement a échoué.");
    }
  };

  const lastIsEach = rows.length > 0 && rows[rows.length - 1].mode === "EACH";
  const taken = new Set(rows.map((r) => r.userId).filter(Boolean));

  const choose = (index: number, value: string) => {
    const next = rows.map((r, i) =>
      i === index
        ? value === "EACH"
          ? { ...r, mode: "EACH" as const, userId: "" }
          : { ...r, mode: "FIXED" as const, userId: value }
        : r,
    );
    void persist(next);
  };

  const add = (mode: "FIXED" | "EACH") => {
    const row: Row = { key: nextKey++, mode, userId: "" };
    // The list of recipients always signs last: a named person goes before it.
    const next = lastIsEach && mode === "FIXED" ? [...rows.slice(0, -1), row, rows[rows.length - 1]] : [...rows, row];
    void persist(next);
  };

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= rows.length) return;
    if (rows[index].mode === "EACH" || rows[target].mode === "EACH") return;
    const next = [...rows];
    [next[index], next[target]] = [next[target], next[index]];
    void persist(next);
  };

  return (
    <div className="card" data-testid="signers-card">
      <div className="card-title">Qui signe, dans l&apos;ordre ?</div>
      <p className="muted small">
        Choisissez les personnes dans la liste des utilisateurs : elles signent l&apos;une après l&apos;autre.
        Pour un document que <strong>chaque personne</strong> doit signer (le RSSI signe d&apos;abord, puis
        chacun signe son exemplaire), ajoutez « Chaque destinataire » en dernier.
      </p>

      {rows.length === 0 && (
        <p className="muted small">Personne pour le moment — ajoutez au moins un signataire.</p>
      )}
      <ol className="signer-rows">
        {rows.map((row, i) => (
          <li key={row.key}>
            <span className="signer-rank">{i + 1}</span>
            <select
              aria-label={`Qui signe en position ${i + 1} ?`}
              value={row.mode === "EACH" ? "EACH" : row.userId}
              onChange={(e) => choose(i, e.target.value)}
            >
              <option value="">— Choisir une personne —</option>
              {i === rows.length - 1 && (
                <option value="EACH">Chaque destinataire (chacun signe son exemplaire)</option>
              )}
              {users?.map((u) => (
                <option key={u.id} value={u.id} disabled={taken.has(u.id) && u.id !== row.userId}>
                  {u.display_name} — {u.email}
                  {u.external ? " (externe)" : ""}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="button button--ghost button--sm"
              aria-label="Monter"
              disabled={i === 0 || row.mode === "EACH" || rows[i - 1].mode === "EACH"}
              onClick={() => move(i, -1)}
            >
              <ArrowUp size={13} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="button button--ghost button--sm"
              aria-label="Descendre"
              disabled={i === rows.length - 1 || row.mode === "EACH" || rows[i + 1].mode === "EACH"}
              onClick={() => move(i, 1)}
            >
              <ArrowDown size={13} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="button button--ghost button--sm"
              aria-label={`Retirer le signataire ${i + 1}`}
              onClick={() => void persist(rows.filter((_, j) => j !== i))}
            >
              <X size={13} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ol>

      <div className="row-actions">
        <button type="button" className="button button--secondary button--sm" onClick={() => add("FIXED")}>
          <Plus size={13} aria-hidden="true" /> Ajouter une personne
        </button>
        {!lastIsEach && (
          <button type="button" className="button button--secondary button--sm" onClick={() => add("EACH")}>
            <Plus size={13} aria-hidden="true" /> Ajouter « Chaque destinataire »
          </button>
        )}
        <span className="muted small" data-testid="signers-status">
          {error ? "" : !complete ? "Choisissez la personne pour enregistrer." : rows.length > 0 && saved ? "Enregistré." : ""}
        </span>
      </div>
      <div className="row-actions">
        <button type="button" className="button button--ghost button--sm" onClick={() => setAdding(!adding)}>
          <UserPlus size={13} aria-hidden="true" /> Ajouter une personne extérieure
        </button>
      </div>
      {adding && (
        <ExternalPersonForm
          onCancel={() => setAdding(false)}
          onCreated={(person) => {
            onUserAdded?.(person);
            setAdding(false);
            // Right away among the signers, before the list of recipients if there is one.
            const row: Row = { key: nextKey++, mode: "FIXED", userId: person.id };
            const next = lastIsEach ? [...rows.slice(0, -1), row, rows[rows.length - 1]] : [...rows, row];
            void persist(next);
          }}
        />
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
