import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, CheckCircle2, Clock, PartyPopper, FileSignature } from "lucide-react";
import EmptyState from "../components/EmptyState";
import { useAuth } from "../auth/AuthContext";
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
  const { user } = useAuth();

  useEffect(() => {
    api.get<MyAssignment[]>("/me/assignments").then(setAssignments);
  }, []);

  if (assignments === null) return <p className="muted">Chargement…</p>;

  const pending = assignments.filter((a) => a.status === "PENDING" || a.status === "VIEWED");
  const signed = assignments.filter((a) => a.status === "SIGNED");
  const upcoming = assignments.filter((a) => a.status === "WAITING");

  return (
    <div className="stack">
      <div>
        <p className="greeting">Bonjour {user?.display_name?.split(" ")[0]}</p>
        <div className="metrics" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 260px))" }}>
          <div className="metric">
            <div className="metric-label">
              À signer
              <span className="metric-icon amber" aria-hidden="true">
                <Clock size={15} />
              </span>
            </div>
            <strong data-testid="count-pending">{pending.length}</strong>
            <small>document(s) en attente</small>
          </div>
          <div className="metric">
            <div className="metric-label">
              Signés
              <span className="metric-icon green" aria-hidden="true">
                <CheckCircle2 size={15} />
              </span>
            </div>
            <strong data-testid="count-signed">{signed.length}</strong>
            <small>document(s) signé(s)</small>
          </div>
        </div>
      </div>
      <section>
        <h1 className="page-title">
          <FileText size={20} aria-hidden="true" /> À signer
          <span className="count-badge">{pending.length}</span>
        </h1>
        {pending.length === 0 ? (
          <EmptyState icon={<PartyPopper size={24} />} title="Tout est à jour">
            Aucun document n&apos;attend votre signature. Vous serez prévenu par e-mail dès qu&apos;un nouveau document vous est adressé.
          </EmptyState>
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

      {upcoming.length > 0 && (
        <section data-testid="upcoming">
          <h1 className="page-title">
            <Clock size={20} aria-hidden="true" /> À venir
            <span className="count-badge">{upcoming.length}</span>
          </h1>
          <div className="card-list">
            {upcoming.map((a) => (
              <div key={a.id} className="card">
                <div className="card-title">{a.document_title}</div>
                <div className="muted small">
                  Version {a.version_label} — {a.campaign_name}
                </div>
                <div className="muted small">
                  Ce sera votre tour après la signature de{" "}
                  {a.waiting_on && a.waiting_on.length > 0 ? a.waiting_on.join(", ") : "l'étape précédente"}.
                  Vous serez prévenu par e-mail.
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <h1 className="page-title">
          <CheckCircle2 size={20} aria-hidden="true" /> Signés
          <span className="count-badge">{signed.length}</span>
        </h1>
        {signed.length === 0 ? (
          <EmptyState icon={<FileSignature size={24} />} title="Aucune signature pour le moment">
            Les documents que vous signerez apparaîtront ici, avec leur preuve vérifiable.
          </EmptyState>
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
