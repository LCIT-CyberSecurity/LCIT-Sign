import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { FileText, CheckCircle2, Clock, PartyPopper, FileSignature, Download, ExternalLink } from "lucide-react";
import EmptyState from "../components/EmptyState";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import { formatDate as formatDay } from "../i18n/format";
import type { MyAssignment, SignatureDetail } from "../api/types";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return formatDay(value, { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** Everything about the person's own signatures in one place: what is to be signed, what comes
 *  later, and what they signed, with the signed PDF, the certificate and the proof. (What others
 *  signed is followed in Suivi.) */
export default function SignerAssignmentsPage() {
  const { t } = useTranslation();
  const [assignments, setAssignments] = useState<MyAssignment[] | null>(null);
  const [signatures, setSignatures] = useState<SignatureDetail[] | null>(null);
  const { user, hasRole } = useAuth();
  const staff = hasRole("SIGNER") || hasRole("OPERATOR") || hasRole("ADMIN");

  useEffect(() => {
    api.get<MyAssignment[]>("/me/assignments").then(setAssignments);
    api.get<SignatureDetail[]>("/signatures/me").then(setSignatures);
  }, []);

  if (assignments === null || signatures === null) return <p className="muted">{t("common.loading")}</p>;

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
          <FileSignature size={22} aria-hidden="true" /> {t("nav.mySignatures")}
        </h1>
        <p className="greeting">{t("assignments.greeting", { name: user?.display_name?.split(" ")[0] })}</p>
        <div className="metrics" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 260px))" }}>
          <div className="metric">
            <div className="metric-label">
              {t("assignments.toSign")}
              <span className="metric-icon amber" aria-hidden="true">
                <Clock size={15} />
              </span>
            </div>
            <strong data-testid="count-pending">{pending.length}</strong>
            <small>{t("assignments.docsWaiting", { count: pending.length })}</small>
          </div>
          <div className="metric">
            <div className="metric-label">
              {t("assignments.signed")}
              <span className="metric-icon green" aria-hidden="true">
                <CheckCircle2 size={15} />
              </span>
            </div>
            <strong data-testid="count-signed">{signed.length}</strong>
            <small>{t("assignments.docsSigned", { count: signed.length })}</small>
          </div>
        </div>
      </div>
      {bulk.map((c) => (
        <Link key={c.id} to={`/sign-all/${c.id}`} className="card card--link" data-testid="sign-all-link">
          <div>
            <div className="card-title">{t("assignments.signAllTitle")}</div>
            <div className="muted small">
              {t("assignments.signAllText", { count: c.count, name: c.name })}
            </div>
          </div>
          <div className="card-meta">{t("assignments.signAllButton", { count: c.count })}</div>
        </Link>
      ))}

      <section>
        <h2 className="page-title">
          <FileText size={20} aria-hidden="true" /> {t("assignments.toSign")}
          <span className="count-badge">{pending.length}</span>
        </h2>
        {pending.length === 0 ? (
          <EmptyState icon={<PartyPopper size={24} />} title={t("assignments.upToDate")}>
            {t("assignments.upToDateText")}
          </EmptyState>
        ) : (
          <div className="card-list">
            {pending.map((a) => (
              <Link key={a.id} to={`/assignments/${a.id}`} className="card card--link">
                <div>
                  <div className="card-title">{a.document_title}</div>
                  <div className="muted small">
                    {t("assignments.version", { version: a.version_label, campaign: a.campaign_name })}
                  </div>
                </div>
                <div className="card-meta">
                  <Clock size={14} aria-hidden="true" />
                  {a.deadline ? t("assignments.before", { date: formatDate(a.deadline) }) : t("assignments.noDeadline")}
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {upcoming.length > 0 && (
        <section data-testid="upcoming">
          <h2 className="page-title">
            <Clock size={20} aria-hidden="true" /> {t("assignments.upcoming")}
            <span className="count-badge">{upcoming.length}</span>
          </h2>
          <div className="card-list">
            {upcoming.map((a) => (
              <div key={a.id} className="card">
                <div className="card-title">{a.document_title}</div>
                <div className="muted small">
                  {t("assignments.version", { version: a.version_label, campaign: a.campaign_name })}
                </div>
                <div className="muted small">
                  {t("assignments.upcomingText", {
                    who: a.waiting_on && a.waiting_on.length > 0 ? a.waiting_on.join(", ") : t("assignments.previousStep"),
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section data-testid="signed-section">
        <h2 className="page-title">
          <CheckCircle2 size={20} aria-hidden="true" /> {t("assignments.signed")}
          <span className="count-badge">{signed.length}</span>
        </h2>
        <p className="muted small">
          <Trans i18nKey="assignments.signedIntro" components={{ strong: <strong /> }} />
          {staff && (
            <>
              {" "}
              <Trans i18nKey="assignments.othersSigned" components={{ view: <Link to="/campaigns?tab=signed" /> }} />
            </>
          )}
        </p>
        {signed.length === 0 ? (
          <EmptyState icon={<FileSignature size={24} />} title={t("assignments.noSignatureTitle")}>
            {t("assignments.noSignatureText")}
          </EmptyState>
        ) : (
          <div className="card-list">
            {signed.map((s) => (
              <div key={s.id} className="card card--row" data-testid={`signed-${s.document_title}`}>
                <Link to={`/signatures/${s.id}`} className="card-link">
                  <div className="card-title">{s.document_title}</div>
                  <div className="muted small">
                    {t("assignments.signedLine", {
                      version: s.version_label,
                      campaign: s.campaign_name ? ` — ${s.campaign_name}` : "",
                      date: formatDate(s.signed_at_utc),
                    })}{" "}
                    —{" "}
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
                    <ExternalLink size={13} aria-hidden="true" /> {t("assignments.open")}
                  </a>
                  <a className="button button--ghost button--sm" href={`/api/signatures/${s.id}/signed-pdf`}>
                    <Download size={13} aria-hidden="true" /> {t("assignments.signedPdf")}
                  </a>
                  <Link className="button button--ghost button--sm" to={`/signatures/${s.id}`}>
                    {t("assignments.proof")}
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
