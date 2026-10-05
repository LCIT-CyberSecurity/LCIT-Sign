import { FileSignature, LogIn } from "lucide-react";

export default function LoginPage() {
  return (
    <div className="centered-page">
      <div className="card auth-card">
        <div className="brand brand--lg">
          <FileSignature size={28} aria-hidden="true" />
          <span>LCIT Sign</span>
        </div>
        <p className="muted">
          Plateforme interne de signature et d&apos;attestation de prise de connaissance de
          documents.
        </p>
        <a className="button button--primary button--block" href="/api/auth/login">
          <LogIn size={16} aria-hidden="true" />
          Se connecter avec le SSO
        </a>
      </div>
    </div>
  );
}
