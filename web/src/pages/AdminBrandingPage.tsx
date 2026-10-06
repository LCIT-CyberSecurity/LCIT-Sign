import { useEffect, useRef, useState } from "react";
import { ImageIcon, Trash2, Upload } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
import { announceBrandingChange } from "../lib/branding";
import type { Branding } from "../api/types";

/** The logo shown at the top left of every page, on the sign-in page and on signed documents.
 *  An administrator replaces the LCIT one with the company's own, or goes back to it. */
export default function AdminBrandingPage() {
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
      setMessage("Logo enregistré : il apparaît dès maintenant en haut à gauche.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "L'envoi du logo a échoué.");
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
    setMessage("Le logo LCIT est de retour.");
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <ImageIcon size={20} aria-hidden="true" /> Logo
      </h1>
      <div className="card" data-testid="branding-card">
        <div className="card-title">Le logo de votre entreprise</div>
        <p className="muted small">
          Il remplace le logo LCIT en haut à gauche, sur la page de connexion et sur les documents signés qui
          comportent un logo. Image PNG ou JPEG, 512 Ko au plus, d&apos;au moins 16 px ; un fond transparent
          (PNG) rend mieux.
        </p>
        <div className="branding-preview">
          {branding?.has_logo ? (
            <img src={`/api/branding/logo?v=${branding.logo_sha256}`} alt="Logo actuel" />
          ) : (
            <img src="/lcit-mark.png" alt="Logo LCIT par défaut" />
          )}
          <span className="muted small">
            {branding?.has_logo ? "Votre logo" : "Logo LCIT par défaut"}
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
            <Upload size={14} aria-hidden="true" /> {branding?.has_logo ? "Changer le logo" : "Choisir mon logo"}
          </button>
          {branding?.has_logo && (
            <ConfirmButton confirmLabel="Oui, revenir au logo LCIT" onConfirm={remove}>
              <Trash2 size={13} aria-hidden="true" /> Revenir au logo LCIT
            </ConfirmButton>
          )}
        </div>
        {message && <p className="status-ok" role="status">{message}</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
      </div>
    </div>
  );
}
