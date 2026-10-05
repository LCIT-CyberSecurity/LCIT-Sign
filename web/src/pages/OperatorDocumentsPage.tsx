import { useEffect, useState } from "react";
import { FileText, CheckCircle2, Trash2, PencilRuler } from "lucide-react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
import UploadDropzone from "../components/UploadDropzone";
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

  const load = () => {
    api.get<DocumentDetail[]>("/documents").then(setDocuments);
  };

  useEffect(load, []);

  const upload = async (files: File[]) => {
    setUploading(true);
    setError(null);
    const batch: UploadResult[] = files.map((file) => ({ name: file.name, state: "waiting" }));
    setResults(batch);
    const update = (index: number, patch: Partial<UploadResult>) => {
      batch[index] = { ...batch[index], ...patch };
      setResults([...batch]);
    };
    for (const [index, file] of files.entries()) {
      if (!/\.pdf$/i.test(file.name)) {
        update(index, { state: "error", message: "Seuls les PDF sont acceptés pour le moment." });
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
        update(index, { state: "error", message: err instanceof ApiError ? err.message : "L'envoi a échoué." });
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
      setError(err instanceof ApiError ? err.message : "La suppression a échoué.");
    }
  };

  const archive = async (versionId: string) => {
    setError(null);
    try {
      await api.post(`/documents/versions/${versionId}/archive`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "L'archivage a échoué.");
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
        ? a.title.localeCompare(b.title, "fr", { sensitivity: "base", numeric: true })
        : b.created_at.localeCompare(a.created_at),
    );

  return (
    <div className="stack">
      <h1 className="page-title">
        <FileText size={20} aria-hidden="true" /> Documents
      </h1>

      <section className="card form" aria-label="Ajouter des documents">
        <div className="form-row">
          <label>
            Titre <span className="muted small">(facultatif — repris du nom du fichier)</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label>
            Version
            <input value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} required />
          </label>
        </div>
        <div className="form-row">
          <label>
            Catégorie
            <input value={category} onChange={(e) => setCategory(e.target.value)} maxLength={100} />
          </label>
          <label>
            Description
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
            />
          </label>
        </div>
        <UploadDropzone onFiles={(files) => void upload(files)} disabled={uploading} hint="PDF, plusieurs à la fois" />
        {results.length > 0 && (
          <ul className="upload-results" aria-live="polite" data-testid="upload-results">
            {results.map((r, i) => (
              <li key={`${r.name}-${i}`}>
                <span className={r.state === "error" ? "status-error" : r.state === "done" ? "status-ok" : "muted"}>
                  {r.state === "done" ? "✓" : r.state === "error" ? "✕" : "…"}
                </span>
                <strong>{r.name}</strong>
                <span className="muted small">
                  {r.state === "done" && "ajouté en brouillon — à préparer puis publier"}
                  {r.state === "uploading" && "envoi…"}
                  {r.state === "waiting" && "en attente"}
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
          placeholder="Rechercher un document, une catégorie…"
          aria-label="Rechercher un document"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label>
          Tri
          <select value={sort} onChange={(e) => setSort(e.target.value as "alpha" | "recent")}>
            <option value="alpha">Ordre alphabétique</option>
            <option value="recent">Plus récents d&apos;abord</option>
          </select>
        </label>
      </div>

      <div className="card-list">
        {visibleDocuments.length === 0 && documents && (
          <p className="muted">Aucun document ne correspond.</p>
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
                  <Trash2 size={13} aria-hidden="true" /> Supprimer le document
                </ConfirmButton>
              )}
            </div>
            {doc.description && <p className="muted small">{doc.description}</p>}
            <table className="simple-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Statut</th>
                  <th>Taille</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {doc.versions.map((v) => (
                  <tr key={v.id}>
                    <td>{v.version_label}</td>
                    <td>
                      <span className={`badge badge--${v.status.toLowerCase()}`}>{v.status}</span>
                    </td>
                    <td>{Math.round(v.file_size / 1024)} Ko</td>
                    <td>
                      <div className="row-actions">
                        <Link
                          className="button button--secondary button--sm"
                          to={`/documents/versions/${v.id}/prepare`}
                        >
                          <PencilRuler size={14} aria-hidden="true" />{" "}
                          {v.status === "DRAFT" ? "Préparer" : "Éléments"}
                        </Link>
                        {v.status === "DRAFT" && (
                          <button className="button button--secondary button--sm" onClick={() => publish(v.id)}>
                            <CheckCircle2 size={14} aria-hidden="true" /> Publier
                          </button>
                        )}
                        {v.status !== "ARCHIVED" && v.status !== "DRAFT" && (
                          <button className="button button--ghost button--sm" onClick={() => archive(v.id)}>
                            Archiver
                          </button>
                        )}
                        {v.can_delete && (
                          <ConfirmButton onConfirm={() => remove(`/documents/versions/${v.id}`)}>
                            <Trash2 size={13} aria-hidden="true" /> Supprimer
                          </ConfirmButton>
                        )}
                      </div>
                      {v.can_delete === false && (
                        <p className="blocker-note" title="Une version signée ou utilisée fait partie de la preuve">
                          Conservée — {v.delete_blockers.join(" ; ")}
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
