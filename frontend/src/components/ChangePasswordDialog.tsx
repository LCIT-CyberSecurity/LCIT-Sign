import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, X } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** The built-in account's owner chooses their own password. */
export default function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
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
      setError(t("password.mismatch"));
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      await refresh();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("password.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="modal card" role="dialog" aria-modal="true" aria-labelledby="pw-title" onSubmit={submit}>
        <div className="page-title-row">
          <h2 id="pw-title" className="card-title" style={{ margin: 0 }}>
            <KeyRound size={16} aria-hidden="true" /> {t("password.title")}
          </h2>
          <button type="button" className="button button--ghost button--sm" onClick={onClose} aria-label={t("common.close")}>
            <X size={14} />
          </button>
        </div>
        <label>
          {t("password.current")}
          <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label>
          {t("password.new")}
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={12} />
        </label>
        <label>
          {t("password.confirm")}
          <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </label>
        <p className="muted small">{t("password.rules")}</p>
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="row-actions" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="button button--ghost" onClick={onClose}>
            {t("common.later")}
          </button>
          <button type="submit" className="button button--primary" disabled={busy}>
            {busy ? t("common.saving") : t("password.title")}
          </button>
        </div>
      </form>
    </div>
  );
}
