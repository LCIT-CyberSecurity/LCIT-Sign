import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BadgeCheck, Download, FileText, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { SignatureChain, SignatureDetail, VerificationResult } from "../api/types";

export const CHECK_LABELS: Record<string, string> = {
  original_document_hash: "Le document original est intact",
  signed_document_hash: "Le PDF signé est intact",
  evidence_hash: "La preuve n'a pas été modifiée",
  cryptographic_signature: "La signature cryptographique est valide",
  signing_key_trusted: "La clé de signature est digne de confiance",
  metadata_consistent: "Les métadonnées sont cohérentes",
};

/** One signature: the signed PDF itself, what was signed, by whom and when, the
 *  downloads, and an on-demand integrity check. Reachable by the signer and,
 *  for follow-up, by operators and administrators. */
export default function SignatureDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [signature, setSignature] = useState<SignatureDetail | null>(null);
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [chain, setChain] = useState<SignatureChain | null>(null);
  const { hasRole } = useAuth();
  const staff = hasRole("PREPARER") || hasRole("OPERATOR") || hasRole("ADMIN");

  useEffect(() => {
    api
      .get<SignatureDetail>(`/signatures/${id}`)
      .then(setSignature)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Signature introuvable."));
  }, [id]);

  useEffect(() => {
    api
      .get<SignatureChain>(`/signatures/${id}/chain`)
      .then(setChain)
      .catch(() => setChain(null));
  }, [id]);

  const verify = async () => {
    setVerifying(true);
    setError(null);
    try {
      setResult(await api.get<VerificationResult>(`/signatures/${id}/verify`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "La vérification a échoué.");
    } finally {
      setVerifying(false);
    }
  };

  if (error && !signature) return <p className="error-text">{error}</p>;
  if (!signature) return <p className="muted">Chargement…</p>;

  return (
    <div className="stack">
      <Link to="/" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> Mes signatures
      </Link>
      <h1 className="page-title">
        <FileText size={22} aria-hidden="true" /> {signature.document_title}
        <span className="badge badge--signed">Signé</span>
      </h1>
      <p className="page-subtitle">
        Version {signature.version_label}
        {signature.campaign_name ? ` — ${signature.campaign_name}` : ""}
      </p>

      <div className="split">
        <div className="pdf-viewer">
          <iframe
            title={`PDF signé — ${signature.document_title}`}
            src={`/api/signatures/${signature.id}/signed-pdf?inline=true`}
          />
        </div>

        <div className="stack">
          {chain && (
            <section className="card" data-testid="signature-chain">
              <div className="card-title">Qui a signé ce document ?</div>
              <ol className="chain">
                {chain.steps.map((step) => (
                  <li key={`${step.role}-${step.email}`} className={step.mine ? "chain__me" : undefined}>
                    <span className={step.status === "SIGNED" ? "status-ok" : "muted"} aria-hidden="true">
                      {step.status === "SIGNED" ? "✓" : "…"}
                    </span>
                    <span>
                      <strong>{step.name}</strong>
                      {step.mine ? " (vous)" : ""}
                      <span className="muted small">
                        {" "}
                        —{" "}
                        {step.status === "SIGNED" && step.signed_at
                          ? `a signé le ${new Date(step.signed_at).toLocaleString("fr-FR")}`
                          : step.status === "WAITING"
                            ? "pas encore son tour"
                            : "doit encore signer"}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
              {chain.others && (
                <p className="muted small" data-testid="chain-others">
                  {chain.others.count} autre(s) destinataire(s), dont {chain.others.signed} ont signé.
                </p>
              )}
              <p className="muted small">
                {chain.complete
                  ? "Tout le monde a signé."
                  : "Il reste des signatures à recueillir."}{" "}
                Ce PDF est <strong>votre exemplaire</strong> : il porte les signatures de ceux qui ont signé
                avant vous.
                {staff && (
                  <>
                    {" "}
                    Toute la campagne se suit dans <Link to="/campaigns?tab=signed">Suivi</Link>.
                  </>
                )}
              </p>
            </section>
          )}

          <section className="card">
            <div className="card-title">Signature</div>
            <dl className="kv">
              <dt>Identifiant</dt>
              <dd className="mono" data-testid="signature-id">
                {signature.display_id}
              </dd>
              <dt>Signataire</dt>
              <dd>
                {signature.display_name_snapshot}
                <div className="muted small">{signature.email_snapshot}</div>
              </dd>
              <dt>Date</dt>
              <dd>{new Date(signature.signed_at_utc).toLocaleString("fr-FR")}</dd>
              <dt>Empreinte du PDF signé</dt>
              <dd className="mono">{signature.signed_file_sha256}</dd>
              <dt>Clé de signature</dt>
              <dd className="mono">{signature.signing_key_id}</dd>
            </dl>
            <div className="button-row" style={{ marginTop: 16 }}>
              <a className="button button--secondary button--sm" href={`/api/signatures/${signature.id}/signed-pdf`}>
                <Download size={14} aria-hidden="true" /> PDF signé
              </a>
              <a className="button button--secondary button--sm" href={`/api/signatures/${signature.id}/certificate`}>
                <Download size={14} aria-hidden="true" /> Certificat
              </a>
              <a className="button button--secondary button--sm" href={`/api/signatures/${signature.id}/evidence`}>
                <Download size={14} aria-hidden="true" /> Preuve (JSON)
              </a>
            </div>
          </section>

          <section className="card">
            <div className="card-title">
              <BadgeCheck size={16} aria-hidden="true" /> Vérification d&apos;intégrité
            </div>
            <p className="muted small">
              Recalcule les empreintes du document et de la preuve et contrôle la signature cryptographique.
            </p>
            <button className="button button--primary" onClick={verify} disabled={verifying}>
              <ShieldCheck size={14} aria-hidden="true" /> {verifying ? "Vérification…" : "Vérifier maintenant"}
            </button>
            {error && <p className="error-text">{error}</p>}
            {result && (
              <div className="stack" style={{ marginTop: 16, gap: 12 }}>
                <div className={`verdict ${result.valid ? "verdict--ok" : "verdict--ko"}`} role="status">
                  {result.valid ? <ShieldCheck size={18} /> : <ShieldAlert size={18} />}
                  {result.valid ? "Signature valide" : "Intégrité invalide"}
                </div>
                <ul className="check-list">
                  {Object.entries(result.checks).map(([name, passed]) => (
                    <li key={name}>
                      <span className={passed ? "status-ok" : "status-error"}>{passed ? "✓" : "✕"}</span>
                      {CHECK_LABELS[name] ?? name}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
