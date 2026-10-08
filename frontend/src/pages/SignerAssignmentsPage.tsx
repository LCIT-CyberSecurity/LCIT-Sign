import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, CheckCircle2, Clock, PartyPopper, FileSignature, Download, ExternalLink } from "lucide-react";
import EmptyState from "../components/EmptyState";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import type { MyAssignment, SignatureDetail } from "../api/types";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** Everything about the person's own signatures in one place: what is to be signed, what comes
 *  later, and what they signed, with the signed PDF, the certificate and the proof. (What others
 *  signed is followed in Suivi.) */
export default function SignerAssignmentsPage() {
  const [assignments, setAssignments] = useState<MyAssignment[] | null>(null);
  const [signatures, setSignatures] = useState<SignatureDetail[] | null>(null);
  const { user, hasRole } = useAuth();
  const staff = hasRole("SIGNER") || hasRole("OPERATOR") || hasRole("ADMIN");

  useEffect(() => {
    api.get<MyAssignment[]>("/me/assignments").then(setAssignments);
    api.get<SignatureDetail[]>("/signatures/me").then(setSignatures);
  }, []);

  if (assignments === null || signatures === null) return <p className="muted">Chargement…</p>;

  const pending = assignments.filter((a) => a.status === "PENDING" || a.status === "VIEWED");
  // The signatures themselves (they also cover what was signed outside any campaign).
  const signed = signatures;
  const upcoming = assignments.filter((a) => a.status === "WAITING");
  // A campaign with several documents to sign: one click for all of them.
  const bulk = [...new Map(pending.map((a) => [a.campaign_id, a.campaign_name])).entries()]
    .map(([id, name]) => ({ id, name, count: pending.filter((a) => a.campaign_id === id).length }))
    .filter((c) => c.count > 1);

  return (
    <div className="stack">
      <div>
        <h1 className="page-title" style={{ marginBottom: 4 }}>
          <FileSignature size={22} aria-hidden="true" /> Mes signatures
        </h1>
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
      {bulk.map((c) => (
        <Link key={c.id} to={`/sign-all/${c.id}`} className="card card--link" data-testid="sign-all-link">
          <div>
            <div className="card-title">Tout signer d&apos;un coup</div>
            <div className="muted small">
              {c.count} documents de « {c.name} » : un seul consentement, chaque document a sa preuve.
            </div>
          </div>
          <div className="card-meta">Signer les {c.count} documents</div>
        </Link>
      ))}

      <section>
        <h2 className="page-title">
          <FileText size={20} aria-hidden="true" /> À signer
          <span className="count-badge">{pending.length}</span>
        </h2>
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
          <h2 className="page-title">
            <Clock size={20} aria-hidden="true" /> À venir
            <span className="count-badge">{upcoming.length}</span>
          </h2>
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

      <section data-testid="signed-section">
        <h2 className="page-title">
          <CheckCircle2 size={20} aria-hidden="true" /> Signés
          <span className="count-badge">{signed.length}</span>
        </h2>
        <p className="muted small">
          Ce que <strong>vous</strong> avez signé, avec le PDF signé, le certificat et la preuve.
          {staff && (
            <>
              {" "}
              Ce que d&apos;autres ont signé se suit dans <Link to="/campaigns?tab=signed">Suivi → Documents signés</Link>.
            </>
          )}
        </p>
        {signed.length === 0 ? (
          <EmptyState icon={<FileSignature size={24} />} title="Aucune signature pour le moment">
            Les documents que vous signerez apparaîtront ici, avec leur preuve vérifiable.
          </EmptyState>
        ) : (
          <div className="card-list">
            {signed.map((s) => (
              <div key={s.id} className="card card--row" data-testid={`signed-${s.document_title}`}>
                <Link to={`/signatures/${s.id}`} className="card-link">
                  <div className="card-title">{s.document_title}</div>
                  <div className="muted small">
                    Version {s.version_label}
                    {s.campaign_name ? ` — ${s.campaign_name}` : ""} — signé le {formatDate(s.signed_at_utc)} —{" "}
                    <span className="mono">{s.display_id}</span>
                  </div>
                </Link>
                {/* The signed PDF itself, at once: no detour through another page or a ZIP. */}
                <div className="row-actions">
                  <a
                    className="button button--secondary button--sm"
                    href={`/api/signatures/${s.id}/signed-pdf?inline=true`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={13} aria-hidden="true" /> Ouvrir
                  </a>
                  <a className="button button--ghost button--sm" href={`/api/signatures/${s.id}/signed-pdf`}>
                    <Download size={13} aria-hidden="true" /> PDF signé
                  </a>
                  <Link className="button button--ghost button--sm" to={`/signatures/${s.id}`}>
                    Preuve et signataires
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
