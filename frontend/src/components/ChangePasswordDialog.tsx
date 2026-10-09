import { useState, type FormEvent } from "react";
import { KeyRound, X } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** The built-in account's owner chooses their own password. */
export default function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const { refresh } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (next !== confirm) {
      setError("Les deux nouveaux mots de passe sont différents.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      await refresh();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Le changement a échoué.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="modal card" role="dialog" aria-modal="true" aria-labelledby="pw-title" onSubmit={submit}>
        <div className="page-title-row">
          <h2 id="pw-title" className="card-title" style={{ margin: 0 }}>
            <KeyRound size={16} aria-hidden="true" /> Changer le mot de passe
          </h2>
          <button type="button" className="button button--ghost button--sm" onClick={onClose} aria-label="Fermer">
            <X size={14} />
          </button>
        </div>
        <label>
          Mot de passe actuel
          <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label>
          Nouveau mot de passe
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={12} />
        </label>
        <label>
          Confirmer le nouveau mot de passe
          <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </label>
        <p className="muted small">12 caractères au minimum, différent de l&apos;actuel, ni courant ni répétitif.</p>
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="row-actions" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="button button--ghost" onClick={onClose}>
            Plus tard
          </button>
          <button type="submit" className="button button--primary" disabled={busy}>
            {busy ? "Enregistrement…" : "Changer le mot de passe"}
          </button>
        </div>
      </form>
    </div>
  );
}
