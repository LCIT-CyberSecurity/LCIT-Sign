import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download, ExternalLink, FileCheck2, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { SignedDocumentsResponse } from "../api/types";

const STATUS_LABEL: Record<string, string> = {
  WAITING: "Pas encore son tour",
  PENDING: "À signer",
  VIEWED: "Consulté, pas signé",
};

const day = (value: string | null) => (value ? new Date(value).toLocaleDateString("fr-FR") : "—");

/** The signed documents of one or several campaigns, in one place: who signed what, who still
 *  has to, the PDFs, and a ZIP of them all. */
export default function SignedDocumentsPage() {
  const [data, setData] = useState<SignedDocumentsResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");

  const params = () => {
    const search = new URLSearchParams();
    selected.forEach((id) => search.append("campaign_ids", id));
    if (query.trim()) search.set("q", query.trim());
    return search.toString();
  };

  useEffect(() => {
    // A short pause while typing, so a search does not fire at every key.
    const timer = setTimeout(() => {
      const suffix = params() ? `?${params()}` : "";
      api.get<SignedDocumentsResponse>(`/signed/documents${suffix}`).then(setData);
    }, 200);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, query]);

  const toggle = (id: string) =>
    setSelected(selected.includes(id) ? selected.filter((c) => c !== id) : [...selected, id]);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <FileCheck2 size={22} aria-hidden="true" /> Documents signés
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            Ce qui a été signé, par qui, et ce qu&apos;il reste à signer — pour une ou plusieurs campagnes.
          </p>
        </div>
        <a
          className={`button button--primary${data && data.totals.signed > 0 ? "" : " is-disabled"}`}
          aria-disabled={!data || data.totals.signed === 0}
          href={data && data.totals.signed > 0 ? `/api/signed/export.zip?${params()}` : undefined}
        >
          <Download size={14} aria-hidden="true" /> Tout télécharger (ZIP)
        </a>
      </div>

      <div className="card" data-testid="signed-filters">
        <div className="field-label">
          Campagnes{" "}
          <span className="muted small">
            {selected.length === 0 ? "— toutes" : `— ${selected.length} sélectionnée(s)`}
          </span>
        </div>
        <div className="chip-list">
          {data?.campaigns.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`chip${selected.includes(c.id) ? " chip--active" : ""}`}
              aria-pressed={selected.includes(c.id)}
              onClick={() => toggle(c.id)}
            >
              {c.name}
            </button>
          ))}
          {selected.length > 0 && (
            <button type="button" className="button button--ghost button--sm" onClick={() => setSelected([])}>
              Toutes les campagnes
            </button>
          )}
        </div>
        <input
          type="search"
          placeholder="Rechercher une personne, un document, une campagne…"
          aria-label="Rechercher"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {data && (
        <div className="metrics" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 240px))" }}>
          <div className="metric">
            <div className="metric-label">Signés</div>
            <strong data-testid="total-signed">{data.totals.signed}</strong>
          </div>
          <div className="metric">
            <div className="metric-label">Reste à signer</div>
            <strong data-testid="total-outstanding">{data.totals.outstanding}</strong>
          </div>
          <div className="metric">
            <div className="metric-label">Pas encore leur tour</div>
            <strong data-testid="total-waiting">{data.totals.waiting}</strong>
          </div>
        </div>
      )}

      <section className="card" data-testid="signed-table">
        <div className="card-title">Documents signés</div>
        {!data ? (
          <p className="muted">Chargement…</p>
        ) : data.signed.length === 0 ? (
          <p className="muted">Aucun document signé pour cette sélection.</p>
        ) : (
          <div className="table-wrap">
            <table className="simple-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Signataire</th>
                  <th>Campagne</th>
                  <th>Signé le</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.signed.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.document_title} <span className="muted small">v{row.version_label}</span>
                    </td>
                    <td>
                      {row.signer_name}
                      <div className="muted small">{row.signer_email}</div>
                    </td>
                    <td>{row.campaign_name ?? "—"}</td>
                    <td>{day(row.signed_at)}</td>
                    <td>
                      <div className="row-actions">
                        <a
                          className="button button--secondary button--sm"
                          href={`/api/signatures/${row.id}/signed-pdf?inline=true`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <ExternalLink size={12} aria-hidden="true" /> Ouvrir
                        </a>
                        <a className="button button--ghost button--sm" href={`/api/signatures/${row.id}/signed-pdf`}>
                          <Download size={12} aria-hidden="true" /> PDF
                        </a>
                        <Link className="button button--ghost button--sm" to={`/signatures/${row.id}`}>
                          <ShieldCheck size={12} aria-hidden="true" /> Preuve
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card" data-testid="outstanding-table">
        <div className="card-title">Reste à signer</div>
        {!data ? (
          <p className="muted">Chargement…</p>
        ) : data.outstanding.length === 0 ? (
          <p className="muted">Personne n&apos;a de document en attente pour cette sélection.</p>
        ) : (
          <div className="table-wrap">
            <table className="simple-table">
              <thead>
                <tr>
                  <th>Signataire</th>
                  <th>Document</th>
                  <th>Campagne</th>
                  <th>Statut</th>
                  <th>Échéance</th>
                </tr>
              </thead>
              <tbody>
                {data.outstanding.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.signer_name}
                      <div className="muted small">{row.signer_email}</div>
                    </td>
                    <td>
                      {row.document_title} <span className="muted small">v{row.version_label}</span>
                    </td>
                    <td>
                      <Link className="row-link" to={`/campaigns/${row.campaign_id}`}>
                        {row.campaign_name}
                      </Link>
                    </td>
                    <td>
                      <span className={`badge badge--${row.status.toLowerCase()}`}>
                        {STATUS_LABEL[row.status] ?? row.status}
                      </span>
                    </td>
                    <td>{day(row.deadline)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
