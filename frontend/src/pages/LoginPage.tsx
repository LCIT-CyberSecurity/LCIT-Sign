import { useCompanyLogo } from "../lib/branding";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Trans, useTranslation } from "react-i18next";
import { FileSearch, FileSignature, Fingerprint, LockKeyhole, LogIn, PenLine } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import { useAuth } from "../auth/AuthContext";
import { GoogleLogo, MicrosoftLogo } from "../components/ProviderLogos";

/** Sign-in, laid out like EARE's: an introduction panel on the left, the sign-in card on the
 *  right. The ONE SSO in use is the main way in (its own provider's button); the
 *  local form — the built-in administrator and the accounts an administrator made — stays
 *  available, discreet. With no SSO, the local form is the sign-in. */
interface Options {
  sso: boolean;
  provider: "entra" | "google" | "generic" | null;
  local: boolean;
  /** The CrashTest stack: fictional accounts, say so. */
  crashtest?: boolean;
}

const SSO_BUTTONS: Record<string, { labelKey: string; logo: ReactNode }> = {
  entra: { labelKey: "auth.continueMicrosoft", logo: <MicrosoftLogo /> },
  google: { labelKey: "auth.continueGoogle", logo: <GoogleLogo /> },
  generic: { labelKey: "auth.continueSso", logo: <LogIn size={18} aria-hidden="true" /> },
};

function LocalForm() {
  const { t } = useTranslation();
  const { refresh } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/local-login", { username, password });
      await refresh();
    } catch (err) {
      setError(errorText(err, "auth.loginFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="local-form">
      <label>
        {t("auth.username")}
        <input value={username} autoComplete="username" onChange={(e) => setUsername(e.target.value)} required />
      </label>
      <label>
        {t("auth.password")}
        <input
          type="password"
          value={password}
          autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button button--secondary" type="submit" disabled={busy}>
        {busy ? t("auth.signingIn") : t("auth.signIn")}
      </button>
    </form>
  );
}

export default function LoginPage() {
  const { t } = useTranslation();
  const companyLogo = useCompanyLogo();
  const [options, setOptions] = useState<Options | null>(null);
  useEffect(() => {
    api
      .get<Options>("/auth/options")
      .then(setOptions)
      .catch(() => setOptions({ sso: false, provider: null, local: true }));
  }, []);
  // A single SSO: the provider in use, or none (then the local form is the sign-in).
  const sso = options?.sso ? (SSO_BUTTONS[options.provider ?? "generic"] ?? SSO_BUTTONS.generic) : null;
  const button = sso !== null;

  return (
    <div className="login-page">
      <div className="auth-layout">
        <aside className="auth-intro">
          <div className="auth-product">
            <span className="auth-product-icon">
              <FileSignature size={22} strokeWidth={1.8} aria-hidden="true" />
            </span>
            <span>
              <strong>LCIT SIGN</strong>
              <small>{t("auth.product")}</small>
            </span>
          </div>

          <div className="auth-message">
            <h2>{t("auth.headline")}</h2>
          </div>

          <div className="auth-foot">
            <Trans i18nKey="auth.madeBy" components={{ strong: <strong /> }} />
          </div>
        </aside>

        <main className="auth-form-wrap">
          <div className="auth-form-content">
            <div className="auth-company">
              {companyLogo ? (
                // The company's own logo: the LCIT name beside it would be wrong.
                <img src={companyLogo} alt={t("shell.logoAlt")} height={76} style={{ maxWidth: 220, objectFit: "contain" }} />
              ) : (
                <img src="/lcit-logo.png" alt="LCIT" width={100} height={76} />
              )}
              <div>
                {!companyLogo && <strong>LCIT Cybersecurity</strong>}
                <span>{t("auth.employeeSpace")}</span>
              </div>
            </div>

            <section className="login-card">
              <span className="auth-eyebrow">{t("auth.eyebrow")}</span>
              <h1>{t("auth.title")}</h1>
              <p>{t("auth.intro")}</p>
              {options?.crashtest && (
                <p className="auth-crashtest" data-testid="crashtest-note">
                  {t("auth.crashtest")}
                </p>
              )}
              {sso && (
                <a
                  className="button button--primary button--block button--provider"
                  href="/api/auth/login"
                  data-testid="sso-button"
                >
                  {sso.logo}
                  {t(sso.labelKey)}
                </a>
              )}
              {options?.local && button && (
                <details className="auth-local" data-testid="local-login">
                  <summary>{t("auth.localLogin")}</summary>
                  <LocalForm />
                </details>
              )}
              {options?.local && !button && (
                <div className="auth-local auth-local--main" data-testid="local-login">
                  <LocalForm />
                </div>
              )}
              {options && !options.local && !button && (
                <p className="form-error" role="alert">
                  {t("auth.noMethod")}
                </p>
              )}
              <p className="auth-steps" aria-hidden="true">
                <FileSearch size={14} /> {t("auth.stepView")} <PenLine size={14} /> {t("auth.stepSign")}{" "}
                <Fingerprint size={14} /> {t("auth.stepProve")}
              </p>
            </section>

            <p className="auth-form-foot">
              <LockKeyhole size={12} aria-hidden="true" /> {t("auth.protected")}
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
