import { useState } from "react";
import { Link } from "react-router-dom";
import { FileText, PencilRuler, Upload, X } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConfirmButton from "./ConfirmButton";
import UploadDropzone from "./UploadDropzone";
import type { Campaign, DocumentDetail } from "../api/types";

/** "charte_informatique-2026.pdf" -> "Charte informatique 2026". */
export function deriveTitle(fileName: string): string {
  const base = fileName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : "Document";
}

/** What the campaign asks people to sign: drop one or several PDFs right here,
 *  prepare each one (where each person signs, dates, text…), nothing else to publish —
 *  the launch freezes them. */
export default function CampaignDocuments({
  campaign,
  library,
  onChanged,
}: {
  campaign: Campaign;
  library: DocumentDetail[] | null;
  onChanged: () => void;
}) {
  const [pending, setPending] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [existing, setExisting] = useState("");
  const [error, setError] = useState<string | null>(null);

  const hasSigners = campaign.roles.length > 0;
  const inCampaign = new Set(campaign.documents.map((d) => d.version_id));
  const reusable = (library ?? [])
    .flatMap((doc) =>
      doc.versions
        .filter((v) => (v.status === "DRAFT" || v.status === "PUBLISHED") && !inCampaign.has(v.id))
        .map((v) => ({ id: v.id, label: `${doc.title} — v${v.version_label}` })),
    )
    .sort((a, b) => a.label.localeCompare(b.label, "fr", { sensitivity: "base", numeric: true }));

  const stage = (files: File[]) => {
    setNotes([]);
    setPending((current) => [
      ...current,
      ...files.filter((f) => !current.some((c) => c.name === f.name && c.size === f.size)),
    ]);
  };

  const importAll = async () => {
    setBusy(true);
    setError(null);
    const messages: string[] = [];
    for (const file of pending) {
      if (!/\.pdf$/i.test(file.name)) {
        messages.push(`${file.name} : seuls les PDF sont acceptés pour le moment.`);
        continue;
      }
      try {
        const form = new FormData();
        form.append("title", deriveTitle(file.name));
        form.append("version_label", "1.0");
        form.append("file", file);
        const created = await api.postForm<DocumentDetail>("/documents", form);
        await api.post(`/campaigns/${campaign.id}/documents`, {
          document_version_id: created.versions[0].id,
        });
      } catch (err) {
        messages.push(`${file.name} : ${err instanceof ApiError ? err.message : "l'envoi a échoué."}`);
      }
    }
    setPending([]);
    setNotes(messages);
    setBusy(false);
    onChanged();
  };

  const addExisting = async () => {
    if (!existing) return;
    setError(null);
    try {
      await api.post(`/campaigns/${campaign.id}/documents`, { document_version_id: existing });
      setExisting("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "L'ajout a échoué.");
    }
  };

  return (
    <div className="card" data-testid="campaign-documents">
      <div className="card-title">2. Quoi faire signer ?</div>
      <p className="muted small">
        Déposez un ou plusieurs PDF, puis « Préparer » chacun : vous placez la signature, la date, le nom…
        pour chaque personne de la liste ci-dessus.
      </p>

      {campaign.documents.length === 0 && <p className="muted small">Aucun document pour le moment.</p>}
      <ul className="plain-list">
        {campaign.documents.map((d) => (
          <li key={d.version_id} className="report-row" data-testid={`campaign-doc-${d.title}`}>
            <span>
              <FileText size={14} aria-hidden="true" /> <strong>{d.title}</strong>{" "}
              <span className="muted small">
                v{d.version_label} —{" "}
                {d.elements > 0 ? `${d.elements} élément(s) placé(s)` : "aucun élément placé"}
              </span>
            </span>
            <span className="row-actions">
              {hasSigners ? (
                <Link
                  className="button button--secondary button--sm"
                  to={`/documents/versions/${d.version_id}/prepare?campaign=${campaign.id}`}
                >
                  <PencilRuler size={14} aria-hidden="true" /> Préparer
                </Link>
              ) : (
                <span className="muted small">Choisissez d&apos;abord qui signe</span>
              )}
              <ConfirmButton
                confirmLabel="Retirer de la campagne"
                onConfirm={async () => {
                  await api.del(`/campaigns/${campaign.id}/documents/${d.version_id}`);
                  onChanged();
                }}
              >
                Retirer
              </ConfirmButton>
            </span>
          </li>
        ))}
      </ul>

      <UploadDropzone onFiles={stage} disabled={busy} hint="PDF, plusieurs à la fois" />
      {pending.length > 0 && (
        <div className="stack" data-testid="pending-files">
          <ul className="upload-results">
            {pending.map((file, i) => (
              <li key={`${file.name}-${i}`}>
                <FileText size={14} aria-hidden="true" />
                <strong>{file.name}</strong>
                <button
                  type="button"
                  className="button button--ghost button--sm"
                  aria-label={`Retirer ${file.name}`}
                  onClick={() => setPending(pending.filter((_, j) => j !== i))}
                >
                  <X size={13} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
          <div className="row-actions">
            <button type="button" className="button" disabled={busy} onClick={() => void importAll()}>
              <Upload size={14} aria-hidden="true" /> Ajouter {pending.length > 1 ? `${pending.length} documents` : "le document"}
            </button>
            <button type="button" className="button button--ghost" onClick={() => setPending([])}>
              Annuler
            </button>
          </div>
        </div>
      )}
      {notes.length > 0 && (
        <ul className="upload-results" role="alert">
          {notes.map((n) => (
            <li key={n} className="status-error">
              {n}
            </li>
          ))}
        </ul>
      )}

      {reusable.length > 0 && (
        <div className="form-row">
          <select aria-label="Document existant" value={existing} onChange={(e) => setExisting(e.target.value)}>
            <option value="">Ou reprendre un document déjà déposé…</option>
            {reusable.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
          <button className="button button--secondary" onClick={() => void addExisting()} disabled={!existing}>
            Ajouter
          </button>
        </div>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
