import { CheckCircle2, Circle } from "lucide-react";
import { DocumentEditor } from "../pages/PrepareDocumentPage";
import type { Campaign } from "../api/types";

/** The "Préparer" step: the editor itself, in the flow. A strip of the documents on top (a tick on
 *  each one that has its elements), the document being prepared below. Finishing one opens the
 *  next that still needs it; finishing the last one moves on. */
export default function PrepareStep({
  campaign,
  selected,
  onSelect,
  onReload,
  onDone,
}: {
  campaign: Campaign;
  /** The version being prepared, from the address; the first one still to prepare when absent. */
  selected: string | null;
  onSelect: (versionId: string) => void;
  onReload: () => void;
  onDone: () => void;
}) {
  const documents = campaign.documents;
  if (documents.length === 0) {
    return (
      <div className="card" data-testid="prepare-step">
        <p className="muted">Aucun document : ajoutez-en à l&apos;étape précédente.</p>
      </div>
    );
  }
  const current =
    documents.find((d) => d.version_id === selected) ??
    documents.find((d) => d.elements === 0) ??
    documents[0];
  const done = documents.filter((d) => d.elements > 0).length;

  return (
    <div className="stack" data-testid="prepare-step">
      <div className="card prepare-strip">
        <div className="prepare-strip__head">
          <strong>Préparer les documents</strong>
          <span className="muted small" data-testid="prepare-progress">
            <strong>
              {done}/{documents.length}
            </strong>{" "}
            préparé(s) — placez la signature, la date, le nom… de chaque signataire
          </span>
        </div>
        <ul className="prepare-tabs" role="tablist" aria-label="Documents à préparer">
          {documents.map((d) => (
            <li key={d.version_id}>
              <button
                type="button"
                role="tab"
                aria-selected={d.version_id === current.version_id}
                className={`prepare-tab${d.version_id === current.version_id ? " is-current" : ""}`}
                onClick={() => onSelect(d.version_id)}
              >
                {d.elements > 0 ? (
                  <CheckCircle2 size={14} aria-label="préparé" />
                ) : (
                  <Circle size={14} aria-label="à préparer" />
                )}
                {d.title}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <DocumentEditor
        key={current.version_id}
        versionId={current.version_id}
        campaignId={campaign.id}
        embedded
        onSaved={onReload}
        onFinish={(next) => (next ? onSelect(next) : onDone())}
      />
    </div>
  );
}
