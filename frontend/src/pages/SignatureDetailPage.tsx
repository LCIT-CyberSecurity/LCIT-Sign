import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BadgeCheck, Download, FileText, ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import i18n from "../i18n";
import { errorText } from "../i18n/errors";
import { assignmentStatus } from "../i18n/enums";
import { formatDateTime } from "../i18n/format";
import { useAuth } from "../auth/AuthContext";
import type { SignatureChain, SignatureDetail, VerificationResult } from "../api/types";

/** What each integrity check says, in the active language (a check this build does not know is
 *  shown under its own name). */
const checkLabel = (name: string) =>
  i18n.exists(`signatureDetail.checks.${name}`) ? i18n.t(`signatureDetail.checks.${name}`) : name;

/** One signature: the signed PDF itself, what was signed, by whom and when, the
 *  downloads, and an on-demand integrity check. Reachable by the signer and,
 *  for follow-up, by operators and administrators. */
export default function SignatureDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [signature, setSignature] = useState<SignatureDetail | null>(null);
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [chain, setChain] = useState<SignatureChain | null>(null);
  const { hasRole } = useAuth();
  const staff = hasRole("SIGNER") || hasRole("OPERATOR") || hasRole("ADMIN");

  useEffect(() => {
    api
      .get<SignatureDetail>(`/signatures/${id}`)
      .then(setSignature)
      .catch((err) => setError(errorText(err, "signatureDetail.notFound")));
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
      setError(errorText(err, "signatureDetail.verifyFailed"));
    } finally {
      setVerifying(false);
    }
  };

  if (error && !signature) return <p className="error-text">{error}</p>;
  if (!signature) return <p className="muted">{t("common.loading")}</p>;

  return (
    <div className="stack">
      <Link to="/" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> {t("nav.mySignatures")}
      </Link>
      <h1 className="page-title">
        <FileText size={22} aria-hidden="true" /> {signature.document_title}
        <span className="badge badge--signed">{assignmentStatus("SIGNED")}</span>
      </h1>
      <p className="page-subtitle">
        {t("signatureDetail.subtitle", {
          version: signature.version_label,
          campaign: signature.campaign_name ? ` — ${signature.campaign_name}` : "",
        })}
      </p>

      <div className="split">
        <div className="pdf-viewer">
          <iframe
            title={t("signatureDetail.pdfTitle", { title: signature.document_title })}
            src={`/api/signatures/${signature.id}/signed-pdf?inline=true`}
          />
        </div>

        <div className="stack">
          {chain && (
            <section className="card" data-testid="signature-chain">
              <div className="card-title">{t("signatureDetail.whoSigned")}</div>
              <ol className="chain">
                {chain.steps.map((step) => (
                  <li key={`${step.role}-${step.email}`} className={step.mine ? "chain__me" : undefined}>
                    <span className={step.status === "SIGNED" ? "status-ok" : "muted"} aria-hidden="true">
                      {step.status === "SIGNED" ? "✓" : "…"}
                    </span>
                    <span>
                      <strong>{step.name}</strong>
                      {step.mine ? ` ${t("signatureDetail.you")}` : ""}
                      <span className="muted small">
                        {" "}
                        —{" "}
                        {step.status === "SIGNED" && step.signed_at
                          ? t("signatureDetail.signedOn", { date: formatDateTime(step.signed_at) })
                          : step.status === "WAITING"
                            ? t("signatureDetail.notYetTurn")
                            : t("signatureDetail.mustSign")}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
              {chain.others && (
                <p className="muted small" data-testid="chain-others">
                  {t("signatureDetail.others", { count: chain.others.count, signed: chain.others.signed })}
                </p>
              )}
              <p className="muted small">
                {chain.complete ? t("signatureDetail.everyoneSigned") : t("signatureDetail.signaturesRemain")}{" "}
                <Trans i18nKey="signatureDetail.yourCopy" components={{ strong: <strong /> }} />
                {staff && (
                  <>
                    {" "}
                    <Trans i18nKey="signatureDetail.trackCampaign" components={{ view: <Link to="/campaigns?tab=signed" /> }} />
                  </>
                )}
              </p>
            </section>
          )}

          <section className="card">
            <div className="card-title">{t("signatureDetail.signature")}</div>
            <dl className="kv">
              <dt>{t("signatureDetail.id")}</dt>
              <dd className="mono" data-testid="signature-id">
                {signature.display_id}
              </dd>
              <dt>{t("signatureDetail.signer")}</dt>
              <dd>
                {signature.display_name_snapshot}
                <div className="muted small">{signature.email_snapshot}</div>
              </dd>
              <dt>{t("signatureDetail.date")}</dt>
              <dd>{formatDateTime(signature.signed_at_utc)}</dd>
              <dt>{t("signatureDetail.pdfHash")}</dt>
              <dd className="mono">{signature.signed_file_sha256}</dd>
              <dt>{t("signatureDetail.signingKey")}</dt>
              <dd className="mono">{signature.signing_key_id}</dd>
            </dl>
            <div className="button-row" style={{ marginTop: 16 }}>
              <a className="button button--secondary button--sm" href={`/api/signatures/${signature.id}/signed-pdf`}>
                <Download size={14} aria-hidden="true" /> {t("assignments.signedPdf")}
              </a>
              <a className="button button--secondary button--sm" href={`/api/signatures/${signature.id}/certificate`}>
                <Download size={14} aria-hidden="true" /> {t("signing.certificate")}
              </a>
              <a className="button button--secondary button--sm" href={`/api/signatures/${signature.id}/evidence`}>
                <Download size={14} aria-hidden="true" /> {t("signatureDetail.evidenceJson")}
              </a>
            </div>
          </section>

          <section className="card">
            <div className="card-title">
              <BadgeCheck size={16} aria-hidden="true" /> {t("signatureDetail.integrity")}
            </div>
            <p className="muted small">
              {t("signatureDetail.integrityHelp")}
            </p>
            <button className="button button--primary" onClick={verify} disabled={verifying}>
              <ShieldCheck size={14} aria-hidden="true" /> {verifying ? t("diagnostics.checking") : t("signatureDetail.verifyNow")}
            </button>
            {error && <p className="error-text">{error}</p>}
            {result && (
              <div className="stack" style={{ marginTop: 16, gap: 12 }}>
                <div className={`verdict ${result.valid ? "verdict--ok" : "verdict--ko"}`} role="status">
                  {result.valid ? <ShieldCheck size={18} /> : <ShieldAlert size={18} />}
                  {result.valid ? t("signatureDetail.valid") : t("signatureDetail.invalid")}
                </div>
                <ul className="check-list">
                  {Object.entries(result.checks).map(([name, passed]) => (
                    <li key={name}>
                      <span className={passed ? "status-ok" : "status-error"}>{passed ? "✓" : "✕"}</span>
                      {checkLabel(name)}
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
