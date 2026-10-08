import { useEffect, useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { api, ApiError } from "../api/client";
import { GoogleLogo, MicrosoftLogo } from "../components/ProviderLogos";

interface Provider {
  provider: "entra" | "google";
  configured: boolean;
  active?: boolean;
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
      setMessage({ ok: true, text: "Enregistré : c'est maintenant le fournisseur de connexion." });
      onSaved();
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : "Échec de l'enregistrement." });
    }
  };

  const activate = async () => {
    setMessage(null);
    try {
      await api.post(`/admin/login-providers/${item.provider}/activate`);
      onSaved();
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : "Échec de l'activation." });
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
        {label.logo} {label.name}{" "}
        {item.active ? "(actif)" : item.configured ? "(configuré, inactif)" : "(non configuré)"}
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
        {item.configured && !item.active && (
          <button className="button" type="button" onClick={activate}>
            Utiliser ce fournisseur
          </button>
        )}
        {item.configured && (
          <button className="button" type="button" onClick={remove}>
            Supprimer
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

/** Connexion: ONE external sign-in provider is in use (the active one), and the local form is
 *  always there next to it. */
export default function AdminLoginPage() {
  const [items, setItems] = useState<Provider[] | null>(null);
  const [fixedByServer, setFixedByServer] = useState(false);
  const load = () => {
    api.get<Provider[]>("/admin/login-providers").then(setItems);
    api
      .get<{ managed_by_environment: boolean }>("/admin/login-providers/status")
      .then((s) => setFixedByServer(Boolean(s?.managed_by_environment)))
      .catch(() => undefined);
  };
  useEffect(load, []);
  if (!items) return <p className="muted">Chargement…</p>;
  return (
    <section className="stack" data-testid="identity-login">
      <h2 className="page-title" style={{ fontSize: 18, margin: 0 }}>
        <KeyRound size={18} aria-hidden="true" /> Connexion
      </h2>
      <p className="muted">
        Comment les gens s&apos;authentifient : <strong>un seul</strong> fournisseur SSO est actif (celui que la
        page de connexion propose), plus la connexion locale, toujours disponible. Les identifiants se saisissent
        ici : ils sont stockés chiffrés dans la base, jamais dans le code ni dans l&apos;environnement.
      </p>
      {fixedByServer && (
        <p className="error-text" role="status" data-testid="sso-fixed-by-server">
          Le SSO est imposé par la configuration du serveur (variables LCIT_SIGN_OIDC_*) : tant qu&apos;elles sont
          définies, elles passent avant les réglages ci-dessous.
        </p>
      )}
      {items.map((item) => (
        <ProviderCard key={`${item.provider}-${item.configured}-${item.active}`} item={item} onSaved={load} />
      ))}
    </section>
  );
}
