import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileSignature } from "lucide-react";
import EmptyState from "../components/EmptyState";
import { api } from "../api/client";
import type { SignatureDetail } from "../api/types";

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

/** Everything the signed-in user has signed, newest first — the entry point to
 *  the signed document, its certificate and its verifiable proof. */
export default function MySignaturesPage() {
  const [signatures, setSignatures] = useState<SignatureDetail[] | null>(null);

  useEffect(() => {
    api.get<SignatureDetail[]>("/signatures/me").then(setSignatures);
  }, []);

  if (signatures === null) return <p className="muted">Chargement…</p>;

  return (
    <div className="stack">
      <h1 className="page-title">
        <FileSignature size={22} aria-hidden="true" /> Mes signatures
        <span className="count-badge">{signatures.length}</span>
      </h1>
      <p className="page-subtitle">
        Retrouvez ici chaque document que vous avez signé : le PDF signé, votre certificat et la preuve
        d&apos;intégrité vérifiable.
      </p>
      {signatures.length === 0 ? (
        <EmptyState icon={<FileSignature size={24} />} title="Vous n'avez encore rien signé">
          Quand vous aurez signé un document, vous retrouverez ici le PDF signé, votre certificat et la preuve d&apos;intégrité.
        </EmptyState>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="simple-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Campagne</th>
                <th>Signé le</th>
                <th>Identifiant</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {signatures.map((s) => (
                <tr key={s.id}>
                  <td>
                    <strong>{s.document_title}</strong>
                    <div className="muted small">Version {s.version_label}</div>
                  </td>
                  <td>{s.campaign_name ?? "—"}</td>
                  <td>{formatDateTime(s.signed_at_utc)}</td>
                  <td className="mono">{s.display_id}</td>
                  <td>
                    <Link className="button button--secondary button--sm" to={`/signatures/${s.id}`}>
                      Voir la signature
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
