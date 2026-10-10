import { AlertTriangle, CheckCircle2, Clock, FileSignature, Megaphone } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { OperatorDashboard } from "../api/types";

function Metric({
  id,
  label,
  value,
  icon,
  tone,
  hint,
}: {
  /** A stable name for the tile (tests and automation find it by this, whatever the language). */
  id: string;
  label: string;
  value: string | number;
  icon: ReactNode;
  tone?: "green" | "red" | "amber";
  hint?: string;
}) {
  return (
    <div className={`metric${tone === "red" && Number(value) > 0 ? " metric-alert" : ""}`}>
      <div className="metric-label">
        {label}
        <span className={`metric-icon${tone ? ` ${tone}` : ""}`} aria-hidden="true">
          {icon}
        </span>
      </div>
      <strong data-testid={`stat-${id}`}>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

/** Overview figures for operators (spec §65), in EARE's metric-tile style, with
 *  a stacked bar splitting the expected signatures. */
export default function DashboardCards({ data }: { data: OperatorDashboard }) {
  const { t } = useTranslation();
  const { expected, signed, outstanding, not_viewed, overdue } = data.assignments;
  const rate = data.signature_rate;
  const late = Math.min(overdue, outstanding);
  const waiting = Math.max(outstanding - late, 0);
  const pct = (n: number) => (expected ? `${(100 * n) / expected}%` : "0%");

  return (
    <section aria-label={t("dashboard.label")} className="stack">
      <div className="metrics">
        <Metric
          id="Campagnes actives"
          label={t("dashboard.activeCampaigns")}
          value={data.campaigns.active}
          icon={<Megaphone size={15} />}
          hint={t("dashboard.closedHint", { count: data.campaigns.closed })}
        />
        <Metric
          id="Signatures attendues"
          label={t("dashboard.expected")}
          value={expected}
          icon={<FileSignature size={15} />}
          hint={t("dashboard.notViewedHint", { count: not_viewed })}
        />
        <Metric
          id="Signatures réalisées"
          label={t("dashboard.done")}
          value={signed}
          icon={<CheckCircle2 size={15} />}
          tone="green"
          hint={rate === null ? undefined : t("dashboard.rateHint", { rate })}
        />
        <Metric
          id="En retard"
          label={t("dashboard.late")}
          value={overdue}
          icon={<AlertTriangle size={15} />}
          tone="red"
          hint={t("dashboard.remindersHint", { count: data.reminders_sent })}
        />
      </div>
      <div className="panel panel--quiet">
        <div className="panel-title">
          <h3>{t("dashboard.rate")}</h3>
          <strong data-testid="signature-rate">{rate === null ? "—" : `${rate} %`}</strong>
        </div>
        <div
          className="stacked-track"
          role="progressbar"
          aria-label={t("dashboard.split")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={rate ?? 0}
        >
          <span className="stacked-part ok" style={{ width: pct(signed) }} />
          <span className="stacked-part warn" style={{ width: pct(waiting) }} />
          <span className="stacked-part bad" style={{ width: pct(late) }} />
        </div>
        <div className="stacked-legend" style={{ marginTop: 10 }}>
          <span>
            <i className="stacked-dot ok" /> {t("dashboard.signedLegend")} <strong>{signed}</strong>
          </span>
          <span>
            <i className="stacked-dot warn" /> {t("dashboard.waiting")} <strong data-testid="stat-En attente">{waiting}</strong>
          </span>
          <span>
            <i className="stacked-dot bad" /> {t("dashboard.late")} <strong>{late}</strong>
          </span>
          <span>
            <Clock size={13} aria-hidden="true" /> {t("dashboard.notViewed")} <strong data-testid="stat-Non consultés">{not_viewed}</strong>
          </span>
        </div>
      </div>
    </section>
  );
}
