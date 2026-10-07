import { useEffect, useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { api, ApiError } from "../api/client";
import { GoogleLogo, MicrosoftLogo } from "../components/ProviderLogos";

interface Provider {
  provider: "entra" | "google";
  configured: boolean;
  client_id: string;
  tenant_id: string;
  redirect_uri: string;
}

const LABELS = {
  entra: { name: "Microsoft (Entra ID)", logo: <MicrosoftLogo /> },
  google: { name: "Google", logo: <GoogleLogo /> },
};

/** One sign-in button per provider, set up by hand: the application's identifiers and its secret.
 *  The secret is written once, stored encrypted, and never shown again. */
function ProviderCard({ item, onSaved }: { item: Provider; onSaved: () => void }) {
  const [clientId, setClientId] = useState(item.client_id);
  const [tenantId, setTenantId] = useState(item.tenant_id);
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const label = LABELS[item.provider];

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setMessage(null);
    try {
      await api.put(`/admin/login-providers/${item.provider}`, {
        client_id: clientId,
        tenant_id: item.provider === "entra" ? tenantId : undefined,
        client_secret: secret || undefined,
      });
      setSecret(""); // the secret never stays in the page once sent
      setMessage({ ok: true, text: "Enregistré. Le bouton apparaît sur la page de connexion." });
      onSaved();
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : "Échec de l'enregistrement." });
    }
  };

  const remove = async () => {
    setMessage(null);
    try {
      await api.del(`/admin/login-providers/${item.provider}`);
      setClientId("");
      setTenantId("");
      setSecret("");
      onSaved();
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : "Échec de la suppression." });
    }
  };

  return (
    <form
      className="card form"
      onSubmit={save}
      autoComplete="off"
      data-testid={`login-provider-${item.provider}`}
    >
      <div className="card-title">
        {label.logo} {label.name} {item.configured ? "(activé)" : "(non configuré)"}
      </div>
      <p className="muted small">
        Adresse de retour à déclarer chez le fournisseur : <code>{item.redirect_uri}</code>
      </p>
      {item.provider === "entra" && (
        <div className="field">
          <label htmlFor="login-entra-tenant">ID du tenant (annuaire)</label>
          <input
            id="login-entra-tenant"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="73405479-f042-45d7-8149-c90341261b65"
            required
          />
        </div>
      )}
      <div className="field">
        <label htmlFor={`login-${item.provider}-client`}>
          {item.provider === "entra" ? "ID de l'application (client)" : "ID client OAuth"}
        </label>
        <input
          id={`login-${item.provider}-client`}
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          placeholder={item.provider === "entra" ? "333a1a3e-1d45-4661-…" : "123-abc.apps.googleusercontent.com"}
          required
        />
      </div>
      <div className="field">
        <label htmlFor={`login-${item.provider}-secret`}>Secret client (la valeur, pas son ID)</label>
        <input
          id={`login-${item.provider}-secret`}
          type="password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          autoComplete="new-password"
          placeholder={item.configured ? "•••••••• (enregistré — laisser vide pour le garder)" : ""}
          required={!item.configured}
        />
      </div>
      <div className="form-row">
        <button className="button button--primary" type="submit">
          Enregistrer
        </button>
        {item.configured && (
          <button className="button" type="button" onClick={remove}>
            Désactiver
          </button>
        )}
      </div>
      {message && (
        <p role="status" className={message.ok ? "" : "error-text"}>
          {message.text}
        </p>
      )}
    </form>
  );
}

export default function AdminLoginPage() {
  const [items, setItems] = useState<Provider[] | null>(null);
  const load = () => api.get<Provider[]>("/admin/login-providers").then(setItems);
  useEffect(() => {
    load();
  }, []);
  if (!items) return <p className="muted">Chargement…</p>;
  return (
    <div className="page">
      <h1>
        <KeyRound size={20} aria-hidden="true" /> Connexion
      </h1>
      <p className="muted">
        Les boutons de la page de connexion. Les identifiants se saisissent ici : ils sont stockés chiffrés
        dans la base, jamais dans le code ni dans l&apos;environnement. La connexion locale reste toujours
        disponible.
      </p>
      {items.map((item) => (
        <ProviderCard key={`${item.provider}-${item.configured}`} item={item} onSaved={load} />
      ))}
    </div>
  );
}
