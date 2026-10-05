import { useEffect, useRef, useState, type FormEvent } from "react";
import { FileText, Upload, CheckCircle2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { DocumentDetail } from "../api/types";

export default function OperatorDocumentsPage() {
  const [documents, setDocuments] = useState<DocumentDetail[] | null>(null);
  const [title, setTitle] = useState("");
  const [versionLabel, setVersionLabel] = useState("1.0");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
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
          <Upload size={14} aria-hidden="true" /> {uploading ? "Envoi…" : "Publier un document"}
        </button>
      </form>

      <div className="card-list">
        {documents?.map((doc) => (
          <div key={doc.id} className="card">
            <div className="card-title">
              {doc.title}{" "}
              {doc.category && <span className="badge badge--viewed">{doc.category}</span>}
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
