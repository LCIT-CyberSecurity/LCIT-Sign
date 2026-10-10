import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { Megaphone, PenLine } from "lucide-react";
import { api } from "../api/client";
import { campaignStatus } from "../i18n/enums";
import i18n from "../i18n";
import { formatDate as formatDay } from "../i18n/format";
import DashboardCards from "../components/DashboardCards";
import SignedDocuments from "../components/SignedDocuments";
import type { Campaign, OperatorDashboard } from "../api/types";

const targetLabel = (mode: string) => (i18n.exists(`campaign.target.${mode}`) ? i18n.t(`campaign.target.${mode}`) : mode);

function totals(c: Campaign): { signed: number; total: number } {
  const counts = c.assignment_counts;
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  return { signed: counts.SIGNED, total };
}

function formatDate(value: string | null): string {
  return value ? formatDay(value) : "—";
}

export default function OperatorCampaignsPage() {
  const { t } = useTranslation();
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [dashboard, setDashboard] = useState<OperatorDashboard | null>(null);
  const [query, setQuery] = useSearchParams();
  const tab = query.get("tab") === "signed" ? "signed" : "campaigns";

  const load = () => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns);
    api.get<OperatorDashboard>("/campaigns/_meta/dashboard").then(setDashboard);
  };

  useEffect(load, []);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <Megaphone size={22} aria-hidden="true" /> {t("nav.tracking")}
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            {t("tracking.subtitle")}
          </p>
        </div>
        <Link className="button button--primary" to="/sign">
          <PenLine size={14} aria-hidden="true" /> {t("tracking.newRequest")}
        </Link>
      </div>

      <div className="tabs" role="tablist" aria-label={t("nav.tracking")}>
        <button
          role="tab"
          type="button"
          aria-selected={tab === "campaigns"}
          className={tab === "campaigns" ? "tab is-active" : "tab"}
          onClick={() => setQuery({})}
        >
          {t("tracking.campaigns")}
        </button>
        <button
          role="tab"
          type="button"
          aria-selected={tab === "signed"}
          className={tab === "signed" ? "tab is-active" : "tab"}
          onClick={() => setQuery({ tab: "signed" })}
        >
          {t("tracking.signedDocuments")}
        </button>
      </div>

      {tab === "signed" && <SignedDocuments />}

      {tab === "campaigns" && dashboard && <DashboardCards data={dashboard} />}

      <div className="table-wrap">
        <table className="simple-table campaigns-table">
          <thead>
            <tr>
              <th>{t("tracking.columns.campaign")}</th>
              <th>{t("tracking.columns.status")}</th>
              <th>{t("tracking.columns.target")}</th>
              <th>{t("tracking.columns.progress")}</th>
              <th>{t("tracking.columns.launched")}</th>
              <th>{t("tracking.columns.deadline")}</th>
            </tr>
          </thead>
          <tbody>
            {campaigns?.filter((c) => c.status !== "DRAFT").length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  {t("tracking.nothingSent")}
                </td>
              </tr>
            )}
            {campaigns?.filter((c) => c.status !== "DRAFT").map((c) => {
              const { signed, total } = totals(c);
              const pct = total ? Math.round((100 * signed) / total) : 0;
              return (
                <tr key={c.id}>
                  <td>
                    <Link className="row-link" to={`/campaigns/${c.id}`}>
                      {c.name}
                    </Link>
                    <div className="muted small">{t("counts.documents", { count: c.document_version_ids.length })}</div>
                  </td>
                  <td>
                    <span className={`badge badge--${c.status.toLowerCase()}`}>{campaignStatus(c.status)}</span>
                  </td>
                  <td>{c.status === "DRAFT" ? "—" : targetLabel(c.target_mode)}</td>
                  <td>
                    {total > 0 ? (
                      <div className="table-progress" title={t("tracking.signedOf", { signed, total })}>
                        <div>
                          <span style={{ width: `${pct}%` }} />
                        </div>
                        {signed}/{total}
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{c.status === "SCHEDULED" ? t("tracking.startingOn", { date: formatDate(c.scheduled_start) }) : formatDate(c.launch_at)}</td>
                  <td>{formatDate(c.deadline)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
