import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Download, ExternalLink, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { formatDate } from "../i18n/format";
import i18n from "../i18n";
import type { SignedDocumentsResponse } from "../api/types";

const statusLabel = (status: string) =>
  i18n.exists(`signedDocs.status.${status}`) ? i18n.t(`signedDocs.status.${status}`) : status;

const day = (value: string | null) => (value ? formatDate(value) : "—");

/** The signed documents of one or several campaigns: who signed what, who still has to, the
 *  PDFs, and a ZIP of them all. With `campaignIds` it is about those campaigns only (a campaign's
 *  own page, the last step of sending); without, the campaigns can be picked. */
export default function SignedDocuments({
  campaignIds,
  refreshKey = 0,
}: {
  campaignIds?: string[];
  refreshKey?: number;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<SignedDocumentsResponse | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const fixed = campaignIds !== undefined;
  const selected = fixed ? campaignIds : picked;
  const setSelected = setPicked;

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
  }, [selected.join(","), query, refreshKey]);

  const toggle = (id: string) =>
    setSelected(selected.includes(id) ? selected.filter((c) => c !== id) : [...selected, id]);

  return (
    <div className="stack">
      <div className="signed-toolbar">
        <input
          type="search"
          placeholder={t("signedDocs.searchPlaceholder")}
          aria-label={t("signedDocs.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <a
          className={`button button--primary${data && data.totals.signed > 0 ? "" : " is-disabled"}`}
          aria-disabled={!data || data.totals.signed === 0}
          href={data && data.totals.signed > 0 ? `/api/signed/export.zip?${params()}` : undefined}
        >
          <Download size={14} aria-hidden="true" /> {t("signedDocs.downloadAll")}
        </a>
      </div>

      {!fixed && (
        <div className="card" data-testid="signed-filters">
          <div className="field-label">
            {t("signedDocs.campaigns")}{" "}
            <span className="muted small">
              {selected.length === 0 ? t("signedDocs.allLower") : t("signedDocs.selectedLower", { count: selected.length })}
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
                {t("signedDocs.allCampaigns")}
              </button>
            )}
          </div>
        </div>
      )}

      {data && (
        <div className="metrics" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 240px))" }}>
          <div className="metric">
            <div className="metric-label">{t("signedDocs.signed")}</div>
            <strong data-testid="total-signed">{data.totals.signed}</strong>
          </div>
          <div className="metric">
            <div className="metric-label">{t("signedDocs.left")}</div>
            <strong data-testid="total-outstanding">{data.totals.outstanding}</strong>
          </div>
          <div className="metric">
            <div className="metric-label">{t("signedDocs.waiting")}</div>
            <strong data-testid="total-waiting">{data.totals.waiting}</strong>
          </div>
        </div>
      )}

      <section className="card" data-testid="signed-table">
        <div className="card-title">{t("signedDocs.signedTitle")}</div>
        {!data ? (
          <p className="muted">{t("common.loading")}</p>
        ) : data.signed.length === 0 ? (
          <p className="muted">{t("signedDocs.noneSigned")}</p>
        ) : (
          <div className="table-wrap">
            <table className="simple-table">
              <thead>
                <tr>
                  <th>{t("signedDocs.columns.document")}</th>
                  <th>{t("signedDocs.columns.signer")}</th>
                  <th>{t("signedDocs.columns.campaign")}</th>
                  <th>{t("signedDocs.columns.signedOn")}</th>
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
                          <ExternalLink size={12} aria-hidden="true" /> {t("signedDocs.open")}
                        </a>
                        <a className="button button--ghost button--sm" href={`/api/signatures/${row.id}/signed-pdf`}>
                          <Download size={12} aria-hidden="true" /> PDF
                        </a>
                        <Link className="button button--ghost button--sm" to={`/signatures/${row.id}`}>
                          <ShieldCheck size={12} aria-hidden="true" /> {t("signedDocs.proof")}
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
        <div className="card-title">{t("signedDocs.left")}</div>
        {!data ? (
          <p className="muted">{t("common.loading")}</p>
        ) : data.outstanding.length === 0 ? (
          <p className="muted">{t("signedDocs.nobodyWaiting")}</p>
        ) : (
          <div className="table-wrap">
            <table className="simple-table">
              <thead>
                <tr>
                  <th>{t("signedDocs.columns.signer")}</th>
                  <th>{t("signedDocs.columns.document")}</th>
                  <th>{t("signedDocs.columns.campaign")}</th>
                  <th>{t("signedDocs.columns.status")}</th>
                  <th>{t("signedDocs.columns.deadline")}</th>
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
                        {statusLabel(row.status)}
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
