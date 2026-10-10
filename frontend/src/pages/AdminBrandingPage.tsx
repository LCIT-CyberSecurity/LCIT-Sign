import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ImageIcon, Trash2, Upload } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import ConfirmButton from "../components/ConfirmButton";
import { announceBrandingChange } from "../lib/branding";
import type { Branding } from "../api/types";

/** The logo shown at the top left of every page, on the sign-in page and on signed documents.
 *  An administrator replaces the LCIT one with the company's own, or goes back to it. */
export default function AdminBrandingPage() {
  const { t } = useTranslation();
  const [branding, setBranding] = useState<Branding | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = () => api.get<Branding>("/branding").then(setBranding);
  useEffect(() => {
    void load();
  }, []);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.putForm("/admin/branding/logo", form);
      await load();
      announceBrandingChange();
      setMessage(t("branding.uploaded"));
    } catch (err) {
      setError(errorText(err, "branding.uploadFailed"));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  const remove = async () => {
    setError(null);
    await api.del("/admin/branding/logo");
    await load();
    announceBrandingChange();
    setMessage(t("branding.reverted"));
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <ImageIcon size={20} aria-hidden="true" /> {t("branding.title")}
      </h1>
      <div className="card" data-testid="branding-card">
        <div className="card-title">{t("branding.cardTitle")}</div>
        <p className="muted small">
          {t("branding.help")}
        </p>
        <div className="branding-preview">
          {branding?.has_logo ? (
            <img src={`/api/branding/logo?v=${branding.logo_sha256}`} alt={t("branding.currentAlt")} />
          ) : (
            <img src="/lcit-mark.png" alt={t("branding.defaultAlt")} />
          )}
          <span className="muted small">
            {branding?.has_logo ? t("branding.yours") : t("branding.default")}
          </span>
        </div>
        <div className="row-actions">
          <input
            ref={input}
            type="file"
            accept="image/png,image/jpeg"
            hidden
            data-testid="logo-input"
            onChange={(e) => void upload(e.target.files?.[0])}
          />
          <button
            type="button"
            className="button button--primary"
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            <Upload size={14} aria-hidden="true" /> {branding?.has_logo ? t("branding.change") : t("branding.choose")}
          </button>
          {branding?.has_logo && (
            <ConfirmButton confirmLabel={t("branding.confirmRevert")} onConfirm={remove}>
              <Trash2 size={13} aria-hidden="true" /> {t("branding.revert")}
            </ConfirmButton>
          )}
        </div>
        {message && <p className="status-ok" role="status">{message}</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
      </div>
    </div>
  );
}
