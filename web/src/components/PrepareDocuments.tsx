import { Link } from "react-router-dom";
import { CheckCircle2, PencilRuler } from "lucide-react";
import type { Campaign } from "../api/types";

/** The step where each document gets its elements: for every document, where each signer
 *  signs, the date, the name… The editor itself is a page of its own; this lists the documents
 *  to prepare and how far along each one is. */
export default function PrepareDocuments({ campaign }: { campaign: Campaign }) {
  const done = campaign.documents.filter((d) => d.elements > 0).length;
  const total = campaign.documents.length;
  const next = campaign.documents.find((d) => d.elements === 0);
  const editor = (versionId: string) => `/documents/versions/${versionId}/prepare?campaign=${campaign.id}`;

  return (
    <div className="card" data-testid="prepare-step">
      <div className="card-title">Préparer les documents</div>
      <p className="muted small">
        Pour chaque document, vous placez à l&apos;endroit voulu la signature, la date, le nom… de chaque
        signataire, par glisser-déposer.
      </p>
      {total === 0 ? (
        <p className="muted">Aucun document : ajoutez-en à l&apos;étape précédente.</p>
      ) : (
        <>
          <p data-testid="prepare-progress">
            <strong>
              {done}/{total}
            </strong>{" "}
            document(s) préparé(s)
          </p>
          <ul className="plain-list">
            {campaign.documents.map((d) => (
              <li key={d.version_id} className="report-row" data-testid={`prepare-${d.title}`}>
                <span>
                  {d.elements > 0 && <CheckCircle2 size={14} aria-hidden="true" />} <strong>{d.title}</strong>{" "}
                  <span className="muted small">
                    v{d.version_label} —{" "}
                    {d.elements > 0 ? `${d.elements} élément(s) placé(s)` : "pas encore préparé"}
                  </span>
                </span>
                <Link
                  className={`button ${d.elements === 0 ? "button--primary" : "button--secondary"} button--sm`}
                  to={editor(d.version_id)}
                >
                  <PencilRuler size={14} aria-hidden="true" /> {d.elements === 0 ? "Préparer" : "Modifier"}
                </Link>
              </li>
            ))}
          </ul>
          {next && (
            <Link className="button button--primary" to={editor(next.version_id)}>
              <PencilRuler size={14} aria-hidden="true" /> Préparer « {next.title} »
            </Link>
          )}
        </>
      )}
    </div>
  );
}
