import { useEffect, useRef, useState, type FormEvent } from "react";
import { FileText, Upload, CheckCircle2, Trash2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
import type { DocumentDetail } from "../api/types";

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
  const fileInput = useRef<HTMLInputElement>(null);

  const load = () => {
    api.get<DocumentDetail[]>("/documents").then(setDocuments);
  };

  useEffect(load, []);

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file || !title) return;
    setUploading(true);
    setError(null);
    const form = new FormData();
    form.append("title", title);
    form.append("version_label", versionLabel);
    form.append("description", description);
    form.append("category", category);
    form.append("file", file);
    try {
      await api.postForm("/documents", form);
      setTitle("");
      setVersionLabel("1.0");
      setDescription("");
      setCategory("");
      if (fileInput.current) fileInput.current.value = "";
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "L'envoi a échoué.");
    } finally {
      setUploading(false);
    }
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

      <form className="card form" onSubmit={upload}>
        <div className="form-row">
          <label>
            Titre
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
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
        <label>
          Fichier PDF
          <input type="file" accept="application/pdf" ref={fileInput} required />
        </label>
        {error && <p className="error-text">{error}</p>}
        <button className="button button--primary" type="submit" disabled={uploading}>
          <Upload size={14} aria-hidden="true" /> {uploading ? "Envoi…" : "Ajouter le document (brouillon)"}
        </button>
      </form>

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
