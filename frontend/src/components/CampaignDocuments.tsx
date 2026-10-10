import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { FileText, PencilRuler, Upload, X } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import { collator } from "../i18n/format";
import ConfirmButton from "./ConfirmButton";
import UploadDropzone from "./UploadDropzone";
import { documentHint, documentRefused, isAcceptedDocument } from "../lib/uploads";
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
  active = false,
  showPrepare = true,
  onImported,
}: {
  campaign: Campaign;
  library: DocumentDetail[] | null;
  onChanged: () => void;
  /** The campaign is already sent: a document added now is prepared, then sent on its own. */
  active?: boolean;
  /** Offer "Préparer" on each document (not in the wizard, where preparing is a step of its own). */
  showPrepare?: boolean;
  /** Called after a drop was imported, instead of opening the editor. */
  onImported?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
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
    .sort((a, b) => collator().compare(a.label, b.label));

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
    const created: string[] = [];
    for (const file of pending) {
      if (!isAcceptedDocument(file.name)) {
        messages.push(t("campaignDocs.fileError", { name: file.name, message: documentRefused() }));
        continue;
      }
      try {
        const form = new FormData();
        form.append("title", deriveTitle(file.name));
        form.append("version_label", "1.0");
        form.append("file", file);
        const document = await api.postForm<DocumentDetail>("/documents", form);
        await api.post(`/campaigns/${campaign.id}/documents`, {
          document_version_id: document.versions[0].id,
        });
        created.push(document.versions[0].id);
      } catch (err) {
        messages.push(
          t("campaignDocs.fileError", { name: file.name, message: errorText(err, "campaignDocs.uploadFailed") }),
        );
      }
    }
    setPending([]);
    setNotes(messages);
    setBusy(false);
    onChanged();
    if (created.length > 0 && messages.length === 0) {
      // On to placing the elements: that is the next thing to do.
      if (onImported) onImported();
      else if (hasSigners) navigate(`/documents/versions/${created[0]}/prepare?campaign=${campaign.id}`);
    }
  };

  const addExisting = async () => {
    if (!existing) return;
    setError(null);
    try {
      await api.post(`/campaigns/${campaign.id}/documents`, { document_version_id: existing });
      setExisting("");
      onChanged();
    } catch (err) {
      setError(errorText(err, "campaignDocs.addFailed"));
    }
  };

  return (
    <div className="card" data-testid="campaign-documents">
      <div className="card-title">{t("campaignDocs.title")}</div>
      <p className="muted small">
        {showPrepare ? t("campaignDocs.helpPrepare") : t("campaignDocs.helpWizard")}
      </p>

      {campaign.documents.length === 0 && <p className="muted small">{t("campaignDocs.none")}</p>}
      <ul className="plain-list">
        {campaign.documents.map((d) => (
          <li key={d.version_id} className="report-row" data-testid={`campaign-doc-${d.title}`}>
            <span>
              <FileText size={14} aria-hidden="true" /> <strong>{d.title}</strong>{" "}
              <span className="muted small">
                v{d.version_label} —{" "}
                {d.elements > 0 ? t("counts.elementsPlaced", { count: d.elements }) : ""}
              </span>
              {active && d.released && <span className="badge badge--signed">{t("campaignDocs.sent")}</span>}
              {showPrepare && !(active && d.released) && d.elements === 0 && (
                <span className="badge badge--pending" data-testid="to-prepare">
                  {t("campaignDocs.toPrepare")}
                </span>
              )}
            </span>
            <span className="row-actions">
              {!showPrepare || (active && d.released) ? null : hasSigners ? (
                <Link
                  className={`button ${d.elements === 0 ? "button--primary" : "button--secondary"} button--sm`}
                  to={`/documents/versions/${d.version_id}/prepare?campaign=${campaign.id}`}
                >
                  <PencilRuler size={14} aria-hidden="true" /> {t("campaignDocs.prepare")}
                </Link>
              ) : (
                <span className="muted small">{t("campaignDocs.chooseSignerFirst")}</span>
              )}
              {active && !d.released && (
                <ConfirmButton
                  className="button button--primary button--sm"
                  confirmClassName="button button--primary button--sm"
                  confirmLabel={t("campaignDocs.confirmRelease")}
                  disabled={d.elements === 0}
                  onConfirm={async () => {
                    try {
                      await api.post(`/campaigns/${campaign.id}/documents/${d.version_id}/release`);
                      onChanged();
                    } catch (err) {
                      setError(errorText(err, "campaignDocs.releaseFailed"));
                    }
                  }}
                >
                  {t("campaignDocs.release")}
                </ConfirmButton>
              )}
              {!(active && d.released) && (
                <ConfirmButton
                  confirmLabel={t("campaignDocs.confirmRemove")}
                  onConfirm={async () => {
                    await api.del(`/campaigns/${campaign.id}/documents/${d.version_id}`);
                    onChanged();
                  }}
                >
                  {t("campaignDocs.remove")}
                </ConfirmButton>
              )}
            </span>
          </li>
        ))}
      </ul>

      <UploadDropzone onFiles={stage} disabled={busy} hint={documentHint()} />
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
                  aria-label={t("campaignDocs.removeFile", { name: file.name })}
                  onClick={() => setPending(pending.filter((_, j) => j !== i))}
                >
                  <X size={13} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
          <div className="row-actions">
            <button type="button" className="button" disabled={busy} onClick={() => void importAll()}>
              <Upload size={14} aria-hidden="true" />{" "}
              {pending.length > 1 ? t("campaignDocs.addDocuments", { count: pending.length }) : t("campaignDocs.addDocument")}
            </button>
            <button type="button" className="button button--ghost" onClick={() => setPending([])}>
              {t("common.cancel")}
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
          <select aria-label={t("campaignDocs.existingAria")} value={existing} onChange={(e) => setExisting(e.target.value)}>
            <option value="">{t("campaignDocs.reuse")}</option>
            {reusable.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
          <button className="button button--secondary" onClick={() => void addExisting()} disabled={!existing}>
            {t("users.add")}
          </button>
        </div>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
