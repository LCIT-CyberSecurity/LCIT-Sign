import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Download, FileCheck } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { MyAssignment, PublicConfig, SignatureSummary } from "../api/types";

interface FormField {
  id: string;
  kind: string;
  label: string;
  required: boolean;
  group_key: string | null;
  page: number;
}

interface SigningForm {
  inputs: FormField[];
  automatic: FormField[];
}

const AUTO_LABELS: Record<string, string> = {
  SIGNATURE: "votre signature",
  DATE: "la date de signature",
  FULL_NAME: "votre nom",
  EMAIL: "votre e-mail",
  LOGO: "le logo de l'entreprise",
};

// Always listed in this order, whatever order the operator placed them in.
const AUTO_ORDER = ["SIGNATURE", "FULL_NAME", "EMAIL", "DATE", "LOGO"];

/** One input per group: fields that share a key are typed once and apply to all. */
export function groupInputs(inputs: FormField[]) {
  const groups = new Map<string, { key: string; label: string; required: boolean; ids: string[] }>();
  for (const f of inputs) {
    const key = f.group_key ? `g:${f.group_key}` : `f:${f.id}`;
    const existing = groups.get(key);
    if (existing) {
      existing.ids.push(f.id);
      existing.required = existing.required || f.required;
    } else {
      groups.set(key, { key, label: f.label || "Texte", required: f.required, ids: [f.id] });
    }
  }
  return [...groups.values()];
}

export default function SignerAssignmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [assignment, setAssignment] = useState<MyAssignment | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [consentChecked, setConsentChecked] = useState(false);
  const [signing, setSigning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signature, setSignature] = useState<SignatureSummary | null>(null);
  const [form, setForm] = useState<SigningForm | null>(null);
  const [typed, setTyped] = useState<Record<string, string>>({});

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

  const versionId = assignment?.document_version_id;
  const alreadySigned = assignment?.status === "SIGNED";
  useEffect(() => {
    if (!versionId || alreadySigned) return;
    api
      .get<SigningForm>(`/documents/versions/${versionId}/signing-form`)
      .then((r) => setForm({ inputs: r.inputs ?? [], automatic: r.automatic ?? [] }))
      .catch(() => setForm(null));
  }, [versionId, alreadySigned]);

  if (!assignment) return <p className="muted">Chargement…</p>;

  const inputGroups = groupInputs(form?.inputs ?? []);
  const missing = inputGroups.some((g) => g.required && !(typed[g.key] ?? "").trim());

  const isSigned = assignment.status === "SIGNED";
  // What this person is shown is what they sign: the document with what the signers before them
  // put on it, and once signed, their own signed copy. The address changes when they sign, so the
  // frame is loaded again.
  const contentUrl = `/api/assignments/${assignment.id}/preview?v=${
    signature?.id ?? assignment.signature_id ?? "pending"
  }`;

  const sign = async () => {
    setSigning(true);
    setError(null);
    try {
      const result = await api.post<SignatureSummary>(
        `/documents/versions/${assignment.document_version_id}/sign`,
        {
          consent: true,
          // The request being signed: the same document may be asked by several campaigns.
          campaign_id: assignment.campaign_id,
          values: Object.fromEntries(
            inputGroups.flatMap((g) => g.ids.map((fieldId) => [fieldId, (typed[g.key] ?? "").trim()])),
          ),
        },
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
            <Link
              className="button button--primary"
              to={`/signatures/${signature ? signature.id : assignment.signature_id}`}
            >
              Voir ma signature et vérifier
            </Link>
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
        <div className="card stack" style={{ gap: 16 }}>
          <div className="signature-preview" aria-label="Aperçu de votre signature">
            <span className="signature-preview__label">Aperçu de votre signature</span>
            <span className="signature-preview__name" data-testid="signature-preview-name">
              {user?.display_name}
            </span>
            <span className="signature-preview__meta">Signé avec LCIT Sign</span>
            <div className="signature-preview__fields">
              <span>
                Signataire : <strong>{user?.display_name}</strong>
              </span>
              <span>
                E-mail : <strong>{user?.email}</strong>
              </span>
              <span>
                Date : <strong>à l&apos;instant de la signature</strong>
              </span>
            </div>
          </div>
          {inputGroups.length > 0 && (
            <div className="stack" style={{ gap: 10 }} data-testid="signing-inputs">
              <div className="field-label">À renseigner avant de signer</div>
              {inputGroups.map((g) => (
                <label key={g.key}>
                  {g.label}
                  {g.required ? " *" : " (facultatif)"}
                  <input
                    value={typed[g.key] ?? ""}
                    maxLength={500}
                    onChange={(e) => setTyped({ ...typed, [g.key]: e.target.value })}
                  />
                </label>
              ))}
            </div>
          )}
          {(form?.automatic.length ?? 0) > 0 && (
            <p className="muted small">
              Seront apposés automatiquement sur le document :{" "}
              {[...new Set(form?.automatic.map((f) => f.kind))]
                .sort((a, b) => AUTO_ORDER.indexOf(a) - AUTO_ORDER.indexOf(b))
                .map((kind) => AUTO_LABELS[kind] ?? kind)
                .join(", ")}.
            </p>
          )}
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
            disabled={!consentChecked || signing || missing}
            onClick={sign}
          >
            {signing ? "Signature en cours…" : "Signer"}
          </button>
        </div>
      )}
    </div>
  );
}
