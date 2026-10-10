import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { FileText, CheckCircle2, Trash2, Upload, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { blockerText, errorText } from "../i18n/errors";
import { versionStatus } from "../i18n/enums";
import { collator, formatSize } from "../i18n/format";
import ConfirmButton from "../components/ConfirmButton";
import UploadDropzone from "../components/UploadDropzone";
import { documentHint, documentRefused, isAcceptedDocument } from "../lib/uploads";
import type { DocumentDetail } from "../api/types";

interface UploadResult {
  name: string;
  state: "waiting" | "uploading" | "done" | "error";
  message?: string;
}

/** "charte_informatique-2026.pdf" -> "Charte informatique 2026". */
export function deriveTitle(fileName: string): string {
  const base = fileName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : "Document";
}

export default function OperatorDocumentsPage() {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState<DocumentDetail[] | null>(null);
  const [title, setTitle] = useState("");
  const [versionLabel, setVersionLabel] = useState("1.0");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"alpha" | "recent">("alpha");
  const [results, setResults] = useState<UploadResult[]>([]);
  // Dropped files wait here until the operator clicks "Importer".
  const [pending, setPending] = useState<File[]>([]);

  const load = () => {
    api.get<DocumentDetail[]>("/documents").then(setDocuments);
  };

  useEffect(load, []);

  const stage = (files: File[]) => {
    setResults([]);
    setPending((current) => [
      ...current,
      ...files.filter((f) => !current.some((c) => c.name === f.name && c.size === f.size)),
    ]);
  };

  const upload = async (files: File[]) => {
    setPending([]);
    setUploading(true);
    setError(null);
    const batch: UploadResult[] = files.map((file) => ({ name: file.name, state: "waiting" }));
    setResults(batch);
    const update = (index: number, patch: Partial<UploadResult>) => {
      batch[index] = { ...batch[index], ...patch };
      setResults([...batch]);
    };
    for (const [index, file] of files.entries()) {
      if (!isAcceptedDocument(file.name)) {
        update(index, { state: "error", message: documentRefused() });
        continue;
      }
      update(index, { state: "uploading" });
      const form = new FormData();
      // One file may take the title typed above; several are named after their files.
      form.append("title", files.length === 1 && title.trim() ? title.trim() : deriveTitle(file.name));
      form.append("version_label", versionLabel);
      form.append("description", description);
      form.append("category", category);
      form.append("file", file);
      try {
        await api.postForm("/documents", form);
        update(index, { state: "done" });
      } catch (err) {
        update(index, { state: "error", message: errorText(err, "documents.uploadFailed") });
      }
    }
    if (files.length === 1 && batch[0].state === "done") setTitle("");
    setUploading(false);
    load();
  };

  const remove = async (path: string) => {
    setError(null);
    try {
      await api.del(path);
      load();
    } catch (err) {
      setError(errorText(err, "documents.deleteFailed"));
    }
  };

  const archive = async (versionId: string) => {
    setError(null);
    try {
      await api.post(`/documents/versions/${versionId}/archive`);
      load();
    } catch (err) {
      setError(errorText(err, "documents.archiveFailed"));
    }
  };

  const publish = async (versionId: string) => {
    await api.post(`/documents/versions/${versionId}/publish`);
    load();
  };

  const visibleDocuments = [...(documents ?? [])]
    .filter((doc) => {
      const q = query.trim().toLowerCase();
      return !q || `${doc.title} ${doc.category} ${doc.description}`.toLowerCase().includes(q);
    })
    .sort((a, b) =>
      sort === "alpha"
        ? collator().compare(a.title, b.title)
        : b.created_at.localeCompare(a.created_at),
    );

  return (
    <div className="stack">
      <h1 className="page-title">
        <FileText size={20} aria-hidden="true" /> {t("documents.title")}
      </h1>

      <p className="muted">
        <Trans i18nKey="documents.intro" components={{ sign: <Link to="/sign" /> }} />
      </p>

      <section className="card form" aria-label={t("documents.addAria")}>
        <UploadDropzone onFiles={stage} disabled={uploading} hint={documentHint()} />
        <details className="upload-options">
          <summary>
            {t("documents.options")} <span className="muted small">{t("documents.optionsHint")}</span>
          </summary>
          <div className="stack" style={{ marginTop: 10 }}>
            <div className="form-row">
              <label>
                {t("documents.titleField")} <span className="muted small">{t("documents.titleHint")}</span>
                <input value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
              <label>
                {t("documents.version")}
                <input value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} required />
              </label>
            </div>
            <div className="form-row">
              <label>
                {t("documents.category")}
                <input value={category} onChange={(e) => setCategory(e.target.value)} maxLength={100} />
              </label>
              <label>
                {t("documents.description")}
                <input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={2000}
                />
              </label>
            </div>
          </div>
        </details>
        {pending.length > 0 && (
          <div className="stack" data-testid="pending-files">
            <ul className="upload-results">
              {pending.map((file, i) => (
                <li key={`${file.name}-${i}`}>
                  <FileText size={14} aria-hidden="true" />
                  <strong>{file.name}</strong>
                  <span className="muted small">{formatSize(file.size)}</span>
                  <button
                    type="button"
                    className="button button--ghost button--sm"
                    aria-label={t("documents.remove", { name: file.name })}
                    onClick={() => setPending(pending.filter((_, j) => j !== i))}
                  >
                    <X size={13} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
            <div className="row-actions">
              <button type="button" className="button" onClick={() => void upload(pending)}>
                <Upload size={14} aria-hidden="true" />{" "}
                {pending.length > 1 ? t("documents.importDocs", { count: pending.length }) : t("documents.importDoc")}
              </button>
              <button type="button" className="button button--ghost" onClick={() => setPending([])}>
                {t("common.cancel")}
              </button>
            </div>
          </div>
        )}
        {results.length > 0 && (
          <ul className="upload-results" aria-live="polite" data-testid="upload-results">
            {results.map((r, i) => (
              <li key={`${r.name}-${i}`}>
                <span className={r.state === "error" ? "status-error" : r.state === "done" ? "status-ok" : "muted"}>
                  {r.state === "done" ? "✓" : r.state === "error" ? "✕" : "…"}
                </span>
                <strong>{r.name}</strong>
                <span className="muted small">
                  {r.state === "done" && t("documents.added")}
                  {r.state === "uploading" && t("documents.uploading")}
                  {r.state === "waiting" && t("documents.waiting")}
                  {r.state === "error" && r.message}
                </span>
              </li>
            ))}
          </ul>
        )}
        {error && <p className="error-text">{error}</p>}
      </section>

      <div className="filter-bar">
        <input
          type="search"
          placeholder={t("documents.searchPlaceholder")}
          aria-label={t("documents.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label>
          {t("documents.sort")}
          <select value={sort} onChange={(e) => setSort(e.target.value as "alpha" | "recent")}>
            <option value="alpha">{t("documents.sortAlpha")}</option>
            <option value="recent">{t("documents.sortRecent")}</option>
          </select>
        </label>
      </div>

      <div className="card-list">
        {visibleDocuments.length === 0 && documents && (
          <p className="muted">{t("documents.noMatch")}</p>
        )}
        {visibleDocuments.map((doc) => (
          <div key={doc.id} className="card">
            <div className="page-title-row">
              <div className="card-title" style={{ margin: 0 }}>
                {doc.title}{" "}
                {doc.category && <span className="badge badge--viewed">{doc.category}</span>}
              </div>
              {doc.can_delete && (
                <ConfirmButton onConfirm={() => remove(`/documents/${doc.id}`)}>
                  <Trash2 size={13} aria-hidden="true" /> {t("documents.deleteDocument")}
                </ConfirmButton>
              )}
            </div>
            {doc.description && <p className="muted small">{doc.description}</p>}
            <table className="simple-table">
              <thead>
                <tr>
                  <th>{t("documents.columns.version")}</th>
                  <th>{t("documents.columns.status")}</th>
                  <th>{t("documents.columns.size")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {doc.versions.map((v) => (
                  <tr key={v.id}>
                    <td>{v.version_label}</td>
                    <td>
                      <span className={`badge badge--${v.status.toLowerCase()}`}>{versionStatus(v.status)}</span>
                    </td>
                    <td>{formatSize(v.file_size)}</td>
                    <td>
                      <div className="row-actions">
                        {v.status === "DRAFT" && (
                          <button className="button button--secondary button--sm" onClick={() => publish(v.id)}>
                            <CheckCircle2 size={14} aria-hidden="true" /> {t("documents.publish")}
                          </button>
                        )}
                        {v.status !== "ARCHIVED" && v.status !== "DRAFT" && (
                          <button className="button button--ghost button--sm" onClick={() => archive(v.id)}>
                            {t("documents.archive")}
                          </button>
                        )}
                        {v.can_delete && (
                          <ConfirmButton onConfirm={() => remove(`/documents/versions/${v.id}`)}>
                            <Trash2 size={13} aria-hidden="true" /> {t("common.delete")}
                          </ConfirmButton>
                        )}
                      </div>
                      {v.can_delete === false && (
                        <p className="blocker-note" title={t("documents.keptHint")}>
                          {t("documents.kept", { reasons: v.delete_blockers.map(blockerText).join(" ; ") })}
                        </p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
