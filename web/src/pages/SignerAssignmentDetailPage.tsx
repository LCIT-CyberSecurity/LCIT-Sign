import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Download, FileCheck } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { MyAssignment, PublicConfig, SignatureSummary } from "../api/types";

export default function SignerAssignmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [assignment, setAssignment] = useState<MyAssignment | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [consentChecked, setConsentChecked] = useState(false);
  const [signing, setSigning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signature, setSignature] = useState<SignatureSummary | null>(null);

  const load = () => {
    api.get<MyAssignment[]>("/me/assignments").then((all) => {
      const found = all.find((a) => a.id === id) ?? null;
      setAssignment(found);
    });
  };

  useEffect(() => {
    load();
    api.get<PublicConfig>("/config").then(setConfig);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!assignment) return <p className="muted">Chargement…</p>;

  const isSigned = assignment.status === "SIGNED";
  const contentUrl = `/api/documents/versions/${assignment.document_version_id}/content`;

  const sign = async () => {
    setSigning(true);
    setError(null);
    try {
      const result = await api.post<SignatureSummary>(
        `/documents/versions/${assignment.document_version_id}/sign`,
        { consent: true },
      );
      setSignature(result);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "La signature a échoué.");
    } finally {
      setSigning(false);
    }
  };

  return (
    <div className="stack">
      <Link to="/" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> Retour
      </Link>

      <h1 className="page-title">{assignment.document_title}</h1>
      <p className="muted">
        Version {assignment.version_label} — {assignment.campaign_name}
      </p>

      <div className="pdf-viewer">
        <iframe title={assignment.document_title} src={contentUrl} />
      </div>

      {isSigned || signature ? (
        <div className="card card--success">
          <div className="card-title">
            <FileCheck size={18} aria-hidden="true" /> Document signé
          </div>
          {signature && (
            <p className="muted">
              Identifiant : <strong data-testid="signature-id">{signature.display_id}</strong>
            </p>
          )}
          <div className="button-row">
            <a
              className="button button--secondary"
              href={
                signature
                  ? `/api/signatures/${signature.id}/signed-pdf`
                  : `/api/signatures/${assignment.signature_id}/signed-pdf`
              }
            >
              <Download size={14} aria-hidden="true" /> PDF signé
            </a>
            <a
              className="button button--secondary"
              href={
                signature
                  ? `/api/signatures/${signature.id}/certificate`
                  : `/api/signatures/${assignment.signature_id}/certificate`
              }
            >
              <Download size={14} aria-hidden="true" /> Certificat
            </a>
          </div>
        </div>
      ) : (
        <div className="card">
          <label className="consent-row">
            <input
              type="checkbox"
              checked={consentChecked}
              onChange={(e) => setConsentChecked(e.target.checked)}
            />
            <span>{config?.consent_text ?? "J'atteste avoir pris connaissance de ce document."}</span>
          </label>
          {error && <p className="error-text">{error}</p>}
          <button
            className="button button--primary"
            disabled={!consentChecked || signing}
            onClick={sign}
          >
            {signing ? "Signature en cours…" : "Signer"}
          </button>
        </div>
      )}
    </div>
  );
}
