import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, CheckCircle2, Clock } from "lucide-react";
import { api } from "../api/client";
import type { MyAssignment } from "../api/types";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export default function SignerAssignmentsPage() {
  const [assignments, setAssignments] = useState<MyAssignment[] | null>(null);

  useEffect(() => {
    api.get<MyAssignment[]>("/me/assignments").then(setAssignments);
  }, []);

  if (assignments === null) return <p className="muted">Chargement…</p>;

  const pending = assignments.filter((a) => a.status === "PENDING" || a.status === "VIEWED");
  const signed = assignments.filter((a) => a.status === "SIGNED");

  return (
    <div className="stack">
      <section>
        <h1 className="page-title">
          <FileText size={20} aria-hidden="true" /> À signer
          <span className="count-badge">{pending.length}</span>
        </h1>
        {pending.length === 0 ? (
          <p className="muted">Rien à signer pour le moment.</p>
        ) : (
          <div className="card-list">
            {pending.map((a) => (
              <Link key={a.id} to={`/assignments/${a.id}`} className="card card--link">
                <div>
                  <div className="card-title">{a.document_title}</div>
                  <div className="muted small">
                    Version {a.version_label} — {a.campaign_name}
                  </div>
                </div>
                <div className="card-meta">
                  <Clock size={14} aria-hidden="true" />
                  {a.deadline ? `Avant le ${formatDate(a.deadline)}` : "Sans échéance"}
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section>
        <h1 className="page-title">
          <CheckCircle2 size={20} aria-hidden="true" /> Signés
          <span className="count-badge">{signed.length}</span>
        </h1>
        {signed.length === 0 ? (
          <p className="muted">Aucune signature pour le moment.</p>
        ) : (
          <div className="card-list">
            {signed.map((a) => (
              <Link key={a.id} to={`/assignments/${a.id}`} className="card card--link">
                <div>
                  <div className="card-title">{a.document_title}</div>
                  <div className="muted small">
                    Version {a.version_label} — {a.campaign_name}
                  </div>
                </div>
                <div className="card-meta">Signé le {formatDate(a.signed_at)}</div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
