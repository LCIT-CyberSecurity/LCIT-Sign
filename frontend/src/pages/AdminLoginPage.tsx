import { useEffect, useState, type FormEvent } from "react";
import { Trans, useTranslation } from "react-i18next";
import { KeyRound } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import { GoogleLogo, MicrosoftLogo } from "../components/ProviderLogos";

interface Provider {
  provider: "entra" | "google";
  configured: boolean;
  active?: boolean;
  client_id: string;
  tenant_id: string;
  redirect_uri: string;
}

// Provider names are proper names: the same in every language.
const LABELS = {
  entra: { name: "Microsoft (Entra ID)", logo: <MicrosoftLogo /> },
  google: { name: "Google", logo: <GoogleLogo /> },
};

/** One sign-in button per provider, set up by hand: the application's identifiers and its secret.
 *  The secret is written once, stored encrypted, and never shown again. */
function ProviderCard({ item, onSaved }: { item: Provider; onSaved: () => void }) {
  const { t } = useTranslation();
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
      setMessage({ ok: true, text: t("identity.login.saved") });
      onSaved();
    } catch (err) {
      setMessage({ ok: false, text: errorText(err, "identity.login.saveFailed") });
    }
  };

  const activate = async () => {
    setMessage(null);
    try {
      await api.post(`/admin/login-providers/${item.provider}/activate`);
      onSaved();
    } catch (err) {
      setMessage({ ok: false, text: errorText(err, "identity.login.activateFailed") });
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
      setMessage({ ok: false, text: errorText(err, "identity.login.deleteFailed") });
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
        {item.active
          ? t("identity.login.active")
          : item.configured
            ? t("identity.login.configuredInactive")
            : t("identity.login.notConfigured")}
      </div>
      <p className="muted small">
        {t("identity.login.redirectUri")} <code>{item.redirect_uri}</code>
      </p>
      {item.provider === "entra" && (
        <div className="field">
          <label htmlFor="login-entra-tenant">{t("identity.login.tenantId")}</label>
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
          {item.provider === "entra" ? t("identity.login.entraClientId") : t("identity.login.googleClientId")}
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
        <label htmlFor={`login-${item.provider}-secret`}>{t("identity.login.secret")}</label>
        <input
          id={`login-${item.provider}-secret`}
          type="password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          autoComplete="new-password"
          placeholder={item.configured ? t("identity.login.secretKept") : ""}
          required={!item.configured}
        />
      </div>
      <div className="form-row">
        <button className="button button--primary" type="submit">
          {t("common.save")}
        </button>
        {item.configured && !item.active && (
          <button className="button" type="button" onClick={activate}>
            {t("identity.login.useProvider")}
          </button>
        )}
        {item.configured && (
          <button className="button" type="button" onClick={remove}>
            {t("common.delete")}
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
  const { t } = useTranslation();
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
  if (!items) return <p className="muted">{t("common.loading")}</p>;
  return (
    <section className="stack" data-testid="identity-login">
      <h2 className="page-title" style={{ fontSize: 18, margin: 0 }}>
        <KeyRound size={18} aria-hidden="true" /> {t("identity.login.title")}
      </h2>
      <p className="muted">
        <Trans i18nKey="identity.login.intro" components={{ strong: <strong /> }} />
      </p>
      {fixedByServer && (
        <p className="error-text" role="status" data-testid="sso-fixed-by-server">
          {t("identity.login.fixedByServer")}
        </p>
      )}
      {items.map((item) => (
        <ProviderCard key={`${item.provider}-${item.configured}-${item.active}`} item={item} onSaved={load} />
      ))}
    </section>
  );
}
