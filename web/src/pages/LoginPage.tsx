import { useCompanyLogo } from "../lib/branding";
import { useEffect, useState, type FormEvent } from "react";
import { FileSearch, FileSignature, Fingerprint, LockKeyhole, LogIn, PenLine } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** Sign-in, laid out like EARE's: an introduction panel on the left, the
 *  sign-in card on the right. SSO is the only way in — there is no password. */
/** The built-in system account form: only when the server says it is enabled. */
function LocalLogin() {
  const { refresh } = useAuth();
  const [username, setUsername] = useState("admin");
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
    <details className="auth-local" data-testid="local-login">
      <summary>Compte système (administrateur local)</summary>
      <form onSubmit={submit}>
        <label>
          Identifiant
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
    </details>
  );
}

export default function LoginPage() {
  const companyLogo = useCompanyLogo();
  const [localEnabled, setLocalEnabled] = useState(false);
  useEffect(() => {
    api
      .get<{ local: boolean }>("/auth/options")
      .then((o) => setLocalEnabled(o.local))
      .catch(() => setLocalEnabled(false));
  }, []);

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
                Connectez-vous avec votre compte d&apos;entreprise pour consulter et signer les
                documents qui vous attendent.
              </p>
              <a className="button button--primary button--block" href="/api/auth/login">
                <LogIn size={18} aria-hidden="true" />
                Se connecter avec le SSO
              </a>
              {localEnabled && <LocalLogin />}
              <p className="auth-steps" aria-hidden="true">
                <FileSearch size={14} /> consulter <PenLine size={14} /> signer{" "}
                <Fingerprint size={14} /> prouver
              </p>
            </section>

            <p className="auth-form-foot">
              <LockKeyhole size={12} aria-hidden="true" /> Espace protégé — aucun mot de passe n&apos;est
              saisi ici : l&apos;authentification est gérée par votre fournisseur d&apos;identité.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
