import { useCompanyLogo } from "../lib/branding";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { FileSearch, FileSignature, Fingerprint, LockKeyhole, LogIn, PenLine } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { GoogleLogo, MicrosoftLogo } from "../components/ProviderLogos";

/** Sign-in, laid out like EARE's: an introduction panel on the left, the sign-in card on the
 *  right. The SSO configured on the server is the main way in (its own provider's button); the
 *  local form — the built-in administrator and the accounts an administrator made — stays
 *  available, discreet. With no SSO, the local form is the sign-in. */
interface Options {
  sso: boolean;
  provider: "entra" | "google" | "generic" | null;
  local: boolean;
  /** The CrashTest stack: fictional accounts, say so. */
  crashtest?: boolean;
  /** CrashTest with a real SSO in front: the mock SSO (fictional people) as a second button. */
  test_sso?: boolean;
}

const SSO_BUTTONS: Record<string, { label: string; logo: ReactNode }> = {
  entra: { label: "Continuer avec Microsoft", logo: <MicrosoftLogo /> },
  google: { label: "Continuer avec Google", logo: <GoogleLogo /> },
  generic: { label: "Continuer avec le SSO", logo: <LogIn size={18} aria-hidden="true" /> },
};

function LocalForm() {
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
      setError(err instanceof ApiError ? err.message : "Connexion impossible.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="local-form">
      <label>
        Identifiant ou e-mail
        <input value={username} autoComplete="username" onChange={(e) => setUsername(e.target.value)} required />
      </label>
      <label>
        Mot de passe
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
        {busy ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  const companyLogo = useCompanyLogo();
  const [options, setOptions] = useState<Options | null>(null);
  useEffect(() => {
    api
      .get<Options>("/auth/options")
      .then(setOptions)
      .catch(() => setOptions({ sso: false, provider: null, local: true }));
  }, []);
  const button = options?.sso ? (SSO_BUTTONS[options.provider ?? "generic"] ?? SSO_BUTTONS.generic) : null;

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
              <small>Signature &amp; attestation de documents</small>
            </span>
          </div>

          <div className="auth-message">
            <h2>Signez facilement vos documents !</h2>
          </div>

          <div className="auth-foot">
            Un produit <strong>LCIT Cybersecurity</strong>
          </div>
        </aside>

        <main className="auth-form-wrap">
          <div className="auth-form-content">
            <div className="auth-company">
              {companyLogo ? (
                // The company's own logo: the LCIT name beside it would be wrong.
                <img src={companyLogo} alt="Logo" height={76} style={{ maxWidth: 220, objectFit: "contain" }} />
              ) : (
                <img src="/lcit-logo.png" alt="LCIT" width={100} height={76} />
              )}
              <div>
                {!companyLogo && <strong>LCIT Cybersecurity</strong>}
                <span>Espace de signature des collaborateurs</span>
              </div>
            </div>

            <section className="login-card">
              <span className="auth-eyebrow">ACCÈS SÉCURISÉ</span>
              <h1>Connexion</h1>
              <p>
                Connectez-vous avec votre compte pour consulter et signer les documents qui vous
                attendent.
              </p>
              {options?.crashtest && (
                <p className="auth-crashtest" data-testid="crashtest-note">
                  Environnement de test CrashTest : comptes fictifs. Identifiant = adresse e-mail,
                  mot de passe = prénom en minuscules (Bob Dupont : bob.dupont@lcit-test.local / bob).
                </p>
              )}
              {button && (
                <a
                  className="button button--primary button--block button--provider"
                  href="/api/auth/login"
                  data-testid="sso-button"
                >
                  {button.logo}
                  {button.label}
                </a>
              )}
              {options?.test_sso && (
                <a
                  className="button button--block button--provider"
                  href="/api/auth/login?test_sso=true"
                  data-testid="test-sso-button"
                >
                  <LogIn size={18} aria-hidden="true" />
                  SSO de test CrashTest (personnes fictives)
                </a>
              )}
              {options?.local && button && (
                <details className="auth-local" data-testid="local-login">
                  <summary>Connexion locale</summary>
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
                  Aucune méthode de connexion n&apos;est configurée : contactez un administrateur.
                </p>
              )}
              <p className="auth-steps" aria-hidden="true">
                <FileSearch size={14} /> consulter <PenLine size={14} /> signer{" "}
                <Fingerprint size={14} /> prouver
              </p>
            </section>

            <p className="auth-form-foot">
              <LockKeyhole size={12} aria-hidden="true" /> Espace protégé — votre mot de passe n&apos;est
              jamais saisi ici si vous passez par le SSO de votre entreprise.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
