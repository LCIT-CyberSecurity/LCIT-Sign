import { FileSearch, FileSignature, Fingerprint, LockKeyhole, LogIn, PenLine } from "lucide-react";

/** Sign-in, laid out like EARE's: an introduction panel on the left, the
 *  sign-in card on the right. SSO is the only way in — there is no password. */
export default function LoginPage() {
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
            <span className="auth-eyebrow">SIGNATURE INTERNE</span>
            <h2>
              Chaque document lu,
              <br />
              <em>signé et prouvé.</em>
            </h2>
            <p>
              Diffusez vos chartes et politiques, recueillez la signature de chaque collaborateur
              et conservez une preuve vérifiable : qui a signé quoi, quelle version, quand.
            </p>
          </div>

          <div className="auth-process">
            <div>
              <span>01</span>
              <strong>Consulter</strong>
              <small>Lire la version exacte du document</small>
            </div>
            <div>
              <span>02</span>
              <strong>Signer</strong>
              <small>Un acte volontaire, avec votre identité SSO</small>
            </div>
            <div>
              <span>03</span>
              <strong>Prouver</strong>
              <small>Empreinte, signature cryptographique, audit</small>
            </div>
          </div>

          <div className="auth-foot">
            Un produit <strong>LCIT Cybersecurity</strong>
          </div>
        </aside>

        <main className="auth-form-wrap">
          <div className="auth-form-content">
            <div className="auth-company">
              <img src="/lcit-logo.png" alt="LCIT" width={100} height={76} />
              <div>
                <strong>LCIT Cybersecurity</strong>
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
